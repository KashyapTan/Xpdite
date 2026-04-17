"""
HTTP REST API endpoints.

Use for:
- One-time data fetches (models list)
- Settings management (enabled models, API keys)
- Health checks
- Cloud provider model listing
"""

import json
import logging
import os
import secrets
import time
import uuid

import requests
from fastapi import APIRouter, Depends, Header, HTTPException, Request

from ollama import AsyncClient as OllamaAsyncClient
from pydantic import BaseModel
from typing import Any, Awaitable, Callable, List, Optional

from ..core.thread_pool import run_in_thread as _run_in_thread
from ..core.connection import manager
from ..infrastructure.config import SERVER_SESSION_TOKEN

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api")

MODEL_CACHE_TTL_SECONDS = 10 * 60
_MODEL_CACHE: dict[str, tuple[float, Any]] = {}
_OLLAMA_REGISTRY_BASE = "https://registry.ollama.ai/v2"

_OLLAMA_LAYER_TYPE_MAP = {
    "application/vnd.ollama.image.model": "model_weights",
    "application/vnd.ollama.image.template": "template",
    "application/vnd.ollama.image.license": "license",
    "application/vnd.ollama.image.params": "params",
    "application/vnd.ollama.image.system": "system",
    "application/vnd.ollama.image.adapter": "adapter",
    "application/vnd.ollama.image.projector": "projector",
}


def _invalidate_model_cache(provider: str) -> None:
    """Drop a provider model cache entry (if present)."""
    _MODEL_CACHE.pop(provider, None)


def _extract_openrouter_error(response: requests.Response) -> str:
    """Best-effort extraction of OpenRouter error details."""
    try:
        payload = response.json()
    except ValueError:
        payload = None

    if isinstance(payload, dict):
        error_obj = payload.get("error")
        if isinstance(error_obj, dict):
            message = error_obj.get("message") or error_obj.get("code")
            if message:
                return str(message)
        if isinstance(error_obj, str) and error_obj.strip():
            return error_obj.strip()

        for key in ("message", "detail"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    body = response.text.strip()
    if body:
        return body[:200]

    return f"HTTP {response.status_code}"


def _parse_ollama_model_ref(model_ref: str) -> tuple[str, str]:
    """Parse model reference into (name, tag)."""
    ref = model_ref.strip()
    if ref.lower().startswith("ollama/"):
        ref = ref[len("ollama/") :].strip()

    if ":" in ref:
        name_part, tag = ref.rsplit(":", 1)
        if "/" in tag:
            return ref.strip("/"), "latest"
        return name_part.strip("/"), tag or "latest"

    return ref.strip("/"), "latest"


def _build_ollama_manifest_url(name: str, tag: str) -> str:
    """Build Ollama registry manifest URL."""
    if "/" in name:
        return f"{_OLLAMA_REGISTRY_BASE}/{name}/manifests/{tag}"
    return f"{_OLLAMA_REGISTRY_BASE}/library/{name}/manifests/{tag}"


def _build_ollama_blob_url(name: str, digest: str) -> str:
    """Build Ollama registry blob URL."""
    if "/" in name:
        return f"{_OLLAMA_REGISTRY_BASE}/{name}/blobs/{digest}"
    return f"{_OLLAMA_REGISTRY_BASE}/library/{name}/blobs/{digest}"


def _human_readable_size(size_bytes: int) -> str:
    """Convert bytes to human-readable value."""
    value = float(max(size_bytes, 0))
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if value < 1024.0:
            return f"{value:.2f} {unit}"
        value /= 1024.0
    return f"{value:.2f} PB"


def _parse_ollama_layer_type(media_type: str) -> str:
    """Map media type to layer type."""
    return _OLLAMA_LAYER_TYPE_MAP.get(media_type, "unknown")


async def _get_cached_or_fetch_models(
    provider: str,
    refresh: bool,
    fetcher: Callable[[], Awaitable[Any]],
) -> Any:
    """Resolve models via in-memory cache with TTL and explicit refresh."""
    if refresh:
        _invalidate_model_cache(provider)

    now = time.time()
    cached = _MODEL_CACHE.get(provider)
    if cached:
        cached_at, cached_payload = cached
        if now - cached_at < MODEL_CACHE_TTL_SECONDS:
            return cached_payload
        _MODEL_CACHE.pop(provider, None)

    payload = await fetcher()
    _MODEL_CACHE[provider] = (now, payload)
    return payload


# ============================================
# Health Check
# ============================================


@router.get("/health")
async def health_check():
    """Check if the server is running."""
    return {"status": "healthy"}


# ============================================
# Artifacts API
# ============================================


_VALID_ARTIFACT_TYPES = {"code", "markdown", "html"}
_VALID_ARTIFACT_STATUSES = {"ready", "deleted"}
_ARTIFACT_AUTH_HEADER = "X-Xpdite-Server-Token"
_LOOPBACK_CLIENT_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}


class ArtifactCreateRequest(BaseModel):
    """Request body for creating an artifact."""

    type: str
    title: str
    content: str
    language: Optional[str] = None
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None


class ArtifactUpdateRequest(BaseModel):
    """Request body for updating an artifact."""

    title: Optional[str] = None
    content: Optional[str] = None
    language: Optional[str] = None


def _artifact_deleted_payload(artifact: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {"artifact_id": artifact["id"]}
    if artifact.get("conversation_id") is not None:
        payload["conversation_id"] = artifact.get("conversation_id")
    if artifact.get("message_id") is not None:
        payload["message_id"] = artifact.get("message_id")
    return payload


def _is_loopback_request(request: Request) -> bool:
    client = request.client
    return bool(client and client.host in _LOOPBACK_CLIENT_HOSTS)


async def _require_local_api_access(
    request: Request,
    server_token: Optional[str] = Header(
        default=None,
        alias=_ARTIFACT_AUTH_HEADER,
    ),
) -> None:
    if not _is_loopback_request(request):
        raise HTTPException(status_code=403, detail="Local API access denied")

    if SERVER_SESSION_TOKEN and not (
        server_token
        and secrets.compare_digest(server_token, SERVER_SESSION_TOKEN)
    ):
        raise HTTPException(status_code=403, detail="Local API access denied")


async def _require_artifact_access(
    request: Request,
    artifact_token: Optional[str] = Header(
        default=None,
        alias=_ARTIFACT_AUTH_HEADER,
    ),
) -> None:
    await _require_local_api_access(request, server_token=artifact_token)


async def _require_marketplace_access(
    request: Request,
    marketplace_token: Optional[str] = Header(
        default=None,
        alias=_ARTIFACT_AUTH_HEADER,
    ),
) -> None:
    await _require_local_api_access(request, server_token=marketplace_token)


def _validate_artifact_type(artifact_type: Optional[str]) -> Optional[str]:
    if artifact_type is None:
        return None
    normalized = artifact_type.strip().lower()
    if normalized not in _VALID_ARTIFACT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid artifact type: {artifact_type}",
        )
    return normalized


def _validate_artifact_status(status: Optional[str]) -> Optional[str]:
    if status is None:
        return None
    normalized = status.strip().lower()
    if normalized not in _VALID_ARTIFACT_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid artifact status: {status}",
        )
    return normalized


