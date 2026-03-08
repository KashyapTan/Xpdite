"""
MCP tool call handlers.

Handles the execution of MCP tool calls from Ollama responses with
interleaved streaming — text is broadcast to the user in real-time
between tool execution rounds.

Uses Ollama's AsyncClient for fully async tool detection and streaming
follow-up calls — no background threads or wrap_with_tab_ctx needed.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from ollama import AsyncClient as OllamaAsyncClient
from ..config import MAX_TOOL_RESULT_LENGTH
from ..core.connection import broadcast_message
from ..core.request_context import is_current_request_cancelled, get_current_model
from ..core.state import app_state
from .manager import mcp_manager
from .retriever import retriever
from .terminal_executor import execute_terminal_tool, is_terminal_tool

logger = logging.getLogger(__name__)


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
    client: Optional[OllamaAsyncClient] = None,
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
        logger.info("No tools retrieved for Ollama query '%s...'", user_query[:40])
        return messages, tool_calls_made, None

    tool_names = [t["function"]["name"] for t in filtered_tools]
    logger.info(
        "Submitting %d tool(s) to Ollama: %s",
        len(tool_names), tool_names,
    )

    # Use provided client or create a new async one
    async_client = client or OllamaAsyncClient()

    if is_current_request_cancelled():
        return messages, tool_calls_made, None

    # ── Phase 1: Non-streamed detection call ──────────────────────
    # think=False works around Ollama bug #10976 (think+tools=empty output)
    # Images are included so the model can analyze image content
    try:
        response = await async_client.chat(
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
        # ── Collect spawn_agent calls for parallel execution ──
        spawn_agent_indices: List[int] = []
        spawn_agent_calls: List[Dict[str, Any]] = []
        for idx, tc in enumerate(current_tool_calls):
            fn_name = tc["name"]
            fn_args = tc["args"]
            sn = mcp_manager.get_tool_server_name(fn_name)
            if fn_name == "spawn_agent" and sn == "sub_agent":
                spawn_agent_indices.append(idx)
                spawn_agent_calls.append({
                    "instruction": fn_args.get("instruction", ""),
                    "model_tier": fn_args.get("model_tier", "fast"),
                    "agent_name": fn_args.get("agent_name", "Sub-Agent"),
                })

        # Run all spawn_agent calls in parallel (if any)
        spawn_results: Dict[int, str] = {}
        if spawn_agent_calls and not is_current_request_cancelled():
            from ..services.sub_agent import execute_sub_agents_parallel
            results = await execute_sub_agents_parallel(spawn_agent_calls)
            for i, result_str in enumerate(results):
                spawn_results[spawn_agent_indices[i]] = result_str

        for idx, tc in enumerate(current_tool_calls):
            fn_name = tc["name"]
            fn_args = tc["args"]
            server_name = mcp_manager.get_tool_server_name(fn_name)

            logger.info("Tool call: %s(%s) from server '%s'", fn_name, fn_args, server_name)

            if is_current_request_cancelled():
                break

            # spawn_agent results already computed in parallel — skip outer broadcast
            if idx in spawn_results:
                result_str = _truncate_result(spawn_results[idx])
            else:
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
            await _stream_tool_follow_up(messages, filtered_tools, client=async_client)
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
    client: Optional[OllamaAsyncClient] = None,
) -> tuple[str, List[Dict[str, Any]], Dict[str, int]]:
    """
    Stream a follow-up Ollama call during the tool loop.

    Broadcasts text chunks to the user in real-time using the async client.
    Collects any tool calls that appear in the stream for the next round.

    Returns: (accumulated_text, tool_calls_found, token_stats)
    """
    text_chunks: list[str] = []
    tool_calls_found: List[Dict[str, Any]] = []
    token_stats: Dict[str, int] = {"prompt_eval_count": 0, "eval_count": 0}

    async_client = client or OllamaAsyncClient()

    try:
        stream = await async_client.chat(
            model=get_current_model() or app_state.selected_model,
            messages=messages,
            tools=tools,
            stream=True,
            think=False,
        )

        async for chunk in stream:
            if is_current_request_cancelled():
                break

            # Extract and broadcast text tokens
            if hasattr(chunk, "message") and chunk.message:
                msg = chunk.message
                if hasattr(msg, "content") and msg.content:
                    text_chunks.append(msg.content)
                    await broadcast_message("response_chunk", msg.content)

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
        if not is_current_request_cancelled():
            logger.error("Error in streaming follow-up: %s", e)
            await broadcast_message("error", f"Tool follow-up streaming error: {e}")

    return "".join(text_chunks), tool_calls_found, token_stats
