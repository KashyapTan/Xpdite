"""
Ollama LLM streaming integration.

Handles streaming responses from Ollama with real-time token broadcasting.

Uses Ollama's AsyncClient for fully async streaming — no background threads,
no producer/consumer queues, no wrap_with_tab_ctx needed.  ContextVars
propagate naturally through the async chain, matching the cloud provider
pattern in cloud_provider.py.
"""

import os
import json
import logging
from typing import List, Dict, Any, Optional

from ollama import AsyncClient as OllamaAsyncClient
from ..config import OLLAMA_CTX_SIZE
from ..core.connection import broadcast_message
from ..core.request_context import get_current_model, get_current_request, is_current_request_cancelled
from ..core.state import app_state
from ..mcp_integration.handlers import handle_mcp_tool_calls
from ..mcp_integration.manager import mcp_manager
from ..mcp_integration.tool_args import normalize_tool_args

logger = logging.getLogger(__name__)


def _build_messages(
    chat_history: List[Dict[str, Any]],
    user_query: str,
    image_paths: List[str],
) -> List[Dict[str, Any]]:
    """Build the messages list from chat history + current user query."""
    messages = []
    for msg in chat_history:
        message_data = {
            "role": msg["role"],
            "content": msg["content"],
        }
        if msg.get("images"):
            existing_images = [p for p in msg["images"] if os.path.exists(p)]
            if existing_images:
                message_data["images"] = existing_images
        messages.append(message_data)

    existing_image_paths = [p for p in image_paths if os.path.exists(p)]
    user_msg: Dict[str, Any] = {"role": "user", "content": user_query}
    if existing_image_paths:
        user_msg["images"] = existing_image_paths
    messages.append(user_msg)

    return messages