@router.get("/artifacts")
async def list_artifacts(
    query: str = "",
    type: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    _artifact_access: None = Depends(_require_artifact_access),
):
    """List stored artifacts with optional search and filtering."""
    from ..services.artifacts import artifact_service

    return await _run_in_thread(
        artifact_service.list_artifacts,
        query=query,
        artifact_type=_validate_artifact_type(type),
        status=_validate_artifact_status(status),
        page=page,
        page_size=page_size,
    )


@router.get("/artifacts/conversation/{conversation_id}")
async def list_artifacts_for_conversation(
    conversation_id: str,
    query: str = "",
    type: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    _artifact_access: None = Depends(_require_artifact_access),
):
    """List artifacts associated with a conversation."""
    from ..services.artifacts import artifact_service

    return await _run_in_thread(
        artifact_service.list_artifacts,
        query=query,
        artifact_type=_validate_artifact_type(type),
        status=_validate_artifact_status(status),
        page=page,
        page_size=page_size,
        conversation_id=conversation_id,
    )


@router.get("/artifacts/{artifact_id}")
async def get_artifact(
    artifact_id: str,
    _artifact_access: None = Depends(_require_artifact_access),
):
    """Fetch a single artifact including full content."""
    from ..services.artifacts import artifact_service

    artifact = await _run_in_thread(artifact_service.get_artifact, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail=f"Artifact '{artifact_id}' not found")
    return artifact


@router.post("/artifacts")
async def create_artifact(
    payload: ArtifactCreateRequest,
    _artifact_access: None = Depends(_require_artifact_access),
):
    """Create a new artifact record."""
    from ..services.artifacts import artifact_service

    artifact_type = _validate_artifact_type(payload.type)
    if not payload.title.strip():
        raise HTTPException(status_code=400, detail="Artifact title is required")

    return await _run_in_thread(
        artifact_service.create_artifact,
        artifact_type=artifact_type,
        title=payload.title,
        content=payload.content,
        language=payload.language,
        conversation_id=payload.conversation_id,
        message_id=payload.message_id,
    )


@router.put("/artifacts/{artifact_id}")
async def update_artifact(
    artifact_id: str,
    payload: ArtifactUpdateRequest,
    _artifact_access: None = Depends(_require_artifact_access),
):
    """Update artifact metadata or content."""
    from ..services.artifacts import artifact_service

    if (
        payload.title is None
        and payload.content is None
        and payload.language is None
    ):
        artifact = await _run_in_thread(artifact_service.get_artifact, artifact_id)
    else:
        artifact = await _run_in_thread(
            artifact_service.update_artifact,
            artifact_id,
            title=payload.title,
            content=payload.content,
            language=payload.language,
        )

    if artifact is None:
        raise HTTPException(status_code=404, detail=f"Artifact '{artifact_id}' not found")
    return artifact


@router.delete("/artifacts/{artifact_id}")
async def delete_artifact(
    artifact_id: str,
    _artifact_access: None = Depends(_require_artifact_access),
):
    """Delete an artifact and notify connected clients."""
    from ..services.artifacts import artifact_service

    deleted = await _run_in_thread(artifact_service.delete_artifact, artifact_id)
    if deleted is None:
        raise HTTPException(status_code=404, detail=f"Artifact '{artifact_id}' not found")

    payload = _artifact_deleted_payload(deleted)
    await manager.broadcast_json("artifact_deleted", payload)
    return {"success": True, "artifact_id": artifact_id}


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
async def get_ollama_models(refresh: bool = False) -> Any:
    """
    Get all Ollama models installed on the user's machine.

    Calls `ollama.list()` which talks to the local Ollama daemon
    and returns every model that has been pulled.
    """

    async def _fetch() -> Any:
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

    return await _get_cached_or_fetch_models("ollama", refresh, _fetch)


@router.get("/models/ollama/info/{model_name:path}")
async def get_ollama_model_info(model_name: str) -> Any:
    """
    Fetch model metadata from Ollama registry without pulling full model.

    Uses the registry manifest + config blob flow to fetch model stats for
    not-yet-installed models.
    """

    model_ref = (model_name or "").strip()
    if not model_ref:
        return {
            "success": False,
            "error": "Model name is required",
        }

    name, tag = _parse_ollama_model_ref(model_ref)
    full_name = f"{name}:{tag}" if tag else name

    if not name:
        return {
            "success": False,
            "error": "Model name is required",
        }

    manifest_url = _build_ollama_manifest_url(name, tag)

    try:
        manifest_response = await _run_in_thread(
            lambda: requests.get(manifest_url, timeout=30)
        )

        if manifest_response.status_code == 404:
            return {
                "success": False,
                "error": f"Model '{full_name}' not found in Ollama registry",
            }

        manifest_response.raise_for_status()
        manifest = manifest_response.json()

        config = manifest.get("config") or {}
        if not isinstance(config, dict):
            config = {}
        config_digest = config.get("digest")
        config_size = int(config.get("size", 0) or 0)

        if not config_digest:
            return {
                "success": False,
                "error": f"No config digest found for '{full_name}'",
            }

        config_url = _build_ollama_blob_url(name, config_digest)
        config_response = await _run_in_thread(
            lambda: requests.get(config_url, timeout=30)
        )
        config_response.raise_for_status()
        config_data = config_response.json()
        if not isinstance(config_data, dict):
            config_data = {}

        # Ollama cloud-hosted manifests may omit local layer details entirely
        # (``layers: null``) because the remote runtime serves the model on demand.
        layers = manifest.get("layers")
        if not isinstance(layers, list):
            layers = []
        total_size = int(
            sum(
                int(layer.get("size", 0) or 0)
                for layer in layers
                if isinstance(layer, dict)
            )
        )

        layer_info = []
        for layer in layers:
            if not isinstance(layer, dict):
                continue
            media_type = str(layer.get("mediaType", ""))
            layer_info.append(
                {
                    "media_type": media_type,
                    "digest": layer.get("digest"),
                    "size": int(layer.get("size", 0) or 0),
                    "type": _parse_ollama_layer_type(media_type),
                }
            )

        # Check local install status
        is_installed = False
        try:
            async_client = OllamaAsyncClient()
            list_response = await async_client.list()

            normalized_target = full_name.lower()
            if ":" not in normalized_target:
                normalized_target = f"{normalized_target}:latest"

            for model in list_response.models:
                model_id = (model.model or "").lower().strip()
                if model_id and ":" not in model_id:
                    model_id = f"{model_id}:latest"
                if model_id == normalized_target:
                    is_installed = True
                    break
        except Exception:
            # Keep API resilient even if local daemon is unavailable.
            is_installed = False

        families = config_data.get("model_families")
        if not isinstance(families, list):
            families = []

        return {
            "success": True,
            "data": {
                "name": name,
                "tag": tag,
                "full_name": full_name,
                "family": config_data.get("model_family", ""),
                "families": families,
                "parameter_size": config_data.get("model_type", ""),
                "quantization": config_data.get("file_type", ""),
                "format": config_data.get("model_format", ""),
                "architecture": config_data.get("architecture", ""),
                "os": config_data.get("os", ""),
                "total_size_bytes": total_size,
                "total_size_human": _human_readable_size(total_size),
                "config_size_bytes": config_size,
                "layers": layer_info,
                "manifest_url": manifest_url,
                "config_url": config_url,
                "is_installed": is_installed,
            },
        }

    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        if status == 404:
            return {
                "success": False,
                "error": f"Model '{full_name}' not found in Ollama registry",
            }
        logger.error("HTTP error fetching Ollama model info for %s: %s", full_name, e)
        return {
            "success": False,
            "error": f"Error fetching model info: {str(e)[:160]}",
        }

    except Exception as e:
        logger.error("Error fetching Ollama model info for %s: %s", full_name, e)
        return {
            "success": False,
            "error": f"Error fetching model info: {str(e)[:160]}",
        }


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
    from ..infrastructure.database import db

    return db.get_enabled_models()


