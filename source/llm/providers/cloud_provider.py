"""
Cloud LLM provider streaming integration with inline tool calling.

Uses LiteLLM as a unified interface to Anthropic (Claude), OpenAI,
Google Gemini, and OpenRouter. All providers share a single streaming implementation
(``_stream_litellm``).  When a model requests a tool call mid-stream,
the tool is executed and the results are fed back — the user sees the
entire process (text → tool → text → tool → text) as a continuous,
transparent flow.

Same return signature as stream_ollama_chat for drop-in compatibility.
"""

import base64
import copy
import json
import logging
import os
from typing import AsyncIterator, List, Dict, Any, Optional, Set, cast

import litellm

from ...core.connection import broadcast_message
from ...infrastructure.config import MAX_MCP_TOOL_ROUNDS, REASONING_EFFORT
from ...core.request_context import is_current_request_cancelled
from ..core.artifacts import (
    ArtifactStreamParser,
    apply_artifact_stream_events,
    emit_artifact_stream_events,
    serialize_blocks_for_model_content,
)
from ..core.stream_recovery import (
    MID_STREAM_RETRY_LIMIT,
    get_mid_stream_generated_suffix,
)
from ..core.provider_errors import build_provider_error_message
from ...mcp_integration.core.tool_args import normalize_tool_args, sanitize_tool_args
from ...mcp_integration.core.tool_output import format_tool_output

logger = logging.getLogger(__name__)

# Let LiteLLM handle provider-specific quirks automatically.
# Critical for Anthropic thinking + tools: drops the ``thinking`` param
# when prior assistant messages lack ``thinking_blocks``.
litellm.modify_params = True

# Suppress litellm's internal info-level HTTP logs (very noisy).
litellm.suppress_debug_info = True

_MAX_INLINE_IMAGE_BYTES = 50 * 1024 * 1024


def _load_image_as_base64(path: str) -> Optional[str]:
    """Load an image file and return its base64-encoded content."""
    try:
        file_size = os.path.getsize(path)
        if file_size > _MAX_INLINE_IMAGE_BYTES:
            logger.warning(
                "Skipping oversized image %s (%d bytes)",
                os.path.basename(path),
                file_size,
            )
            return None

        with open(path, "rb") as f:
            return base64.standard_b64encode(f.read()).decode("utf-8")
    except Exception as e:
        logger.error(
            "Failed to load image %s (%s)",
            os.path.basename(path),
            type(e).__name__,
        )
        return None


def _guess_media_type(path: str) -> str:
    """Guess the MIME type from a file extension."""
    ext = os.path.splitext(path)[1].lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(ext, "image/png")


def _truncate_tool_result(result: str) -> str:
    """Truncate excessively large tool results."""
    from ...infrastructure.config import MAX_TOOL_RESULT_LENGTH

    result_str = str(result)
    if len(result_str) > MAX_TOOL_RESULT_LENGTH:
        logger.warning("Truncating large tool output (%d chars)", len(result_str))
        return (
            result_str[:MAX_TOOL_RESULT_LENGTH] + "... [Output truncated due to length]"
        )
    return result_str


def _format_image(b64: str, media_type: str) -> dict:
    """Format an image block in OpenAI vision format (used by all providers via LiteLLM)."""
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{media_type};base64,{b64}"},
    }


def _build_user_content(text: str, image_paths: List[str]) -> Any:
    """Return either plain text or multipart user content with images."""
    parts: List[Dict[str, Any]] = []

    for img_path in image_paths:
        if not os.path.exists(img_path):
            continue

        b64 = _load_image_as_base64(img_path)
        if b64:
            parts.append(_format_image(b64, _guess_media_type(img_path)))

    if not parts:
        return text

    parts.append({"type": "text", "text": text})
    return parts


