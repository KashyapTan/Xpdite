"""Provider-neutral execution for Xpdite MCP and inline tools."""

from __future__ import annotations

import copy
import json
import logging
from typing import Any, Awaitable, Callable, Optional

from ...core.connection import broadcast_message
from ...mcp_integration.core.tool_args import sanitize_tool_args
from ...mcp_integration.core.tool_output import format_tool_output

logger = logging.getLogger(__name__)


def _truncate_tool_result(result: str) -> str:
    from ...infrastructure.config import MAX_TOOL_RESULT_LENGTH

    if len(result) <= MAX_TOOL_RESULT_LENGTH:
        return result
    logger.warning("Truncating large tool output (%d chars)", len(result))
    return result[:MAX_TOOL_RESULT_LENGTH] + "... [Output truncated due to length]"


def _append_tool_result(
    fn_name: str,
    fn_args: dict[str, Any],
    result: str,
    server_name: str,
    tool_calls: list[dict[str, Any]],
    interleaved_blocks: list[dict[str, Any]],
) -> None:
    safe_args = sanitize_tool_args(fn_name, server_name, fn_args)
    tool_calls.append(
        {"name": fn_name, "args": safe_args, "result": result, "server": server_name}
    )
    interleaved_blocks.append(
        {"type": "tool_call", "name": fn_name, "args": safe_args, "server": server_name}
    )


def _build_spawn_agent_request(fn_args: dict[str, Any]) -> dict[str, Any]:
    return {
        "instruction": fn_args.get("instruction", ""),
        "model_tier": fn_args.get("model_tier", "fast"),
        "agent_name": fn_args.get("agent_name", "Sub-Agent"),
    }


class XpditeToolExecutor:
    """Execute exactly one already-authorized Xpdite tool call."""

    async def execute(
        self,
        fn_name: str,
        fn_args: dict[str, Any],
        provider_label: str,
        tool_calls: list[dict[str, Any]],
        interleaved_blocks: list[dict[str, Any]],
        *,
        precomputed_result: Optional[str] = None,
        broadcaster: Callable[[str, Any], Awaitable[Any]] = broadcast_message,
    ) -> str | dict[str, Any]:
        from ...mcp_integration.core.manager import mcp_manager
        from ...mcp_integration.executors.memory_executor import (
            execute_memory_tool,
            is_memory_tool,
        )
        from ...mcp_integration.executors.scheduler_executor import (
            execute_scheduler_tool,
            is_scheduler_tool,
        )
        from ...mcp_integration.executors.skills_executor import execute_skill_tool
        from ...mcp_integration.executors.terminal_executor import (
            execute_terminal_tool,
            is_terminal_tool,
        )
        from ...mcp_integration.executors.video_watcher_executor import (
            execute_video_watcher_tool,
            is_video_watcher_tool,
        )
        from ...services.hooks_runtime import get_hooks_runtime

        try:
            server_name = mcp_manager.get_tool_server_name(fn_name) or "unknown"
        except Exception as exc:
            logger.warning(
                "%s tool server lookup failed for %s (%s)",
                provider_label,
                fn_name,
                type(exc).__name__,
            )
            server_name = "unknown"

        hooks_runtime = get_hooks_runtime()
        effective_args = copy.deepcopy(fn_args)
        pre_hook_result = await hooks_runtime.dispatch_pre_tool_use(
            fn_name, effective_args, server_name=server_name
        )
        if pre_hook_result.updated_input is not None:
            effective_args = copy.deepcopy(pre_hook_result.updated_input)

        safe_args = sanitize_tool_args(fn_name, server_name, effective_args)
        logger.info(
            "%s tool call: %s(%s) from '%s'",
            provider_label,
            fn_name,
            safe_args,
            server_name,
        )

        hook_context_messages: list[str] = []
        if not pre_hook_result.suppress_output:
            hook_context_messages.extend(pre_hook_result.system_messages)
            hook_context_messages.extend(pre_hook_result.additional_context)

        if pre_hook_result.blocked:
            result: Any = "Error: Blocked by Claude-compatible hook: " + (
                pre_hook_result.reason or "Tool execution denied."
            )
        else:
            await broadcaster(
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
                elif server_name == "skills" and fn_name in {"list_skills", "use_skill"}:
                    result = execute_skill_tool(fn_name, effective_args)
                elif is_scheduler_tool(fn_name, server_name):
                    result = await execute_scheduler_tool(fn_name, effective_args, server_name)
                else:
                    result = await mcp_manager.call_tool(fn_name, effective_args)
            except Exception as exc:
                logger.warning(
                    "%s tool execution failed for %s on '%s' (%s)",
                    provider_label,
                    fn_name,
                    server_name,
                    type(exc).__name__,
                )
                result = "System error: tool execution failed. See server logs for details."

        tool_failed = isinstance(result, str) and result.startswith(("Error:", "System error:"))
        if not pre_hook_result.blocked:
            if tool_failed:
                post_hook_result = await hooks_runtime.dispatch_post_tool_use_failure(
                    fn_name, effective_args, str(result), server_name=server_name
                )
            else:
                post_hook_result = await hooks_runtime.dispatch_post_tool_use(
                    fn_name, effective_args, result, server_name=server_name
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
                result = "Error: Blocked by Claude-compatible hook: " + (
                    post_hook_result.reason or "Tool output was blocked."
                )

        if isinstance(result, dict) and result.get("type") == "image" and not hook_context_messages:
            summary = (
                f"[Image: {result.get('width', '?')}x{result.get('height', '?')}, "
                f"{result.get('file_size_bytes', 0):,} bytes]"
            )
            await broadcaster(
                "tool_call",
                json.dumps(
                    {
                        "name": fn_name,
                        "args": safe_args,
                        "result": summary,
                        "server": server_name,
                        "status": "complete",
                    }
                ),
            )
            _append_tool_result(
                fn_name, effective_args, summary, server_name, tool_calls, interleaved_blocks
            )
            return result

        formatted_result = format_tool_output(result)
        if isinstance(formatted_result, dict):
            serialized = json.dumps(formatted_result, ensure_ascii=False, default=str)
        else:
            serialized = str(formatted_result)
        if hook_context_messages:
            serialized += "\n\n[Claude-compatible hook context]\n" + "\n\n".join(
                message for message in hook_context_messages if message
            )
        result_text = _truncate_tool_result(serialized)
        await broadcaster(
            "tool_call",
            json.dumps(
                {
                    "name": fn_name,
                    "args": safe_args,
                    "result": result_text,
                    "server": server_name,
                    "status": "complete",
                }
            ),
        )
        _append_tool_result(
            fn_name,
            effective_args,
            result_text,
            server_name,
            tool_calls,
            interleaved_blocks,
        )
        return result_text


xpdite_tool_executor = XpditeToolExecutor()


async def execute_and_broadcast_tool(
    fn_name: str,
    fn_args: dict[str, Any],
    provider_label: str,
    tool_calls: list[dict[str, Any]],
    interleaved_blocks: list[dict[str, Any]],
    *,
    precomputed_result: Optional[str] = None,
    broadcaster: Callable[[str, Any], Awaitable[Any]] = broadcast_message,
) -> str | dict[str, Any]:
    """Functional compatibility wrapper used by cloud providers."""
    return await xpdite_tool_executor.execute(
        fn_name,
        fn_args,
        provider_label,
        tool_calls,
        interleaved_blocks,
        precomputed_result=precomputed_result,
        broadcaster=broadcaster,
    )
