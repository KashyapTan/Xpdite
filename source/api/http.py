"""
HTTP REST API endpoints.

Use for:
- One-time data fetches (models list)
- Settings management (enabled models, API keys)
- Health checks
- Cloud provider model listing
"""

from fastapi import APIRouter, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import logging
from ollama import AsyncClient as OllamaAsyncClient

logger = logging.getLogger(__name__)

from ..core.thread_pool import run_in_thread as _run_in_thread


router = APIRouter(prefix="/api")


# ============================================
# Health Check
# ============================================


@router.get("/health")
async def health_check():
    """Check if the server is running."""
    return {"status": "healthy"}


# ============================================
# Models API
# ============================================


class OllamaModel(BaseModel):
    """Represents an Ollama model."""

    name: str
    size: int  # in bytes
    parameter_size: str
    quantization: str


@router.get("/models/ollama")
async def get_ollama_models() -> List[dict]:
    """
    Get all Ollama models installed on the user's machine.

    Calls `ollama.list()` which talks to the local Ollama daemon
    and returns every model that has been pulled.
    """
    try:
        # Use async client — no thread needed
        async_client = OllamaAsyncClient()
        response = await async_client.list()
        models = []
        # The Ollama SDK returns objects with attributes, not dicts.
        # e.g. Model(model='gemma3:12b', size=..., details=ModelDetails(...))
        for m in response.models:
            details = m.details
            models.append(
                {
                    "name": m.model or "unknown",
                    "size": m.size or 0,
                    "parameter_size": getattr(details, "parameter_size", "")
                    if details
                    else "",
                    "quantization": getattr(details, "quantization_level", "")
                    if details
                    else "",
                }
            )
        return models
    except Exception as e:
        logger.error("Error fetching Ollama models: %s", e)
        return {"models": [], "error": f"Ollama not reachable: {str(e)[:100]}"}


# ============================================
# Enabled Models API (persisted in DB)
# ============================================


class EnabledModelsUpdate(BaseModel):
    """Request body for toggling models."""

    models: List[str]


@router.get("/models/enabled")
async def get_enabled_models() -> List[str]:
    """
    Get the list of model names the user has toggled on.

    These are stored in the SQLite database so they persist across restarts.
    """
    from ..database import db

    return db.get_enabled_models()


@router.put("/models/enabled")
async def set_enabled_models(body: EnabledModelsUpdate):
    """
    Replace the full list of enabled models with the given list.

    Called every time the user toggles a model on/off in SettingsModels.
    """
    from ..database import db

    db.set_enabled_models(body.models)
    return {"status": "updated", "models": body.models}


# ============================================
# API Key Management
# ============================================


class ApiKeyUpdate(BaseModel):
    """Request body for saving an API key."""

    key: str


@router.get("/keys")
async def get_api_key_status():
    """
    Get status of all provider API keys.
    Returns which providers have keys stored and their masked values.
    """
    from ..llm.key_manager import key_manager

    return key_manager.get_api_key_status()


@router.put("/keys/{provider}")
async def save_api_key(provider: str, body: ApiKeyUpdate):
    """
    Validate and store an API key for a provider.

    Performs a lightweight validation call before storing.
    Uses async clients/threads to avoid blocking the server loop.
    """
    from ..llm.key_manager import key_manager, VALID_PROVIDERS

    if provider not in VALID_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Invalid provider: {provider}")

    api_key = body.key.strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="API key cannot be empty")

    # Validate the key by making a lightweight API call
    try:
        if provider == "anthropic":
            import anthropic

            client = anthropic.AsyncAnthropic(api_key=api_key)
            # Validate by counting tokens — try multiple models in case one is deprecated
            _ANTHROPIC_VALIDATION_MODELS = [
                "claude-sonnet-4-20250514",
                "claude-3-haiku-20240307",
            ]
            last_err = None
            for model_id in _ANTHROPIC_VALIDATION_MODELS:
                try:
                    await client.messages.count_tokens(
                        model=model_id,
                        messages=[{"role": "user", "content": "hi"}],
                    )
                    last_err = None
                    break
                except anthropic.NotFoundError:
                    last_err = None  # model gone, but key was accepted
                    break
                except anthropic.AuthenticationError as e:
                    raise e  # key itself is invalid — propagate immediately
                except Exception as e:
                    last_err = e
            if last_err is not None:
                raise last_err

        elif provider == "openai":
            import openai

            client = openai.AsyncOpenAI(api_key=api_key)
            # List models as a lightweight validation
            await client.models.list()

        elif provider == "gemini":
            from google import genai

            client = genai.Client(api_key=api_key)
            # List models as a lightweight validation (run in thread)
            await _run_in_thread(
                lambda: list(client.models.list(config={"page_size": 1}))
            )

    except Exception as e:
        error_msg = str(e)
        logger.warning("API key validation failed for %s: %s", provider, error_msg)
        raise HTTPException(
            status_code=401, detail=f"Invalid API key: {error_msg[:200]}"
        )

    # Key is valid — encrypt and store
    key_manager.save_api_key(provider, api_key)
    return {
        "status": "saved",
        "provider": provider,
        "masked": key_manager.mask_key(api_key),
    }