@router.put("/models/enabled")
async def set_enabled_models(body: EnabledModelsUpdate):
    """
    Replace the full list of enabled models with the given list.

    Called every time the user toggles a model on/off in SettingsModels.
    """
    from ..infrastructure.database import db

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
    from ..llm.core.key_manager import key_manager

    return key_manager.get_api_key_status()


@router.put("/keys/{provider}")
async def save_api_key(provider: str, body: ApiKeyUpdate):
    """
    Validate and store an API key for a provider.

    Performs a lightweight validation call before storing.
    Uses async clients/threads to avoid blocking the server loop.
    """
    from ..llm.core.key_manager import key_manager, VALID_PROVIDERS

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

        elif provider == "openrouter":

            def _validate_openrouter() -> requests.Response:
                return requests.get(
                    "https://openrouter.ai/api/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=20,
                )

            response = await _run_in_thread(_validate_openrouter)
            if response.status_code != 200:
                raise ValueError(_extract_openrouter_error(response))

    except Exception as e:
        error_msg = str(e)
        logger.warning("API key validation failed for %s: %s", provider, error_msg)
        raise HTTPException(
            status_code=401, detail=f"Invalid API key: {error_msg[:200]}"
        )

    # Key is valid — encrypt and store
    key_manager.save_api_key(provider, api_key)
    _invalidate_model_cache(provider)
    return {
        "status": "saved",
        "provider": provider,
        "masked": key_manager.mask_key(api_key),
    }


@router.delete("/keys/{provider}")
async def delete_api_key(provider: str):
    """Remove a stored API key for a provider."""
    from ..llm.core.key_manager import key_manager, VALID_PROVIDERS

    if provider not in VALID_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Invalid provider: {provider}")

    key_manager.delete_api_key(provider)

    # Also remove any cloud models from the enabled list that belong to this provider
    from ..infrastructure.database import db

    enabled = db.get_enabled_models()
    filtered = [m for m in enabled if not m.startswith(f"{provider}/")]
    if len(filtered) != len(enabled):
        db.set_enabled_models(filtered)

    _invalidate_model_cache(provider)

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
    from ..services.integrations.google_auth import google_auth

    return google_auth.get_status()


@router.post("/google/connect")
async def connect_google():
    """
    Initiate Google OAuth flow.

    Opens the user's browser for Google login.
    This is a blocking call that waits for the OAuth callback.

    Uses the app-owned thread pool to avoid the default executor shutdown issue.
    """
    from ..services.integrations.google_auth import google_auth

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
        from ..mcp_integration.core.manager import mcp_manager

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
    from ..services.integrations.google_auth import google_auth
    from ..mcp_integration.core.manager import mcp_manager

    # Disconnect MCP servers first
    try:
        await mcp_manager.disconnect_google_servers()
    except Exception as e:
        logger.warning("Google MCP server disconnect failed (non-fatal): %s", e)

    return google_auth.disconnect()


# ============================================
# Cloud Provider Models
# ============================================


def _to_cloud_model(
    model_id: str,
    provider: str,
    display_name: str,
    *,
    provider_group: Optional[str] = None,
    context_length: Optional[int] = None,
) -> dict:
    """Normalize cloud model payload shape across providers."""
    return {
        "id": model_id,
        "provider": provider,
        "display_name": display_name,
        "provider_group": provider_group or provider,
        "context_length": context_length,
    }


@router.get("/models/anthropic")
async def get_anthropic_models(refresh: bool = False) -> List[dict]:
    """Get available Anthropic models. Requires a stored API key."""
    from ..llm.core.key_manager import key_manager

    async def _fetch() -> List[dict]:
        api_key = key_manager.get_api_key("anthropic")
        if not api_key:
            return []

        try:
            import anthropic

            client = anthropic.AsyncAnthropic(api_key=api_key)

            models: List[dict] = []
            async for m in client.models.list(limit=100):
                # Use display_name if available, else ID
                display = getattr(m, "display_name", m.id)
                models.append(
                    _to_cloud_model(
                        model_id=f"anthropic/{m.id}",
                        provider="anthropic",
                        display_name=display,
                    )
                )

            if models:
                models.sort(key=lambda x: x["id"], reverse=True)
                return models

        except Exception as e:
            logger.error("Error fetching Anthropic models via API: %s", e)
            # Fall through to fallback

        return [
            _to_cloud_model(
                model_id=f"anthropic/{m['name']}",
                provider="anthropic",
                display_name=m["description"],
            )
            for m in ANTHROPIC_FALLBACK
        ]

    return await _get_cached_or_fetch_models("anthropic", refresh, _fetch)


@router.get("/models/openai")
async def get_openai_models(refresh: bool = False) -> List[dict]:
    """Get available OpenAI models. Requires a stored API key."""
    from ..llm.core.key_manager import key_manager

    async def _fetch() -> List[dict]:
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

            models: List[dict] = []
            for m in response.data:
                model_id = m.id
                # Simple check: starts with a known prefix AND doesn't contain excluded keywords
                if any(model_id.startswith(p) for p in chat_prefixes):
                    if not any(kw in model_id for kw in exclude_keywords):
                        models.append(
                            _to_cloud_model(
                                model_id=f"openai/{model_id}",
                                provider="openai",
                                display_name=model_id,
                            )
                        )

            models.sort(key=lambda x: x["id"])
            if models:
                return models

        except Exception as e:
            logger.error("Error fetching OpenAI models: %s", e)
            # Fall through to fallback

        return [
            _to_cloud_model(
                model_id=f"openai/{m['name']}",
                provider="openai",
                display_name=m["description"],
            )
            for m in OPENAI_FALLBACK
        ]

    return await _get_cached_or_fetch_models("openai", refresh, _fetch)


@router.get("/models/gemini")
async def get_gemini_models(refresh: bool = False) -> List[dict]:
    """Get available Gemini models. Requires a stored API key."""
    from ..llm.core.key_manager import key_manager

    async def _fetch() -> List[dict]:
        api_key = key_manager.get_api_key("gemini")
        if not api_key:
            return []

        try:
            from google import genai

            client = genai.Client(api_key=api_key)

            # Run sync list_models in thread
            # Note: The Google GenAI SDK might return an iterator or list depending on version
            response = await _run_in_thread(lambda: list(client.models.list()))

            models: List[dict] = []
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
                if any(
                    kw in model_name for kw in ("embedding", "aqa", "bison", "gecko")
                ):
                    continue
                display_name = m.display_name or model_name
                models.append(
                    _to_cloud_model(
                        model_id=f"gemini/{model_name}",
                        provider="gemini",
                        display_name=display_name,
                    )
                )

            models.sort(key=lambda x: x["id"])
            if models:
                return models

        except Exception as e:
            logger.error("Error fetching Gemini models: %s", e)
            # Fall through to fallback

        return [
            _to_cloud_model(
                model_id=f"gemini/{m['name']}",
                provider="gemini",
                display_name=m["description"],
            )
            for m in GEMINI_FALLBACK
        ]

    return await _get_cached_or_fetch_models("gemini", refresh, _fetch)


