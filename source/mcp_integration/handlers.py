"""
MCP tool call handlers.

Handles the execution of MCP tool calls from Ollama responses with
interleaved streaming — text is broadcast to the user in real-time
between tool execution rounds.
"""

import json
import asyncio
import logging
import threading
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

from ollama import chat, Client as OllamaClient

from .manager import mcp_manager
from .retriever import retriever
from .terminal_executor import is_terminal_tool, execute_terminal_tool
from ..core.connection import broadcast_message, get_current_tab_id, set_current_tab_id, wrap_with_tab_ctx
from ..core.state import app_state
from ..core.request_context import is_current_request_cancelled, get_current_model, get_current_request
from ..core.thread_pool import run_in_thread
from ..config import MAX_TOOL_RESULT_LENGTH


# ---------------------------------------------------------------------------
# Shared tool retrieval helper (used by both Ollama and cloud paths)
# ---------------------------------------------------------------------------


def retrieve_relevant_tools(user_query: str) -> list:
    """
    Retrieve filtered MCP tools relevant to a user query.

    Shared helper used by both Ollama and cloud provider tool paths.
    Returns filtered tool list in Ollama format (used as base for conversion).
    """
    if not mcp_manager.has_tools():
        return []

    from ..database import db

    always_on_json = db.get_setting("tool_always_on")
    always_on = []
    if always_on_json:
        try:
            always_on = json.loads(always_on_json)
        except Exception:
            pass

    top_k_str = db.get_setting("tool_retriever_top_k")
    top_k = int(top_k_str) if top_k_str else 5

    all_tools = mcp_manager.get_ollama_tools() or []

    filtered_tools = retriever.retrieve_tools(
        query=user_query, all_tools=all_tools, always_on=always_on, top_k=top_k
    )

    if len(filtered_tools) < len(all_tools):
        logger.debug(
            "Retriever selected %d/%d tools for query: '%s...'",
            len(filtered_tools), len(all_tools), user_query[:30]
        )

    return filtered_tools


def _truncate_result(result: str) -> str:
    """Truncate excessively large tool results."""
    result_str = str(result)
    if len(result_str) > MAX_TOOL_RESULT_LENGTH:
        logger.warning("Truncating large tool output (%d chars)", len(result_str))
        return result_str[:MAX_TOOL_RESULT_LENGTH] + "... [Output truncated due to length]"
    return result_str


# ---------------------------------------------------------------------------
# Ollama tool call handler with interleaved streaming
# ---------------------------------------------------------------------------


