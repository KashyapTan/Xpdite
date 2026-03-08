"""
Cloud LLM provider streaming integration with inline tool calling.

Uses LiteLLM as a unified interface to Anthropic (Claude), OpenAI, and
Google Gemini.  All providers share a single streaming implementation
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

from ..core.connection import broadcast_message
from ..config import MAX_MCP_TOOL_ROUNDS, REASONING_EFFORT
from ..core.request_context import is_current_request_cancelled

logger = logging.getLogger(__name__)

# Let LiteLLM handle provider-specific quirks automatically.
# Critical for Anthropic thinking + tools: drops the ``thinking`` param
# when prior assistant messages lack ``thinking_blocks``.
litellm.modify_params = True

# Suppress litellm's internal info-level HTTP logs (very noisy).
litellm.suppress_debug_info = True

_MAX_INLINE_IMAGE_BYTES = 50 * 1024 * 1024
_REDACTED_VALUE = "[REDACTED]"
_SENSITIVE_TOOL_ARG_KEYS = (
    "api_key",
    "token",
    "secret",
    "password",
    "authorization",
    "cookie",
    "session",
    "key",
)




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
    from ..config import MAX_TOOL_RESULT_LENGTH

    result_str = str(result)
    if len(result_str) > MAX_TOOL_RESULT_LENGTH:
        logger.warning("Truncating large tool output (%d chars)", len(result_str))
        return result_str[:MAX_TOOL_RESULT_LENGTH] + "... [Output truncated due to length]"
    return result_str


def _format_image(b64: str, media_type: str) -> dict:
    """Format an image block in OpenAI vision format (used by all providers via LiteLLM)."""
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{media_type};base64,{b64}"},
    }


def _sanitize_tool_args(value: Any) -> Any:
    """Redact sensitive tool arguments before exposing them outside execution."""
    if isinstance(value, dict):
        redacted: Dict[str, Any] = {}
        for key, item in value.items():
            key_lower = key.lower()
            if any(fragment in key_lower for fragment in _SENSITIVE_TOOL_ARG_KEYS):
                redacted[key] = _REDACTED_VALUE
            else:
                redacted[key] = _sanitize_tool_args(item)
        return redacted

    if isinstance(value, list):
        return [_sanitize_tool_args(item) for item in value]

    return value


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
    safe_args = _sanitize_tool_args(fn_args)
    tool_calls_list.append({
        "name": fn_name,
        "args": safe_args,
        "result": result_str,
        "server": server_name,
    })
    interleaved_blocks.append({
        "type": "tool_call",
        "name": fn_name,
        "args": safe_args,
        "server": server_name,
    })


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
            messages.append({
                "role": "user",
                "content": _build_user_content(content, msg["images"]),
            })
        else:
            messages.append({"role": role, "content": content})

    # Current user message
    messages.append({"role": "user", "content": _build_user_content(user_query, image_paths)})

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
) -> str:
    """Execute a single MCP tool call, broadcast progress, and record results.

    This is the common core shared by all cloud providers.  The caller
    is responsible for appending the tool result message to the conversation.

    Returns the (possibly truncated) result string.
    """
    from ..mcp_integration.manager import mcp_manager
    from ..mcp_integration.terminal_executor import is_terminal_tool, execute_terminal_tool

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

    logger.info(
        "%s tool call: %s(%s) from '%s'",
        provider_label,
        fn_name,
        _sanitize_tool_args(fn_args),
        server_name,
    )

    safe_args = _sanitize_tool_args(fn_args)

    await broadcast_message(
        "tool_call",
        json.dumps({
            "name": fn_name, "args": safe_args,
            "server": server_name, "status": "calling",
        }),
    )

    try:
        if is_terminal_tool(fn_name, server_name):
            result = await execute_terminal_tool(fn_name, fn_args, server_name)
        else:
            result = await mcp_manager.call_tool(fn_name, dict(fn_args))
    except Exception as e:
        logger.warning(
            "%s tool execution failed for %s on '%s' (%s)",
            provider_label,
            fn_name,
            server_name,
            type(e).__name__,
        )
        result = "System error: tool execution failed. See server logs for details."

    result_str = _truncate_tool_result(str(result))
    await broadcast_message(
        "tool_call",
        json.dumps({
            "name": fn_name, "args": safe_args, "result": result_str,
            "server": server_name, "status": "complete",
        }),
    )

    _append_tool_result(
        fn_name,
        fn_args,
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
    from ..mcp_integration.manager import mcp_manager

    # Build unified message list
    messages = _build_messages(chat_history, user_query, image_paths, system_prompt)

    # State accumulators (persist across all rounds)
    tool_calls_list: List[Dict[str, Any]] = []
    all_accumulated: list[str] = []
    total_token_stats: Dict[str, int] = {"prompt_eval_count": 0, "eval_count": 0}
    interleaved_blocks: List[Dict[str, Any]] = []

    # LiteLLM model string: "provider/model-name"
    litellm_model = f"{provider}/{model}"

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
    if max_tokens is None and provider == "anthropic":
        max_tokens = 16384
        logger.debug("Anthropic model not in registry; using fallback max_tokens=%d", max_tokens)

    # Reasoning params (hoisted outside the loop — model doesn't change)
    reasoning_params = _get_reasoning_params(litellm_model, model_info)

    current_round_text: list[str] = []
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
                tools = [t for t in all_tools if t["function"]["name"] in allowed_tool_names]
                if not tools:
                    tools = None

        rounds = 0
        has_more = True
        while has_more:
            # Per-round state resets
            current_round_text = []
            thinking_tokens: list[str] = []
            thinking_complete_sent = False
            round_prompt_tokens = 0
            round_completion_tokens = 0

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
                "api_key": api_key,
                "timeout": 300.0,
            }

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

            # Stream the response
            response = cast(AsyncIterator[Any], await litellm.acompletion(**create_kwargs))

            # Accumulate tool call deltas during streaming
            pending_tool_calls: Dict[int, Dict[str, str]] = {}
            finish_reason = None

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
                    if thinking_tokens and not thinking_complete_sent:
                        await broadcast_message("thinking_complete", "")
                        thinking_complete_sent = True
                    all_accumulated.append(delta.content)
                    current_round_text.append(delta.content)
                    await broadcast_message("response_chunk", delta.content)

                # Accumulate tool call deltas
                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        if idx not in pending_tool_calls:
                            pending_tool_calls[idx] = {"id": "", "name": "", "arguments": ""}
                        if tc_delta.id:
                            pending_tool_calls[idx]["id"] = tc_delta.id
                        if tc_delta.function:
                            if tc_delta.function.name:
                                pending_tool_calls[idx]["name"] = tc_delta.function.name
                            if tc_delta.function.arguments:
                                pending_tool_calls[idx]["arguments"] += tc_delta.function.arguments

            # Add this round's usage to running totals (summed across rounds)
            total_token_stats["prompt_eval_count"] += round_prompt_tokens
            total_token_stats["eval_count"] += round_completion_tokens

            # Finalize thinking section in UI for this round
            if thinking_tokens and not thinking_complete_sent:
                await broadcast_message("thinking_complete", "")
                thinking_complete_sent = True

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
                        provider, finish_reason,
                    )
                # Build assistant message with tool calls
                assistant_tool_calls = []
                for idx in sorted(pending_tool_calls.keys()):
                    tc = pending_tool_calls[idx]
                    # Ensure tool call ID is present (some providers omit it)
                    if not tc["id"]:
                        tc["id"] = f"call_{rounds}_{idx}"
                    assistant_tool_calls.append({
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": tc["arguments"]},
                    })

                # Build the assistant message to append
                assistant_msg: Dict[str, Any] = {
                    "role": "assistant",
                    "tool_calls": assistant_tool_calls,
                }

                # Include text content if the model produced any before tool calls
                assistant_msg["content"] = "".join(current_round_text) if current_round_text else None

                if current_round_text:
                    interleaved_blocks.append({"type": "text", "content": "".join(current_round_text)})
                    current_round_text.clear()

                # Execute each tool and append results
                tool_result_messages: List[Dict[str, str]] = []
                cancelled_during_tool_loop = False

                # ── Collect spawn_agent calls for parallel execution ──
                spawn_agent_indices: List[int] = []
                spawn_agent_calls: List[Dict[str, Any]] = []
                parsed_args_by_index: Dict[int, Dict[str, Any]] = {}

                for idx, tc_info in enumerate(assistant_tool_calls):
                    fn_name = tc_info["function"]["name"]
                    raw_args = tc_info["function"]["arguments"]
                    try:
                        fn_args = json.loads(raw_args) if raw_args else {}
                    except json.JSONDecodeError:
                        continue
                    parsed_args_by_index[idx] = fn_args

                    from ..mcp_integration.manager import mcp_manager as _mm
                    try:
                        sn = _mm.get_tool_server_name(fn_name) or "unknown"
                    except Exception:
                        sn = "unknown"

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

                # Now iterate all tool calls — spawn_agents already have results
                for idx, tc_info in enumerate(assistant_tool_calls):
                    fn_name = tc_info["function"]["name"]
                    raw_args = tc_info["function"]["arguments"]

                    try:
                        fn_args = parsed_args_by_index.get(idx)
                        if fn_args is None:
                            fn_args = json.loads(raw_args) if raw_args else {}
                    except json.JSONDecodeError:
                        error_result = (
                            f"System error: you provided invalid JSON arguments "
                            f"for tool '{fn_name}': {raw_args}"
                        )
                        logger.warning(
                            "Malformed tool call JSON for %s (%d chars)",
                            fn_name,
                            len(raw_args or ""),
                        )
                        tool_result_messages.append({
                            "role": "tool",
                            "tool_call_id": tc_info["id"],
                            "content": error_result,
                        })
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
                        tool_result_messages.append({
                            "role": "tool",
                            "tool_call_id": tc_info["id"],
                            "content": error_result,
                        })
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

                    # spawn_agent results already computed in parallel
                    if idx in spawn_results:
                        result_str = spawn_results[idx]
                        _append_tool_result(
                            fn_name,
                            fn_args,
                            result_str,
                            "sub_agent",
                            tool_calls_list,
                            interleaved_blocks,
                        )
                    else:
                        result_str = await _execute_and_broadcast_tool(
                            fn_name, fn_args, provider.capitalize(),
                            tool_calls_list, interleaved_blocks,
                        )

                    # Append tool result in OpenAI format (LiteLLM translates)
                    tool_result_messages.append({
                        "role": "tool",
                        "tool_call_id": tc_info["id"],
                        "content": result_str,
                    })

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
            logger.info("%s tool loop complete after %d round(s)", provider.capitalize(), rounds)
        if current_round_text:
            interleaved_blocks.append({"type": "text", "content": "".join(current_round_text)})

        return "".join(all_accumulated), total_token_stats, tool_calls_list, interleaved_blocks or None

    except Exception as e:
        # Keep detailed error in server logs only — exception messages
        # from LiteLLM / provider SDKs may contain API keys.
        error_msg = "LLM service temporarily unavailable. See server logs for details."
        logger.error(
            "%s streaming error (%s)",
            provider.capitalize(),
            type(e).__name__,
        )
        await broadcast_message("error", error_msg)
        # Return accumulated data so partial responses are preserved
        return "".join(all_accumulated), total_token_stats, tool_calls_list, interleaved_blocks or None


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
        provider, api_key, model, user_query, image_paths,
        chat_history, allowed_tool_names, system_prompt,
    )


# Note: stream_cloud_chat returns a 4-tuple:
#   (response_text, token_stats, tool_calls_list, interleaved_blocks | None)