@router.get("/models/openrouter")
async def get_openrouter_models(refresh: bool = False) -> List[dict]:
    """Get tool-capable OpenRouter models. Requires a stored OpenRouter API key."""
    from ..llm.core.key_manager import key_manager

    async def _fetch() -> List[dict]:
        api_key = key_manager.get_api_key("openrouter")
        if not api_key:
            return []

        def _request_models() -> requests.Response:
            return requests.get(
                "https://openrouter.ai/api/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=30,
            )

        try:
            response = await _run_in_thread(_request_models)
        except Exception as e:
            logger.warning("Error fetching OpenRouter models: %s", e)
            raise HTTPException(
                status_code=502,
                detail=f"Could not connect to OpenRouter: {str(e)[:200]}",
            ) from e

        if response.status_code != 200:
            status = 401 if response.status_code in (401, 403) else 502
            detail = _extract_openrouter_error(response)
            raise HTTPException(
                status_code=status,
                detail=f"Failed to fetch OpenRouter models: {detail[:200]}",
            )

        try:
            payload = response.json()
        except ValueError as e:
            raise HTTPException(
                status_code=502,
                detail="OpenRouter returned invalid JSON for model list.",
            ) from e

        model_data = payload.get("data")
        if not isinstance(model_data, list):
            raise HTTPException(
                status_code=502,
                detail="OpenRouter returned an unexpected model list format.",
            )

        models: List[dict] = []
        for model in model_data:
            if not isinstance(model, dict):
                continue

            supported_parameters = model.get("supported_parameters")
            if (
                not isinstance(supported_parameters, list)
                or "tools" not in supported_parameters
            ):
                continue

            model_id = str(model.get("id") or "").strip()
            if not model_id:
                continue

            display_name = str(model.get("name") or model_id).strip()
            provider_group = (
                model_id.split("/", 1)[0] if "/" in model_id else "openrouter"
            )
            context_length_raw = model.get("context_length")
            context_length = (
                context_length_raw if isinstance(context_length_raw, int) else None
            )

            models.append(
                _to_cloud_model(
                    model_id=model_id,
                    provider="openrouter",
                    display_name=display_name,
                    provider_group=provider_group,
                    context_length=context_length,
                )
            )

        models.sort(
            key=lambda x: (
                x.get("provider_group", ""),
                str(x.get("display_name", "")).lower(),
            )
        )
        return models

    return await _get_cached_or_fetch_models("openrouter", refresh, _fetch)


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
    from ..mcp_integration.core.manager import mcp_manager

    return mcp_manager.get_server_tools()


@router.get("/settings/tools")
async def get_tools_settings():
    """Get current tool retrieval settings."""
    from ..infrastructure.database import db

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
    from ..infrastructure.database import db

    db.set_setting("tool_always_on", json.dumps(body.always_on))
    db.set_setting("tool_retriever_top_k", str(body.top_k))

    return {"status": "updated", "settings": body.model_dump()}


# ============================================
# Sub-Agent Settings API
# ============================================


class SubAgentSettingsUpdate(BaseModel):
    """Request body for updating sub-agent tier settings."""

    fast_model: Optional[str] = None
    smart_model: Optional[str] = None


class MemorySettingsUpdate(BaseModel):
    """Request body for memory settings."""

    profile_auto_inject: bool


class MemoryFileUpdate(BaseModel):
    """Request body for updating a single memory file."""

    path: str
    title: str
    category: str
    importance: float
    tags: List[str]
    abstract: str
    body: str


def _raise_memory_http_error(operation: str, exc: Exception) -> None:
    logger.warning("Memory %s failed (%s)", operation, type(exc).__name__)
    raise HTTPException(
        status_code=500,
        detail=f"Memory {operation} failed. See server logs for details.",
    ) from exc


@router.get("/settings/sub-agents")
async def get_sub_agent_settings():
    """Get current sub-agent tier model settings."""
    from ..infrastructure.database import db

    fast_model = db.get_setting("sub_agent_tier_fast") or ""
    smart_model = db.get_setting("sub_agent_tier_smart") or ""

    return {
        "fast_model": fast_model,
        "smart_model": smart_model,
    }


@router.put("/settings/sub-agents")
async def set_sub_agent_settings(body: SubAgentSettingsUpdate):
    """Update sub-agent tier model settings."""
    from ..infrastructure.database import db

    if body.fast_model is not None:
        if body.fast_model.strip():
            db.set_setting("sub_agent_tier_fast", body.fast_model.strip())
        else:
            db.delete_setting("sub_agent_tier_fast")

    if body.smart_model is not None:
        if body.smart_model.strip():
            db.set_setting("sub_agent_tier_smart", body.smart_model.strip())
        else:
            db.delete_setting("sub_agent_tier_smart")

    return {"status": "updated"}


@router.get("/settings/memory")
async def get_memory_settings():
    """Get persisted memory-related settings."""
    from ..infrastructure.database import db

    stored = db.get_setting("memory_profile_auto_inject")
    return {"profile_auto_inject": stored != "false"}


@router.put("/settings/memory")
async def set_memory_settings(body: MemorySettingsUpdate):
    """Persist memory-related settings."""
    from ..infrastructure.database import db

    db.set_setting(
        "memory_profile_auto_inject",
        "true" if body.profile_auto_inject else "false",
    )
    return {"status": "updated", "settings": body.model_dump()}


