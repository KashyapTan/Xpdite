"""
Sub-agent execution service.

Executes focused, self-contained LLM calls for the ``spawn_agent`` tool.
Sub-agents receive only their instruction (no conversation history), have
access to MCP tools (minus terminal and spawn_agent), and return their
complete response as a string.

Parallelism:
- Cloud providers and remote Ollama: concurrent execution (up to cap)
- Local Ollama: sequential execution (single GPU constraint)
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import litellm

from ...infrastructure.config import MAX_MCP_TOOL_ROUNDS, MAX_TOOL_RESULT_LENGTH, OLLAMA_CTX_SIZE, USER_DATA_DIR
from ...core.connection import broadcast_message
from ...core.request_context import get_current_model, is_current_request_cancelled
from ...core.thread_pool import run_in_thread
from ...infrastructure.database import db
from ...mcp_integration.core.tool_args import normalize_tool_args

logger = logging.getLogger(__name__)

# Concurrency limit tuned for typical single-GPU setups + cloud API rate limits.
# Increase for multi-GPU hardware; cloud-only workloads may tolerate higher values.
_CONCURRENCY_CAP = 10

# Global semaphore enforced on every execute_sub_agent call
_concurrency_semaphore = asyncio.Semaphore(_CONCURRENCY_CAP)

# Hard timeout per sub-agent call (seconds)
_SUB_AGENT_TIMEOUT = 500


def _tool_progress_description(fn_name: str, fn_args: dict) -> str:
    """Human-readable one-liner describing a tool the sub-agent is calling."""
    desc = ""
    if fn_name == "read_website":
        url = fn_args.get("url", "")
        # Show domain only for brevity
        short = url.split("//")[-1].split("/")[0] if "//" in url else url
        desc = f"Reading {short[:100]}..."
    elif fn_name == "search_web_pages":
        query = fn_args.get("query", "")[:100]
        desc = f'Searching: "{query}"'
    elif fn_name == "read_file":
        desc = f"Reading file {fn_args.get('path', '')[:100]}..."
    elif fn_name == "list_directory":
        desc = f"Listing {fn_args.get('path', '')[:100]}..."
    elif fn_name == "thinking":
        desc = "Thinking..."
    else:
        desc = f"Using {fn_name}..."
    return desc[:200]

# Tools that sub-agents must never access
_EXCLUDED_TOOLS = {
    # Terminal tools require interactive approval
    "run_command",
    "request_session_mode",
    "end_session_mode",
    "send_input",
    "read_output",
    "kill_process",
    "get_environment",
    # Prevent recursive spawning
    "spawn_agent",
}

_SUB_AGENT_SYSTEM_PROMPT = """\
You are a focused sub-agent executing a single task. Be concise and precise.
Return only what was asked — no preamble, no sign-off.
You have access to tools (file reading, web search, etc.) to complete your task.
Do not attempt terminal commands or spawn other agents.\
"""


def _truncate_safely(text: str, max_length: int) -> str:
    """Truncate text at a word boundary to avoid cutting mid-token."""
    if len(text) <= max_length:
        return text
    truncated = text[:max_length]
    # Try to break at last space within the truncated region
    last_space = truncated.rfind(" ", max(0, max_length - 200))
    if last_space > max_length // 2:
        truncated = truncated[:last_space]
    return truncated + "... [truncated]"


# Max chars of a tool result to include in the live transcript steps
_TRANSCRIPT_RESULT_PREVIEW = 1000


_SUB_AGENT_LOG_FILE = str(USER_DATA_DIR / "sub_agent_calls.txt")


def _log_sub_agent_call(
    agent_id: str,
    agent_name: str,
    model_tier: str,
    model_name: str,
    instruction: str,
    result_text: str,
    error: str | None,
    token_stats: dict,
) -> None:
    """Append a sub-agent call record to the debug log file."""
    try:
        os.makedirs(os.path.dirname(_SUB_AGENT_LOG_FILE), exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        entry = (
            f"\n{'=' * 80}\n"
            f"[{ts}] agent_id={agent_id}  name={agent_name}  tier={model_tier}  model={model_name}\n"
            f"{'=' * 80}\n"
            f"INSTRUCTION:\n{instruction[:2000]}\n"
            f"{'-' * 40}\n"
            f"RESULT ({len(result_text)} chars):\n{result_text[:3000]}\n"
        )
        if error:
            entry += f"ERROR: {error}\n"
        if token_stats:
            entry += f"TOKENS: prompt={token_stats.get('prompt_tokens', 0)} completion={token_stats.get('completion_tokens', 0)}\n"
        entry += f"{'=' * 80}\n"

        with open(_SUB_AGENT_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(entry)
    except Exception as e:
        logger.debug("Failed to write sub-agent log: %s", e)


# ---------------------------------------------------------------------------
# Tier resolution
# ---------------------------------------------------------------------------


def _resolve_tier_model(tier: str) -> str:
    """Resolve a tier label ("fast", "smart", "self") to a model identifier.

    Falls back to the current model for all tiers if no user override is set.
    """
    current_model = get_current_model()
    if not current_model:
        from ...core.state import app_state
        current_model = app_state.selected_model

    if not current_model:
        raise ValueError("No model available for sub-agent execution")

    if tier == "self":
        return current_model

    # Check user-configured overrides in DB
    setting_key = f"sub_agent_tier_{tier}"
    configured = db.get_setting(setting_key)
    if configured and configured.strip():
        return configured.strip()

    # Default: use current model
    return current_model


def _uses_ollama_client(model_name: str) -> bool:
    """Whether the model should be called via the Ollama AsyncClient.

    Models with a known cloud provider prefix (``anthropic/``, ``openai/``,
    ``gemini/``, ``openrouter/``) go through LiteLLM.  Everything else — including cloud-
    hosted Ollama models like ``qwen3.5:397b-cloud`` — goes through the
    Ollama client.
    """
    if "/" in model_name:
        provider = model_name.split("/")[0]
        if provider in ("anthropic", "openai", "gemini", "openrouter"):
            return False
    return True


def _is_local_ollama(model_name: str) -> bool:
    """Whether the model runs on a **local** GPU via Ollama.

    Cloud-hosted Ollama models tagged as ``:cloud`` or ``-cloud`` can be
    parallelised.  True-local models share a single GPU — multiple concurrent
    calls would compete for VRAM and degrade performance, so they run
    sequentially.
    """
    from ...llm.core.router import is_local_ollama_model

    return is_local_ollama_model(model_name)


def _normalize_model_tier(model_tier: str) -> str:
    """Normalize model tier values to the supported set."""
    if model_tier not in ("fast", "smart", "self"):
        logger.warning("Invalid model_tier '%s', defaulting to 'fast'", model_tier)
        return "fast"
    return model_tier


# ---------------------------------------------------------------------------
# Tool retrieval for sub-agents
# ---------------------------------------------------------------------------


def _get_sub_agent_tools(instruction: str) -> Optional[List[Dict[str, Any]]]:
    """Retrieve MCP tools relevant to the sub-agent's instruction.

    Excludes terminal tools and spawn_agent to prevent recursion and
    approval-blocking.
    """
    from ...mcp_integration.core.manager import mcp_manager
    from ...mcp_integration.core.handlers import retrieve_relevant_tools

    if not mcp_manager.has_tools():
        return None

    retrieved = retrieve_relevant_tools(instruction)
    if not retrieved:
        return None

    # Filter out excluded tools
    filtered = [
        t for t in retrieved
        if t["function"]["name"] not in _EXCLUDED_TOOLS
    ]
    return filtered if filtered else None


# ---------------------------------------------------------------------------
# Cloud sub-agent execution (LiteLLM)
# ---------------------------------------------------------------------------


async def _run_cloud_sub_agent(
    model_name: str,
    instruction: str,
    tools: Optional[List[Dict[str, Any]]],
    agent_id: str = "",
    agent_name: str = "Sub-Agent",
    model_tier: str = "fast",
) -> Dict[str, Any]:
    """Execute a sub-agent call via LiteLLM (cloud providers) with streaming.

    Streams thinking tokens and tool execution in real-time to the UI.
    Returns {"response": str, "token_stats": dict, "error": str | None}.
    """
    from ...llm.core.router import parse_provider
    from ...llm.core.key_manager import key_manager
    from ...mcp_integration.core.manager import mcp_manager

    provider, model = parse_provider(model_name)
    api_key = key_manager.get_api_key(provider)
    if not api_key:
        return {
            "response": f"Error: No API key for {provider}",
            "token_stats": {"prompt_tokens": 0, "completion_tokens": 0},
            "error": f"No API key for {provider}",
        }

    litellm_model = f"{provider}/{model}"
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": _SUB_AGENT_SYSTEM_PROMPT},
        {"role": "user", "content": instruction},
    ]

    # Cache the tool lookup once at the start (avoid re-fetching per round)
    all_openai_tools = mcp_manager.get_tools() or []

    # Resolve tools to OpenAI format
    openai_tools: Optional[List[Dict]] = None
    if tools:
        tool_names = {t["function"]["name"] for t in tools}
        openai_tools = [t for t in all_openai_tools if t["function"]["name"] in tool_names]
        if not openai_tools:
            openai_tools = None

    total_tokens = {"prompt_tokens": 0, "completion_tokens": 0}
    accumulated_text: list[str] = []
    transcript_steps: list[dict[str, Any]] = []

    # Broadcast the instruction as the first transcript step
    transcript_steps.append({"type": "instruction", "content": instruction})
    if agent_id:
        await broadcast_message(
            "sub_agent_stream",
            json.dumps({
                "agent_id": agent_id,
                "agent_name": agent_name,
                "model_tier": model_tier,
                "stream_type": "instruction",
                "content": instruction,
                "transcript": transcript_steps,
            }),
        )

    try:
        model_info = litellm.get_model_info(litellm_model)
    except Exception:
        model_info = {}

    max_tokens = model_info.get("max_output_tokens")
    if max_tokens is None and provider == "anthropic":
        max_tokens = 16384

    rounds = 0
    while True:
        if is_current_request_cancelled():
            break

        rounds += 1
        if rounds > MAX_MCP_TOOL_ROUNDS + 1:
            break

        allow_tools = openai_tools is not None and rounds <= MAX_MCP_TOOL_ROUNDS

        create_kwargs: Dict[str, Any] = {
            "model": litellm_model,
            "messages": messages,
            "stream": True,  # Enable streaming
            "api_key": api_key,
            "timeout": _SUB_AGENT_TIMEOUT,
        }
        if max_tokens and max_tokens > 0:
            create_kwargs["max_tokens"] = max_tokens
        if allow_tools:
            create_kwargs["tools"] = openai_tools

        try:
            # Stream the response
            round_text_chunks: list[str] = []
            tool_calls_accum: Dict[int, Dict[str, Any]] = {}
            finish_reason = None
            round_text_step_index: int | None = None

            def _append_stream_text(chunk_text: str) -> None:
                """Append streamed text and keep transcript text block in sync."""
                nonlocal round_text_step_index
                if not chunk_text:
                    return
                round_text_chunks.append(chunk_text)
                if round_text_step_index is None:
                    transcript_steps.append({"type": "text", "content": chunk_text})
                    round_text_step_index = len(transcript_steps) - 1
                    return
                existing = str(transcript_steps[round_text_step_index].get("content", ""))
                transcript_steps[round_text_step_index]["content"] = f"{existing}{chunk_text}"

            async for chunk in await litellm.acompletion(**create_kwargs):
                if is_current_request_cancelled():
                    break

                # Extract usage from final chunk if available
                if hasattr(chunk, "usage") and chunk.usage:
                    total_tokens["prompt_tokens"] += getattr(chunk.usage, "prompt_tokens", 0) or 0
                    total_tokens["completion_tokens"] += getattr(chunk.usage, "completion_tokens", 0) or 0

                if not chunk.choices:
                    continue

                delta = chunk.choices[0].delta
                finish_reason = chunk.choices[0].finish_reason

                # Stream reasoning/thinking content if provider exposes it
                reasoning_content = getattr(delta, "reasoning_content", None) if delta else None
                if reasoning_content:
                    if isinstance(reasoning_content, str):
                        thinking_text = reasoning_content
                    else:
                        try:
                            thinking_text = json.dumps(reasoning_content, ensure_ascii=False)
                        except TypeError:
                            thinking_text = str(reasoning_content)
                    _append_stream_text(thinking_text)
                    if agent_id:
                        await broadcast_message(
                            "sub_agent_stream",
                            json.dumps({
                                "agent_id": agent_id,
                                "agent_name": agent_name,
                                "model_tier": model_tier,
                                "stream_type": "thinking",
                                "content": thinking_text,
                                "accumulated": "".join(round_text_chunks),
                                "transcript": transcript_steps,
                            }),
                        )

                # Stream text content
                if delta and delta.content:
                    _append_stream_text(delta.content)
                    # Broadcast streaming text
                    if agent_id:
                        await broadcast_message(
                            "sub_agent_stream",
                            json.dumps({
                                "agent_id": agent_id,
                                "agent_name": agent_name,
                                "model_tier": model_tier,
                                "stream_type": "thinking",
                                "content": delta.content,
                                "accumulated": "".join(round_text_chunks),
                                "transcript": transcript_steps,
                            }),
                        )

                # Accumulate tool calls from deltas
                if delta and delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        if idx not in tool_calls_accum:
                            tool_calls_accum[idx] = {
                                "id": tc_delta.id or "",
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            }
                        if tc_delta.id:
                            tool_calls_accum[idx]["id"] = tc_delta.id
                        if tc_delta.function:
                            if tc_delta.function.name:
                                tool_calls_accum[idx]["function"]["name"] = tc_delta.function.name
                            if tc_delta.function.arguments:
                                tool_calls_accum[idx]["function"]["arguments"] += tc_delta.function.arguments

            # After streaming, add collected text to accumulated
            round_text = "".join(round_text_chunks)
            if round_text:
                accumulated_text.append(round_text)
                if agent_id:
                    await broadcast_message(
                        "sub_agent_stream",
                        json.dumps({
                            "agent_id": agent_id,
                            "agent_name": agent_name,
                            "model_tier": model_tier,
                            "stream_type": "thinking_complete",
                            "content": round_text,
                            "transcript": transcript_steps,
                        }),
                    )

            # Process tool calls if any
            if tool_calls_accum:
                sorted_tool_calls = [tool_calls_accum[i] for i in sorted(tool_calls_accum.keys())]

                # Append assistant message with tool calls
                assistant_msg: Dict[str, Any] = {
                    "role": "assistant",
                    "content": round_text or None,
                    "tool_calls": sorted_tool_calls,
                }
                messages.append(assistant_msg)

                # Execute each tool
                for tc in sorted_tool_calls:
                    fn_name = tc["function"]["name"]
                    fn_args, arg_error = normalize_tool_args(tc["function"]["arguments"])
                    tc_id = tc.get("id", "")

                    if arg_error:
                        result_str = f"Error: Invalid tool arguments for {fn_name}: {arg_error}"
                        messages.append({"role": "tool", "tool_call_id": tc_id, "content": result_str})
                        transcript_steps.append({"type": "tool_call", "name": fn_name, "args": {}, "status": "error", "result": result_str})
                        if agent_id:
                            await broadcast_message(
                                "sub_agent_stream",
                                json.dumps({
                                    "agent_id": agent_id,
                                    "agent_name": agent_name,
                                    "model_tier": model_tier,
                                    "stream_type": "tool_error",
                                    "tool_name": fn_name,
                                    "error": result_str,
                                    "transcript": transcript_steps,
                                }),
                            )
                        continue

                    if fn_name in _EXCLUDED_TOOLS:
                        result_str = f"Error: Tool '{fn_name}' is not available to sub-agents."
                        messages.append({"role": "tool", "tool_call_id": tc_id, "content": result_str})
                        transcript_steps.append({"type": "tool_call", "name": fn_name, "args": fn_args, "status": "blocked", "result": result_str})
                        if agent_id:
                            await broadcast_message(
                                "sub_agent_stream",
                                json.dumps({
                                    "agent_id": agent_id,
                                    "agent_name": agent_name,
                                    "model_tier": model_tier,
                                    "stream_type": "tool_blocked",
                                    "tool_name": fn_name,
                                    "error": result_str,
                                    "transcript": transcript_steps,
                                }),
                            )
                        continue

                    if is_current_request_cancelled():
                        break

                    # Broadcast tool call start
                    step_index = len(transcript_steps)
                    transcript_steps.append({"type": "tool_call", "name": fn_name, "args": fn_args, "status": "calling"})
                    if agent_id:
                        await broadcast_message(
                            "sub_agent_stream",
                            json.dumps({
                                "agent_id": agent_id,
                                "agent_name": agent_name,
                                "model_tier": model_tier,
                                "stream_type": "tool_call",
                                "tool_name": fn_name,
                                "tool_args": fn_args,
                                "transcript": transcript_steps,
                            }),
                        )

                    try:
                        result = await mcp_manager.call_tool(fn_name, fn_args)
                        result_str = str(result)
                        if len(result_str) > MAX_TOOL_RESULT_LENGTH:
                            result_str = _truncate_safely(result_str, MAX_TOOL_RESULT_LENGTH)
                    except Exception as e:
                        logger.warning("Cloud sub-agent tool %s failed: %s", fn_name, e)
                        result_str = f"Tool execution error: {type(e).__name__}"

                    messages.append({"role": "tool", "tool_call_id": tc_id, "content": result_str})
                    result_preview = result_str[:_TRANSCRIPT_RESULT_PREVIEW] if len(result_str) > _TRANSCRIPT_RESULT_PREVIEW else result_str
                    transcript_steps[step_index] = {"type": "tool_call", "name": fn_name, "args": fn_args, "status": "complete", "result": result_preview}

                    # Broadcast tool result
                    if agent_id:
                        await broadcast_message(
                            "sub_agent_stream",
                            json.dumps({
                                "agent_id": agent_id,
                                "agent_name": agent_name,
                                "model_tier": model_tier,
                                "stream_type": "tool_result",
                                "tool_name": fn_name,
                                "tool_result": result_preview,
                                "transcript": transcript_steps,
                            }),
                        )

                # Check cancellation after tool execution loop
                if is_current_request_cancelled():
                    break
            elif finish_reason == "stop" or not tool_calls_accum:
                # No tool calls — response is complete
                break

        except Exception as e:
            logger.error("Sub-agent LiteLLM streaming failed: %s", e, exc_info=True)
            return {
                "response": f"Sub-agent error: {type(e).__name__}",
                "token_stats": total_tokens,
                "error": type(e).__name__,
            }

    # Broadcast final complete state
    final_response = "".join(accumulated_text)
    if agent_id:
        await broadcast_message(
            "sub_agent_stream",
            json.dumps({
                "agent_id": agent_id,
                "agent_name": agent_name,
                "model_tier": model_tier,
                "stream_type": "final",
                "content": final_response,
                "transcript": transcript_steps,
                "token_stats": total_tokens,
            }),
        )

    return {
        "response": final_response,
        "token_stats": total_tokens,
        "error": None,
    }


# ---------------------------------------------------------------------------
# Ollama sub-agent execution
# ---------------------------------------------------------------------------


async def _run_ollama_sub_agent(
    model_name: str,
    instruction: str,
    tools: Optional[List[Dict[str, Any]]],
    agent_id: str = "",
    agent_name: str = "Sub-Agent",
    model_tier: str = "fast",
) -> Dict[str, Any]:
    """Execute a sub-agent call via Ollama AsyncClient with streaming.

    Streams thinking tokens and tool execution in real-time to the UI.
    Returns {"response": str, "token_stats": dict, "error": str | None}.
    """
    from ollama import AsyncClient as OllamaAsyncClient
    from ...mcp_integration.core.manager import mcp_manager

    client = OllamaAsyncClient()
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": _SUB_AGENT_SYSTEM_PROMPT},
        {"role": "user", "content": instruction},
    ]

    total_tokens = {"prompt_tokens": 0, "completion_tokens": 0}
    accumulated_text: list[str] = []
    transcript_steps: list[dict[str, Any]] = []

    # Strip provider prefix if present (e.g., "ollama/model" → "model")
    if "/" in model_name:
        _, _, model_name = model_name.partition("/")

    # Broadcast the instruction as the first transcript step
    transcript_steps.append({"type": "instruction", "content": instruction})
    if agent_id:
        await broadcast_message(
            "sub_agent_stream",
            json.dumps({
                "agent_id": agent_id,
                "agent_name": agent_name,
                "model_tier": model_tier,
                "stream_type": "instruction",
                "content": instruction,
                "transcript": transcript_steps,
            }),
        )

    rounds = 0
    while True:
        if is_current_request_cancelled():
            break

        rounds += 1
        if rounds > MAX_MCP_TOOL_ROUNDS + 1:
            break

        allow_tools = tools is not None and rounds <= MAX_MCP_TOOL_ROUNDS

        chat_kwargs: Dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "stream": True,  # Enable streaming
            "options": {"num_ctx": OLLAMA_CTX_SIZE},
        }
        if allow_tools:
            chat_kwargs["tools"] = tools
            chat_kwargs["think"] = False  # Ollama bug #10976 workaround

        try:
            # Stream the response
            round_text_chunks: list[str] = []
            tool_calls_list: list = []
            round_text_step_index: int | None = None

            def _append_stream_text(chunk_text: str) -> None:
                """Append streamed text and keep transcript text block in sync."""
                nonlocal round_text_step_index
                if not chunk_text:
                    return
                round_text_chunks.append(chunk_text)
                if round_text_step_index is None:
                    transcript_steps.append({"type": "text", "content": chunk_text})
                    round_text_step_index = len(transcript_steps) - 1
                    return
                existing = str(transcript_steps[round_text_step_index].get("content", ""))
                transcript_steps[round_text_step_index]["content"] = f"{existing}{chunk_text}"

            async for chunk in await client.chat(**chat_kwargs):
                if is_current_request_cancelled():
                    break

                # Handle dict response (streaming chunks)
                if isinstance(chunk, dict):
                    msg = chunk.get("message", {})
                    done = chunk.get("done", False)

                    # Accumulate token counts from final chunk
                    if done:
                        total_tokens["prompt_tokens"] += chunk.get("prompt_eval_count", 0) or 0
                        total_tokens["completion_tokens"] += chunk.get("eval_count", 0) or 0

                    # Stream model thinking/reasoning when available
                    thinking = msg.get("thinking", "") or msg.get("reasoning_content", "")
                    if thinking:
                        _append_stream_text(thinking)
                        if agent_id:
                            await broadcast_message(
                                "sub_agent_stream",
                                json.dumps({
                                    "agent_id": agent_id,
                                    "agent_name": agent_name,
                                    "model_tier": model_tier,
                                    "stream_type": "thinking",
                                    "content": thinking,
                                    "accumulated": "".join(round_text_chunks),
                                    "transcript": transcript_steps,
                                }),
                            )

                    # Stream text content
                    content = msg.get("content", "")
                    if content:
                        _append_stream_text(content)
                        if agent_id:
                            await broadcast_message(
                                "sub_agent_stream",
                                json.dumps({
                                    "agent_id": agent_id,
                                    "agent_name": agent_name,
                                    "model_tier": model_tier,
                                    "stream_type": "thinking",
                                    "content": content,
                                    "accumulated": "".join(round_text_chunks),
                                    "transcript": transcript_steps,
                                }),
                            )

                    # Collect tool calls from the message
                    if msg.get("tool_calls"):
                        tool_calls_list = msg["tool_calls"]
                else:
                    # Handle object response
                    msg = getattr(chunk, "message", None)
                    done = getattr(chunk, "done", False)

                    if done:
                        total_tokens["prompt_tokens"] += getattr(chunk, "prompt_eval_count", 0) or 0
                        total_tokens["completion_tokens"] += getattr(chunk, "eval_count", 0) or 0

                    if msg:
                        thinking = (
                            getattr(msg, "thinking", "") or
                            getattr(msg, "reasoning_content", "")
                        ) or ""
                        if thinking:
                            _append_stream_text(thinking)
                            if agent_id:
                                await broadcast_message(
                                    "sub_agent_stream",
                                    json.dumps({
                                        "agent_id": agent_id,
                                        "agent_name": agent_name,
                                        "model_tier": model_tier,
                                        "stream_type": "thinking",
                                        "content": thinking,
                                        "accumulated": "".join(round_text_chunks),
                                        "transcript": transcript_steps,
                                    }),
                                )

                        content = getattr(msg, "content", "") or ""
                        if content:
                            _append_stream_text(content)
                            if agent_id:
                                await broadcast_message(
                                    "sub_agent_stream",
                                    json.dumps({
                                        "agent_id": agent_id,
                                        "agent_name": agent_name,
                                        "model_tier": model_tier,
                                        "stream_type": "thinking",
                                        "content": content,
                                        "accumulated": "".join(round_text_chunks),
                                        "transcript": transcript_steps,
                                    }),
                                )

                        if getattr(msg, "tool_calls", None):
                            tool_calls_list = msg.tool_calls

            # After streaming, add collected text to accumulated
            round_text = "".join(round_text_chunks)
            if round_text:
                accumulated_text.append(round_text)
                if agent_id:
                    await broadcast_message(
                        "sub_agent_stream",
                        json.dumps({
                            "agent_id": agent_id,
                            "agent_name": agent_name,
                            "model_tier": model_tier,
                            "stream_type": "thinking_complete",
                            "content": round_text,
                            "transcript": transcript_steps,
                        }),
                    )

            # Process tool calls if any
            if tool_calls_list:
                # Append assistant message
                messages.append({"role": "assistant", "content": round_text, "tool_calls": tool_calls_list})

                for tc in tool_calls_list:
                    if isinstance(tc, dict):
                        fn = tc.get("function", {})
                        if not fn or not fn.get("name"):
                            logger.warning("Skipping malformed Ollama tool call: %s", tc)
                            continue
                        fn_name = fn["name"]
                        fn_args = fn.get("arguments", {})
                    else:
                        if not getattr(tc, "function", None) or not getattr(tc.function, "name", None):
                            logger.warning("Skipping malformed Ollama tool call object: %s", tc)
                            continue
                        fn_name = tc.function.name
                        fn_args = tc.function.arguments

                    # Decode args: may be dict already or a JSON string
                    fn_args, arg_error = normalize_tool_args(fn_args)
                    if arg_error:
                        result_str = f"Error: Invalid tool arguments for {fn_name}: {arg_error}"
                        messages.append({"role": "tool", "content": result_str, "name": fn_name})
                        transcript_steps.append({"type": "tool_call", "name": fn_name, "args": {}, "status": "error", "result": result_str})
                        if agent_id:
                            await broadcast_message(
                                "sub_agent_stream",
                                json.dumps({
                                    "agent_id": agent_id,
                                    "agent_name": agent_name,
                                    "model_tier": model_tier,
                                    "stream_type": "tool_error",
                                    "tool_name": fn_name,
                                    "error": result_str,
                                    "transcript": transcript_steps,
                                }),
                            )
                        continue

                    if fn_name in _EXCLUDED_TOOLS:
                        result_str = f"Error: Tool '{fn_name}' is not available to sub-agents."
                        messages.append({"role": "tool", "content": result_str, "name": fn_name})
                        transcript_steps.append({"type": "tool_call", "name": fn_name, "args": fn_args, "status": "blocked", "result": result_str})
                        if agent_id:
                            await broadcast_message(
                                "sub_agent_stream",
                                json.dumps({
                                    "agent_id": agent_id,
                                    "agent_name": agent_name,
                                    "model_tier": model_tier,
                                    "stream_type": "tool_blocked",
                                    "tool_name": fn_name,
                                    "error": result_str,
                                    "transcript": transcript_steps,
                                }),
                            )
                        continue

                    if is_current_request_cancelled():
                        break

                    # Broadcast tool call start
                    step_index = len(transcript_steps)
                    transcript_steps.append({"type": "tool_call", "name": fn_name, "args": fn_args, "status": "calling"})
                    if agent_id:
                        await broadcast_message(
                            "sub_agent_stream",
                            json.dumps({
                                "agent_id": agent_id,
                                "agent_name": agent_name,
                                "model_tier": model_tier,
                                "stream_type": "tool_call",
                                "tool_name": fn_name,
                                "tool_args": fn_args,
                                "transcript": transcript_steps,
                            }),
                        )

                    try:
                        result = await mcp_manager.call_tool(fn_name, fn_args)
                        result_str = str(result)
                        if len(result_str) > MAX_TOOL_RESULT_LENGTH:
                            result_str = _truncate_safely(result_str, MAX_TOOL_RESULT_LENGTH)
                    except Exception as e:
                        logger.warning("Ollama sub-agent tool %s failed: %s", fn_name, e)
                        result_str = f"Tool execution error: {type(e).__name__}"

                    messages.append({"role": "tool", "content": result_str, "name": fn_name})
                    result_preview = result_str[:_TRANSCRIPT_RESULT_PREVIEW] if len(result_str) > _TRANSCRIPT_RESULT_PREVIEW else result_str
                    transcript_steps[step_index] = {"type": "tool_call", "name": fn_name, "args": fn_args, "status": "complete", "result": result_preview}

                    # Broadcast tool result
                    if agent_id:
                        await broadcast_message(
                            "sub_agent_stream",
                            json.dumps({
                                "agent_id": agent_id,
                                "agent_name": agent_name,
                                "model_tier": model_tier,
                                "stream_type": "tool_result",
                                "tool_name": fn_name,
                                "tool_result": result_preview,
                                "transcript": transcript_steps,
                            }),
                        )

                # Check cancellation after tool execution loop
                if is_current_request_cancelled():
                    break
            else:
                # No tool calls — response is complete
                break

        except Exception as e:
            logger.error("Sub-agent Ollama streaming failed: %s", e, exc_info=True)
            return {
                "response": f"Sub-agent error: {type(e).__name__}",
                "token_stats": total_tokens,
                "error": type(e).__name__,
            }

    # Broadcast final complete state
    final_response = "".join(accumulated_text)
    if agent_id:
        await broadcast_message(
            "sub_agent_stream",
            json.dumps({
                "agent_id": agent_id,
                "agent_name": agent_name,
                "model_tier": model_tier,
                "stream_type": "final",
                "content": final_response,
                "transcript": transcript_steps,
                "token_stats": total_tokens,
            }),
        )

    return {
        "response": final_response,
        "token_stats": total_tokens,
        "error": None,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def execute_sub_agent(
    instruction: str,
    model_tier: str = "fast",
    agent_name: str = "Sub-Agent",
) -> str:
    """Execute a single sub-agent call and return the result as a string.

    This is the entry point called by the spawn_agent tool interceptor.
    Broadcasts status updates so the user can see progress.
    Enforces a global concurrency limit via ``_concurrency_semaphore``.

    Returns the sub-agent's response text, or an error message.
    """
    model_tier = _normalize_model_tier(model_tier)

    agent_id = uuid.uuid4().hex[:12]

    model_name = _resolve_tier_model(model_tier)
    logger.info(
        "Spawning sub-agent '%s' [%s] (tier=%s, model=%s)",
        agent_name, agent_id, model_tier, model_name,
    )

    # Retrieve tools for this sub-agent's instruction
    tools = _get_sub_agent_tools(instruction)

    try:
        async with _concurrency_semaphore:
            if _uses_ollama_client(model_name):
                result = await asyncio.wait_for(
                    _run_ollama_sub_agent(
                        model_name, instruction, tools,
                        agent_id=agent_id, agent_name=agent_name, model_tier=model_tier,
                    ),
                    timeout=_SUB_AGENT_TIMEOUT,
                )
            else:
                result = await asyncio.wait_for(
                    _run_cloud_sub_agent(
                        model_name, instruction, tools,
                        agent_id=agent_id, agent_name=agent_name, model_tier=model_tier,
                    ),
                    timeout=_SUB_AGENT_TIMEOUT,
                )
    except asyncio.TimeoutError:
        error_msg = f"Sub-agent '{agent_name}' timed out after {_SUB_AGENT_TIMEOUT}s"
        logger.warning(error_msg)
        return f"Error: Sub-agent '{agent_name}' timed out after {_SUB_AGENT_TIMEOUT}s"
    except Exception as e:
        # Log full error internally; expose only type name to caller
        error_msg = f"Sub-agent '{agent_name}' failed: {type(e).__name__}"
        logger.error("Sub-agent '%s' failed: %s", agent_name, e)
        return f"Error: {error_msg}"

    response_text = result.get("response", "")
    token_stats = result.get("token_stats", {})
    error = result.get("error")

    # Log to debug file for inspection (offloaded to thread to avoid blocking)
    await run_in_thread(
        _log_sub_agent_call,
        agent_id=agent_id,
        agent_name=agent_name,
        model_tier=model_tier,
        model_name=model_name,
        instruction=instruction,
        result_text=response_text,
        error=error,
        token_stats=token_stats,
    )

    total_tokens = token_stats.get("prompt_tokens", 0) + token_stats.get("completion_tokens", 0)
    token_label = f" \u2022 {total_tokens} tokens" if total_tokens else ""

    if error:
        return f"Error: {error}\n\nPartial response:\n{response_text}" if response_text else f"Error: {error}"

    return response_text


async def execute_sub_agents_parallel(
    calls: List[Dict[str, Any]],
) -> List[str]:
    """Execute multiple sub-agent calls, respecting parallelism rules.

    For local Ollama: sequential execution.
    For cloud/remote: concurrent execution up to _CONCURRENCY_CAP.

    Each item in ``calls`` has keys: instruction, model_tier, agent_name.
    Returns a list of result strings in the same order.
    """
    if not calls:
        return []

    normalized_tiers = [
        _normalize_model_tier(c.get("model_tier", "fast"))
        for c in calls
    ]

    # Pre-resolve tiers once to avoid repeated DB queries (H5 fix)
    tier_cache: Dict[str, str] = {}
    for tier in normalized_tiers:
        if tier not in tier_cache:
            tier_cache[tier] = _resolve_tier_model(tier)

    # Check if ANY call resolves to local Ollama — if so, run all sequentially
    # to avoid overwhelming the local GPU
    any_local = any(_is_local_ollama(tier_cache[tier]) for tier in normalized_tiers)

    if any_local or len(calls) == 1:
        # Sequential execution
        results = []
        for call, model_tier in zip(calls, normalized_tiers):
            result = await execute_sub_agent(
                instruction=call["instruction"],
                model_tier=model_tier,
                agent_name=call.get("agent_name", "Sub-Agent"),
            )
            results.append(result)
        return results

    # Parallel execution — semaphore is enforced inside execute_sub_agent
    raw_results = await asyncio.gather(
        *[
            execute_sub_agent(
                instruction=c["instruction"],
                model_tier=model_tier,
                agent_name=c.get("agent_name", "Sub-Agent"),
            )
            for c, model_tier in zip(calls, normalized_tiers)
        ],
        return_exceptions=True,
    )

    # Convert exceptions to error strings
    results: list[str] = []
    for i, r in enumerate(raw_results):
        if isinstance(r, BaseException):
            agent = calls[i].get("agent_name", "Sub-Agent")
            logger.error("Sub-agent '%s' raised: %s", agent, r)
            results.append(f"Error: Sub-agent '{agent}' failed: {type(r).__name__}")
        else:
            results.append(r)
    return results
