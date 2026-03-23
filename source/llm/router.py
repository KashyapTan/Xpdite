"""
LLM Provider Router.

Routes chat requests to the correct provider (Ollama or cloud) based on the
model name prefix. Cloud models use the format "provider/model-name" (e.g.,
"anthropic/claude-sonnet-4-20250514"). Ollama models have no prefix.
"""

from typing import List, Dict, Any, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


def parse_provider(model_name: str) -> Tuple[str, str]:
    """
    Parse a model name into (provider, model).

    Examples:
        "anthropic/claude-sonnet-4-20250514" -> ("anthropic", "claude-sonnet-4-20250514")
        "openai/gpt-4o" -> ("openai", "gpt-4o")
        "gemini/gemini-2.5-pro" -> ("gemini", "gemini-2.5-pro")
        "openrouter/anthropic/claude-3-5-sonnet" -> ("openrouter", "anthropic/claude-3-5-sonnet")
        "qwen3-vl:8b-instruct" -> ("ollama", "qwen3-vl:8b-instruct")
    """
    if "/" in model_name:
        provider, _, model = model_name.partition("/")
        if provider in ("anthropic", "openai", "gemini", "openrouter"):
            return provider, model
    return "ollama", model_name


def is_local_ollama_model(model_name: str) -> bool:
    """Whether a model resolves to a local Ollama runtime.

    Rules:
    - Non-Ollama providers (anthropic/openai/gemini/openrouter) return False.
    - Ollama models tagged as cloud (``:cloud`` or ``-cloud``) return False.
    - All other Ollama models are treated as local and return True.
    """
    normalized = model_name.strip()
    provider, _ = parse_provider(normalized)
    if provider != "ollama":
        return False

    if normalized.lower().startswith("ollama/"):
        normalized = normalized.partition("/")[2]

    lower_name = normalized.lower()
    if lower_name.endswith(":cloud"):
        return False
    if lower_name.endswith("-cloud"):
        return False

    return True


async def route_chat(
    model_name: str,
    user_query: str,
    image_paths: List[str],
    chat_history: List[Dict[str, Any]],
    forced_skills: list | None = None,  # List[Skill] at runtime
) -> tuple[str, Dict[str, int], List[Dict[str, Any]], Optional[List[Dict[str, Any]]]]:
    """
    Route a chat request to the correct LLM provider.

    Returns:
        (response_text, token_stats, tool_calls_list, interleaved_blocks)

    For Ollama models, delegates to stream_ollama_chat (MCP tool handling built-in).
    For cloud models, retrieves relevant tools and passes them to stream_cloud_chat
    which handles tool execution inline during streaming.
    """
    provider, model = parse_provider(model_name)

    from ..database import db
    from .prompt import build_system_prompt
    from ..mcp_integration.skill_injector import (
        get_skills_to_inject,
        build_skills_prompt_block,
    )
    from ..mcp_integration.manager import mcp_manager
    from ..core.request_context import is_current_request_cancelled

    # Retrieve relevant MCP tools for this query
    retrieved_tools: list = []
    if mcp_manager.has_tools():
        from ..mcp_integration.handlers import retrieve_relevant_tools

        retrieved_tools = retrieve_relevant_tools(user_query)

    if retrieved_tools:
        tool_names = [t["function"]["name"] for t in retrieved_tools]
        logger.info(
            "Retrieved %d tool(s) for query '%s...': %s",
            len(tool_names),
            user_query[:40],
            tool_names,
        )
    else:
        logger.info("No tools retrieved for query '%s...'", user_query[:40])

    # Skill injection: only inject when forced via slash commands or YouTube URL
    # For on-demand discovery, the LLM uses list_skills/use_skill tools
    skills_to_inject = get_skills_to_inject(
        forced_skills=forced_skills or [],
        user_query=user_query,
    )
    skills_block = build_skills_prompt_block(skills_to_inject)

    if skills_to_inject:
        logger.debug(
            "Injecting %d skill(s): %s",
            len(skills_to_inject),
            [s.name for s in skills_to_inject],
        )

    custom_template = db.get_setting("system_prompt_template")
    system_prompt = build_system_prompt(
        skills_block=skills_block, template=custom_template
    )

    if provider == "ollama":
        if is_current_request_cancelled():
            return "", {"prompt_eval_count": 0, "eval_count": 0}, [], None

        from .ollama_provider import stream_ollama_chat

        return await stream_ollama_chat(
            user_query, image_paths, chat_history, system_prompt
        )

    # ── Cloud provider path ──────────────────────────────────────────
    # Tools are handled inline during streaming — no separate detection phase.
    from .key_manager import key_manager
    from .cloud_provider import stream_cloud_chat

    api_key = key_manager.get_api_key(provider)
    if not api_key:
        from ..core.connection import broadcast_message

        await broadcast_message(
            "error", f"No API key configured for {provider}. Add one in Settings."
        )
        return (
            f"Error: No API key for {provider}",
            {"prompt_eval_count": 0, "eval_count": 0},
            [],
            None,
        )

    if is_current_request_cancelled():
        return "", {"prompt_eval_count": 0, "eval_count": 0}, [], None

    # Reuse tools already retrieved above for skill injection
    allowed_tool_names: set[str] = (
        {t["function"]["name"] for t in retrieved_tools} if retrieved_tools else set()
    )

    if allowed_tool_names:
        logger.info(
            "Submitting %d tool(s) to %s/%s: %s",
            len(allowed_tool_names),
            provider,
            model,
            sorted(allowed_tool_names),
        )

    # Stream with inline tool calling — text and tool results are
    # interleaved and broadcast to the user in real-time
    (
        response_text,
        token_stats,
        tool_calls_list,
        interleaved_blocks,
    ) = await stream_cloud_chat(
        provider,
        model,
        api_key,
        user_query,
        image_paths,
        chat_history,
        allowed_tool_names=allowed_tool_names if allowed_tool_names else None,
        system_prompt=system_prompt,
    )

    return response_text, token_stats, tool_calls_list, interleaved_blocks
