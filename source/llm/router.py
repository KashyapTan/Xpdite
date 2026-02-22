"""
LLM Provider Router.

Routes chat requests to the correct provider (Ollama or cloud) based on the
model name prefix. Cloud models use the format "provider/model-name" (e.g.,
"anthropic/claude-sonnet-4-20250514"). Ollama models have no prefix.
"""

from typing import List, Dict, Any, Tuple


def parse_provider(model_name: str) -> Tuple[str, str]:
    """
    Parse a model name into (provider, model).

    Examples:
        "anthropic/claude-sonnet-4-20250514" -> ("anthropic", "claude-sonnet-4-20250514")
        "openai/gpt-4o" -> ("openai", "gpt-4o")
        "gemini/gemini-2.5-pro" -> ("gemini", "gemini-2.5-pro")
        "qwen3-vl:8b-instruct" -> ("ollama", "qwen3-vl:8b-instruct")
    """
    if "/" in model_name:
        provider, _, model = model_name.partition("/")
        if provider in ("anthropic", "openai", "gemini"):
            return provider, model
    return "ollama", model_name


async def route_chat(
    model_name: str,
    user_query: str,
    image_paths: List[str],
    chat_history: List[Dict[str, Any]],
    forced_skills: List[Dict[str, Any]] | None = None,
) -> tuple[str, Dict[str, int], List[Dict[str, Any]]]:
    """
    Route a chat request to the correct LLM provider.

    Same return signature as stream_ollama_chat:
        (response_text, token_stats, tool_calls_list)

    For Ollama models, delegates to stream_ollama_chat (MCP tool handling built-in).
    For cloud models, retrieves relevant tools and passes them to stream_cloud_chat
    which handles tool execution inline during streaming.
    """
    provider, model = parse_provider(model_name)

    from ..database import db
    from .prompt import build_system_prompt
    from ..mcp_integration.skill_injector import get_skills_to_inject, build_skills_prompt_block
    from ..mcp_integration.manager import mcp_manager
    from ..core.state import app_state

    # Build skills block for system prompt
    skills_to_inject = get_skills_to_inject(
        retrieved_tools=[],
        forced_skills=forced_skills or [],
        db=db,
        mcp_manager=mcp_manager,
    )
    skills_block = build_skills_prompt_block(skills_to_inject)

    if skills_to_inject:
        print(f"[Skills] Injecting {len(skills_to_inject)} skill(s): {[s['skill_name'] for s in skills_to_inject]}")

    custom_template = db.get_setting("system_prompt_template")
    system_prompt = build_system_prompt(skills_block=skills_block, template=custom_template)

    if provider == "ollama":
        if app_state.stop_streaming:
            return "", {"prompt_eval_count": 0, "eval_count": 0}, []

        from .ollama_provider import stream_ollama_chat

        return await stream_ollama_chat(user_query, image_paths, chat_history, system_prompt)

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
        )

    if app_state.stop_streaming:
        return "", {"prompt_eval_count": 0, "eval_count": 0}, []

    # Get relevant tool names for the streaming function
    allowed_tool_names: set[str] = set()
    if mcp_manager.has_tools():
        from ..mcp_integration.handlers import retrieve_relevant_tools

        filtered_tools = retrieve_relevant_tools(user_query)
        allowed_tool_names = {t["function"]["name"] for t in filtered_tools}

    # Stream with inline tool calling — text and tool results are
    # interleaved and broadcast to the user in real-time
    response_text, token_stats, tool_calls_list = await stream_cloud_chat(
        provider,
        model,
        api_key,
        user_query,
        image_paths,
        chat_history,
        allowed_tool_names=allowed_tool_names if allowed_tool_names else None,
        system_prompt=system_prompt,
    )

    return response_text, token_stats, tool_calls_list