@router.delete("/keys/{provider}")
async def delete_api_key(provider: str):
    """Remove a stored API key for a provider."""
    from ..llm.key_manager import key_manager, VALID_PROVIDERS

    if provider not in VALID_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Invalid provider: {provider}")

    key_manager.delete_api_key(provider)

    # Also remove any cloud models from the enabled list that belong to this provider
    from ..database import db

    enabled = db.get_enabled_models()
    filtered = [m for m in enabled if not m.startswith(f"{provider}/")]
    if len(filtered) != len(enabled):
        db.set_enabled_models(filtered)

    return {"status": "deleted", "provider": provider}


# ============================================
# Cloud Provider Models
# ============================================

# Fallback lists in case APIs fail
ANTHROPIC_FALLBACK = [
    {
        "name": "claude-3-7-sonnet-20250219",
        "description": "Claude 3.7 Sonnet — latest hybrid reasoning",
    },
    {
        "name": "claude-3-5-sonnet-20241022",
        "description": "Claude 3.5 Sonnet — high intelligence",
    },
    {
        "name": "claude-3-5-haiku-20241022",
        "description": "Claude 3.5 Haiku — fastest",
    },
    {"name": "claude-3-opus-20240229", "description": "Claude 3 Opus — powerful"},
]

OPENAI_FALLBACK = [
    {"name": "o3-mini", "description": "o3-mini — latest fast reasoning"},
    {"name": "o1", "description": "o1 — high-reasoning flagship"},
    {"name": "gpt-4o", "description": "GPT-4o — versatile flagship"},
    {"name": "gpt-4o-mini", "description": "GPT-4o Mini — fast & cheap"},
    {"name": "o1-mini", "description": "o1-mini — efficient reasoning"},
]

GEMINI_FALLBACK = [
    {"name": "gemini-2.0-flash", "description": "Gemini 2.0 Flash — next-gen speed"},
    {
        "name": "gemini-2.0-pro-exp-0505",
        "description": "Gemini 2.0 Pro (Exp) — highest intelligence",
    },
    {"name": "gemini-1.5-pro", "description": "Gemini 1.5 Pro — balanced"},
    {"name": "gemini-1.5-flash", "description": "Gemini 1.5 Flash — fast"},
]


# ============================================
# Google OAuth Connection
# ============================================


@router.get("/google/status")
async def get_google_status():
    """Get the current Google account connection status."""
    from ..services.google_auth import google_auth

    return google_auth.get_status()


@router.post("/google/connect")
async def connect_google():
    """
    Initiate Google OAuth flow.

    Opens the user's browser for Google login.
    This is a blocking call that waits for the OAuth callback.

    Uses the app-owned thread pool to avoid the default executor shutdown issue.
    """
    from ..services.google_auth import google_auth

    try:
        result = await _run_in_thread(google_auth.start_oauth_flow)
    except Exception as e:
        logger.error("Google OAuth error: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"OAuth flow failed: {str(e)[:300]}",
        )

    if not result.get("success"):
        # Return the error as a proper 400 so the frontend can parse it
        raise HTTPException(
            status_code=400,
            detail=result.get("error", "OAuth flow failed"),
        )

    # Start Gmail and Calendar MCP servers after successful auth
    try:
        from ..mcp_integration.manager import mcp_manager

        await mcp_manager.connect_google_servers()
    except Exception as e:
        logger.warning("Google MCP server startup failed (non-fatal): %s", e)

    return result


@router.post("/google/disconnect")
async def disconnect_google():
    """
    Disconnect Google account: revoke token, remove token file,
    and stop Gmail/Calendar MCP servers.
    """
    from ..services.google_auth import google_auth
    from ..mcp_integration.manager import mcp_manager

    # Disconnect MCP servers first
    try:
        await mcp_manager.disconnect_google_servers()
    except Exception as e:
        logger.warning("Google MCP server disconnect failed (non-fatal): %s", e)

    return google_auth.disconnect()


# ============================================
# Cloud Provider Models
# ============================================