async def stream_ollama_chat(
    user_query: str, image_paths: List[str], chat_history: List[Dict[str, Any]], system_prompt: str = ""
) -> tuple[str, Dict[str, int], List[Dict[str, Any]], Optional[List[Dict[str, Any]]]]:
    """
    Stream Ollama response using the async client.

    Uses ``ollama.AsyncClient`` for native async streaming — no background
    threads needed.  ContextVars (tab_id, request context, model) propagate
    naturally through the async chain.

    Args:
        user_query: The user's question
        image_paths: List of image file paths (can be empty for text-only)
        chat_history: Previous conversation messages
        system_prompt: System prompt to prepend

    Returns:
        Tuple of (response_text, token_stats, tool_calls, interleaved_blocks)
    """
    # Build messages
    messages = _build_messages(chat_history, user_query, image_paths)
    if system_prompt:
        messages.insert(0, {"role": "system", "content": system_prompt})

    # ── Per-request async client ─────────────────────────────────
    client = OllamaAsyncClient()

    tool_calls_list: List[Dict[str, Any]] = []
    _empty_stats: Dict[str, int] = {"prompt_eval_count": 0, "eval_count": 0}

    ctx = get_current_request() or app_state.current_request

    # Register cancel callback to close the HTTP transport immediately,
    # which makes the in-flight await raise an error and breaks out.
    # Cancel callbacks fire on the event loop thread (from the WS handler),
    # so we always have a running loop available.
    def _abort():
        try:
            import asyncio
            loop = asyncio.get_running_loop()
            loop.create_task(client._client.aclose())  # type: ignore[union-attr]
        except Exception:
            pass  # is_current_request_cancelled() checks are the primary mechanism

    if ctx is not None:
        ctx.on_cancel(_abort)

    # ── MCP Tool Calling Phase ───────────────────────────────────
    pre_computed_response: Optional[Dict[str, Any]] = None

    if mcp_manager.has_tools():
        try:
            (
                updated_messages,
                tool_calls_list,
                pre_computed_response,
            ) = await handle_mcp_tool_calls(messages.copy(), image_paths, client=client)
            messages = updated_messages
        except Exception as e:
            if is_current_request_cancelled():
                logger.info("MCP phase interrupted by user cancel")
                return ("", _empty_stats.copy(), tool_calls_list, None)
            logger.error("Tool calling phase failed: %s", e)

    # If cancelled during MCP
    if is_current_request_cancelled():
        return ("", _empty_stats.copy(), tool_calls_list, None)

    # If the MCP phase streamed a response (interleaved text + tools),
    # everything was already broadcast to the user. Return directly.
    if pre_computed_response:
        if pre_computed_response.get("already_streamed"):
            return (
                pre_computed_response.get("content", ""),
                pre_computed_response.get(
                    "token_stats", {"prompt_eval_count": 0, "eval_count": 0}
                ),
                tool_calls_list,
                pre_computed_response.get("interleaved_blocks"),
            )
        # Legacy pre-computed path (safety net)
        return await _broadcast_tool_final_response(
            pre_computed_response, tool_calls_list
        )

    # ── Streaming Phase ──────────────────────────────────────────
    accumulated: list[str] = []
    thinking_tokens: list[str] = []
    final_message_content: str | None = None
    collected_token_stats: Dict[str, int] = {
        "prompt_eval_count": 0,
        "eval_count": 0,
    }

    try:
        chat_kwargs: Dict[str, Any] = {
            "model": get_current_model() or app_state.selected_model,
            "messages": messages,
            "stream": True,
            "options": {"num_ctx": OLLAMA_CTX_SIZE},
        }

        stream = await client.chat(**chat_kwargs)

        async for chunk in stream:
            if is_current_request_cancelled():
                break

            content_token, thinking_token = _extract_token(chunk)

            # Handle thinking tokens
            if thinking_token:
                thinking_tokens.append(thinking_token)
                await broadcast_message("thinking_chunk", thinking_token)

            # Handle regular content
            if content_token:
                if thinking_tokens and not accumulated:
                    await broadcast_message("thinking_complete", "")
                accumulated.append(content_token)
                await broadcast_message("response_chunk", content_token)

            # Handle unexpected tool calls in the stream
            if hasattr(chunk, "message"):
                msg = getattr(chunk, "message")
                if msg and hasattr(msg, "tool_calls") and msg.tool_calls:
                    for tool_call in msg.tool_calls:
                        fn = tool_call.function.name
                        args, arg_error = normalize_tool_args(tool_call.function.arguments)
                        if arg_error:
                            args = {"_arg_error": arg_error}
                        tool_text = f"\n\n[Model requested tool: {fn}({args})]"

                        if thinking_tokens and not accumulated:
                            await broadcast_message("thinking_complete", "")

                        accumulated.append(tool_text)
                        await broadcast_message("response_chunk", tool_text)
            elif isinstance(chunk, dict):
                msg = chunk.get("message", {})
                if isinstance(msg, dict) and msg.get("tool_calls"):
                    for tool_call in msg["tool_calls"]:
                        fn = tool_call.get("function", {}).get("name", "unknown")
                        raw_args = tool_call.get("function", {}).get("arguments", {})
                        args, arg_error = normalize_tool_args(raw_args)
                        if arg_error:
                            args = {"_arg_error": arg_error}
                        tool_text = f"\n\n[Model requested tool: {fn}({args})]"

                        if thinking_tokens and not accumulated:
                            await broadcast_message("thinking_complete", "")

                        accumulated.append(tool_text)
                        await broadcast_message("response_chunk", tool_text)

            # Track final message and token stats
            if hasattr(chunk, "done") and getattr(chunk, "done"):
                token_stats = {
                    "prompt_eval_count": getattr(chunk, "prompt_eval_count", 0),
                    "eval_count": getattr(chunk, "eval_count", 0),
                }
                collected_token_stats["prompt_eval_count"] = (
                    token_stats["prompt_eval_count"] or 0
                )
                collected_token_stats["eval_count"] = token_stats["eval_count"] or 0
                await broadcast_message("token_usage", json.dumps(token_stats))

                if hasattr(chunk, "message"):
                    msg = getattr(chunk, "message")
                    if msg is not None and hasattr(msg, "content"):
                        mc = getattr(msg, "content")
                        if isinstance(mc, str) and mc:
                            final_message_content = mc

        # Handle edge cases
        if thinking_tokens and not accumulated:
            await broadcast_message("thinking_complete", "")

        if not accumulated and final_message_content:
            accumulated.append(final_message_content)
            await broadcast_message("response_chunk", final_message_content)
        elif not accumulated and not is_current_request_cancelled():
            # Fallback to non-streaming call if streaming yielded nothing
            try:
                logger.warning("Stream empty. Attempting non-streamed fallback...")
                fallback_kwargs: Dict[str, Any] = {
                    "model": get_current_model() or app_state.selected_model,
                    "messages": messages,
                    "stream": False,
                    "options": {"num_ctx": OLLAMA_CTX_SIZE},
                }
                fallback = await client.chat(**fallback_kwargs)

                content_str = ""
                if hasattr(fallback, "message"):
                    msg = getattr(fallback, "message")
                    if msg:
                        if hasattr(msg, "thinking") and msg.thinking:
                            await broadcast_message("thinking_chunk", msg.thinking)
                            await broadcast_message("thinking_complete", "")

                        if hasattr(msg, "content") and msg.content:
                            content_str = msg.content

                if content_str:
                    accumulated.append(content_str)
                    await broadcast_message("response_chunk", content_str)
                else:
                    no_content_msg = "[Model returned no content after tool loop]"
                    accumulated.append(no_content_msg)
                    await broadcast_message("response_chunk", no_content_msg)
            except Exception as e:
                logger.warning("Non-streamed fallback failed after empty stream: %s", e)
                no_content_msg = "[Model returned no content after tool loop]"
                accumulated.append(no_content_msg)
                await broadcast_message("response_chunk", no_content_msg)

        if not is_current_request_cancelled():
            await broadcast_message("response_complete", "")

        return ("".join(accumulated), collected_token_stats, tool_calls_list, None)

    except Exception as e:
        if is_current_request_cancelled():
            logger.info("Ollama stream aborted by user cancel")
        else:
            error_msg = f"LLM API error ({type(e).__name__})"
            logger.error("Ollama error: %s", e)
            await broadcast_message("error", error_msg)

        await broadcast_message("response_complete", "")
        return (
            "".join(accumulated) if accumulated else "",
            collected_token_stats,
            tool_calls_list,
            None,
        )


