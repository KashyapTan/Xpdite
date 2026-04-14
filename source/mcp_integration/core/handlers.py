"""
MCP tool call handlers.

Handles the execution of MCP tool calls from Ollama responses with
interleaved streaming — text is broadcast to the user in real-time
between tool execution rounds.

Uses Ollama's AsyncClient for fully async tool detection and streaming
follow-up calls — no background threads or wrap_with_tab_ctx needed.
"""

import copy
import json
import logging
from typing import Any, Dict, List, Optional

from ollama import AsyncClient as OllamaAsyncClient
from ...infrastructure.config import DEFAULT_MODEL, MAX_TOOL_RESULT_LENGTH
from ...core.connection import broadcast_message
from ...core.request_context import is_current_request_cancelled, get_current_model
from ...llm.core.artifacts import (
    ArtifactStreamParser,
    apply_artifact_stream_events,
    emit_artifact_stream_events,
    serialize_blocks_for_model_content,
)
from .manager import mcp_manager
from .retriever import retriever
from ..executors.terminal_executor import execute_terminal_tool, is_terminal_tool
from ..executors.video_watcher_executor import (
    execute_video_watcher_tool,
    is_video_watcher_tool,
)
from ..executors.memory_executor import execute_memory_tool, is_memory_tool
from ..executors.skills_executor import execute_skill_tool
from ..executors.scheduler_executor import is_scheduler_tool, execute_scheduler_tool
from .tool_args import normalize_tool_args, sanitize_tool_args

logger = logging.getLogger(__name__)


def _get_request_model() -> str:
    """Resolve model from request-scoped context with safe fallback."""
    model = get_current_model()
    if model:
        return model
    logger.warning(
        "Request model missing in ContextVar; falling back to DEFAULT_MODEL '%s'",
        DEFAULT_MODEL,
    )
    return DEFAULT_MODEL


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

    from ...infrastructure.database import db

    always_on_json = db.get_setting("tool_always_on")
    always_on = []
    if always_on_json:
        try:
            always_on = json.loads(always_on_json)
        except Exception:
            pass

    top_k_str = db.get_setting("tool_retriever_top_k")
    try:
        top_k = int(top_k_str) if top_k_str else 5
    except (TypeError, ValueError):
        logger.warning(
            "Invalid tool_retriever_top_k setting %r; defaulting to 5", top_k_str
        )
        top_k = 5

    if top_k < 0:
        top_k = 0

    all_tools = mcp_manager.get_ollama_tools() or []

    filtered_tools = retriever.retrieve_tools(
        query=user_query, all_tools=all_tools, always_on=always_on, top_k=top_k
    )

    if len(filtered_tools) < len(all_tools):
        logger.debug(
            "Retriever selected %d/%d tools for query: '%s...'",
            len(filtered_tools),
            len(all_tools),
            user_query[:30],
        )

    return filtered_tools


def _truncate_result(result: str) -> str:
    """Truncate excessively large tool results."""
    result_str = str(result)
    if len(result_str) > MAX_TOOL_RESULT_LENGTH:
        logger.warning("Truncating large tool output (%d chars)", len(result_str))
        return (
            result_str[:MAX_TOOL_RESULT_LENGTH] + "... [Output truncated due to length]"
        )
    return result_str


def _build_spawn_agent_request(fn_args: Dict[str, Any]) -> Dict[str, Any]:
    """Build the normalized sub-agent batch payload from tool arguments."""
    return {
        "instruction": fn_args.get("instruction", ""),
        "model_tier": fn_args.get("model_tier", "fast"),
        "agent_name": fn_args.get("agent_name", "Sub-Agent"),
    }


