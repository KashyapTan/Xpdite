"""LLM provider router for the unified LiteLLM chat path."""

from typing import List, Dict, Any, Optional
import logging

from . import provider_resolution as _provider_resolution

logger = logging.getLogger(__name__)

parse_provider = _provider_resolution.parse_provider
is_local_ollama_model = _provider_resolution.is_local_ollama_model
resolve_model_target = _provider_resolution.resolve_model_target


async def route_chat(
    model_name: str,
    user_query: str,
    image_paths: List[str],
    chat_history: List[Dict[str, Any]],
    forced_skills: list | None = None,  # List[Skill] at runtime
) -> tuple[str, Dict[str, int], List[Dict[str, Any]], Optional[List[Dict[str, Any]]]]:
    """
    Route a chat request through the unified LiteLLM provider path.

    Returns:
        (response_text, token_stats, tool_calls_list, interleaved_blocks)
    """
    target = resolve_model_target(model_name)

    from ..database import db
    from ..core.thread_pool import run_in_thread
    from ..config import MEMORY_PROFILE_FILE
    from ..services.memory import memory_service
    from .prompt import (
        build_memory_prompt_block,
        build_system_prompt,
        build_user_profile_block,
    )
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
    memory_block = build_memory_prompt_block()
    user_profile_block = ""
    auto_inject_profile = db.get_setting("memory_profile_auto_inject")
    should_inject_profile = auto_inject_profile != "false"

    if should_inject_profile and MEMORY_PROFILE_FILE.exists():
        try:
            profile_detail = await run_in_thread(
                memory_service.read_memory,
                "profile/user_profile.md",
                touch_access=False,
            )
            profile_body = str(profile_detail.get("body", "")).strip()
            if profile_body:
                user_profile_block = build_user_profile_block(profile_body)
        except FileNotFoundError:
            user_profile_block = ""
        except Exception as exc:
            logger.warning("Profile auto-injection skipped: %s", exc)

    system_prompt = build_system_prompt(
        skills_block=skills_block,
        memory_block=memory_block,
        user_profile_block=user_profile_block,
        template=custom_template,
    )

    from .cloud_provider import stream_cloud_chat

    if target.provider != "ollama" and not target.api_key:
        from ..core.connection import broadcast_message

        await broadcast_message(
            "error",
            f"No API key configured for {target.provider}. Add one in Settings.",
        )
        return (
            f"Error: No API key for {target.provider}",
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
            target.provider,
            target.model,
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
        target.provider,
        target.model,
        target.api_key,
        user_query,
        image_paths,
        chat_history,
        allowed_tool_names=allowed_tool_names if allowed_tool_names else None,
        system_prompt=system_prompt,
        api_base=target.api_base,
        litellm_model_override=target.litellm_model,
        provider_kwargs=target.provider_kwargs,
    )

    return response_text, token_stats, tool_calls_list, interleaved_blocks
