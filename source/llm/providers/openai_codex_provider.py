"""ChatGPT subscription inference through the bundled Codex app-server."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import logging
import mimetypes
import os
import re
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, Set
from urllib.parse import urlparse

from ...core.connection import broadcast_message
from ...core.request_context import is_current_request_cancelled
from ...core.thread_pool import run_in_thread
from ...infrastructure.config import MAX_MCP_TOOL_ROUNDS, REASONING_EFFORT
from ...mcp_integration.core.tool_args import normalize_tool_args, sanitize_tool_args
from ...services.integrations.codex_app_server import CodexConnectorError
from ...services.integrations.openai_codex import openai_codex
from ..core.artifacts import (
    ArtifactStreamParser,
    emit_artifact_stream_events,
    serialize_blocks_for_model_content,
)
from ..core.tool_executor import xpdite_tool_executor
from ..core.token_usage import empty_token_stats

logger = logging.getLogger(__name__)

_SAFE_TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_MAX_TOOL_CALLS = max(8, MAX_MCP_TOOL_ROUNDS * 8)
_TURN_IDLE_TIMEOUT = 90.0
_TURN_OVERALL_TIMEOUT = 600.0
_TOOL_TIMEOUT = 180.0
_INTERRUPT_TIMEOUT = 10.0
_MAX_IMAGE_BYTES = 50 * 1024 * 1024
_MAX_TOTAL_IMAGE_BYTES = 100 * 1024 * 1024
_MAX_TEXT_INPUT_BYTES = 8 * 1024 * 1024
_MAX_HISTORY_MESSAGES = 2_000
_MAX_TOOL_SCHEMA_BYTES = 256 * 1024
_MAX_DYNAMIC_TOOLS_BYTES = 4 * 1024 * 1024
_MAX_SCHEMA_DEPTH = 32

_ISOLATION_CONFIG: dict[str, Any] = {
    "project_doc_max_bytes": 0,
    "include_environment_context": False,
    "include_permissions_instructions": False,
    "include_apps_instructions": False,
    "skills.include_instructions": False,
    "web_search": "disabled",
    "features.shell_tool": False,
    "features.unified_exec": False,
    "features.apply_patch_freeform": False,
    "features.code_mode": False,
    "features.js_repl": False,
    "features.multi_agent": False,
    "features.multi_agent_v2": False,
    "features.apps": False,
    "features.plugins": False,
    "features.tool_search": False,
    "features.computer_use": False,
    "features.image_generation": False,
    "features.request_permissions_tool": False,
    "features.default_mode_request_user_input": False,
    "features.codex_hooks": False,
    "features.memories": False,
    "features.tool_suggest": False,
    "features.browser_use": False,
    "features.in_app_browser": False,
    "features.guardian_approval": False,
}

_PASSIVE_ITEM_TYPES = {"agentMessage", "reasoning", "userMessage"}
_DYNAMIC_TOOL_ITEM_TYPE = "dynamicToolCall"


def _prepare_codex_inputs(
    user_query: str,
    image_paths: list[str],
    chat_history: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Read and encode attachments off-loop with a bounded aggregate payload."""
    total_bytes = 0
    total_text_bytes = len(user_query.encode("utf-8"))
    if (
        len(chat_history) > _MAX_HISTORY_MESSAGES
        or total_text_bytes > _MAX_TEXT_INPUT_BYTES
    ):
        raise CodexConnectorError(
            "chatgpt_context_limit",
            "This conversation exceeds the ChatGPT connector's input size limit.",
        )

    def encode(path: str) -> str | None:
        nonlocal total_bytes
        if path.startswith("data:"):
            header, separator, payload = path.partition(",")
            if (
                not separator
                or not header.lower().startswith("data:image/")
                or ";base64" not in header.lower()
            ):
                raise CodexConnectorError(
                    "chatgpt_attachment_unavailable",
                    "An attachment is not a supported image data URL.",
                )
            try:
                decoded_size = len(base64.b64decode(payload, validate=True))
            except (ValueError, binascii.Error) as exc:
                raise CodexConnectorError(
                    "chatgpt_attachment_unavailable",
                    "An attached image data URL is invalid.",
                ) from exc
            if (
                decoded_size > _MAX_IMAGE_BYTES
                or total_bytes + decoded_size > _MAX_TOTAL_IMAGE_BYTES
            ):
                raise CodexConnectorError(
                    "chatgpt_attachment_limit",
                    "The attached images exceed the ChatGPT connector's size limit.",
                )
            total_bytes += decoded_size
            return path
        parsed_url = urlparse(path)
        if parsed_url.scheme in {"http", "https"} and parsed_url.netloc:
            if len(path) > 8192:
                raise CodexConnectorError(
                    "chatgpt_attachment_unavailable",
                    "An attached image URL is too long.",
                )
            return path
        try:
            size = os.path.getsize(path)
        except OSError as exc:
            raise CodexConnectorError(
                "chatgpt_attachment_unavailable",
                "An attached image could not be read by the ChatGPT connector.",
            ) from exc
        if size > _MAX_IMAGE_BYTES:
            raise CodexConnectorError(
                "chatgpt_attachment_limit",
                "An attached image is too large for the ChatGPT connector.",
            )
        if total_bytes + size > _MAX_TOTAL_IMAGE_BYTES:
            raise CodexConnectorError(
                "chatgpt_attachment_limit",
                "The attached images exceed the ChatGPT connector's total size limit.",
            )
        media_type = mimetypes.guess_type(path)[0]
        if not media_type or not media_type.startswith("image/"):
            raise CodexConnectorError(
                "chatgpt_attachment_unavailable",
                "An attachment is not a supported image file.",
            )
        try:
            encoded = base64.b64encode(Path(path).read_bytes()).decode("ascii")
        except OSError as exc:
            raise CodexConnectorError(
                "chatgpt_attachment_unavailable",
                "An attached image could not be read by the ChatGPT connector.",
            ) from exc
        total_bytes += size
        return f"data:{media_type};base64,{encoded}"

    history_items: list[dict[str, Any]] = []
    for message in chat_history:
        role = str(message.get("role") or "")
        if role not in {"user", "assistant"}:
            continue
        content_type = "input_text" if role == "user" else "output_text"
        history_text = _history_text(message)
        total_text_bytes += len(history_text.encode("utf-8"))
        if total_text_bytes > _MAX_TEXT_INPUT_BYTES:
            raise CodexConnectorError(
                "chatgpt_context_limit",
                "This conversation exceeds the ChatGPT connector's input size limit.",
            )
        content: list[dict[str, Any]] = [{"type": content_type, "text": history_text}]
        if role == "user":
            for image_path in message.get("images") or []:
                image_url = encode(str(image_path))
                if image_url:
                    content.append({"type": "input_image", "image_url": image_url})
        history_items.append({"type": "message", "role": role, "content": content})

    turn_input: list[dict[str, Any]] = []
    for image_path in image_paths:
        image_url = encode(image_path)
        if image_url:
            turn_input.append({"type": "image", "url": image_url})
    turn_input.append({"type": "text", "text": user_query, "textElements": []})
    return history_items, turn_input


