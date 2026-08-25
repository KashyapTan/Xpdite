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
from ..core.prompt_cache import (
    mark_messages_for_anthropic_prompt_cache,
    mark_tools_for_anthropic_prompt_cache,
)
from ..core.token_usage import (
    add_token_stats,
    build_prompt_cache_key,
    empty_token_stats,
    has_token_usage,
    supports_anthropic_cache_control,
    supports_openai_prompt_cache_key,
    usage_from_litellm_chat_usage,
)
from ...mcp_integration.core.tool_args import normalize_tool_args, sanitize_tool_args

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
    """Compatibility wrapper around the provider-neutral tool executor."""
    from ..core.tool_executor import execute_and_broadcast_tool

    return await execute_and_broadcast_tool(
        fn_name,
        fn_args,
        provider_label,
        tool_calls_list,
        interleaved_blocks,
        precomputed_result=precomputed_result,
        broadcaster=broadcast_message,
    )


def _tool_result_message(
    tc_info: Dict[str, Any],
    tool_result: str | Dict[str, Any],
    result_format: str,
) -> Dict[str, Any]:
    """Build a provider input item for a completed tool call."""
    if isinstance(tool_result, dict) and tool_result.get("type") == "image":
        if result_format == "responses":
            output = (
                f"Image: {tool_result.get('width', '?')}x{tool_result.get('height', '?')}, "
                f"{tool_result.get('file_size_bytes', 0):,} bytes"
            )
            return {
                "type": "function_call_output",
                "call_id": tc_info.get("call_id") or tc_info["id"],
                "output": output,
            }

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
        return {
            "role": "tool",
            "tool_call_id": tc_info["id"],
            "content": image_content,
        }

    result_str = tool_result if isinstance(tool_result, str) else str(tool_result)
    if result_format == "responses":
        return {
            "type": "function_call_output",
            "call_id": tc_info.get("call_id") or tc_info["id"],
            "output": result_str,
        }

    return {
        "role": "tool",
        "tool_call_id": tc_info["id"],
        "content": result_str,
    }


async def _execute_assistant_tool_calls(
    assistant_tool_calls: List[Dict[str, Any]],
    *,
    provider: str,
    model: str,
    allowed_tool_names: Optional[Set[str]],
    tool_calls_list: List[Dict[str, Any]],
    interleaved_blocks: List[Dict[str, Any]],
    result_format: str,
) -> tuple[List[Dict[str, Any]], bool]:
    """Execute model-requested tools and return messages/items for the next round."""
    tool_result_messages: List[Dict[str, Any]] = []
    cancelled_during_tool_loop = False

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
            server_name = _mm.get_tool_server_name(fn_name) or "unknown"
        except Exception:
            server_name = "unknown"

        if fn_name == "spawn_agent" and server_name == "sub_agent":
            spawn_agent_indices.append(idx)
            spawn_agent_calls.append(_build_spawn_agent_request(fn_args))

    spawn_results: Dict[int, str] = {}
    if spawn_agent_calls and not is_current_request_cancelled():
        from ...services.skills_runtime.sub_agent import execute_sub_agents_parallel

        results = await execute_sub_agents_parallel(spawn_agent_calls)
        for i, result_str in enumerate(results):
            spawn_results[spawn_agent_indices[i]] = result_str

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
                f"System error: invalid arguments for tool '{fn_name}': {arg_error}"
            )
            logger.warning(
                "Malformed tool call args for %s (%d chars)",
                fn_name,
                len(raw_args or ""),
            )
            tool_result_messages.append(
                _tool_result_message(tc_info, error_result, result_format)
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

        if allowed_tool_names is not None and fn_name not in allowed_tool_names:
            error_result = (
                f"System error: tool '{fn_name}' is not available for this request."
            )
            logger.warning(
                "Rejected unauthorized tool call from %s/%s: %s",
                provider,
                model,
                fn_name,
            )
            tool_result_messages.append(
                _tool_result_message(tc_info, error_result, result_format)
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
        tool_result_messages.append(
            _tool_result_message(tc_info, tool_result, result_format)
        )

    return tool_result_messages, cancelled_during_tool_loop


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


def _provider_log_label(provider: str) -> str:
    return provider.capitalize()


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

    litellm_provider = provider

    # Build unified message list
    messages = _build_messages(chat_history, user_query, image_paths, system_prompt)

    # State accumulators (persist across all rounds)
    tool_calls_list: List[Dict[str, Any]] = []
    all_accumulated: list[str] = []
    total_token_stats: Dict[str, int] = empty_token_stats()
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

        use_anthropic_cache_control = supports_anthropic_cache_control(provider, model)
        prompt_cache_key = (
            build_prompt_cache_key(
                provider,
                model,
                system_prompt=system_prompt,
                tools=tools,
            )
            if supports_openai_prompt_cache_key(provider)
            else None
        )
        if use_anthropic_cache_control:
            messages = mark_messages_for_anthropic_prompt_cache(messages)
            tools = mark_tools_for_anthropic_prompt_cache(tools)

        rounds = 0
        has_more = True
        while has_more:
            # Per-round state resets
            current_round_blocks: List[Dict[str, Any]] = []
            thinking_tokens: list[str] = []
            thinking_complete_sent = False
            artifact_parser = ArtifactStreamParser()
            round_token_stats: Dict[str, int] = empty_token_stats()
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
            if prompt_cache_key:
                create_kwargs["prompt_cache_key"] = prompt_cache_key

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
                            parsed_usage = usage_from_litellm_chat_usage(chunk.usage)
                            if has_token_usage(parsed_usage):
                                round_token_stats = parsed_usage

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
            add_token_stats(total_token_stats, round_token_stats)

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

                tool_result_messages, cancelled_during_tool_loop = (
                    await _execute_assistant_tool_calls(
                        assistant_tool_calls,
                        provider=provider,
                        model=model,
                        allowed_tool_names=allowed_tool_names,
                        tool_calls_list=tool_calls_list,
                        interleaved_blocks=interleaved_blocks,
                        result_format="chat",
                    )
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