async def _save_temp_image_for_ollama(image_result: Dict[str, Any]) -> Optional[str]:
    """
    Save a base64 image result to a temp file for Ollama's native image format.

    Ollama expects image paths in the 'images' key of messages, not base64 data.
    This saves the image to the screenshots folder with a temp prefix.

    Returns the file path if successful, None otherwise.
    """
    import base64
    import os
    import re
    import uuid
    from ...infrastructure.config import SCREENSHOT_FOLDER

    # Max 50MB for image data (base64 is ~33% larger than binary)
    MAX_BASE64_LENGTH = 70 * 1024 * 1024  # ~50MB decoded

    try:
        data = image_result.get("data", "")
        if not data:
            return None

        # Validate base64 data size before decoding
        if len(data) > MAX_BASE64_LENGTH:
            logger.warning(
                "Image data too large for Ollama temp file: %d bytes", len(data)
            )
            return None

        media_type = image_result.get("media_type", "image/png")
        raw_ext = media_type.split("/")[-1] if "/" in media_type else "png"
        # Sanitize extension
        safe_ext = re.sub(r"[^a-zA-Z0-9]", "", raw_ext.lower())[:10]
        if not safe_ext or safe_ext not in ("png", "jpg", "jpeg", "webp", "gif", "bmp"):
            safe_ext = "png"
        if safe_ext == "jpeg":
            safe_ext = "jpg"

        # Generate unique filename
        filename = f"ollama_tool_img_{uuid.uuid4().hex[:8]}.{safe_ext}"
        filepath = os.path.join(SCREENSHOT_FOLDER, filename)

        # Validate the final path stays within SCREENSHOT_FOLDER (defense in depth)
        real_folder = os.path.realpath(SCREENSHOT_FOLDER)
        real_filepath = os.path.realpath(filepath)
        if (
            not real_filepath.startswith(real_folder + os.sep)
            and real_filepath != real_folder
        ):
            logger.error("Path traversal detected in temp image save")
            return None

        # Decode and save
        image_bytes = base64.b64decode(data)
        with open(real_filepath, "wb") as f:
            f.write(image_bytes)

        return real_filepath

    except Exception as e:
        logger.warning("Failed to save temp image for Ollama: %s", e)
        return None


# ---------------------------------------------------------------------------
# Ollama tool call handler with interleaved streaming
# ---------------------------------------------------------------------------