@router.get("/models/anthropic")
async def get_anthropic_models() -> List[dict]:
    """Get available Anthropic models. Requires a stored API key."""
    from ..llm.key_manager import key_manager

    api_key = key_manager.get_api_key("anthropic")
    if not api_key:
        return []

    try:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=api_key)

        models = []
        async for m in client.models.list(limit=100):
            # Use display_name if available, else ID
            display = getattr(m, "display_name", m.id)
            models.append(
                {
                    "name": f"anthropic/{m.id}",
                    "provider": "anthropic",
                    "description": display,
                }
            )

        # If we got models, return them
        if models:
            # Sort by creation date if available (descending), else name
            models.sort(key=lambda x: x["name"], reverse=True)
            return models

    except Exception as e:
        logger.error("Error fetching Anthropic models via API: %s", e)
        # Fall through to fallback

    # Fallback
    return [
        {
            "name": f"anthropic/{m['name']}",
            "provider": "anthropic",
            "description": m["description"],
        }
        for m in ANTHROPIC_FALLBACK
    ]


@router.get("/models/openai")
async def get_openai_models() -> List[dict]:
    """Get available OpenAI models. Requires a stored API key."""
    from ..llm.key_manager import key_manager

    api_key = key_manager.get_api_key("openai")
    if not api_key:
        return []

    try:
        import openai

        client = openai.AsyncOpenAI(api_key=api_key)
        response = await client.models.list()

        # Filter to chat-capable models (gpt-*, o1*, o3*, o4*, chatgpt-*)
        chat_prefixes = ("gpt-4", "o1", "o3", "o4", "chatgpt-", "gpt-5")
        exclude_keywords = (
            "instruct",
            "realtime",
            "audio",
            "search",
            "tts",
            "whisper",
            "dall-e",
            "embedding",
            "moderation",
            "davinci",
            "babbage",
        )

        models = []
        for m in response.data:
            model_id = m.id
            # Simple check: starts with a known prefix AND doesn't contain excluded keywords
            if any(model_id.startswith(p) for p in chat_prefixes):
                if not any(kw in model_id for kw in exclude_keywords):
                    models.append(
                        {
                            "name": f"openai/{model_id}",
                            "provider": "openai",
                            "description": model_id,
                        }
                    )

        # Sort alphabetically
        models.sort(key=lambda x: x["name"])
        if models:
            return models

    except Exception as e:
        logger.error("Error fetching OpenAI models: %s", e)
        # Fall through to fallback

    # Fallback
    return [
        {
            "name": f"openai/{m['name']}",
            "provider": "openai",
            "description": m["description"],
        }
        for m in OPENAI_FALLBACK
    ]


@router.get("/models/gemini")
async def get_gemini_models() -> List[dict]:
    """Get available Gemini models. Requires a stored API key."""
    from ..llm.key_manager import key_manager

    api_key = key_manager.get_api_key("gemini")
    if not api_key:
        return []

    try:
        from google import genai

        client = genai.Client(api_key=api_key)

        # Run sync list_models in thread
        # Note: The Google GenAI SDK might return an iterator or list depending on version
        response = await _run_in_thread(lambda: list(client.models.list()))

        models = []
        for m in response:
            model_name = m.name or ""
            # Only include generateContent-capable models
            actions = m.supported_actions or []
            if "generateContent" not in actions:
                continue
            # Strip "models/" prefix if present
            if model_name.startswith("models/"):
                model_name = model_name[7:]
            # Skip embedding/vision-only/legacy models
            if any(kw in model_name for kw in ("embedding", "aqa", "bison", "gecko")):
                continue
            display_name = m.display_name or model_name
            models.append(
                {
                    "name": f"gemini/{model_name}",
                    "provider": "gemini",
                    "description": display_name,
                }
            )

        models.sort(key=lambda x: x["name"])
        if models:
            return models

    except Exception as e:
        logger.error("Error fetching Gemini models: %s", e)
        # Fall through to fallback

    # Fallback
    return [
        {
            "name": f"gemini/{m['name']}",
            "provider": "gemini",
            "description": m["description"],
        }
        for m in GEMINI_FALLBACK
    ]


# ============================================
# MCP Tools API
# ============================================


class ToolsSettingsUpdate(BaseModel):
    """Request body for updating tool settings."""

    always_on: List[str]
    top_k: int


@router.get("/mcp/servers")
async def get_mcp_servers():
    """Get connected MCP servers and their tools."""
    from ..mcp_integration.manager import mcp_manager

    servers = mcp_manager.get_server_tools()

    result = [{"server": name, "tools": sorted(tools)} for name, tools in servers.items()]
    return sorted(result, key=lambda x: x["server"])


