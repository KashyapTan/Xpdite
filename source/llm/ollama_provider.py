"""
Ollama LLM streaming integration.

Handles streaming responses from Ollama with real-time token broadcasting.
"""

import os
import threading
import asyncio
import json
from typing import List, Dict, Any, Optional

from ollama import chat

from ..core.connection import broadcast_message
from ..core.state import app_state
from ..mcp_integration.handlers import handle_mcp_tool_calls
from ..mcp_integration.manager import mcp_manager


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
) -> tuple[str, Dict[str, int], List[Dict[str, Any]]]:
    """
    Stream Ollama response without blocking the event loop.

    A background thread iterates the blocking Ollama generator and schedules
    WebSocket broadcasts for each incremental token. Returns a tuple of
    (full_output_text, token_stats_dict, tool_calls_list) once streaming completes.

    Args:
        user_query: The user's question
        image_paths: List of image file paths (can be empty for text-only)
        chat_history: Previous conversation messages

    Returns:
        Tuple of (response_text, token_stats, tool_calls)
    """
    loop = asyncio.get_running_loop()

    # Build messages
    messages = _build_messages(chat_history, user_query, image_paths)
    if system_prompt:
        messages.insert(0, {"role": "system", "content": system_prompt})

    # ── MCP Tool Calling Phase (runs on the event loop, not in producer thread) ──
    tool_calls_list: List[Dict[str, Any]] = []
    pre_computed_response: Optional[Dict[str, Any]] = None

    if mcp_manager.has_tools():
        try:
            (
                updated_messages,
                tool_calls_list,
                pre_computed_response,
            ) = await handle_mcp_tool_calls(messages.copy(), image_paths)
            messages = updated_messages
        except Exception as e:
            print(f"[MCP] Tool calling phase failed: {e}")

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
    # Reached in all normal cases:
    # - No MCP tools configured (tool detection skipped)
    # - Tool detection ran but no tools needed (messages unchanged)
    # - Tool calls completed (messages now include tool exchange history)
    # The streaming call produces the final response with proper token-by-token
    # delivery and thinking support. Don't pass tools — they're handled above.
    should_pass_tools = False

    done_future: asyncio.Future[tuple[str, Dict[str, int], List[Dict[str, Any]]]] = (
        loop.create_future()
    )

    def safe_schedule(coro):
        try:
            loop.call_soon_threadsafe(asyncio.create_task, coro)
        except RuntimeError:
            pass

    def producer():
        accumulated: list[str] = []
        thinking_tokens: list[str] = []
        final_message_content: str | None = None
        collected_token_stats: Dict[str, int] = {
            "prompt_eval_count": 0,
            "eval_count": 0,
        }

        try:
            chat_kwargs: Dict[str, Any] = {
                "model": app_state.selected_model,
                "messages": messages,
                "stream": True,
                "options": {"num_ctx": 32768},
            }
            if should_pass_tools:
                chat_kwargs["tools"] = mcp_manager.get_ollama_tools()

            generator = chat(**chat_kwargs)

            for idx, chunk in enumerate(generator):
                # Check if stop was requested
                if app_state.stop_streaming:
                    break

                content_token, thinking_token = _extract_token(chunk)

                # Handle thinking tokens
                if thinking_token:
                    thinking_tokens.append(thinking_token)
                    safe_schedule(broadcast_message("thinking_chunk", thinking_token))

                # Handle regular content
                if content_token:
                    if thinking_tokens and not accumulated:
                        safe_schedule(broadcast_message("thinking_complete", ""))
                    accumulated.append(content_token)
                    safe_schedule(broadcast_message("response_chunk", content_token))

                # Handle unexpected tool calls in the stream
                if hasattr(chunk, "message"):
                    msg = getattr(chunk, "message")
                    if msg and hasattr(msg, "tool_calls") and msg.tool_calls:
                        for tool_call in msg.tool_calls:
                            fn = tool_call.function.name
                            args = tool_call.function.arguments
                            tool_text = f"\n\n[Model requested tool: {fn}({args})]"

                            if thinking_tokens and not accumulated:
                                safe_schedule(
                                    broadcast_message("thinking_complete", "")
                                )

                            accumulated.append(tool_text)
                            safe_schedule(
                                broadcast_message("response_chunk", tool_text)
                            )
                elif isinstance(chunk, dict):
                    msg = chunk.get("message", {})
                    if isinstance(msg, dict) and msg.get("tool_calls"):
                        for tool_call in msg["tool_calls"]:
                            fn = tool_call.get("function", {}).get("name", "unknown")
                            args = tool_call.get("function", {}).get("arguments", {})
                            tool_text = f"\n\n[Model requested tool: {fn}({args})]"

                            if thinking_tokens and not accumulated:
                                safe_schedule(
                                    broadcast_message("thinking_complete", "")
                                )

                            accumulated.append(tool_text)
                            safe_schedule(
                                broadcast_message("response_chunk", tool_text)
                            )

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
                    safe_schedule(
                        broadcast_message("token_usage", json.dumps(token_stats))
                    )

                    if hasattr(chunk, "message"):
                        msg = getattr(chunk, "message")
                        if msg is not None and hasattr(msg, "content"):
                            mc = getattr(msg, "content")
                            if isinstance(mc, str) and mc:
                                final_message_content = mc

            # Handle edge cases
            if thinking_tokens and not accumulated:
                safe_schedule(broadcast_message("thinking_complete", ""))

            if not accumulated and final_message_content:
                accumulated.append(final_message_content)
                safe_schedule(
                    broadcast_message("response_chunk", final_message_content)
                )
            elif not accumulated and not app_state.stop_streaming:
                # Fallback to non-streaming call if streaming yielded nothing
                try:
                    print("[Ollama] Stream empty. Attempting non-streamed fallback...")
                    fallback_kwargs: Dict[str, Any] = {
                        "model": app_state.selected_model,
                        "messages": messages,
                        "stream": False,
                        "options": {"num_ctx": 32768},
                    }
                    # Don't pass tools in fallback - just get a text response
                    fallback = chat(**fallback_kwargs)

                    content_str = ""
                    if hasattr(fallback, "message"):
                        msg = getattr(fallback, "message")
                        if msg:
                            # Check for thinking content in fallback
                            if hasattr(msg, "thinking") and msg.thinking:
                                safe_schedule(
                                    broadcast_message("thinking_chunk", msg.thinking)
                                )
                                safe_schedule(
                                    broadcast_message("thinking_complete", "")
                                )

                            if hasattr(msg, "content") and msg.content:
                                content_str = msg.content

                    if content_str:
                        accumulated.append(content_str)
                        safe_schedule(broadcast_message("response_chunk", content_str))
                    else:
                        safe_schedule(
                            broadcast_message(
                                "error",
                                "No content tokens extracted from stream (and fallback failed).",
                            )
                        )
                except Exception as e:
                    safe_schedule(
                        broadcast_message(
                            "error",
                            f"No content tokens extracted from stream. Fallback error: {e}",
                        )
                    )

            safe_schedule(broadcast_message("response_complete", ""))
            loop.call_soon_threadsafe(
                done_future.set_result,
                ("".join(accumulated), collected_token_stats, tool_calls_list, None),
            )

        except Exception as e:
            err = f"Error streaming from Ollama: {e}"
            print(err)
            safe_schedule(broadcast_message("error", err))
            if not done_future.done():
                loop.call_soon_threadsafe(
                    done_future.set_result,
                    (err, collected_token_stats, tool_calls_list, None),
                )

    threading.Thread(target=producer, daemon=True).start()
    return await done_future


async def _broadcast_tool_final_response(
    pre_computed: Dict[str, Any],
    tool_calls_list: List[Dict[str, Any]],
) -> tuple[str, Dict[str, int], List[Dict[str, Any]]]:
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