async def handle_mcp_tool_calls(
    messages: List[Dict[str, Any]],
    image_paths: List[str],
    client: Optional[OllamaAsyncClient] = None,
    prefiltered_tools: Optional[List[Dict[str, Any]]] = None,
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

    filtered_tools = prefiltered_tools
    if filtered_tools is None:
        filtered_tools = retrieve_relevant_tools(user_query)

    if not filtered_tools:
        logger.info("No tools retrieved for Ollama query '%s...'", user_query[:40])
        return messages, tool_calls_made, None

    tool_names = [t["function"]["name"] for t in filtered_tools]
    logger.info(
        "Submitting %d tool(s) to Ollama: %s",
        len(tool_names),
        tool_names,
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
            model=_get_request_model(),
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
    from ...infrastructure.config import MAX_MCP_TOOL_ROUNDS

    all_accumulated_text: list[str] = []
    total_token_stats: Dict[str, int] = {"prompt_eval_count": 0, "eval_count": 0}
    rounds = 0
    is_first_round = True

    # Normalize initial tool calls from the detection response
    current_content = response.message.content or ""
    current_model_content: Optional[str] = current_content or None
    current_thinking = ""
    if hasattr(response.message, "thinking") and response.message.thinking:
        current_thinking = response.message.thinking
    current_tool_calls = []
    for tc in response.message.tool_calls or []:
        raw_args = tc.function.arguments
        parsed_args, arg_error = normalize_tool_args(raw_args)
        current_tool_calls.append(
            {
                "name": tc.function.name,
                "args": parsed_args,
                "arg_error": arg_error,
                "raw_args": raw_args,
            }
        )

    while current_tool_calls and rounds < MAX_MCP_TOOL_ROUNDS:
        rounds += 1

        if is_current_request_cancelled():
            logger.info("Request cancelled — aborting tool call loop")
            break

        # Broadcast content from this round
        # First round: text from the non-streamed detection call (not yet broadcast)
        # Later rounds: text/thinking were already streamed by _stream_tool_follow_up
        if is_first_round:
            if current_thinking:
                await broadcast_message("thinking_chunk", current_thinking)
                await broadcast_message("thinking_complete", "")
                interleaved_blocks.append(
                    {"type": "thinking", "content": current_thinking}
                )
            if current_content:
                parser = ArtifactStreamParser()
                detection_events = parser.feed(current_content)
                detection_events.extend(parser.finalize())
                current_round_blocks: List[Dict[str, Any]] = []
                current_content = apply_artifact_stream_events(
                    detection_events,
                    current_round_blocks,
                )
                current_model_content = (
                    serialize_blocks_for_model_content(
                        current_round_blocks,
                        fallback_text=current_content,
                    )
                    or None
                )
                await emit_artifact_stream_events(
                    detection_events,
                    interleaved_blocks,
                    broadcaster=broadcast_message,
                )
                if current_content:
                    all_accumulated_text.append(current_content)
            else:
                current_model_content = None
            is_first_round = False
        elif current_content:
            all_accumulated_text.append(current_content)

        # Add assistant message (with tool calls) to history
        assistant_msg: Dict[str, Any] = {
            "role": "assistant",
            "content": current_model_content,
        }
        assistant_msg["tool_calls"] = [
            {
                "function": {
                    "name": tc["name"],
                    "arguments": tc.get("raw_args", tc["args"]),
                }
            }
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
            arg_error = tc.get("arg_error")
            sn = mcp_manager.get_tool_server_name(fn_name)
            if arg_error:
                logger.warning(
                    "Skipping spawn_agent pre-batch for malformed args on %s: %s",
                    fn_name,
                    arg_error,
                )
                continue
            if fn_name == "spawn_agent" and sn == "sub_agent":
                spawn_agent_indices.append(idx)
                spawn_agent_calls.append(_build_spawn_agent_request(fn_args))

        # Run all spawn_agent calls in parallel (if any)
        spawn_results: Dict[int, str] = {}
        if spawn_agent_calls and not is_current_request_cancelled():
            from ...services.skills_runtime.sub_agent import execute_sub_agents_parallel

            results = await execute_sub_agents_parallel(spawn_agent_calls)
            for i, result_str in enumerate(results):
                spawn_results[spawn_agent_indices[i]] = result_str

        for idx, tc in enumerate(current_tool_calls):
            fn_name = tc["name"]
            fn_args = tc["args"]
            arg_error = tc.get("arg_error")
            server_name = mcp_manager.get_tool_server_name(fn_name)
            effective_args = copy.deepcopy(fn_args)
            safe_args = sanitize_tool_args(fn_name, server_name, effective_args)

            logger.info(
                "Tool call: %s(%s) from server '%s'", fn_name, safe_args, server_name
            )

            if is_current_request_cancelled():
                break

            # Initialize result tracking
            result: Any = None
            is_image_result = False

            if arg_error:
                await broadcast_message(
                    "tool_call",
                    json.dumps(
                        {
                            "name": fn_name,
                            "args": safe_args,
                            "server": server_name,
                            "status": "calling",
                        }
                    ),
                )
                result_str = _truncate_result(
                    f"System error: invalid arguments for tool '{fn_name}': {arg_error}"
                )
                await broadcast_message(
                    "tool_call",
                    json.dumps(
                        {
                            "name": fn_name,
                            "args": safe_args,
                            "result": result_str,
                            "server": server_name,
                            "status": "complete",
                        }
                    ),
                )
            else:
                from ...services.hooks_runtime import get_hooks_runtime

                hooks_runtime = get_hooks_runtime()
                pre_hook_result = await hooks_runtime.dispatch_pre_tool_use(
                    fn_name,
                    effective_args,
                    server_name=server_name,
                )
                if pre_hook_result.updated_input is not None:
                    effective_args = copy.deepcopy(pre_hook_result.updated_input)
                safe_args = sanitize_tool_args(fn_name, server_name, effective_args)
                hook_context_messages: List[str] = []
                if not pre_hook_result.suppress_output:
                    hook_context_messages.extend(pre_hook_result.system_messages)
                    hook_context_messages.extend(pre_hook_result.additional_context)

                if pre_hook_result.blocked:
                    result = (
                        "Error: Blocked by Claude-compatible hook: "
                        + (pre_hook_result.reason or "Tool execution denied.")
                    )
                else:
                    await broadcast_message(
                        "tool_call",
                        json.dumps(
                            {
                                "name": fn_name,
                                "args": safe_args,
                                "server": server_name,
                                "status": "calling",
                            }
                        ),
                    )

                    # Execute (terminal interception or standard MCP)
                    try:
                        if idx in spawn_results and pre_hook_result.updated_input is None:
                            result = spawn_results[idx]
                        elif fn_name == "spawn_agent" and server_name == "sub_agent":
                            from ...services.skills_runtime.sub_agent import execute_sub_agents_parallel

                            results = await execute_sub_agents_parallel(
                                [_build_spawn_agent_request(effective_args)]
                            )
                            result = results[0] if results else ""
                        elif is_terminal_tool(fn_name, server_name):
                            result = await execute_terminal_tool(
                                fn_name, effective_args, server_name
                            )
                        elif is_video_watcher_tool(fn_name, server_name):
                            result = await execute_video_watcher_tool(
                                fn_name, effective_args, server_name
                            )
                        elif is_memory_tool(fn_name, server_name):
                            result = await execute_memory_tool(
                                fn_name, effective_args, server_name
                            )
                        elif server_name == "skills" and fn_name in (
                            "list_skills",
                            "use_skill",
                        ):
                            try:
                                result = execute_skill_tool(fn_name, effective_args)
                            except Exception as e:
                                logger.warning(
                                    "Skills tool error for %s: %s", fn_name, e
                                )
                                result = f"Error executing skill tool: {e}"
                        elif is_scheduler_tool(fn_name, server_name):
                            result = await execute_scheduler_tool(
                                fn_name, effective_args, server_name
                            )
                        else:
                            result = await mcp_manager.call_tool(
                                fn_name, effective_args
                            )
                    except Exception as e:
                        logger.warning(
                            "Tool execution failed for %s on server '%s' (%s)",
                            fn_name,
                            server_name,
                            type(e).__name__,
                        )
                        result = "System error: tool execution failed. See server logs for details."

                tool_failed = isinstance(result, str) and result.startswith(
                    ("Error:", "System error:")
                )
                if not pre_hook_result.blocked:
                    if tool_failed:
                        post_hook_result = await hooks_runtime.dispatch_post_tool_use_failure(
                            fn_name,
                            effective_args,
                            str(result),
                            server_name=server_name,
                        )
                    else:
                        post_hook_result = await hooks_runtime.dispatch_post_tool_use(
                            fn_name,
                            effective_args,
                            result,
                            server_name=server_name,
                        )
                    if not post_hook_result.suppress_output:
                        hook_context_messages.extend(post_hook_result.system_messages)
                        hook_context_messages.extend(post_hook_result.additional_context)
                    if (
                        post_hook_result.updated_mcp_tool_output is not None
                        and mcp_manager.tool_uses_mcp_session(fn_name)
                    ):
                        result = post_hook_result.updated_mcp_tool_output
                    if post_hook_result.blocked:
                        result = (
                            "Error: Blocked by Claude-compatible hook: "
                            + (post_hook_result.reason or "Tool output was blocked.")
                        )

                # Handle image results specially for Ollama
                is_image_result = (
                    isinstance(result, dict) and result.get("type") == "image"
                )
                if (
                    is_image_result
                    and isinstance(result, dict)
                    and not hook_context_messages
                ):
                    # For broadcast and storage, use a summary
                    result_str = f"[Image: {result.get('width', '?')}x{result.get('height', '?')}, {result.get('file_size_bytes', 0):,} bytes]"
                else:
                    if isinstance(result, dict):
                        serialized_result = json.dumps(
                            result, ensure_ascii=False, default=str
                        )
                    else:
                        serialized_result = str(result)
                    if hook_context_messages:
                        serialized_result = (
                            serialized_result
                            + "\n\n[Claude-compatible hook context]\n"
                            + "\n\n".join(
                                message
                                for message in hook_context_messages
                                if message
                            )
                        )
                    result_str = _truncate_result(serialized_result)
                logger.debug("Tool result:\n%s...", result_str[:100])

                await broadcast_message(
                    "tool_call",
                    json.dumps(
                        {
                            "name": fn_name,
                            "args": safe_args,
                            "result": result_str,
                            "server": server_name,
                            "status": "complete",
                        }
                    ),
                )

            tool_calls_made.append(
                {
                    "name": fn_name,
                    "args": safe_args,
                    "result": result_str,
                    "server": server_name,
                }
            )
            interleaved_blocks.append(
                {
                    "type": "tool_call",
                    "name": fn_name,
                    "args": safe_args,
                    "server": server_name,
                }
            )

            # For Ollama, we need to save image to temp file and use images key
            # is_image_result is only True when result is a dict (set in else block)
            if is_image_result and isinstance(result, dict):
                # Save base64 image to temp file for Ollama
                temp_path = await _save_temp_image_for_ollama(result)
                if temp_path:
                    messages.append(
                        {
                            "role": "tool",
                            "content": result_str,
                            "name": fn_name,
                            "images": [temp_path],
                        }
                    )
                else:
                    # Fallback to text-only if save failed
                    messages.append(
                        {"role": "tool", "content": result_str, "name": fn_name}
                    )
            else:
                messages.append(
                    {"role": "tool", "content": result_str, "name": fn_name}
                )

        if is_current_request_cancelled():
            break

        # ── Stream follow-up call ─────────────────────────────────
        # Text is broadcast to the user in real-time inside this call
        follow_up_result = await _stream_tool_follow_up(
            messages,
            filtered_tools,
            interleaved_blocks=interleaved_blocks,
            client=async_client,
            include_model_content=True,
        )
        if len(follow_up_result) == 5:
            (
                current_content,
                current_model_content,
                current_tool_calls,
                round_stats,
                current_thinking,
            ) = follow_up_result
        else:
            (
                current_content,
                current_tool_calls,
                round_stats,
                current_thinking,
            ) = follow_up_result
            current_model_content = current_content or None

        total_token_stats["prompt_eval_count"] += round_stats.get(
            "prompt_eval_count", 0
        )
        total_token_stats["eval_count"] += round_stats.get("eval_count", 0)
        is_first_round = False

        # If no more tool calls, the final text was already streamed
        if not current_tool_calls:
            if current_content:
                all_accumulated_text.append(current_content)
            break

    # Broadcast response_complete (text was streamed throughout the loop)
    if tool_calls_made:
        await broadcast_message("response_complete", "")
        await broadcast_message("token_usage", json.dumps(total_token_stats))
        logger.info(
            "Tool loop complete after %d round(s) with interleaved streaming", rounds
        )
        return (
            messages,
            tool_calls_made,
            {
                "content": "".join(all_accumulated_text),
                "token_stats": total_token_stats,
                "already_streamed": True,
                "interleaved_blocks": interleaved_blocks,
            },
        )

    return messages, tool_calls_made, None


async def _stream_tool_follow_up(
    messages: List[Dict[str, Any]],
    tools: list,
    interleaved_blocks: Optional[List[Dict[str, Any]]] = None,
    client: Optional[OllamaAsyncClient] = None,
    *,
    include_model_content: bool = False,
) -> tuple[str, List[Dict[str, Any]], Dict[str, int], str] | tuple[
    str, Optional[str], List[Dict[str, Any]], Dict[str, int], str
]:
    """
    Stream a follow-up Ollama call during the tool loop.

    Broadcasts text chunks to the user in real-time using the async client.
    Collects any tool calls that appear in the stream for the next round.

    Returns:
      default: (visible_text, tool_calls_found, token_stats, thinking_text)
      include_model_content=True:
          (visible_text, model_content, tool_calls_found, token_stats, thinking_text)
    """
    async_client = client or OllamaAsyncClient()
    active_interleaved_blocks = interleaved_blocks if interleaved_blocks is not None else []

    async def _consume_stream(
        think_enabled: bool,
    ) -> tuple[str, Optional[str], List[Dict[str, Any]], Dict[str, int], str]:
        text_chunks: list[str] = []
        current_round_blocks: List[Dict[str, Any]] = []
        thinking_chunks: list[str] = []
        tool_calls_found: List[Dict[str, Any]] = []
        token_stats: Dict[str, int] = {"prompt_eval_count": 0, "eval_count": 0}
        thinking_complete_sent = False
        artifact_parser = ArtifactStreamParser()

        stream = await async_client.chat(
            model=_get_request_model(),
            messages=messages,
            tools=tools,
            stream=True,
            think=think_enabled,
        )

        async for chunk in stream:
            if is_current_request_cancelled():
                break

            message_obj = getattr(chunk, "message", None)
            message_dict = chunk.get("message") if isinstance(chunk, dict) else None

            content_token = None
            thinking_token = None
            tool_calls = None

            if message_obj is not None:
                content_val = getattr(message_obj, "content", None)
                if isinstance(content_val, str) and content_val:
                    content_token = content_val

                thinking_val = getattr(message_obj, "thinking", None)
                if isinstance(thinking_val, str) and thinking_val:
                    thinking_token = thinking_val

                tool_calls = getattr(message_obj, "tool_calls", None)
            elif isinstance(message_dict, dict):
                content_val = message_dict.get("content")
                if isinstance(content_val, str) and content_val:
                    content_token = content_val

                thinking_val = message_dict.get("thinking")
                if isinstance(thinking_val, str) and thinking_val:
                    thinking_token = thinking_val

                tool_calls = message_dict.get("tool_calls")

            if thinking_token:
                thinking_chunks.append(thinking_token)
                await broadcast_message("thinking_chunk", thinking_token)

            if content_token:
                if thinking_chunks and not thinking_complete_sent:
                    await broadcast_message("thinking_complete", "")
                    active_interleaved_blocks.append(
                        {"type": "thinking", "content": "".join(thinking_chunks)}
                    )
                    thinking_complete_sent = True
                events = artifact_parser.feed(content_token)
                cleaned_text = apply_artifact_stream_events(
                    events,
                    current_round_blocks,
                )
                await emit_artifact_stream_events(
                    events,
                    active_interleaved_blocks,
                    broadcaster=broadcast_message,
                )
                if cleaned_text:
                    text_chunks.append(cleaned_text)

            if tool_calls:
                for tc in tool_calls:
                    fn_name = "unknown"
                    raw_args: Any = {}

                    if hasattr(tc, "function") and tc.function is not None:
                        fn_name = getattr(tc.function, "name", "unknown")
                        raw_args = getattr(tc.function, "arguments", {})
                    elif isinstance(tc, dict):
                        function_data = tc.get("function", {})
                        if isinstance(function_data, dict):
                            fn_name = function_data.get("name", "unknown")
                            raw_args = function_data.get("arguments", {})

                    parsed_args, arg_error = normalize_tool_args(raw_args)
                    tool_calls_found.append(
                        {
                            "name": fn_name,
                            "args": parsed_args,
                            "arg_error": arg_error,
                            "raw_args": raw_args,
                        }
                    )

            # Track token stats on done
            if hasattr(chunk, "done") and getattr(chunk, "done"):
                token_stats["prompt_eval_count"] = (
                    getattr(chunk, "prompt_eval_count", 0) or 0
                )
                token_stats["eval_count"] = getattr(chunk, "eval_count", 0) or 0
            elif isinstance(chunk, dict) and chunk.get("done"):
                token_stats["prompt_eval_count"] = (
                    chunk.get("prompt_eval_count", 0) or 0
                )
                token_stats["eval_count"] = chunk.get("eval_count", 0) or 0

        if thinking_chunks and not thinking_complete_sent:
            await broadcast_message("thinking_complete", "")
            active_interleaved_blocks.append(
                {"type": "thinking", "content": "".join(thinking_chunks)}
            )
            thinking_complete_sent = True

        final_events = artifact_parser.finalize()
        if final_events:
            cleaned_text = apply_artifact_stream_events(
                final_events,
                current_round_blocks,
            )
            await emit_artifact_stream_events(
                final_events,
                active_interleaved_blocks,
                broadcaster=broadcast_message,
            )
            if cleaned_text:
                text_chunks.append(cleaned_text)

        visible_text = "".join(text_chunks)
        return (
            visible_text,
            serialize_blocks_for_model_content(
                current_round_blocks,
                fallback_text=visible_text,
            )
            or None,
            tool_calls_found,
            token_stats,
            "".join(thinking_chunks),
        )

    try:
        text, model_content, tool_calls_found, token_stats, thinking_text = await _consume_stream(
            think_enabled=True
        )
        if (
            not text
            and not model_content
            and not thinking_text
            and not tool_calls_found
            and not is_current_request_cancelled()
        ):
            logger.debug(
                "Ollama tool follow-up with think=True returned no output; retrying with think=False"
            )
            text, model_content, tool_calls_found, token_stats, thinking_text = await _consume_stream(
                think_enabled=False
            )

        if include_model_content:
            return text, model_content, tool_calls_found, token_stats, thinking_text
        return text, tool_calls_found, token_stats, thinking_text

    except Exception as e:
        if not is_current_request_cancelled():
            logger.warning(
                "Error in thinking-enabled streaming follow-up (%s), retrying think=False",
                type(e).__name__,
            )
            try:
                text, model_content, tool_calls_found, token_stats, thinking_text = await _consume_stream(
                    think_enabled=False
                )
                if include_model_content:
                    return (
                        text,
                        model_content,
                        tool_calls_found,
                        token_stats,
                        thinking_text,
                    )
                return text, tool_calls_found, token_stats, thinking_text
            except Exception as fallback_error:
                logger.error("Error in streaming follow-up: %s", fallback_error)
                await broadcast_message(
                    "error", "Tool follow-up streaming error. Please retry."
                )

    if include_model_content:
        return "", None, [], {"prompt_eval_count": 0, "eval_count": 0}, ""
    return "", [], {"prompt_eval_count": 0, "eval_count": 0}, ""