async def _broadcast_tool_final_response(
    pre_computed: Dict[str, Any],
    tool_calls_list: List[Dict[str, Any]],
) -> tuple[str, Dict[str, int], List[Dict[str, Any]], Optional[List[Dict[str, Any]]]]:
    """
    Broadcast a pre-computed response directly (no re-streaming needed).

    This is used in two scenarios:
    1. MCP tool detection ran but found no tools needed — the non-streamed
       response already contains the full answer (content + thinking + token stats).
    2. MCP tool calls were made — the final response after the tool loop is
       captured and broadcast directly.

    Broadcasting directly avoids the double-call problem that breaks streaming,
    loses thinking tokens, and loses token stats due to Ollama's KV cache.
    """
    thinking = pre_computed.get("thinking", "")
    content = pre_computed.get("content", "")
    token_stats = pre_computed.get(
        "token_stats", {"prompt_eval_count": 0, "eval_count": 0}
    )

    # Broadcast thinking if present
    if thinking:
        await broadcast_message("thinking_chunk", thinking)
        await broadcast_message("thinking_complete", "")

    # Broadcast the content
    if content:
        await broadcast_message("response_chunk", content)

    await broadcast_message("response_complete", "")

    # Broadcast token stats
    if token_stats.get("prompt_eval_count") or token_stats.get("eval_count"):
        await broadcast_message("token_usage", json.dumps(token_stats))

    return content, token_stats, tool_calls_list, None


def _extract_token(chunk) -> tuple[str | None, str | None]:
    """
    Extract content and thinking tokens from a streaming chunk.

    Supports both dict (older client) and object (dataclass) shapes.
    Returns (content_token, thinking_token).
    """
    content_token = None
    thinking_token = None

    # Dict-based chunk
    if isinstance(chunk, dict):
        msg = chunk.get("message")
        if isinstance(msg, dict):
            content_token = (
                msg.get("content")
                if isinstance(msg.get("content"), str) and msg.get("content")
                else None
            )
            thinking_token = (
                msg.get("thinking")
                if isinstance(msg.get("thinking"), str) and msg.get("thinking")
                else None
            )
        if not content_token:
            for key in ("response", "content", "delta", "text", "token"):
                tok = chunk.get(key)
                if isinstance(tok, str) and tok:
                    content_token = tok
                    break
        return (content_token, thinking_token)

    # Object-based chunk
    if hasattr(chunk, "message"):
        msg = getattr(chunk, "message")
        if msg is not None:
            if hasattr(msg, "thinking"):
                val = getattr(msg, "thinking")
                if isinstance(val, str) and val:
                    thinking_token = val
            if hasattr(msg, "content"):
                val = getattr(msg, "content")
                if isinstance(val, str) and val:
                    content_token = val

    # Fallback for content
    if not content_token:
        for attr in ("response", "content", "delta", "token"):
            if hasattr(chunk, attr):
                val = getattr(chunk, attr)
                if isinstance(val, str) and val:
                    content_token = val
                    break

    return (content_token, thinking_token)
