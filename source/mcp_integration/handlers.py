"""Shared MCP tool retrieval helpers."""

import json
import logging

from .manager import mcp_manager
from .retriever import retriever

logger = logging.getLogger(__name__)


def retrieve_relevant_tools(user_query: str) -> list:
    """Retrieve filtered MCP tools relevant to a user query."""
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

    all_tools = mcp_manager.get_tools() or []

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