def _append_tool_result(
    fn_name: str,
    fn_args: Dict[str, Any],
    result_str: str,
    server_name: str,
    tool_calls_list: List[Dict[str, Any]],
    interleaved_blocks: List[Dict[str, Any]],
) -> None:
    """Record a tool result for persistence and UI reconstruction."""
    safe_args = sanitize_tool_args(fn_name, server_name, fn_args)
    tool_calls_list.append(
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


def _build_spawn_agent_request(fn_args: Dict[str, Any]) -> Dict[str, Any]:
    """Build the normalized sub-agent batch payload from tool arguments."""
    return {
        "instruction": fn_args.get("instruction", ""),
        "model_tier": fn_args.get("model_tier", "fast"),
        "agent_name": fn_args.get("agent_name", "Sub-Agent"),
    }


# ---------------------------------------------------------------------------
# Message builder (unified OpenAI format — LiteLLM translates per-provider)
# ---------------------------------------------------------------------------


def _build_messages(
    chat_history: List[Dict[str, Any]],
    user_query: str,
    image_paths: List[str],
    system_prompt: str = "",
) -> List[Dict[str, Any]]:
    """Build an OpenAI-format message list from chat history.

    LiteLLM translates these to the native format for each provider.
    Images use the OpenAI ``image_url`` content part format.
    """
    messages: List[Dict[str, Any]] = []

    # System prompt
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    # History — only role + content are extracted.  This naturally strips
    # any "tool_calls" metadata from persisted assistant messages and skips
    # transient "tool" role results, keeping the history schema-clean for
    # all providers.
    for msg in chat_history:
        role = msg["role"]
        content = msg["content"]

        if role == "tool":
            continue

        if role == "user" and msg.get("images"):
            messages.append(
                {
                    "role": "user",
                    "content": _build_user_content(content, msg["images"]),
                }
            )
        else:
            messages.append({"role": role, "content": content})

    # Current user message
    messages.append(
        {"role": "user", "content": _build_user_content(user_query, image_paths)}
    )

    return messages


# ---------------------------------------------------------------------------
# Shared tool execution helper
# ---------------------------------------------------------------------------


async def _execute_and_broadcast_tool(
    fn_name: str,
    fn_args: Dict[str, Any],
    provider_label: str,
    tool_calls_list: List[Dict[str, Any]],
    interleaved_blocks: List[Dict[str, Any]],
    *,
    precomputed_result: Optional[str] = None,
) -> str | Dict[str, Any]:
    """Execute a single MCP tool call, broadcast progress, and record results.

    This is the common core shared by all cloud providers.  The caller
    is responsible for appending the tool result message to the conversation.

    Returns:
        str: The (possibly truncated) result string for normal tools
        dict: An image result dict {"type": "image", ...} for image tools
    """
    from ...mcp_integration.core.manager import mcp_manager
    from ...mcp_integration.executors.terminal_executor import is_terminal_tool, execute_terminal_tool
    from ...mcp_integration.executors.video_watcher_executor import is_video_watcher_tool, execute_video_watcher_tool
    from ...mcp_integration.executors.memory_executor import is_memory_tool, execute_memory_tool
    from ...mcp_integration.executors.skills_executor import execute_skill_tool
    from ...mcp_integration.executors.scheduler_executor import is_scheduler_tool, execute_scheduler_tool
    from ...services.hooks_runtime import get_hooks_runtime

    try:
        server_name = mcp_manager.get_tool_server_name(fn_name) or "unknown"
    except Exception as e:
        logger.warning(
            "%s tool server lookup failed for %s (%s)",
            provider_label,
            fn_name,
            type(e).__name__,
        )
        server_name = "unknown"

    hooks_runtime = get_hooks_runtime()
    effective_args = copy.deepcopy(fn_args)
    pre_hook_result = await hooks_runtime.dispatch_pre_tool_use(
        fn_name,
        effective_args,
        server_name=server_name,
    )
    if pre_hook_result.updated_input is not None:
        effective_args = copy.deepcopy(pre_hook_result.updated_input)

    logger.info(
        "%s tool call: %s(%s) from '%s'",
        provider_label,
        fn_name,
        sanitize_tool_args(fn_name, server_name, effective_args),
        server_name,
    )

    safe_args = sanitize_tool_args(fn_name, server_name, effective_args)
    hook_context_messages: list[str] = []
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

        try:
            if precomputed_result is not None and pre_hook_result.updated_input is None:
                result = precomputed_result
            elif fn_name == "spawn_agent" and server_name == "sub_agent":
                from ...services.skills_runtime.sub_agent import execute_sub_agents_parallel

                results = await execute_sub_agents_parallel(
                    [_build_spawn_agent_request(effective_args)]
                )
                result = results[0] if results else ""
            elif is_terminal_tool(fn_name, server_name):
                result = await execute_terminal_tool(fn_name, effective_args, server_name)
            elif is_video_watcher_tool(fn_name, server_name):
                result = await execute_video_watcher_tool(fn_name, effective_args, server_name)
            elif is_memory_tool(fn_name, server_name):
                result = await execute_memory_tool(fn_name, effective_args, server_name)
            elif server_name == "skills" and fn_name in ("list_skills", "use_skill"):
                result = execute_skill_tool(fn_name, effective_args)
            elif is_scheduler_tool(fn_name, server_name):
                result = await execute_scheduler_tool(fn_name, effective_args, server_name)
            else:
                result = await mcp_manager.call_tool(fn_name, effective_args)
        except Exception as e:
            logger.warning(
                "%s tool execution failed for %s on '%s' (%s)",
                provider_label,
                fn_name,
                server_name,
                type(e).__name__,
            )
            result = "System error: tool execution failed. See server logs for details."

    tool_failed = isinstance(result, str) and result.startswith(("Error:", "System error:"))
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

    if isinstance(result, dict) and result.get("type") == "image" and not hook_context_messages:
        result_summary = f"[Image: {result.get('width', '?')}x{result.get('height', '?')}, {result.get('file_size_bytes', 0):,} bytes]"
        await broadcast_message(
            "tool_call",
            json.dumps(
                {
                    "name": fn_name,
                    "args": safe_args,
                    "result": result_summary,
                    "server": server_name,
                    "status": "complete",
                }
            ),
        )
        _append_tool_result(
            fn_name,
            effective_args,
            result_summary,
            server_name,
            tool_calls_list,
            interleaved_blocks,
        )
        return result

    formatted_result = format_tool_output(result)
    if isinstance(formatted_result, dict):
        serialized_result = json.dumps(
            formatted_result, ensure_ascii=False, default=str
        )
    else:
        serialized_result = str(formatted_result)
    if hook_context_messages:
        serialized_result = (
            serialized_result
            + "\n\n[Claude-compatible hook context]\n"
            + "\n\n".join(message for message in hook_context_messages if message)
        )
    result_str = _truncate_tool_result(serialized_result)
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

    _append_tool_result(
        fn_name,
        effective_args,
        result_str,
        server_name,
        tool_calls_list,
        interleaved_blocks,
    )

    return result_str


# ---------------------------------------------------------------------------
# Provider-specific parameter helpers
# ---------------------------------------------------------------------------


def _get_reasoning_params(
    litellm_model: str,
    model_info: Optional[Any] = None,
) -> Dict[str, Any]:
    """Build reasoning/thinking parameters if the model supports it.

    Uses ``litellm.get_model_info()`` for capability detection — no hardcoded
    model names or keyword lists.  Returns a ``reasoning_effort`` kwarg that
    LiteLLM translates to the native format for each provider:

    - Anthropic → ``thinking`` parameter with budget_tokens
    - Gemini 2.5 → ``thinkingConfig`` with budget_tokens
    - Gemini 3+ → ``thinking_level``
    - OpenAI → native ``reasoning_effort``
    """
    try:
        resolved_model_info = model_info or litellm.get_model_info(litellm_model)
        if not resolved_model_info.get("supports_reasoning", False):
            return {}
    except Exception:
        logger.debug(
            "Model %s not in litellm registry, skipping reasoning params",
            litellm_model,
        )
        return {}

    return {"reasoning_effort": REASONING_EFFORT}


def _get_max_tokens(
    litellm_model: str,
    model_info: Optional[Any] = None,
) -> Optional[int]:
    """Look up the model's maximum output tokens via litellm.

    Returns the model's native ``max_output_tokens`` if known, ``None``
    otherwise.  No hardcoded limits — each model gets its full capacity.
    Providers that require ``max_tokens`` (e.g. Anthropic) are satisfied
    automatically.
    """
    try:
        resolved_model_info = model_info or litellm.get_model_info(litellm_model)
        return resolved_model_info.get("max_output_tokens")
    except Exception:
        logger.debug(
            "Model %s not in litellm registry, skipping max_tokens",
            litellm_model,
        )
        return None


def _litellm_provider_for(provider: str) -> str:
    """Map Xpdite provider names to LiteLLM provider names."""
    if provider == "openai-codex":
        return "chatgpt"
    return provider


def _provider_log_label(provider: str) -> str:
    if provider == "openai-codex":
        return "ChatGPT subscription"
    return provider.capitalize()


# ---------------------------------------------------------------------------
# Unified LiteLLM streaming implementation
# ---------------------------------------------------------------------------


async def _stream_litellm(
    provider: str,
    api_key: str,
    model: str,
    user_query: str,
    image_paths: List[str],
    chat_history: List[Dict[str, Any]],
    allowed_tool_names: Optional[Set[str]] = None,
    system_prompt: str = "",
) -> tuple[str, Dict[str, int], List[Dict[str, Any]], Optional[List[Dict[str, Any]]]]:
    """
    Stream a response from any cloud LLM provider via LiteLLM with interleaved
    tool calling.

    Tool call deltas are accumulated during streaming.  After the stream ends,
    if any tool call deltas were received the tools are executed and results fed
    back for the next streaming round.  The presence of accumulated tool call
    deltas is the trigger — not ``finish_reason`` — because providers like
    Gemini may use a non-standard finish reason (e.g. ``"stop"``).
    Text and thinking tokens are broadcast continuously in real-time.

    Returns:
        (response_text, token_stats, tool_calls_list, interleaved_blocks | None)
    """
    from ...mcp_integration.core.manager import mcp_manager

    litellm_provider = _litellm_provider_for(provider)
    if provider == "openai-codex":
        from ...services.integrations.openai_codex import openai_codex

        openai_codex.configure_litellm_environment()

    # Build unified message list
    messages = _build_messages(chat_history, user_query, image_paths, system_prompt)

    # State accumulators (persist across all rounds)
    tool_calls_list: List[Dict[str, Any]] = []
    all_accumulated: list[str] = []
    total_token_stats: Dict[str, int] = {"prompt_eval_count": 0, "eval_count": 0}
    interleaved_blocks: List[Dict[str, Any]] = []

    # LiteLLM model string: "provider/model-name"
    litellm_model = f"{litellm_provider}/{model}"

    # Query model info once and derive all model-specific params from it.
    # This avoids redundant get_model_info() calls per round.
    try:
        model_info = litellm.get_model_info(litellm_model)
    except Exception:
        logger.debug("Model %s not in litellm registry", litellm_model)
        model_info = {}

    # Max output tokens — no hardcoded limits.  Each model gets its native
    # capacity.  Providers that *require* max_tokens (Anthropic) are
    # satisfied automatically; others simply get their full limit.
    # For unknown Anthropic models not in the registry, use a safe fallback
    # since Anthropic's API mandates the max_tokens parameter.
    max_tokens = _get_max_tokens(litellm_model, model_info)
    if max_tokens is None and litellm_provider == "anthropic":
        max_tokens = 16384
        logger.debug(
            "Anthropic model not in registry; using fallback max_tokens=%d", max_tokens
        )

    # Reasoning params (hoisted outside the loop — model doesn't change)
    reasoning_params = _get_reasoning_params(litellm_model, model_info)

    try:
        if is_current_request_cancelled():
            return "", total_token_stats, tool_calls_list, None

        tools: Optional[List[Dict]] = None
        if allowed_tool_names:
            try:
                all_tools = mcp_manager.get_tools()
            except Exception as e:
                logger.warning(
                    "Failed to resolve tool definitions for %s/%s (%s); continuing without tools",
                    provider,
                    model,
                    type(e).__name__,
                )
                all_tools = []

            if all_tools:
                tools = [
                    t for t in all_tools if t["function"]["name"] in allowed_tool_names
                ]
                if not tools:
                    tools = None

        rounds = 0
        has_more = True
        while has_more:
            # Per-round state resets
            current_round_blocks: List[Dict[str, Any]] = []
            thinking_tokens: list[str] = []
            thinking_complete_sent = False
            artifact_parser = ArtifactStreamParser()
            round_prompt_tokens = 0
            round_completion_tokens = 0
            round_raw_text_chunks: list[str] = []

            def _store_thinking_block() -> None:
                nonlocal thinking_complete_sent
                if thinking_tokens and not thinking_complete_sent:
                    interleaved_blocks.append(
                        {"type": "thinking", "content": "".join(thinking_tokens)}
                    )
                    thinking_complete_sent = True

            if is_current_request_cancelled():
                break

            rounds += 1

            # Safety valve: tool rounds + 1 summarisation round
            if rounds > MAX_MCP_TOOL_ROUNDS + 1:
                logger.warning(
                    "Exceeded max rounds (%d + 1 summarisation), forcing stop",
                    MAX_MCP_TOOL_ROUNDS,
                )
                break

            # Only offer tools within the tool-calling budget
            allow_tools = tools is not None and rounds <= MAX_MCP_TOOL_ROUNDS

            # Build acompletion kwargs
            create_kwargs: Dict[str, Any] = {
                "model": litellm_model,
                "messages": messages,
                "stream": True,
                "stream_options": {"include_usage": True},
                "timeout": 300.0,
            }
            if api_key:
                create_kwargs["api_key"] = api_key

            if max_tokens is not None and max_tokens > 0:
                create_kwargs["max_tokens"] = max_tokens

            if reasoning_params:
                create_kwargs.update(reasoning_params)

            if allow_tools:
                create_kwargs["tools"] = tools

            logger.debug(
                "LiteLLM acompletion: model=%s, round=%d/%d, reasoning=%s, tools=%d, messages=%d",
                litellm_model,
                rounds,
                MAX_MCP_TOOL_ROUNDS,
                "enabled" if reasoning_params else "disabled",
                len(tools) if allow_tools and tools else 0,
                len(messages),
            )

            # Accumulate tool call deltas during streaming
            pending_tool_calls: Dict[int, Dict[str, str]] = {}
            finish_reason = None
            stream_retry_count = 0

            while True:
                try:
                    response = cast(
                        AsyncIterator[Any], await litellm.acompletion(**create_kwargs)
                    )

                    async for chunk in response:
                        if is_current_request_cancelled():
                            break

                        # Capture usage from ANY chunk that carries it.
                        # LiteLLM normalises provider-native usage into the
                        # OpenAI `usage` shape, but the chunk it lands on varies:
                        #   OpenAI  → separate usage-only chunk (choices=[])
                        #   Anthropic/Gemini → may be on the final content chunk
                        # Using assignment (last value wins) avoids double-counting
                        # if both a content chunk and a usage-only chunk carry data.
                        if hasattr(chunk, "usage") and chunk.usage:
                            prompt = getattr(chunk.usage, "prompt_tokens", 0) or 0
                            completion = getattr(chunk.usage, "completion_tokens", 0) or 0
                            if prompt or completion:
                                round_prompt_tokens = prompt
                                round_completion_tokens = completion

                        if not chunk.choices:
                            continue

                        choice = chunk.choices[0]
                        delta = choice.delta
                        finish_reason = choice.finish_reason or finish_reason

                        # Handle reasoning/thinking content
                        # LiteLLM normalizes this across providers into delta.reasoning_content
                        reasoning = getattr(delta, "reasoning_content", None)
                        if reasoning:
                            thinking_tokens.append(reasoning)
                            await broadcast_message("thinking_chunk", reasoning)

                        # Handle regular text content
                        if delta.content:
                            round_raw_text_chunks.append(delta.content)
                            events = artifact_parser.feed(delta.content)
                            if events and thinking_tokens and not thinking_complete_sent:
                                await broadcast_message("thinking_complete", "")
                                _store_thinking_block()
                            cleaned_text = apply_artifact_stream_events(
                                events,
                                current_round_blocks,
                            )
                            await emit_artifact_stream_events(
                                events,
                                interleaved_blocks,
                                broadcaster=broadcast_message,
                            )
                            if cleaned_text:
                                all_accumulated.append(cleaned_text)

                        # Accumulate tool call deltas
                        if delta.tool_calls:
                            for tc_delta in delta.tool_calls:
                                idx = tc_delta.index
                                if idx not in pending_tool_calls:
                                    pending_tool_calls[idx] = {
                                        "id": "",
                                        "name": "",
                                        "arguments": "",
                                    }
                                if tc_delta.id:
                                    pending_tool_calls[idx]["id"] = tc_delta.id
                                if tc_delta.function:
                                    if tc_delta.function.name:
                                        pending_tool_calls[idx]["name"] = tc_delta.function.name
                                    if tc_delta.function.arguments:
                                        pending_tool_calls[idx]["arguments"] += (
                                            tc_delta.function.arguments
                                        )
                    break
                except litellm.exceptions.MidStreamFallbackError as e:
                    recovered_suffix = get_mid_stream_generated_suffix(
                        "".join(round_raw_text_chunks),
                        getattr(e, "generated_content", "") or "",
                    )
                    if recovered_suffix:
                        round_raw_text_chunks.append(recovered_suffix)
                        events = artifact_parser.feed(recovered_suffix)
                        if events and thinking_tokens and not thinking_complete_sent:
                            await broadcast_message("thinking_complete", "")
                            _store_thinking_block()
                        cleaned_text = apply_artifact_stream_events(
                            events,
                            current_round_blocks,
                        )
                        await emit_artifact_stream_events(
                            events,
                            interleaved_blocks,
                            broadcaster=broadcast_message,
                        )
                        if cleaned_text:
                            all_accumulated.append(cleaned_text)
                        logger.warning(
                            "%s mid-stream fallback recovered %d trailing chars for %s/%s (%s)",
                            _provider_log_label(provider),
                            len(recovered_suffix),
                            provider,
                            model,
                            type(e.original_exception).__name__
                            if e.original_exception is not None
                            else type(e).__name__,
                        )
                        break

                    if e.is_pre_first_chunk and stream_retry_count < MID_STREAM_RETRY_LIMIT:
                        stream_retry_count += 1
                        logger.warning(
                            "%s stream failed before first chunk for %s/%s; retrying round %d/%d (%s)",
                            _provider_log_label(provider),
                            provider,
                            model,
                            stream_retry_count,
                            MID_STREAM_RETRY_LIMIT,
                            type(e.original_exception).__name__
                            if e.original_exception is not None
                            else type(e).__name__,
                        )
                        continue

                    raise

            # Add this round's usage to running totals (summed across rounds)
            total_token_stats["prompt_eval_count"] += round_prompt_tokens
            total_token_stats["eval_count"] += round_completion_tokens

            # Finalize thinking section in UI for this round
            if thinking_tokens and not thinking_complete_sent:
                await broadcast_message("thinking_complete", "")
                _store_thinking_block()

            final_events = artifact_parser.finalize()
            if final_events:
                cleaned_text = apply_artifact_stream_events(
                    final_events,
                    current_round_blocks,
                )
                await emit_artifact_stream_events(
                    final_events,
                    interleaved_blocks,
                    broadcaster=broadcast_message,
                )
                if cleaned_text:
                    all_accumulated.append(cleaned_text)

            # After stream: check if tool calls were made.
            # Use pending_tool_calls as the primary signal instead of
            # finish_reason, because not all providers use the OpenAI
            # convention of finish_reason=="tool_calls" (e.g. Gemini
            # may return "stop" even when tool calls are present).
            if pending_tool_calls:
                if finish_reason != "tool_calls":
                    logger.debug(
                        "Provider %s returned tool calls with finish_reason=%r "
                        "(expected 'tool_calls'); proceeding with execution.",
                        provider,
                        finish_reason,
                    )
                # Build assistant message with tool calls
                assistant_tool_calls = []
                for idx in sorted(pending_tool_calls.keys()):
                    tc = pending_tool_calls[idx]
                    # Ensure tool call ID is present (some providers omit it)
                    if not tc["id"]:
                        tc["id"] = f"call_{rounds}_{idx}"
                    assistant_tool_calls.append(
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": tc["arguments"],
                            },
                        }
                    )

                # Build the assistant message to append
                assistant_msg: Dict[str, Any] = {
                    "role": "assistant",
                    "tool_calls": assistant_tool_calls,
                }

                # Include text content if the model produced any before tool calls
                assistant_msg["content"] = (
                    serialize_blocks_for_model_content(current_round_blocks) or None
                )

                # Execute each tool and append results
                tool_result_messages: List[Dict[str, Any]] = []
                cancelled_during_tool_loop = False

                # ── Collect spawn_agent calls for parallel execution ──
                spawn_agent_indices: List[int] = []
                spawn_agent_calls: List[Dict[str, Any]] = []
                parsed_args_by_index: Dict[int, Dict[str, Any]] = {}

                for idx, tc_info in enumerate(assistant_tool_calls):
                    fn_name = tc_info["function"]["name"]
                    raw_args = tc_info["function"]["arguments"]
                    fn_args, arg_error = normalize_tool_args(raw_args)
                    if arg_error:
                        logger.warning(
                            "Skipping spawn_agent pre-batch for malformed args on %s: %s",
                            fn_name,
                            arg_error,
                        )
                        continue
                    parsed_args_by_index[idx] = fn_args

                    from ...mcp_integration.core.manager import mcp_manager as _mm

                    try:
                        sn = _mm.get_tool_server_name(fn_name) or "unknown"
                    except Exception:
                        sn = "unknown"

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

                # Now iterate all tool calls — spawn_agents already have results
                for idx, tc_info in enumerate(assistant_tool_calls):
                    fn_name = tc_info["function"]["name"]
                    raw_args = tc_info["function"]["arguments"]

                    fn_args = parsed_args_by_index.get(idx)
                    if fn_args is None:
                        fn_args, arg_error = normalize_tool_args(raw_args)
                    else:
                        arg_error = None
                    if arg_error:
                        error_result = (
                            f"System error: invalid arguments for tool "
                            f"'{fn_name}': {arg_error}"
                        )
                        logger.warning(
                            "Malformed tool call args for %s (%d chars)",
                            fn_name,
                            len(raw_args or ""),
                        )
                        tool_result_messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc_info["id"],
                                "content": error_result,
                            }
                        )
                        _append_tool_result(
                            fn_name,
                            {},
                            error_result,
                            "unknown",
                            tool_calls_list,
                            interleaved_blocks,
                        )
                        continue

                    if (
                        allowed_tool_names is not None
                        and fn_name not in allowed_tool_names
                    ):
                        error_result = f"System error: tool '{fn_name}' is not available for this request."
                        logger.warning(
                            "Rejected unauthorized tool call from %s/%s: %s",
                            provider,
                            model,
                            fn_name,
                        )
                        tool_result_messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc_info["id"],
                                "content": error_result,
                            }
                        )
                        _append_tool_result(
                            fn_name,
                            fn_args,
                            error_result,
                            "unknown",
                            tool_calls_list,
                            interleaved_blocks,
                        )
                        continue

                    if is_current_request_cancelled():
                        has_more = False
                        cancelled_during_tool_loop = True
                        break

                    tool_result = await _execute_and_broadcast_tool(
                        fn_name,
                        fn_args,
                        _provider_log_label(provider),
                        tool_calls_list,
                        interleaved_blocks,
                        precomputed_result=spawn_results.get(idx),
                    )

                    # Append tool result in OpenAI format (LiteLLM translates)
                    # Handle image results specially - construct image content block
                    if (
                        isinstance(tool_result, dict)
                        and tool_result.get("type") == "image"
                    ):
                        # Build multipart content with image and text description
                        image_content = [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{tool_result.get('media_type', 'image/png')};base64,{tool_result.get('data', '')}"
                                },
                            },
                            {
                                "type": "text",
                                "text": f"Image: {tool_result.get('width', '?')}x{tool_result.get('height', '?')}, {tool_result.get('file_size_bytes', 0):,} bytes",
                            },
                        ]
                        tool_result_messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc_info["id"],
                                "content": image_content,
                            }
                        )
                    else:
                        # Normal string result
                        result_str = (
                            tool_result
                            if isinstance(tool_result, str)
                            else str(tool_result)
                        )
                        tool_result_messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc_info["id"],
                                "content": result_str,
                            }
                        )

                if not cancelled_during_tool_loop:
                    messages.append(assistant_msg)
                    messages.extend(tool_result_messages)

                # Propagate cancellation to outer loop
                if is_current_request_cancelled():
                    has_more = False
            else:
                # No tool calls — response is complete
                has_more = False

        # Final cleanup
        await broadcast_message("response_complete", "")
        await broadcast_message("token_usage", json.dumps(total_token_stats))

        if tool_calls_list:
            logger.info(
                "%s tool loop complete after %d round(s)",
                _provider_log_label(provider),
                rounds,
            )

        return (
            "".join(all_accumulated),
            total_token_stats,
            tool_calls_list,
            interleaved_blocks or None,
        )

    except Exception as e:
        error_msg = build_provider_error_message(provider, e)
        logger.error(
            "%s streaming error (%s): %s",
            _provider_log_label(provider),
            type(e).__name__,
            error_msg,
        )
        await broadcast_message("error", error_msg)
        # Return accumulated data so partial responses are preserved
        return (
            "".join(all_accumulated),
            total_token_stats,
            tool_calls_list,
            interleaved_blocks or None,
        )


# ---------------------------------------------------------------------------
# Public API — called by the router
# ---------------------------------------------------------------------------


async def stream_cloud_chat(
    provider: str,
    model: str,
    api_key: str,
    user_query: str,
    image_paths: List[str],
    chat_history: List[Dict[str, Any]],
    allowed_tool_names: Optional[Set[str]] = None,
    system_prompt: str = "",
) -> tuple[str, Dict[str, int], List[Dict[str, Any]], Optional[List[Dict[str, Any]]]]:
    """
    Stream a response from a cloud LLM provider with inline tool calling.

    Returns:
        (response_text, token_stats, tool_calls_list, interleaved_blocks)

    All providers use a single unified implementation via LiteLLM.
    Text and tool calls are interleaved and broadcast in real-time.
    """
    return await _stream_litellm(
        provider,
        api_key,
        model,
        user_query,
        image_paths,
        chat_history,
        allowed_tool_names,
        system_prompt,
    )


# Note: stream_cloud_chat returns a 4-tuple:
#   (response_text, token_stats, tool_calls_list, interleaved_blocks | None)