@router.get("/memory")
async def list_memories(folder: Optional[str] = None):
    """List memory summaries, optionally scoped to a subtree."""
    from ..services.memory_store.memory import memory_service

    try:
        memories = await _run_in_thread(memory_service.list_memories, folder)
        return {"memories": memories}
    except (OSError, UnicodeError) as exc:
        _raise_memory_http_error("listing", exc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _raise_memory_http_error("listing", exc)


@router.get("/memory/file")
async def get_memory_file(path: str):
    """Read a single memory file in full."""
    from ..services.memory_store.memory import memory_service

    try:
        return await _run_in_thread(memory_service.read_memory, path, touch_access=True)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Memory '{path}' not found")
    except (OSError, UnicodeError) as exc:
        _raise_memory_http_error("read", exc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _raise_memory_http_error("read", exc)


@router.put("/memory/file")
async def update_memory_file(body: MemoryFileUpdate):
    """Create or overwrite a single memory file."""
    from ..services.memory_store.memory import memory_service

    try:
        return await _run_in_thread(
            memory_service.upsert_memory,
            path=body.path,
            title=body.title,
            category=body.category,
            importance=body.importance,
            tags=body.tags,
            abstract=body.abstract,
            body=body.body,
        )
    except (OSError, UnicodeError) as exc:
        _raise_memory_http_error("write", exc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _raise_memory_http_error("write", exc)


@router.delete("/memory/file")
async def delete_memory_file(path: str):
    """Delete a single memory file."""
    from ..services.memory_store.memory import memory_service

    try:
        deleted = await _run_in_thread(memory_service.delete_memory, path)
    except (OSError, UnicodeError) as exc:
        _raise_memory_http_error("delete", exc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _raise_memory_http_error("delete", exc)

    if not deleted:
        raise HTTPException(status_code=404, detail=f"Memory '{path}' not found")

    return {"success": True, "path": path}


@router.delete("/memory")
async def clear_all_memories():
    """Delete all memory files and recreate the default directory layout."""
    from ..services.memory_store.memory import memory_service

    try:
        deleted_count = await _run_in_thread(memory_service.clear_all_memories)
    except (OSError, UnicodeError) as exc:
        _raise_memory_http_error("clear", exc)
    except Exception as exc:
        _raise_memory_http_error("clear", exc)
    return {"success": True, "deleted_count": deleted_count}


# ============================================
# System Prompt API
# ============================================


class SystemPromptUpdate(BaseModel):
    template: str


@router.get("/settings/system-prompt")
async def get_system_prompt():
    """Returns the current custom template, or the default if none is saved."""
    from ..infrastructure.database import db
    from ..llm.core.prompt import _BASE_TEMPLATE

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
    from ..infrastructure.database import db

    template = body.template.strip()
    db.set_system_prompt_template(template if template else None)
    return {"ok": True}


# ============================================
# Skills API (filesystem-backed)
# ============================================


class SkillCreate(BaseModel):
    name: str
    description: str
    slash_command: Optional[str] = None
    content: str
    trigger_servers: List[str] = []


# Sentinel so we can distinguish "field not sent" from "explicitly set to null".
_UNSET: Any = object()


class SkillUpdate(BaseModel):
    description: Optional[str] = None
    slash_command: Optional[str] = _UNSET
    content: Optional[str] = None
    trigger_servers: Optional[List[str]] = None


class SkillToggle(BaseModel):
    enabled: bool


class ReferenceFileCreate(BaseModel):
    filename: str
    content: str


class MarketplaceSourceCreate(BaseModel):
    name: str
    location: str
    kind: Optional[str] = None


class MarketplaceInstallRequest(BaseModel):
    source_id: str
    manifest_item_id: str
    secrets: dict[str, str] = {}


class MarketplacePackageInstallRequest(BaseModel):
    runner: str
    package_input: str


class MarketplaceRepoInstallRequest(BaseModel):
    repo_input: str


class MarketplaceSecretsUpdate(BaseModel):
    secrets: dict[str, str]


@router.get("/skills")
async def get_skills():
    """Get all skills (builtin + user), with override info for the UI."""
    from ..services.skills_runtime.skills import get_skill_manager

    manager = get_skill_manager()
    return await _run_in_thread(manager.get_all_skills_with_overrides)


@router.get("/skills/{name}/content")
async def get_skill_content(name: str):
    """Return the full SKILL.md text for a skill."""
    from ..services.skills_runtime.skills import get_skill_manager

    manager = get_skill_manager()
    content = await _run_in_thread(manager.get_skill_content, name)
    if content is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"name": name, "content": content}


@router.post("/skills")
async def create_skill(body: SkillCreate):
    """Create a new user skill."""
    from ..services.skills_runtime.skills import get_skill_manager

    if not body.name or not body.name.strip():
        raise HTTPException(status_code=400, detail="Skill name is required")
    if not body.content or not body.content.strip():
        raise HTTPException(status_code=400, detail="Skill content is required")

    manager = get_skill_manager()
    try:
        skill = await _run_in_thread(
            manager.create_user_skill,
            name=body.name,
            description=body.description,
            slash_command=body.slash_command or None,
            content=body.content,
            trigger_servers=body.trigger_servers,
        )
        return {"status": "created", "skill": skill.to_dict()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/skills/{name}")
async def update_skill(name: str, body: SkillUpdate):
    """Update an existing user skill. Rejects edits to builtin skills."""
    from ..services.skills_runtime.skills import get_skill_manager

    manager = get_skill_manager()
    try:
        kwargs = {}
        if body.description is not None:
            kwargs["description"] = body.description
        if body.slash_command is not _UNSET:
            # Explicitly sent (could be null to clear, or a new value).
            kwargs["slash_command"] = body.slash_command or None
        if body.content is not None:
            kwargs["content"] = body.content
        if body.trigger_servers is not None:
            kwargs["trigger_servers"] = body.trigger_servers

        skill = await _run_in_thread(manager.update_user_skill, name, **kwargs)
        return {"status": "updated", "skill": skill.to_dict()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/skills/{name}/toggle")
async def toggle_skill(name: str, body: SkillToggle):
    """Enable or disable a skill (works for both builtin and user)."""
    from ..services.skills_runtime.skills import get_skill_manager

    manager = get_skill_manager()
    result = await _run_in_thread(manager.toggle_skill, name, body.enabled)
    if not result:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"status": "toggled", "name": name, "enabled": body.enabled}


@router.delete("/skills/{name}")
async def delete_skill(name: str):
    """Delete a user skill folder. Rejects deletion of builtin skills."""
    from ..services.skills_runtime.skills import get_skill_manager

    manager = get_skill_manager()
    result = await _run_in_thread(manager.delete_user_skill, name)
    if not result:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete builtin skill or skill not found",
        )
    return {"status": "deleted"}


@router.post("/skills/{name}/references")
async def add_reference_file(name: str, body: ReferenceFileCreate):
    """Add a reference .md file to a user skill."""
    from ..services.skills_runtime.skills import get_skill_manager

    if not body.filename.endswith(".md"):
        raise HTTPException(status_code=400, detail="Reference files must be .md")

    manager = get_skill_manager()
    try:
        await _run_in_thread(
            manager.add_reference_file, name, body.filename, body.content
        )
        return {"status": "created", "filename": body.filename}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ============================================
# Marketplace API
# ============================================


@router.get("/marketplace/sources")
async def get_marketplace_sources(_: None = Depends(_require_marketplace_access)):
    from ..services.marketplace.service import get_marketplace_service

    service = get_marketplace_service()
    return await _run_in_thread(service.list_sources)


@router.post("/marketplace/sources")
async def create_marketplace_source(
    body: MarketplaceSourceCreate,
    _: None = Depends(_require_marketplace_access),
):
    from ..services.marketplace.service import get_marketplace_service

    if not body.location.strip():
        raise HTTPException(status_code=400, detail="Marketplace source location is required")
    service = get_marketplace_service()
    created_source = None
    try:
        created_source = await _run_in_thread(
            service.create_source,
            name=body.name,
            location=body.location,
            kind=body.kind or "manifest",
        )
        await service.refresh_source_async(created_source["id"])
        return {"status": "created", "source": service.get_source(created_source["id"])}
    except ValueError as e:
        if created_source is not None:
            try:
                await _run_in_thread(service.delete_source, created_source["id"])
            except ValueError:
                pass
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/marketplace/sources/{source_id}")
async def delete_marketplace_source(
    source_id: str,
    _: None = Depends(_require_marketplace_access),
):
    from ..services.marketplace.service import get_marketplace_service

    service = get_marketplace_service()
    try:
        await _run_in_thread(service.delete_source, source_id)
        return {"status": "deleted", "source_id": source_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/marketplace/sources/{source_id}/refresh")
async def refresh_marketplace_source(
    source_id: str,
    _: None = Depends(_require_marketplace_access),
):
    from ..services.marketplace.service import get_marketplace_service

    service = get_marketplace_service()
    try:
        source = await service.refresh_source_async(source_id)
        return {"status": "refreshed", "source": source}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/marketplace/catalog")
async def get_marketplace_catalog(_: None = Depends(_require_marketplace_access)):
    from ..services.marketplace.service import get_marketplace_service

    service = get_marketplace_service()
    catalog = await _run_in_thread(service.list_catalog)
    return {"items": catalog}


@router.get("/marketplace/installs")
async def get_marketplace_installs(_: None = Depends(_require_marketplace_access)):
    from ..services.marketplace.service import get_marketplace_service

    service = get_marketplace_service()
    installs = await _run_in_thread(service.list_installs)
    return {"installs": installs}


@router.post("/marketplace/install")
async def install_marketplace_item(
    body: MarketplaceInstallRequest,
    _: None = Depends(_require_marketplace_access),
):
    from ..services.marketplace.service import get_marketplace_service

    service = get_marketplace_service()
    try:
        install = await service.install_item_async(
            source_id=body.source_id,
            manifest_item_id=body.manifest_item_id,
            secrets=body.secrets,
        )
        return {"status": "installed", "install": install}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(
            "Unexpected marketplace install failure for source=%s item=%s",
            body.source_id,
            body.manifest_item_id,
        )
        raise HTTPException(status_code=400, detail=str(e) or "Marketplace install failed")


@router.post("/marketplace/install-package")
async def install_marketplace_package(
    body: MarketplacePackageInstallRequest,
    _: None = Depends(_require_marketplace_access),
):
    from ..services.marketplace.service import get_marketplace_service

    runner = body.runner.strip().lower()
    package_input = body.package_input.strip()
    if not runner:
        raise HTTPException(status_code=400, detail="Package runner is required")
    if not package_input:
        raise HTTPException(status_code=400, detail="Package command is required")

    service = get_marketplace_service()
    try:
        install = await service.install_package_async(
            runner=runner,
            package_input=package_input,
        )
        return {"status": "installed", "install": install}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(
            "Unexpected marketplace package install failure for runner=%s input=%s",
            runner,
            package_input,
        )
        raise HTTPException(
            status_code=400,
            detail=str(e) or "Marketplace package install failed",
        )


@router.post("/marketplace/install-repo")
async def install_marketplace_repo(
    body: MarketplaceRepoInstallRequest,
    _: None = Depends(_require_marketplace_access),
):
    from ..services.marketplace.service import get_marketplace_service

    repo_input = body.repo_input.strip()
    if not repo_input:
        raise HTTPException(status_code=400, detail="Repository input is required")

    service = get_marketplace_service()
    try:
        install = await service.install_repo_async(repo_input=repo_input)
        return {"status": "installed", "install": install}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Unexpected marketplace repo install failure for %s", repo_input)
        raise HTTPException(
            status_code=400,
            detail=str(e) or "Marketplace repo install failed",
        )


@router.post("/marketplace/installs/{install_id}/enable")
async def enable_marketplace_install(
    install_id: str,
    _: None = Depends(_require_marketplace_access),
):
    from ..services.marketplace.service import get_marketplace_service

    service = get_marketplace_service()
    try:
        install = await service.enable_install_async(install_id)
        return {"status": "enabled", "install": install}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/marketplace/installs/{install_id}/disable")
async def disable_marketplace_install(
    install_id: str,
    _: None = Depends(_require_marketplace_access),
):
    from ..services.marketplace.service import get_marketplace_service

    service = get_marketplace_service()
    try:
        install = await service.disable_install_async(install_id)
        return {"status": "disabled", "install": install}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/marketplace/installs/{install_id}/update")
async def update_marketplace_install(
    install_id: str,
    _: None = Depends(_require_marketplace_access),
):
    from ..services.marketplace.service import get_marketplace_service

    service = get_marketplace_service()
    try:
        install = await service.update_install_async(install_id)
        return {"status": "updated", "install": install}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/marketplace/installs/{install_id}")
async def uninstall_marketplace_install(
    install_id: str,
    _: None = Depends(_require_marketplace_access),
):
    from ..services.marketplace.service import get_marketplace_service

    service = get_marketplace_service()
    try:
        result = await service.uninstall_async(install_id)
        return {"status": "deleted", **result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/marketplace/installs/{install_id}/secrets")
async def update_marketplace_install_secrets(
    install_id: str,
    body: MarketplaceSecretsUpdate,
    _: None = Depends(_require_marketplace_access),
):
    from ..services.marketplace.service import get_marketplace_service

    service = get_marketplace_service()
    try:
        result = await _run_in_thread(service.set_install_secrets, install_id, body.secrets)
        return {"status": "updated", **result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ============================================
# External MCP Connectors API
# ============================================


@router.get("/external-connectors")
async def get_external_connectors():
    """
    Get all available external connectors with their status.

    Returns a list of connector info including:
    - name, display_name, description, services, icon_type
    - auth_type: "browser" (OAuth via browser popup) or null
    - enabled: whether user has enabled this connector
    - connected: whether currently connected to MCP server
    - last_error: last connection error if any
    """
    from ..services.integrations.external_connectors import external_connectors

    return external_connectors.get_all_connectors()


@router.post("/external-connectors/{name}/connect")
async def connect_external_connector_endpoint(name: str):
    """
    Connect an external MCP server.

    For browser auth connectors (like Figma, Slack), this launches
    an OAuth flow via mcp-remote that opens the user's browser.

    Returns: {success: true} or {success: false, error: "..."}
    """
    from ..services.integrations.external_connectors import (
        connect_external_connector,
        external_connectors,
    )

    connector = external_connectors.get_connector(name)
    if not connector:
        raise HTTPException(status_code=404, detail=f"Unknown connector: {name}")

    try:
        result = await connect_external_connector(name)
        if not result.get("success"):
            return result
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("External connector connect error: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Connection failed: {str(e)[:300]}",
        )


@router.post("/external-connectors/{name}/disconnect")
async def disconnect_external_connector_endpoint(name: str):
    """
    Disconnect an external MCP server.

    Stops the subprocess, marks as disabled, and clears errors.
    """
    from ..services.integrations.external_connectors import (
        disconnect_external_connector,
        external_connectors,
    )

    connector = external_connectors.get_connector(name)
    if not connector:
        raise HTTPException(status_code=404, detail=f"Unknown connector: {name}")

    try:
        result = await disconnect_external_connector(name)
        if not result.get("success"):
            raise HTTPException(
                status_code=400,
                detail=result.get("error", "Disconnect failed"),
            )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("External connector disconnect error: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Disconnect failed: {str(e)[:300]}",
        )


# ============================================
# Mobile Channels Config Endpoints
# ============================================


class MobilePlatformConfig(BaseModel):
    """Request body for setting a platform config."""

    token: Optional[str] = None
    enabled: Optional[bool] = None
    publicKey: Optional[str] = None
    applicationId: Optional[str] = None
    phoneNumber: Optional[str] = None  # For WhatsApp pairing code auth
    authMethod: Optional[str] = None  # pairing_code only
    forcePairing: Optional[bool] = None  # Force clearing existing auth state


def _mask_token(token: str | None) -> str:
    """Mask sensitive tokens while preserving configured/not-configured semantics."""
    if not token:
        return ""
    return "***"


@router.get("/mobile-channels/config")
async def get_mobile_channels_config():
    """
    Get mobile channels configuration.

    Returns config for all platforms with their enabled status and connection state.
    """
    from ..infrastructure.database import db

    # Read configs from database settings
    platforms = {}
    for platform_id in ["telegram", "discord", "whatsapp"]:
        config_raw = db.get_setting(f"mobile_channel_{platform_id}")
        default_config = {
            "enabled": False,
            "status": "disconnected",
        }

        if not config_raw:
            platforms[platform_id] = default_config
            continue

        try:
            parsed = json.loads(config_raw)
            parsed_dict = parsed if isinstance(parsed, dict) else default_config
            if platform_id == "whatsapp" and isinstance(parsed_dict, dict):
                parsed_dict["authMethod"] = "pairing_code"
            if isinstance(parsed_dict, dict) and parsed_dict.get("token"):
                parsed_dict["token"] = _mask_token(parsed_dict.get("token"))
            platforms[platform_id] = parsed_dict
        except (json.JSONDecodeError, TypeError, ValueError):
            platforms[platform_id] = default_config

    return {"platforms": platforms}


def _write_mobile_channels_config_file() -> None:
    """
    Write the mobile channels config to a JSON file for the Channel Bridge to read.
    This bridges the gap between the Python backend and the TypeScript service.
    """
    from ..infrastructure.database import db
    from ..infrastructure.config import USER_DATA_DIR, DEFAULT_PORT
    from ..core.state import app_state
    import json
    import logging

    logger = logging.getLogger(__name__)

    api_port = app_state.server_loop_holder.get("port", DEFAULT_PORT)

    config_data: dict[str, Any] = {
        "version": 1,
        "pythonServerPort": api_port,
        "platforms": {
            "telegram": {
                "enabled": False,
                "botToken": "",
                "botUsername": "xpdite-bot",
            },
            "discord": {
                "enabled": False,
                "botToken": "",
                "publicKey": "",
                "applicationId": "",
            },
            "whatsapp": {
                "enabled": False,
                # Pairing-code authentication only
                "authMethod": "pairing_code",
                "phoneNumber": "",
                "forcePairing": False,
            },
        },
    }

    # Telegram
    telegram_raw = db.get_setting("mobile_channel_telegram")
    if telegram_raw:
        try:
            telegram = json.loads(telegram_raw)
            if isinstance(telegram, dict):
                config_data["platforms"]["telegram"].update(
                    {
                        "enabled": telegram.get("enabled", False),
                        "botToken": telegram.get("token", ""),
                        "botUsername": telegram.get("username", "xpdite-bot"),
                    }
                )
        except Exception as e:
            logger.debug(f"Error parsing telegram settings: {e}")

    # Discord
    discord_raw = db.get_setting("mobile_channel_discord")
    if discord_raw:
        try:
            discord = json.loads(discord_raw)
            if isinstance(discord, dict):
                config_data["platforms"]["discord"].update(
                    {
                        "enabled": discord.get("enabled", False),
                        "botToken": discord.get("token", ""),
                        "publicKey": discord.get("publicKey", ""),
                        "applicationId": discord.get("applicationId", ""),
                    }
                )
        except Exception as e:
            logger.debug(f"Error parsing discord settings: {e}")

    # WhatsApp
    whatsapp_raw = db.get_setting("mobile_channel_whatsapp")
    if whatsapp_raw:
        try:
            whatsapp = json.loads(whatsapp_raw)
            if isinstance(whatsapp, dict):
                config_data["platforms"]["whatsapp"].update(
                    {
                        "enabled": whatsapp.get("enabled", False),
                        # Pairing-code authentication only
                        "authMethod": "pairing_code",
                        "phoneNumber": whatsapp.get("phoneNumber", ""),
                        # Pass through forcePairing flag to clear auth state
                        "forcePairing": whatsapp.get("forcePairing", False),
                    }
                )
        except Exception as e:
            logger.debug(f"Error parsing whatsapp settings: {e}")

    config_path = USER_DATA_DIR / "mobile_channels_config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = config_path.with_name(f"{config_path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, config_path)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                logger.debug("Failed to remove temporary config file: %s", temp_path)


@router.put("/mobile-channels/config/{platform_id}")
async def set_mobile_platform_config(platform_id: str, config: MobilePlatformConfig):
    """
    Set configuration for a mobile platform.

    Saves the token (encrypted) and enabled status.
    """
    from ..infrastructure.database import db

    if platform_id not in ["telegram", "discord", "whatsapp"]:
        raise HTTPException(status_code=400, detail=f"Unknown platform: {platform_id}")

    # Get existing config (stored as JSON string in SQLite)
    existing_raw = db.get_setting(f"mobile_channel_{platform_id}")
    existing: dict[str, Any] = {}
    if existing_raw:
        try:
            parsed = json.loads(existing_raw)
            if isinstance(parsed, dict):
                existing = parsed
        except (json.JSONDecodeError, TypeError, ValueError):
            existing = {}

    # Update with new values
    if config.token is not None:
        existing["token"] = config.token.strip()  # TODO: encrypt
    if config.enabled is not None:
        existing["enabled"] = config.enabled
    if config.publicKey is not None:
        existing["publicKey"] = config.publicKey.strip()
    if config.applicationId is not None:
        existing["applicationId"] = config.applicationId.strip()
    if config.phoneNumber is not None:
        existing["phoneNumber"] = config.phoneNumber.strip()
    if config.forcePairing is not None:
        existing["forcePairing"] = config.forcePairing
    if platform_id == "whatsapp":
        # WhatsApp always uses pairing-code auth in this app.
        existing["authMethod"] = "pairing_code"
    if platform_id == "discord" and existing.get("enabled"):
        if not existing.get("token"):
            raise HTTPException(status_code=400, detail="Discord bot token is required.")
        if not existing.get("publicKey"):
            raise HTTPException(status_code=400, detail="Discord public key is required.")
        if not existing.get("applicationId"):
            raise HTTPException(status_code=400, detail="Discord application ID is required.")

    # Set initial status
    if "status" not in existing:
        existing["status"] = "disconnected"

    # Save back (serialize dict to JSON string for SQLite storage)
    db.set_setting(f"mobile_channel_{platform_id}", json.dumps(existing))

    # Notify Channel Bridge to reconnect by writing the config file
    try:
        _write_mobile_channels_config_file()
    except Exception as e:
        logger.error(f"Failed to write mobile channels config file: {e}")
        raise HTTPException(
            status_code=500,
            detail="Configuration saved, but failed to sync mobile bridge config.",
        )

    return {"success": True}


# ============================================
# Scheduled Jobs API
# ============================================


class ScheduledJobCreate(BaseModel):
    """Request body for creating a scheduled job."""

    name: str
    cron_expression: str
    instruction: str
    timezone: str
    model: Optional[str] = None
    delivery_platform: Optional[str] = None
    delivery_sender_id: Optional[str] = None
    is_one_shot: bool = False


class ScheduledJobUpdate(BaseModel):
    """Request body for updating a scheduled job."""

    name: Optional[str] = None
    cron_expression: Optional[str] = None
    instruction: Optional[str] = None
    timezone: Optional[str] = None
    model: Optional[str] = None
    delivery_platform: Optional[str] = None
    delivery_sender_id: Optional[str] = None
    enabled: Optional[bool] = None
    is_one_shot: Optional[bool] = None


@router.get("/scheduled-jobs")
async def list_scheduled_jobs():
    """List all scheduled jobs."""
    from ..services.scheduling.scheduler import scheduler_service

    jobs = scheduler_service.list_jobs()
    return {"jobs": jobs}


@router.get("/scheduled-jobs/conversations")
async def list_scheduled_job_conversations():
    """List all conversations created by scheduled jobs."""
    from ..infrastructure.database import db

    conversations = db.get_job_conversations()
    return {"conversations": conversations}


@router.get("/scheduled-jobs/{job_id}")
async def get_scheduled_job(job_id: str):
    """Get a specific scheduled job by ID."""
    from ..services.scheduling.scheduler import scheduler_service

    job = scheduler_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return job


@router.post("/scheduled-jobs")
async def create_scheduled_job(job_data: ScheduledJobCreate):
    """Create a new scheduled job."""
    from ..services.scheduling.scheduler import scheduler_service

    try:
        job = await scheduler_service.create_job(
            name=job_data.name,
            cron_expression=job_data.cron_expression,
            instruction=job_data.instruction,
            timezone=job_data.timezone,
            model=job_data.model,
            delivery_platform=job_data.delivery_platform,
            delivery_sender_id=job_data.delivery_sender_id,
            is_one_shot=job_data.is_one_shot,
        )
        return job
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create scheduled job: {e}")
        raise HTTPException(status_code=500, detail="Failed to create job")


@router.put("/scheduled-jobs/{job_id}")
async def update_scheduled_job(job_id: str, job_data: ScheduledJobUpdate):
    """Update an existing scheduled job."""
    from ..infrastructure.database import db
    from ..services.scheduling.scheduler import scheduler_service

    job = scheduler_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    # Build update dict from non-None values
    updates: dict[str, Any] = {}
    if job_data.name is not None:
        updates["name"] = job_data.name
    if job_data.cron_expression is not None:
        updates["cron_expression"] = job_data.cron_expression
    if job_data.instruction is not None:
        updates["instruction"] = job_data.instruction
    if job_data.timezone is not None:
        updates["timezone"] = job_data.timezone
    if job_data.model is not None:
        updates["model"] = job_data.model
    if job_data.delivery_platform is not None:
        updates["delivery_platform"] = job_data.delivery_platform
    if job_data.delivery_sender_id is not None:
        updates["delivery_sender_id"] = job_data.delivery_sender_id
    if job_data.enabled is not None:
        updates["enabled"] = job_data.enabled
    if job_data.is_one_shot is not None:
        updates["is_one_shot"] = job_data.is_one_shot

    if not updates:
        return job  # Nothing to update

    # Update the job in DB
    try:
        updated_job = db.update_scheduled_job(job_id, **updates)
        if not updated_job:
            raise HTTPException(status_code=500, detail="Failed to update job")

        # Reschedule in APScheduler if needed
        await scheduler_service._reschedule_job(job_id)

        return updated_job
    except Exception as e:
        logger.error(f"Failed to update scheduled job: {e}")
        raise HTTPException(status_code=500, detail="Failed to update job")


@router.delete("/scheduled-jobs/{job_id}")
async def delete_scheduled_job(job_id: str):
    """Delete a scheduled job."""
    from ..services.scheduling.scheduler import scheduler_service

    job = scheduler_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    success = await scheduler_service.delete_job(job_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete job")

    return {"success": True}


@router.post("/scheduled-jobs/{job_id}/pause")
async def pause_scheduled_job(job_id: str):
    """Pause a scheduled job."""
    from ..services.scheduling.scheduler import scheduler_service

    job = await scheduler_service.pause_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    return job


@router.post("/scheduled-jobs/{job_id}/resume")
async def resume_scheduled_job(job_id: str):
    """Resume a paused scheduled job."""
    from ..services.scheduling.scheduler import scheduler_service

    job = await scheduler_service.resume_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    return job


@router.post("/scheduled-jobs/{job_id}/run-now")
async def run_scheduled_job_now(job_id: str):
    """Trigger a scheduled job to run immediately."""
    from ..services.scheduling.scheduler import scheduler_service

    job = scheduler_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    try:
        conversation_id = await scheduler_service.run_job_now(job_id)
        return {
            "success": True,
            "conversation_id": conversation_id,
            "job_name": job["name"],
        }
    except Exception as e:
        logger.error(f"Failed to run job now: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to run job: {e}")


@router.get("/scheduled-jobs/{job_id}/conversations")
async def list_job_conversations(job_id: str):
    """List conversations for a specific scheduled job."""
    from ..infrastructure.database import db
    from ..services.scheduling.scheduler import scheduler_service

    job = scheduler_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    conversations = db.get_job_conversations(job_id)
    return {"conversations": conversations, "job": job}


# ============================================
# Notifications API
# ============================================


@router.get("/notifications")
async def list_notifications():
    """List all notifications."""
    from ..services.scheduling.notifications import notification_service

    notifications = notification_service.list()
    count = notification_service.count()
    return {"notifications": notifications, "unread_count": count}


@router.get("/notifications/count")
async def get_notification_count():
    """Get the count of unread notifications."""
    from ..services.scheduling.notifications import notification_service

    count = notification_service.count()
    return {"count": count}


@router.delete("/notifications/{notification_id}")
async def dismiss_notification(notification_id: str):
    """Dismiss (delete) a single notification."""
    from ..services.scheduling.notifications import notification_service

    success = await notification_service.dismiss(notification_id)
    if not success:
        raise HTTPException(
            status_code=404, detail=f"Notification '{notification_id}' not found"
        )
    return {"success": True}


@router.delete("/notifications")
async def dismiss_all_notifications():
    """Dismiss (delete) all notifications."""
    from ..services.scheduling.notifications import notification_service

    count = await notification_service.dismiss_all()
    return {"success": True, "dismissed_count": count}


# ============================================
# File Browser API (for @ file attachments)
# ============================================


@router.get("/files/browse")
async def browse_files(query: Optional[str] = None):
    """
    Search the filesystem for file attachments.

    Search is global (from home), relevance-ranked, and does not support
    interactive folder navigation.

    Returns:
        entries: list of file/folder entries
        current_path: absolute home/search root path
        parent_path: always null (navigation disabled)
    """
    from ..services.filesystem.file_browser import file_browser_service

    try:
        result = await _run_in_thread(file_browser_service.search, query or "", None)

        return {
            "entries": [e.to_dict() for e in result.entries],
            "current_path": result.current_path,
            "parent_path": result.parent_path,
        }

    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("File browse error: %s", e)
        raise HTTPException(
            status_code=500,
            detail="Failed to browse files. See server logs.",
        )