@router.get("/settings/tools")
async def get_tools_settings():
    """Get current tool retrieval settings."""
    from ..database import db
    import json

    always_on_json = db.get_setting("tool_always_on")
    always_on = []
    if always_on_json:
        try:
            always_on = json.loads(always_on_json)
        except (json.JSONDecodeError, ValueError):
            pass

    top_k_str = db.get_setting("tool_retriever_top_k")
    top_k = int(top_k_str) if top_k_str else 5

    return {"always_on": always_on, "top_k": top_k}


@router.put("/settings/tools")
async def set_tools_settings(body: ToolsSettingsUpdate):
    """Update tool retrieval settings."""
    from ..database import db
    import json

    db.set_setting("tool_always_on", json.dumps(body.always_on))
    db.set_setting("tool_retriever_top_k", str(body.top_k))

    return {"status": "updated", "settings": body.model_dump()}


# ============================================
# System Prompt API
# ============================================


class SystemPromptUpdate(BaseModel):
    template: str


@router.get("/settings/system-prompt")
async def get_system_prompt():
    """Returns the current custom template, or the default if none is saved."""
    from ..database import db
    from ..llm.prompt import _BASE_TEMPLATE

    custom = db.get_system_prompt_template()
    return {
        "template": custom if custom else _BASE_TEMPLATE,
        "is_custom": custom is not None,
    }


@router.put("/settings/system-prompt")
async def update_system_prompt(body: SystemPromptUpdate):
    """
    Saves a custom template. Expects: {"template": "..."}
    Send an empty string or omit the key to reset to the default.
    """
    from ..database import db

    template = body.template.strip()
    db.set_system_prompt_template(template if template else None)
    return {"ok": True}


# ============================================
# Skills API
# ============================================


class SkillCreate(BaseModel):
    skill_name: str
    display_name: str
    slash_command: str
    content: str
    enabled: bool = True


class SkillUpdate(BaseModel):
    display_name: str
    slash_command: str
    content: str
    enabled: bool


@router.get("/skills")
async def get_skills():
    """Get all skills from the database."""
    from ..database import db
    return db.get_all_skills()


@router.post("/skills")
async def create_skill(body: SkillCreate):
    """Create a new user-defined skill."""
    from ..database import db
    
    # Validation
    if not body.skill_name or not body.slash_command:
        raise HTTPException(status_code=400, detail="Name and slash command are required")
        
    if db.get_skill_by_name(body.skill_name):
        raise HTTPException(status_code=400, detail=f"Skill name '{body.skill_name}' already exists")
        
    if db.get_skill_by_slash_command(body.slash_command):
        raise HTTPException(status_code=400, detail=f"Slash command '{body.slash_command}' already exists")

    db.upsert_skill(
        skill_name=body.skill_name,
        display_name=body.display_name,
        slash_command=body.slash_command,
        content=body.content,
        is_default=False,
        enabled=body.enabled,
    )
    return {"status": "created", "skill_name": body.skill_name}


@router.put("/skills/{skill_name}")
async def update_skill(skill_name: str, body: SkillUpdate):
    """Update an existing skill."""
    from ..database import db
    
    skill = db.get_skill_by_name(skill_name)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    # Check command uniqueness if changed
    if body.slash_command != skill["slash_command"]:
        existing = db.get_skill_by_slash_command(body.slash_command)
        if existing and existing["skill_name"] != skill_name:
             raise HTTPException(status_code=400, detail=f"Slash command '{body.slash_command}' already in use")

    db.upsert_skill(
        skill_name=skill_name,
        display_name=body.display_name,
        slash_command=body.slash_command,
        content=body.content,
        is_default=skill["is_default"],
        enabled=body.enabled,
        # Mark as modified when a default skill's content is changed
        is_modified=skill["is_default"] and body.content != skill["content"],
    )

    return {"status": "updated"}


@router.delete("/skills/{skill_name}")
async def delete_skill(skill_name: str):
    """Delete a user-created skill."""
    from ..database import db
    
    success = db.delete_skill(skill_name)
    if not success:
        raise HTTPException(status_code=400, detail="Cannot delete default skill or skill not found")
        
    return {"status": "deleted"}


@router.post("/skills/{skill_name}/reset")
async def reset_skill(skill_name: str):
    """Reset a default skill to its original content."""
    from ..database import db
    
    skill = db.get_skill_by_name(skill_name)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
        
    if not skill["is_default"]:
         raise HTTPException(status_code=400, detail="Only default skills can be reset")
         
    db.reset_skill_to_default(skill_name)
    return {"status": "reset"}

