"""
Memory inline tool executor.

Handles filesystem-backed memory tools directly in the backend without routing
through an MCP subprocess.
"""

from __future__ import annotations

from collections import defaultdict
import logging
from typing import Any

from ...core.thread_pool import run_in_thread
from ...services.memory_store.memory import memory_service

logger = logging.getLogger(__name__)

MEMORY_TOOLS = {
    "memlist",
    "memread",
    "memcommit",
}


def is_memory_tool(fn_name: str, server_name: str) -> bool:
    """Check whether a tool call should be handled by the memory executor."""
    return server_name == "memory" and fn_name in MEMORY_TOOLS


async def execute_memory_tool(
    fn_name: str,
    fn_args: dict[str, Any],
    server_name: str,
) -> str:
    """Execute a memory tool and return a string formatted for the LLM."""
    try:
        if fn_name == "memlist":
            folder = str(fn_args.get("folder", "") or "").strip() or None
            memories = await run_in_thread(memory_service.list_memories, folder)
            return _format_memory_listing(memories, folder)

        if fn_name == "memread":
            path = str(fn_args.get("path", "") or "").strip()
            if not path:
                return "Error: path is required"
            detail = await run_in_thread(memory_service.read_memory, path, touch_access=True)
            return detail["raw_text"]

        if fn_name == "memcommit":
            path = str(fn_args.get("path", "") or "").strip()
            if not path:
                return "Error: path is required"

            title = str(fn_args.get("title", "") or "").strip()
            category = str(fn_args.get("category", "") or "").strip()
            importance = fn_args.get("importance")
            abstract = str(fn_args.get("abstract", "") or "").strip()
            body = str(fn_args.get("body", "") or "")
            tags = fn_args.get("tags") or []
            if not isinstance(tags, list):
                return "Error: tags must be an array of strings"

            existed = False
            try:
                await run_in_thread(memory_service.read_memory, path, touch_access=False)
                existed = True
            except FileNotFoundError:
                existed = False

            detail = await run_in_thread(
                memory_service.upsert_memory,
                path=path,
                title=title,
                category=category,
                importance=importance,
                tags=tags,
                abstract=abstract,
                body=body,
            )
            action = "Updated" if existed else "Created"
            return f"{action} memory at '{detail['path']}'."

        return f"Unknown memory tool: {fn_name}"
    except FileNotFoundError:
        path = str(fn_args.get("path", "") or "").strip()
        return f"Error: memory '{path}' was not found"
    except ValueError as exc:
        return f"Error: {exc}"
    except (OSError, UnicodeError) as exc:
        logger.warning("Memory tool %s failed (%s)", fn_name, type(exc).__name__)
        return "Error: memory operation failed. See server logs for details."
    except Exception:
        logger.exception("Unexpected memory tool failure for %s", fn_name)
        return "Error: memory operation failed. See server logs for details."


def _format_memory_listing(memories: list[dict[str, Any]], folder: str | None) -> str:
    if not memories:
        if folder:
            return f"No memories found in '{folder}'."
        return "No memories found."

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for memory in memories:
        grouped[memory.get("folder") or "."].append(memory)

    header = "Memory listing"
    if folder:
        header += f" for '{folder}'"
    lines = [f"{header}:", ""]

    for group_name in sorted(grouped):
        display_name = group_name if group_name != "." else "(root)"
        lines.append(f"[{display_name}]")
        for memory in sorted(grouped[group_name], key=lambda item: item["path"]):
            line = f"- {memory['path']} :: {memory.get('abstract', '')}"
            if memory.get("parse_warning"):
                line += f" [warning: {memory['parse_warning']}]"
            lines.append(line)
        lines.append("")

    return "\n".join(lines).strip()