def _history_text(message: dict[str, Any]) -> str:
    return serialize_blocks_for_model_content(
        message.get("content_blocks"), fallback_text=str(message.get("content") or "")
    )


def _alias_for_tool(name: str, used: set[str]) -> str:
    if _SAFE_TOOL_NAME_RE.fullmatch(name) and name not in used:
        return name
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:16]
    alias = f"xpdite_{digest}"
    counter = 1
    while alias in used:
        alias = f"xpdite_{digest}_{counter}"
        counter += 1
    return alias


def _validated_tool_schema(schema: Any) -> dict[str, Any]:
    if schema is None:
        return {"type": "object", "properties": {}}
    if not isinstance(schema, dict):
        raise CodexConnectorError(
            "chatgpt_tool_protocol_error",
            "A retrieved tool has an invalid input schema.",
        )
    normalized = dict(schema)
    normalized.setdefault("type", "object")
    if normalized.get("type") != "object":
        raise CodexConnectorError(
            "chatgpt_tool_protocol_error",
            "A retrieved tool has a non-object input schema.",
        )
    try:
        encoded = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError, RecursionError) as exc:
        raise CodexConnectorError(
            "chatgpt_tool_protocol_error",
            "A retrieved tool has an invalid input schema.",
        ) from exc
    if len(encoded.encode("utf-8")) > _MAX_TOOL_SCHEMA_BYTES:
        raise CodexConnectorError(
            "chatgpt_tool_protocol_error",
            "A retrieved tool input schema exceeds the connector's size limit.",
        )
    stack: list[tuple[Any, int]] = [(json.loads(encoded), 0)]
    while stack:
        value, depth = stack.pop()
        if depth > _MAX_SCHEMA_DEPTH:
            raise CodexConnectorError(
                "chatgpt_tool_protocol_error",
                "A retrieved tool input schema is nested too deeply.",
            )
        if isinstance(value, (dict, list)):
            children = value.values() if isinstance(value, dict) else value
            stack.extend((child, depth + 1) for child in children)
    return normalized