async def handle_mcp_tool_calls(
    messages: List[Dict[str, Any]],
    image_paths: List[str],
    client: Optional[OllamaClient] = None,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    Check for and execute MCP tool calls from Ollama with interleaved streaming.

    Phase 1 (detection): Non-streamed call with think=False to detect tool requests.
    If no tools needed, returns None so the caller streams normally (with thinking).

    Phase 2 (streaming tool loop): When tools are detected, enters a loop that
    STREAMS follow-up responses in real-time. The user sees the model's intermediate
    text (e.g. "Let me search for that...") between tool executions, giving full
    visibility into the model's process.

    Returns:
        (updated_messages, tool_calls_made, pre_computed_response)
        - If no tools needed: pre_computed_response is None, caller streams normally
        - If tools used: pre_computed_response = {"content": ..., "token_stats": ...,
          "already_streamed": True} — caller skips re-streaming
    """
    tool_calls_made: List[Dict[str, Any]] = []
    interleaved_blocks: List[Dict[str, Any]] = []

    if not mcp_manager.has_tools():
        return messages, tool_calls_made, None

    # Extract user query for retrieval
    user_query = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            user_query = msg.get("content", "")
            break

    filtered_tools = retrieve_relevant_tools(user_query)
    if not filtered_tools:
        return messages, tool_calls_made, None

    # Use provided client or fall back to module-level chat function
    chat_fn = client.chat if client else chat

    if is_current_request_cancelled():
        return messages, tool_calls_made, None

    # ── Phase 1: Non-streamed detection call ──────────────────────
    # think=False works around Ollama bug #10976 (think+tools=empty output)
    # Images are included so the model can analyze image content
    try:
        response = await run_in_thread(
            chat_fn,
            model=get_current_model() or app_state.selected_model,
            messages=messages,
            tools=filtered_tools,
            think=False,
        )
    except Exception as e:
        logger.error("Error in tool detection call: %s", e)
        return messages, tool_calls_made, None

    # No tool calls detected — fall through to normal streaming (with thinking)
    if not response.message.tool_calls:
        return messages, tool_calls_made, None

    # ── Phase 2: Streaming tool loop ──────────────────────────────
    # Normalize the detection response into standard dicts
    from ..config import MAX_MCP_TOOL_ROUNDS

    loop = asyncio.get_running_loop()
    all_accumulated_text: list[str] = []
    total_token_stats: Dict[str, int] = {"prompt_eval_count": 0, "eval_count": 0}
    rounds = 0
    is_first_round = True

    # Normalize initial tool calls from the detection response
    current_content = response.message.content or ""
    current_tool_calls = [
        {"name": tc.function.name, "args": tc.function.arguments}
        for tc in (response.message.tool_calls or [])
    ]

    while current_tool_calls and rounds < MAX_MCP_TOOL_ROUNDS:
        rounds += 1

        if is_current_request_cancelled():
            logger.info("Request cancelled — aborting tool call loop")
            break

        # Broadcast text from this round
        # First round: text from the non-streamed detection call (not yet broadcast)
        # Later rounds: text was already streamed by _stream_tool_follow_up
        if is_first_round and current_content:
            await broadcast_message("response_chunk", current_content)
            all_accumulated_text.append(current_content)
            interleaved_blocks.append({"type": "text", "content": current_content})
            is_first_round = False
        elif not is_first_round and current_content:
            # Text was already broadcast by _stream_tool_follow_up
            all_accumulated_text.append(current_content)
            interleaved_blocks.append({"type": "text", "content": current_content})

        # Add assistant message (with tool calls) to history
        assistant_msg: Dict[str, Any] = {
            "role": "assistant",
            "content": current_content,
        }
        assistant_msg["tool_calls"] = [
            {"function": {"name": tc["name"], "arguments": tc["args"]}}
            for tc in current_tool_calls
        ]
        messages.append(assistant_msg)

        # Execute each tool call
        for tc in current_tool_calls:
            fn_name = tc["name"]
            fn_args = tc["args"]
            server_name = mcp_manager.get_tool_server_name(fn_name)

            logger.info("Tool call: %s(%s) from server '%s'", fn_name, fn_args, server_name)

            if is_current_request_cancelled():
                break

            await broadcast_message(
                "tool_call",
                json.dumps(
                    {
                        "name": fn_name,
                        "args": fn_args,
                        "server": server_name,
                        "status": "calling",
                    }
                ),
            )

            # Execute (terminal interception or standard MCP)
            if is_terminal_tool(fn_name, server_name):
                result = await execute_terminal_tool(fn_name, fn_args, server_name)
            else:
                try:
                    result = await mcp_manager.call_tool(fn_name, dict(fn_args))
                except Exception as e:
                    result = f"Error executing tool: {e}"

            result_str = _truncate_result(str(result))
            logger.debug("Tool result:\n%s...", result_str[:100])

            await broadcast_message(
                "tool_call",
                json.dumps(
                    {
                        "name": fn_name,
                        "args": fn_args,
                        "result": result_str,
                        "server": server_name,
                        "status": "complete",
                    }
                ),
            )

            tool_calls_made.append(
                {
                    "name": fn_name,
                    "args": fn_args,
                    "result": result_str,
                    "server": server_name,
                }
            )
            interleaved_blocks.append(
                {
                    "type": "tool_call",
                    "name": fn_name,
                    "args": fn_args,
                    "server": server_name,
                }
            )

            messages.append({"role": "tool", "content": result_str, "name": fn_name})

        if is_current_request_cancelled():
            break

        # ── Stream follow-up call ─────────────────────────────────
        # Text is broadcast to the user in real-time inside this call
        current_content, current_tool_calls, round_stats = (
            await _stream_tool_follow_up(messages, filtered_tools, loop, client=client)
        )

        total_token_stats["prompt_eval_count"] += round_stats.get(
            "prompt_eval_count", 0
        )
        total_token_stats["eval_count"] += round_stats.get("eval_count", 0)
        is_first_round = False

        # If no more tool calls, the final text was already streamed
        if not current_tool_calls:
            if current_content:
                all_accumulated_text.append(current_content)
                interleaved_blocks.append({"type": "text", "content": current_content})
            break

    # Broadcast response_complete (text was streamed throughout the loop)
    if tool_calls_made:
        await broadcast_message("response_complete", "")
        await broadcast_message("token_usage", json.dumps(total_token_stats))
        logger.info(
            "Tool loop complete after %d round(s) with interleaved streaming", rounds
        )
        return messages, tool_calls_made, {
            "content": "".join(all_accumulated_text),
            "token_stats": total_token_stats,
            "already_streamed": True,
            "interleaved_blocks": interleaved_blocks,
        }

    return messages, tool_calls_made, None


async def _stream_tool_follow_up(
    messages: List[Dict[str, Any]],
    tools: list,
    loop: asyncio.AbstractEventLoop,
    client: Optional[OllamaClient] = None,
) -> tuple[str, List[Dict[str, Any]], Dict[str, int]]:
    """
    Stream a follow-up Ollama call during the tool loop.

    Broadcasts text chunks to the user in real-time via safe_schedule
    (runs the synchronous Ollama generator in a background thread).
    Collects any tool calls that appear in the stream for the next round.

    Returns: (accumulated_text, tool_calls_found, token_stats)
    """
    text_chunks: list[str] = []
    tool_calls_found: List[Dict[str, Any]] = []
    token_stats: Dict[str, int] = {"prompt_eval_count": 0, "eval_count": 0}

    # Use provided client or fall back to module-level chat function
    chat_fn = client.chat if client else chat

    # ── Capture tab_id for thread→eventloop context propagation ───
    _tab_id = get_current_tab_id()

    # ── Cancellation support (same pattern as ollama_provider) ───
    stop_event = threading.Event()
    generator_ref: list = [None]

    ctx = get_current_request() or app_state.current_request

    def _abort():
        # Note: the outer _abort in stream_ollama_chat also closes the shared
        # client._client transport, which will interrupt this connection too.
        # This callback is belt-and-suspenders for generator cleanup.
        stop_event.set()
        gen = generator_ref[0]
        if gen is not None and hasattr(gen, 'close'):
            try:
                gen.close()  # type: ignore[union-attr]
            except Exception:
                pass

    if ctx is not None:
        ctx.on_cancel(_abort)

    def safe_schedule(coro):
        wrapped = wrap_with_tab_ctx(_tab_id, coro)
        try:
            asyncio.run_coroutine_threadsafe(wrapped, loop)
        except RuntimeError:
            wrapped.close()  # prevent RuntimeWarning on shutdown

    def _do_stream():
        try:
            generator = chat_fn(
                model=get_current_model() or app_state.selected_model,
                messages=messages,
                tools=tools,
                stream=True,
                think=False,
            )
            generator_ref[0] = generator

            for chunk in generator:
                if stop_event.is_set() or is_current_request_cancelled():
                    break

                # Extract and broadcast text tokens
                if hasattr(chunk, "message") and chunk.message:
                    msg = chunk.message
                    if hasattr(msg, "content") and msg.content:
                        text_chunks.append(msg.content)
                        safe_schedule(
                            broadcast_message("response_chunk", msg.content)
                        )

                    # Collect tool calls (typically arrive in/near the final chunk)
                    if hasattr(msg, "tool_calls") and msg.tool_calls:
                        for tc in msg.tool_calls:
                            tool_calls_found.append(
                                {
                                    "name": tc.function.name,
                                    "args": tc.function.arguments,
                                }
                            )

                # Track token stats on done
                if hasattr(chunk, "done") and getattr(chunk, "done"):
                    token_stats["prompt_eval_count"] = (
                        getattr(chunk, "prompt_eval_count", 0) or 0
                    )
                    token_stats["eval_count"] = (
                        getattr(chunk, "eval_count", 0) or 0
                    )
        except Exception as e:
            if not stop_event.is_set():
                logger.error("Error in streaming follow-up: %s", e)
                safe_schedule(
                    broadcast_message("error", f"Tool follow-up streaming error: {e}")
                )
        finally:
            gen = generator_ref[0]
            if gen is not None and hasattr(gen, 'close'):
                try:
                    gen.close()  # type: ignore[union-attr]
                except Exception:
                    pass
                generator_ref[0] = None

    await run_in_thread(_do_stream)
    return "".join(text_chunks), tool_calls_found, token_stats