def build_dynamic_tools(
    tools: list[dict[str, Any]], allowed_tool_names: Set[str]
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Build the exact per-turn dynamic-tool allowlist and private alias map."""
    dynamic_tools: list[dict[str, Any]] = []
    alias_map: dict[str, str] = {}
    used: set[str] = set()
    for tool in tools:
        function = tool.get("function") if isinstance(tool, dict) else None
        if not isinstance(function, dict):
            continue
        original_name = str(function.get("name") or "")
        if not original_name or original_name not in allowed_tool_names:
            continue
        alias = _alias_for_tool(original_name, used)
        used.add(alias)
        alias_map[alias] = original_name
        schema = _validated_tool_schema(function.get("parameters"))
        dynamic_tools.append(
            {
                "name": alias,
                "description": str(function.get("description") or ""),
                "deferLoading": False,
                "inputSchema": schema,
            }
        )
    encoded_tools = json.dumps(dynamic_tools, ensure_ascii=False, separators=(",", ":"))
    if len(encoded_tools.encode("utf-8")) > _MAX_DYNAMIC_TOOLS_BYTES:
        raise CodexConnectorError(
            "chatgpt_tool_protocol_error",
            "The retrieved tool schemas exceed the connector's total size limit.",
        )
    return dynamic_tools, alias_map


def _supported_reasoning_efforts(model: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for entry in model.get("supportedReasoningEfforts") or []:
        if isinstance(entry, str):
            result.add(entry)
        elif isinstance(entry, dict) and entry.get("reasoningEffort"):
            result.add(str(entry["reasoningEffort"]))
    return result


def _reasoning_effort(
    model: dict[str, Any], preferred_effort: str | None = None
) -> str | None:
    supported = _supported_reasoning_efforts(model)
    if preferred_effort and preferred_effort in supported:
        return preferred_effort
    if preferred_effort:
        logger.debug(
            "Saved reasoning effort is unavailable; using the configured fallback"
        )
    if REASONING_EFFORT in supported:
        return REASONING_EFFORT
    default = model.get("defaultReasoningEffort")
    if default and REASONING_EFFORT:
        logger.debug(
            "Configured reasoning effort is unavailable; using the account model default"
        )
    return str(default) if default else None


def _has_image_input(model: dict[str, Any]) -> bool:
    return any(
        str(value).lower() == "image" for value in model.get("inputModalities") or []
    )


def _extract_thread_id(result: dict[str, Any]) -> str:
    thread = result.get("thread")
    thread_id = thread.get("id") if isinstance(thread, dict) else result.get("threadId")
    if not thread_id:
        raise CodexConnectorError(
            "codex_protocol_mismatch", "Codex app-server did not return a thread ID."
        )
    return str(thread_id)


def _extract_turn_id(result: dict[str, Any]) -> str:
    turn = result.get("turn")
    turn_id = turn.get("id") if isinstance(turn, dict) else result.get("turnId")
    if not turn_id:
        raise CodexConnectorError(
            "codex_protocol_mismatch", "Codex app-server did not return a turn ID."
        )
    return str(turn_id)


def _agent_message_text(item: Any) -> str | None:
    if not isinstance(item, dict) or item.get("type") != "agentMessage":
        return None
    text = item.get("text")
    if isinstance(text, str):
        return text
    content = item.get("content")
    if isinstance(content, list):
        parts = [
            str(part.get("text") or "")
            for part in content
            if isinstance(part, dict) and part.get("type") in {"output_text", "text"}
        ]
        return "".join(parts)
    return None


def _reasoning_summary_text(item: Any) -> str | None:
    """Return only the model-provided readable reasoning summary."""
    if not isinstance(item, dict) or item.get("type") != "reasoning":
        return None
    summary = item.get("summary")
    if not isinstance(summary, list):
        return None
    parts = [str(part) for part in summary if isinstance(part, str) and part]
    return "\n\n".join(parts) if parts else None


def _usage_snapshot(params: dict[str, Any]) -> dict[str, int]:
    token_usage = params.get("tokenUsage")
    total = token_usage.get("total") if isinstance(token_usage, dict) else None
    if not isinstance(total, dict):
        return empty_token_stats()
    return {
        "prompt_eval_count": int(total.get("inputTokens") or 0),
        "eval_count": int(total.get("outputTokens") or 0),
        "cached_tokens": int(total.get("cachedInputTokens") or 0),
        "cache_write_tokens": 0,
    }


def _safe_turn_error(
    turn: dict[str, Any] | None, protocol_error: dict[str, Any] | None
) -> tuple[str, str]:
    error = turn.get("error") if isinstance(turn, dict) else None
    if not isinstance(error, dict):
        error = protocol_error or {}
    info = str(error.get("codexErrorInfo") or "").lower()
    message_text = str(error.get("message") or "").lower()
    combined = f"{info} {message_text}"
    if "contextwindow" in combined or "context limit" in combined:
        return (
            "chatgpt_context_limit",
            "This conversation exceeds the selected model's context limit.",
        )
    if "usage" in combined or "rate limit" in combined or "quota" in combined:
        return (
            "chatgpt_usage_limit",
            "Your ChatGPT usage limit has been reached. Try again after it resets.",
        )
    if "unauthorized" in combined or "auth" in combined:
        return (
            "chatgpt_auth_expired",
            "Your ChatGPT connection expired. Reconnect it in Settings.",
        )
    if "workspace" in combined or "permission" in combined:
        return (
            "chatgpt_workspace_denied",
            "Your ChatGPT workspace does not allow this request.",
        )
    return "chatgpt_turn_failed", "The ChatGPT model turn failed. Please try again."


async def _record_rejected_tool(
    name: str,
    args: dict[str, Any],
    result: str,
    tool_calls: list[dict[str, Any]],
    blocks: list[dict[str, Any]],
    broadcaster: Callable[[str, Any], Awaitable[Any]] = broadcast_message,
) -> None:
    safe_args = sanitize_tool_args(name, "unknown", args)
    tool_calls.append(
        {"name": name, "args": safe_args, "result": result, "server": "unknown"}
    )
    blocks.append(
        {"type": "tool_call", "name": name, "args": safe_args, "server": "unknown"}
    )
    await broadcaster(
        "tool_call",
        json.dumps(
            {
                "name": name,
                "args": safe_args,
                "result": result,
                "server": "unknown",
                "status": "complete",
            }
        ),
    )


async def stream_openai_codex_chat(
    model: str,
    user_query: str,
    image_paths: list[str],
    chat_history: list[dict[str, Any]],
    allowed_tool_names: Optional[Set[str]] = None,
    system_prompt: str = "",
    reasoning_effort: str | None = None,
    event_broadcaster: Callable[[str, Any], Awaitable[Any]] = broadcast_message,
    emit_terminal_events: bool = True,
) -> tuple[str, dict[str, int], list[dict[str, Any]], Optional[list[dict[str, Any]]]]:
    """Run one Xpdite request as one isolated ephemeral Codex thread."""
    allowed = set(allowed_tool_names or set())
    token_stats = empty_token_stats()
    tool_calls: list[dict[str, Any]] = []
    blocks: list[dict[str, Any]] = []
    visible_parts: list[str] = []
    streamed_reasoning_text: dict[str, list[str]] = {}
    thinking_active = False
    artifact_parser = ArtifactStreamParser()
    parser_finalized = False
    event_stream = None
    thread_id: str | None = None
    turn_id: str | None = None
    terminal = False
    interrupted = False
    interrupt_sent = False
    interrupt_requested = False
    protocol_error: dict[str, Any] | None = None
    tool_tasks: set[asyncio.Task[None]] = set()
    tool_call_count = 0
    tool_round_count = 0
    seen_tool_call_ids: set[str] = set()
    completed_item_ids: set[str] = set()
    streamed_agent_text: dict[str, list[str]] = {}
    started_at = time.monotonic()
    last_event_at = started_at
    interrupted_at: float | None = None

    async def emit_thinking(delta: str, item_id: str = "") -> None:
        nonlocal thinking_active
        if not delta or interrupted:
            return
        streamed_reasoning_text.setdefault(item_id, []).append(delta)
        if not thinking_active or not blocks or blocks[-1].get("type") != "thinking":
            blocks.append({"type": "thinking", "content": delta})
        else:
            blocks[-1]["content"] = str(blocks[-1].get("content") or "") + delta
        thinking_active = True
        await event_broadcaster("thinking_chunk", delta)

    async def complete_thinking() -> None:
        nonlocal thinking_active
        if not thinking_active:
            return
        thinking_active = False
        await event_broadcaster("thinking_complete", "")

    async def finalize_parser() -> None:
        nonlocal parser_finalized
        if parser_finalized:
            return
        parser_finalized = True
        final_events = artifact_parser.finalize()
        if final_events:
            cleaned = await emit_artifact_stream_events(
                final_events, blocks, broadcaster=event_broadcaster
            )
            if cleaned:
                visible_parts.append(cleaned)

    async def interrupt_once() -> None:
        nonlocal interrupt_requested, interrupt_sent
        interrupt_requested = True
        if interrupt_sent or not thread_id or not turn_id:
            return
        interrupt_sent = True
        try:
            await openai_codex.client.turn_interrupt(thread_id, turn_id)
        except Exception as exc:
            logger.debug("Codex turn interrupt failed: %s", type(exc).__name__)

    async def handle_tool_request(event: dict[str, Any]) -> None:
        nonlocal tool_call_count
        params = event.get("params") or {}
        event_generation = int(event.get("generation") or -1)
        request_id = event.get("server_request_id")
        call_id = str(params.get("callId") or request_id)
        alias = str(params.get("tool") or "")
        raw_args = params.get("arguments")
        original_name = alias_map.get(alias)
        success = True
        failure_recorded = False
        executor_recorded = False
        content_items: list[dict[str, Any]]
        if call_id in seen_tool_call_ids:
            success = False
            result_text = "System error: duplicate tool call ID."
            content_items = [{"type": "inputText", "text": result_text}]
        else:
            seen_tool_call_ids.add(call_id)
            tool_call_count += 1
            parsed_args, arg_error = normalize_tool_args(raw_args)
            if event.get("round_budget_exhausted"):
                success = False
                result_text = "System error: tool-round safety budget exhausted."
                content_items = [{"type": "inputText", "text": result_text}]
                await interrupt_once()
            elif tool_call_count > _MAX_TOOL_CALLS:
                success = False
                result_text = "System error: tool-call safety budget exhausted."
                content_items = [{"type": "inputText", "text": result_text}]
                await interrupt_once()
            elif not original_name or original_name not in allowed:
                success = False
                result_text = (
                    "System error: requested tool is not available for this request."
                )
                content_items = [{"type": "inputText", "text": result_text}]
                await _record_rejected_tool(
                    alias or "unknown",
                    {},
                    result_text,
                    tool_calls,
                    blocks,
                    event_broadcaster,
                )
                failure_recorded = True
            elif arg_error:
                success = False
                result_text = f"System error: invalid arguments for tool '{original_name}': {arg_error}"
                content_items = [{"type": "inputText", "text": result_text}]
                await _record_rejected_tool(
                    original_name,
                    {},
                    result_text,
                    tool_calls,
                    blocks,
                    event_broadcaster,
                )
                failure_recorded = True
            elif is_current_request_cancelled():
                success = False
                result_text = "System error: request was cancelled."
                content_items = [{"type": "inputText", "text": result_text}]
            else:
                try:
                    result = await asyncio.wait_for(
                        xpdite_tool_executor.execute(
                            original_name,
                            parsed_args,
                            "ChatGPT subscription",
                            tool_calls,
                            blocks,
                            broadcaster=event_broadcaster,
                        ),
                        timeout=_TOOL_TIMEOUT,
                    )
                    executor_recorded = True
                    if isinstance(result, dict) and result.get("type") == "image":
                        image_url = (
                            f"data:{result.get('media_type', 'image/png')};base64,"
                            f"{result.get('data', '')}"
                        )
                        content_items = [{"type": "inputImage", "imageUrl": image_url}]
                    else:
                        result_text = str(result)
                        success = not result_text.startswith(
                            ("Error:", "System error:")
                        )
                        content_items = [{"type": "inputText", "text": result_text}]
                except asyncio.CancelledError:
                    success = False
                    result_text = "System error: request was cancelled."
                    content_items = [{"type": "inputText", "text": result_text}]
                except asyncio.TimeoutError:
                    success = False
                    result_text = "System error: tool execution timed out."
                    content_items = [{"type": "inputText", "text": result_text}]
                except Exception:
                    success = False
                    result_text = "System error: tool execution failed."
                    content_items = [{"type": "inputText", "text": result_text}]
        if not success and not failure_recorded and not executor_recorded:
            await _record_rejected_tool(
                original_name or alias or "unknown",
                {},
                content_items[0].get("text", "System error: tool execution failed."),
                tool_calls,
                blocks,
                event_broadcaster,
            )
        try:
            await openai_codex.client.respond_server_request(
                request_id,
                generation=event_generation,
                result={"contentItems": content_items, "success": success},
            )
        except Exception as exc:
            logger.warning(
                "Could not return Codex dynamic tool result (%s)", type(exc).__name__
            )

    def schedule_tool_request(event: dict[str, Any]) -> None:
        nonlocal tool_round_count, last_event_at
        if not any(not task.done() for task in tool_tasks):
            tool_round_count += 1
        if tool_round_count > MAX_MCP_TOOL_ROUNDS:
            event["round_budget_exhausted"] = True
        task = asyncio.create_task(handle_tool_request(event))
        tool_tasks.add(task)

        def tool_finished(completed_task: asyncio.Task[None]) -> None:
            nonlocal last_event_at
            tool_tasks.discard(completed_task)
            last_event_at = time.monotonic()

        task.add_done_callback(tool_finished)

    async def refresh_auth_once() -> None:
        nonlocal auth_refresh_attempted
        if auth_refresh_attempted:
            raise CodexConnectorError(
                "chatgpt_auth_expired",
                "Your ChatGPT connection expired. Reconnect it in Settings.",
            )
        auth_refresh_attempted = True
        refreshed = await openai_codex.get_status_async(refresh_token=True)
        if not refreshed.get("connected"):
            raise CodexConnectorError(
                str(refreshed.get("error_code") or "chatgpt_auth_expired"),
                str(
                    refreshed.get("last_error")
                    or "Your ChatGPT connection expired. Reconnect it in Settings."
                ),
            )

    async def preturn_call(factory: Callable[[], Awaitable[Any]]) -> Any:
        try:
            return await factory()
        except CodexConnectorError as exc:
            if exc.code != "chatgpt_auth_expired":
                raise
            await refresh_auth_once()
            return await factory()

    async def start_turn_with_early_events(params: dict[str, Any]) -> dict[str, Any]:
        assert event_stream is not None
        task = asyncio.create_task(
            openai_codex.client.turn_start(thread_id or "", params)
        )
        while not task.done():
            try:
                early_event = await event_stream.get(timeout=0.05)
            except CodexConnectorError:
                continue
            if early_event.get("method") == "item/tool/call":
                await complete_thinking()
                schedule_tool_request(early_event)
            else:
                pre_turn_events.append(early_event)
        return await task

    try:
        if is_current_request_cancelled():
            return "", token_stats, tool_calls, None
        auth_refresh_attempted = False
        pre_turn_events: list[dict[str, Any]] = []
        status = await openai_codex.get_status_async(refresh_token=False)
        if is_current_request_cancelled():
            raise CodexConnectorError("chatgpt_cancelled", "Request cancelled.")
        if not status.get("connected") and status.get("available"):
            auth_refresh_attempted = True
            status = await openai_codex.get_status_async(refresh_token=True)
            if is_current_request_cancelled():
                raise CodexConnectorError("chatgpt_cancelled", "Request cancelled.")
        if not status.get("connected"):
            code = str(status.get("error_code") or "chatgpt_not_connected")
            message = str(
                status.get("last_error")
                or "Connect ChatGPT in Settings > OpenAI before using subscription models."
            )
            raise CodexConnectorError(
                code,
                message,
            )

        models_result = await preturn_call(
            lambda: openai_codex.list_models_async(account_already_verified=True)
        )
        models = list(models_result)
        if is_current_request_cancelled():
            raise CodexConnectorError("chatgpt_cancelled", "Request cancelled.")
        selected_model = next(
            (entry for entry in models if entry.get("id") == model), None
        )
        if not selected_model:
            raise CodexConnectorError(
                "chatgpt_model_unavailable",
                "The selected model is no longer available to this ChatGPT account.",
            )
        has_history_images = any(message.get("images") for message in chat_history)
        if (image_paths or has_history_images) and not _has_image_input(selected_model):
            raise CodexConnectorError(
                "chatgpt_model_unavailable",
                "The selected ChatGPT model does not accept image input.",
            )

        history_items, turn_input = await run_in_thread(
            _prepare_codex_inputs, user_query, image_paths, chat_history
        )
        if is_current_request_cancelled():
            raise CodexConnectorError("chatgpt_cancelled", "Request cancelled.")

        from ...mcp_integration.core.manager import mcp_manager

        all_tools = mcp_manager.get_tools() if allowed else []
        dynamic_tools, alias_map = build_dynamic_tools(all_tools, allowed)
        thread_params: dict[str, Any] = {
            "model": model,
            "cwd": str(openai_codex.client.get_isolated_cwd()),
            "baseInstructions": system_prompt,
            "personality": "none",
            "ephemeral": True,
            "serviceName": "xpdite",
            "environments": [],
            "config": dict(_ISOLATION_CONFIG),
            "dynamicTools": dynamic_tools,
        }
        thread_result = await preturn_call(
            lambda: openai_codex.client.thread_start(thread_params)
        )
        thread_id = _extract_thread_id(thread_result)
        event_stream = await openai_codex.client.create_turn_event_stream(thread_id)
        if is_current_request_cancelled():
            raise CodexConnectorError("chatgpt_cancelled", "Request cancelled.")

        if history_items:
            await preturn_call(
                lambda: openai_codex.client.thread_inject_items(
                    thread_id or "", history_items
                )
            )
        if is_current_request_cancelled():
            raise CodexConnectorError("chatgpt_cancelled", "Request cancelled.")

        turn_params: dict[str, Any] = {
            "input": turn_input,
            # Request the safe, model-generated reasoning summary. Raw reasoning
            # text is intentionally never forwarded to Xpdite's UI.
            "summary": "auto",
        }
        effort = _reasoning_effort(selected_model, reasoning_effort)
        if effort:
            turn_params["effort"] = effort
        try:
            turn_result = await start_turn_with_early_events(turn_params)
        except CodexConnectorError as exc:
            if (
                exc.code != "chatgpt_auth_expired"
                or tool_call_count
                or tool_tasks
                or pre_turn_events
            ):
                raise
            await refresh_auth_once()
            turn_result = await start_turn_with_early_events(turn_params)
        turn_id = _extract_turn_id(turn_result)
        await event_stream.set_turn_id(turn_id)
        if interrupt_requested:
            await interrupt_once()

        while not terminal:
            if time.monotonic() - started_at > _TURN_OVERALL_TIMEOUT:
                await interrupt_once()
                raise CodexConnectorError(
                    "chatgpt_stream_disconnected", "The ChatGPT model turn timed out."
                )
            if is_current_request_cancelled():
                interrupted = True
                if interrupted_at is None:
                    interrupted_at = time.monotonic()
                    for task in tool_tasks:
                        if not task.done():
                            task.cancel()
                await interrupt_once()
            if (
                interrupted_at is not None
                and time.monotonic() - interrupted_at > _INTERRUPT_TIMEOUT
            ):
                break
            try:
                if pre_turn_events:
                    event = pre_turn_events.pop(0)
                else:
                    event = await event_stream.get(timeout=0.25)
            except CodexConnectorError:
                if interrupted and interrupt_sent:
                    continue
                if tool_tasks:
                    continue
                if time.monotonic() - last_event_at > _TURN_IDLE_TIMEOUT:
                    await interrupt_once()
                    raise
                continue

            last_event_at = time.monotonic()

            method = str(event.get("method") or "")
            params = (
                event.get("params") if isinstance(event.get("params"), dict) else {}
            )
            if method == "_transport/error":
                raise CodexConnectorError(
                    str(params.get("code") or "chatgpt_stream_disconnected"),
                    str(params.get("message") or "The ChatGPT connector disconnected."),
                )
            if method == "item/tool/call":
                await complete_thinking()
                schedule_tool_request(event)
                continue
            if method == "item/agentMessage/delta":
                delta = str(params.get("delta") or "")
                if delta and not interrupted:
                    await complete_thinking()
                    item_id = str(params.get("itemId") or "")
                    streamed_agent_text.setdefault(item_id, []).append(delta)
                    events = artifact_parser.feed(delta)
                    cleaned = await emit_artifact_stream_events(
                        events, blocks, broadcaster=event_broadcaster
                    )
                    if cleaned:
                        visible_parts.append(cleaned)
                continue
            if method == "item/reasoning/summaryTextDelta":
                delta = str(params.get("delta") or "")
                await emit_thinking(delta, str(params.get("itemId") or ""))
                continue
            if method == "item/reasoning/summaryPartAdded":
                item_id = str(params.get("itemId") or "")
                streamed = "".join(streamed_reasoning_text.get(item_id, []))
                if streamed and not streamed.endswith(("\n", "\r")):
                    await emit_thinking("\n\n", item_id)
                continue
            if method == "thread/tokenUsage/updated":
                token_stats = _usage_snapshot(params)
                continue
            if method == "error":
                raw_error = params.get("error")
                protocol_error = (
                    raw_error
                    if isinstance(raw_error, dict)
                    else {"message": str(raw_error or "")}
                )
                continue
            if method in {"item/started", "item/completed"}:
                item = params.get("item")
                if isinstance(item, dict):
                    item_type = str(item.get("type") or "")
                    is_known_dynamic = (
                        item_type == _DYNAMIC_TOOL_ITEM_TYPE
                        and str(item.get("tool") or item.get("name") or "") in alias_map
                    )
                    if item_type not in _PASSIVE_ITEM_TYPES and not is_known_dynamic:
                        await interrupt_once()
                        raise CodexConnectorError(
                            "chatgpt_tool_protocol_error",
                            "The ChatGPT runtime attempted a tool outside Xpdite's allowed tool boundary.",
                        )
                if method == "item/completed" and isinstance(item, dict):
                    item_id = str(item.get("id") or "")
                    if item_id and item_id in completed_item_ids:
                        continue
                    if item_id:
                        completed_item_ids.add(item_id)
                    if item.get("type") == "reasoning":
                        final_summary = _reasoning_summary_text(item)
                        streamed_summary = "".join(
                            streamed_reasoning_text.get(item_id, [])
                        )
                        if final_summary and not streamed_summary:
                            await emit_thinking(final_summary, item_id)
                        elif (
                            final_summary
                            and streamed_summary
                            and final_summary.startswith(streamed_summary)
                            and len(final_summary) > len(streamed_summary)
                        ):
                            await emit_thinking(
                                final_summary[len(streamed_summary) :], item_id
                            )
                        await complete_thinking()
                    final_text = _agent_message_text(item)
                    streamed = "".join(streamed_agent_text.get(item_id, []))
                    if final_text is not None and not interrupted:
                        if not streamed:
                            events = artifact_parser.feed(final_text)
                            cleaned = await emit_artifact_stream_events(
                                events, blocks, broadcaster=event_broadcaster
                            )
                            if cleaned:
                                visible_parts.append(cleaned)
                        elif final_text.startswith(streamed) and len(final_text) > len(
                            streamed
                        ):
                            suffix = final_text[len(streamed) :]
                            events = artifact_parser.feed(suffix)
                            cleaned = await emit_artifact_stream_events(
                                events, blocks, broadcaster=event_broadcaster
                            )
                            if cleaned:
                                visible_parts.append(cleaned)
                continue
            if method == "turn/completed":
                await complete_thinking()
                turn = (
                    params.get("turn") if isinstance(params.get("turn"), dict) else {}
                )
                status_value = str(turn.get("status") or "")
                if status_value == "completed":
                    logger.info(
                        "ChatGPT turn completed in %.2fs with %d tool call(s)",
                        time.monotonic() - started_at,
                        tool_call_count,
                    )
                    terminal = True
                elif status_value == "interrupted":
                    logger.info(
                        "ChatGPT turn interrupted after %.2fs",
                        time.monotonic() - started_at,
                    )
                    interrupted = True
                    for task in tool_tasks:
                        if not task.done():
                            task.cancel()
                    terminal = True
                elif status_value == "failed":
                    terminal = True
                    code, message = _safe_turn_error(turn, protocol_error)
                    raise CodexConnectorError(code, message)

        if tool_tasks:
            await asyncio.wait_for(
                asyncio.gather(*tool_tasks, return_exceptions=True), timeout=2.0
            )
        await finalize_parser()
        if not interrupted:
            if not visible_parts and not any(
                block.get("type") == "artifact" for block in blocks
            ):
                raise CodexConnectorError(
                    "chatgpt_unsupported_output",
                    "The ChatGPT model completed without a supported text response.",
                )
            openai_codex.record_connector_success()
            if emit_terminal_events:
                await event_broadcaster("response_complete", "")
                await event_broadcaster("token_usage", json.dumps(token_stats))
        return "".join(visible_parts), token_stats, tool_calls, blocks or None
    except CodexConnectorError as exc:
        await complete_thinking()
        await finalize_parser()
        if exc.code != "chatgpt_cancelled":
            openai_codex.record_connector_error(exc.code, str(exc))
        if not (interrupted or exc.code == "chatgpt_cancelled"):
            await event_broadcaster("error", str(exc))
        return "".join(visible_parts), token_stats, tool_calls, blocks or None
    except Exception:
        await complete_thinking()
        logger.exception("ChatGPT app-server provider failed")
        await finalize_parser()
        message = (
            "The ChatGPT connector encountered an unexpected error. Please try again."
        )
        await event_broadcaster("error", message)
        return "".join(visible_parts), token_stats, tool_calls, blocks or None
    finally:
        if tool_tasks:
            for task in tool_tasks:
                if not task.done():
                    task.cancel()
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tool_tasks, return_exceptions=True), timeout=2.0
                )
            except asyncio.TimeoutError:
                logger.warning("Timed out cancelling ChatGPT dynamic tool tasks")
        if event_stream is not None:
            if turn_id and not terminal:
                try:
                    await asyncio.wait_for(interrupt_once(), timeout=_INTERRUPT_TIMEOUT)
                except asyncio.TimeoutError:
                    pass
            await event_stream.close()
