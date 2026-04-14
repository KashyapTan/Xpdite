"""
Anthropic-compatible marketplace service.

Handles source registry, manifest normalization, and install lifecycle for
Claude-style skills, plugins, and MCP bundles.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal, Optional
from urllib.parse import urlparse

import requests

from ...core.connection import manager
from ...infrastructure.config import (
    MARKETPLACE_MCP_DIR,
    MARKETPLACE_PLUGINS_DIR,
    MARKETPLACE_SKILLS_DIR,
    MARKETPLACE_PLUGIN_DATA_DIR,
    PROJECT_ROOT,
)
from ...infrastructure.database import db
from ...llm.core.key_manager import key_manager

logger = logging.getLogger(__name__)

MarketplaceItemKind = Literal["skill", "plugin", "mcp"]

_CANONICAL_SKILL_RE = re.compile(r"^[A-Za-z0-9_-]+(?::[A-Za-z0-9_-]+)*$")
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)
_BUILTIN_SOURCE_IDS = (
    "builtin-claude-plugins",
    "builtin-claude-skills",
    "builtin-mcp-registry",
    "builtin-xpdite-curated",
)
_MCP_REGISTRY_URL = "https://registry.modelcontextprotocol.io/v0.1/servers"
_PACKAGE_RUNNERS = {"npx", "uvx"}
_GITHUB_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:#[A-Za-z0-9._/-]+)?$")
_ENV_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")
_PLACEHOLDER_ONLY_RE = re.compile(r"^\$\{([^}]+)\}$")
_GITHUB_MANIFEST_FILENAMES = (
    ".claude-plugin/marketplace.json",
    "marketplace.json",
)
_PACKAGE_FLAGS_WITH_VALUE = {
    "npx": {"-p", "--package", "-c", "--call", "--registry", "--cache", "--userconfig", "--prefix", "--node-options"},
    "uvx": {"--from", "--index-url", "--extra-index-url", "--python", "--cache-dir"},
}
_PACKAGE_FLAGS_NO_VALUE = {
    "npx": {"-y", "--yes", "--quiet", "-q", "--ignore-existing"},
    "uvx": {"--refresh", "--isolated", "--verbose", "-v", "-q", "--quiet"},
}


@dataclass(frozen=True)
class SourceContext:
    source_id: str
    name: str
    kind: str
    location: str
    manifest: dict[str, Any]
    manifest_location: str
    base_path: Optional[Path]
    github_repo: Optional[str]
    github_ref: Optional[str]
    github_base_path: str


@dataclass(frozen=True)
class DirectRepoSpec:
    input: str
    kind: Literal["github", "local"]
    label: str
    base_path: Optional[Path]
    github_repo: Optional[str]
    github_ref: Optional[str]
    github_base_path: str


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", value.strip()).strip("-_").lower()
    return slug or f"item-{uuid.uuid4().hex[:8]}"


def _utc_now() -> float:
    return time.time()


def _install_root_for(kind: MarketplaceItemKind, install_id: str) -> Path:
    if kind == "plugin":
        return MARKETPLACE_PLUGINS_DIR / install_id
    if kind == "skill":
        return MARKETPLACE_SKILLS_DIR / install_id
    return MARKETPLACE_MCP_DIR / install_id


def _normalize_text_lines(value: str) -> list[str]:
    return [line.rstrip() for line in value.replace("\r\n", "\n").split("\n")]


def _parse_simple_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text

    raw_meta, body = match.groups()
    meta: dict[str, Any] = {}
    current_list_key: Optional[str] = None

    for line in _normalize_text_lines(raw_meta):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- ") and current_list_key:
            meta.setdefault(current_list_key, []).append(stripped[2:].strip())
            continue
        current_list_key = None
        if ":" not in stripped:
            continue
        key, raw_value = stripped.split(":", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if not raw_value:
            meta[key] = []
            current_list_key = key
            continue
        if raw_value.startswith("[") and raw_value.endswith("]"):
            items = [item.strip().strip("'\"") for item in raw_value[1:-1].split(",")]
            meta[key] = [item for item in items if item]
            continue
        lowered = raw_value.lower()
        if lowered in {"true", "false"}:
            meta[key] = lowered == "true"
            continue
        meta[key] = raw_value.strip("'\"")

    return meta, body


def _guess_item_kind(item: dict[str, Any]) -> MarketplaceItemKind:
    raw_kind = str(item.get("kind") or item.get("type") or "").strip().lower()
    if raw_kind in {"skill", "skills"}:
        return "skill"
    if raw_kind in {"plugin", "plugins"}:
        return "plugin"
    if raw_kind in {"mcp", "server", "servers", "mcp_server", "mcp_bundle"}:
        return "mcp"
    if item.get("plugin") or item.get("plugin_url"):
        return "plugin"
    if item.get("skill") or item.get("skill_url"):
        return "skill"
    if item.get("mcp") or item.get("mcp_url") or item.get("server"):
        return "mcp"
    return "plugin"


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"}


def _normalize_url_like_value(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        return normalized
    if normalized.startswith(("http:\\", "https:\\")):
        normalized = normalized.replace("\\", "/")
    if re.match(r"^https?:/[^/]", normalized):
        normalized = re.sub(r"^(https?):/+", r"\1://", normalized)
    if normalized.startswith(("github.com/", "www.github.com/", "raw.githubusercontent.com/")):
        normalized = f"https://{normalized}"
    return normalized


def _looks_like_npm_package_spec(value: str) -> bool:
    value = value.strip()
    if not value or value.startswith((".", "/", "\\")):
        return False
    if " " in value or value.endswith(".json"):
        return False
    if "==" in value:
        package_name, _, version = value.partition("==")
        return bool(package_name) and bool(version) and re.fullmatch(r"[A-Za-z0-9._-]+", package_name) is not None
    if value.startswith("@"):
        return value.count("/") == 1
    if value.count("/") == 1 and ":" not in value:
        owner, repo = value.split("/", 1)
        return bool(owner) and bool(repo)
    return "/" not in value and re.fullmatch(r"[A-Za-z0-9._-]+", value) is not None


def _is_github_raw_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.netloc in {
        "raw.githubusercontent.com",
        "github.com",
    }


def _github_archive_url(repo: str, ref: str) -> str:
    return f"https://api.github.com/repos/{repo}/zipball/{ref}"


def _normalize_relative_path(path: str) -> str:
    normalized = path.replace("\\", "/").strip()
    parts = [part for part in normalized.split("/") if part and part != "."]
    if ".." in parts:
        raise ValueError(f"Invalid relative path: {path}")
    return "/".join(parts)


def _split_manifest_path_parts(parts: list[str]) -> list[str]:
    for manifest_filename in _GITHUB_MANIFEST_FILENAMES:
        manifest_parts = [part for part in manifest_filename.split("/") if part]
        if len(parts) >= len(manifest_parts) and parts[-len(manifest_parts):] == manifest_parts:
            return parts[:-len(manifest_parts)]
    return parts[:-1] if parts else []


def _split_github_ref_and_base_path(parts: list[str]) -> tuple[Optional[str], list[str]]:
    if not parts:
        return None, []
    if len(parts) >= 3 and parts[0] == "refs" and parts[1] in {"heads", "tags"}:
        return parts[2], parts[3:]
    return parts[0], parts[1:]


def _parse_github_manifest_context(location: str) -> tuple[Optional[str], Optional[str], str]:
    parsed = urlparse(location)
    if parsed.netloc == "raw.githubusercontent.com":
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 4:
            owner, repo = parts[0], parts[1]
            ref, path_parts = _split_github_ref_and_base_path(
                _split_manifest_path_parts(parts[2:])
            )
            if ref is None:
                return None, None, ""
            path = "/".join(path_parts)
            return f"{owner}/{repo}", ref, path

    if parsed.netloc == "github.com":
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 5 and parts[2] in {"blob", "raw"}:
            owner, repo = parts[0], parts[1]
            ref, path_parts = _split_github_ref_and_base_path(
                _split_manifest_path_parts(parts[3:])
            )
            if ref is None:
                return None, None, ""
            path = "/".join(path_parts)
            return f"{owner}/{repo}", ref, path

    return None, None, ""


def _parse_github_repo_url(url: str) -> Optional[str]:
    parsed = urlparse(url)
    if parsed.netloc != "github.com":
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return None
    owner = parts[0]
    repo = parts[1].removesuffix(".git")
    return f"{owner}/{repo}"


def _github_raw_url(repo: str, ref: str, path: str) -> str:
    normalized_path = path.lstrip("/")
    return f"https://raw.githubusercontent.com/{repo}/{ref}/{normalized_path}"


def _sanitize_secret_name(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", value.strip()).strip("_").upper()
    return normalized or "VALUE"


def _unwrap_quoted_token(token: str) -> str:
    token = token.strip()
    if len(token) >= 2 and token[0] == token[-1] and token[0] in {"'", '"'}:
        return token[1:-1]
    return token


def _format_command_tokens(tokens: list[str]) -> str:
    if not tokens:
        return ""
    if os.name == "nt":
        return subprocess.list2cmdline(tokens)
    return shlex.join(tokens)


def _contains_placeholder(value: str) -> bool:
    return bool(re.search(r"\$\{[^}]+\}", value))


def _placeholder_only_name(value: str) -> Optional[str]:
    match = _PLACEHOLDER_ONLY_RE.fullmatch(value.strip())
    if match:
        return match.group(1).strip() or None
    return None


def _normalize_archive_member_path(path: str) -> str:
    normalized = path.replace("\\", "/").strip()
    if not normalized:
        return ""
    normalized = normalized.lstrip("/")
    if re.match(r"^[A-Za-z]:", normalized):
        raise ValueError(f"Unsafe archive path: {path}")
    parts = [part for part in normalized.split("/") if part and part != "."]
    if ".." in parts:
        raise ValueError(f"Unsafe archive path: {path}")
    return "/".join(parts)


class MarketplaceService:
    """Marketplace source registry and install lifecycle manager."""

    BUILTIN_SOURCES: tuple[dict[str, Any], ...] = (
        {
            "id": "builtin-claude-plugins",
            "name": "Anthropic Plugins",
            "kind": "remote_manifest",
            "location": "https://raw.githubusercontent.com/anthropics/claude-plugins-official/main/.claude-plugin/marketplace.json",
            "builtin": True,
        },
        {
            "id": "builtin-claude-skills",
            "name": "Anthropic Skills",
            "kind": "remote_manifest",
            "location": "https://raw.githubusercontent.com/anthropics/skills/main/.claude-plugin/marketplace.json",
            "builtin": True,
        },
        {
            "id": "builtin-mcp-registry",
            "name": "Official MCP Registry",
            "kind": "registry_manifest",
            "location": "builtin://mcp-registry",
            "builtin": True,
        },
        {
            "id": "builtin-xpdite-curated",
            "name": "Xpdite Curated",
            "kind": "builtin_manifest",
            "location": "builtin://xpdite-curated",
            "builtin": True,
        },
    )

    def __init__(self) -> None:
        self._initialized = False
        self._lock = threading.Lock()

    def initialize(self) -> None:
        with self._lock:
            if self._initialized:
                return
            for source in self.BUILTIN_SOURCES:
                self._upsert_source_row(
                    source_id=source["id"],
                    name=source["name"],
                    kind=source["kind"],
                    location=source["location"],
                    enabled=True,
                    builtin=bool(source["builtin"]),
                    manifest_json=None,
                    last_sync_at=None,
                    last_error=None,
                )
            self._initialized = True

    async def initialize_async(self) -> None:
        await asyncio.to_thread(self.initialize)

    async def refresh_builtin_sources_async(self) -> None:
        self.initialize()
        for source_id in _BUILTIN_SOURCE_IDS:
            try:
                await self.refresh_source_async(source_id)
            except Exception as exc:
                logger.warning("Marketplace source refresh failed for %s: %s", source_id, exc)

    def list_sources(self) -> list[dict[str, Any]]:
        self.initialize()
        with db._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, name, kind, location, enabled, builtin, manifest_json,
                       last_sync_at, last_error, created_at, updated_at
                FROM marketplace_sources
                ORDER BY builtin DESC, name COLLATE NOCASE ASC
                """
            ).fetchall()
        return [self._row_to_source(row) for row in rows]

    def create_source(self, name: str, location: str, kind: str = "manifest") -> dict[str, Any]:
        self.initialize()
        source_id = f"user-{uuid.uuid4().hex}"
        builtin = False
        normalized_name = name.strip()
        normalized_location = self._normalize_marketplace_source_location(location)
        requested_kind = kind.strip()
        if requested_kind == "manifest":
            requested_kind = ""
        if normalized_name.lower() in _PACKAGE_RUNNERS:
            direct_repo = self._parse_direct_repo_input(normalized_location)
            if direct_repo is not None:
                raise ValueError(
                    "GitHub or local Claude repos should be installed from Direct Claude Repos, not added as MCP package sources"
                )
        if normalized_location.startswith(("npx:", "uvx:")):
            normalized_kind = "generated_manifest"
        elif normalized_name.lower() == "npx" and _looks_like_npm_package_spec(normalized_location):
            normalized_kind = "generated_manifest"
            normalized_location = f"npx:{normalized_location}"
        elif normalized_name.lower() == "uvx" and _looks_like_npm_package_spec(normalized_location):
            normalized_kind = "generated_manifest"
            normalized_location = f"uvx:{normalized_location}"
        else:
            normalized_kind = requested_kind or ("remote_manifest" if _is_http_url(normalized_location) else "local_manifest")
        self._upsert_source_row(
            source_id=source_id,
            name=normalized_name or normalized_location,
            kind=normalized_kind,
            location=normalized_location,
            enabled=True,
            builtin=builtin,
            manifest_json=None,
            last_sync_at=None,
            last_error=None,
        )
        return self.get_source(source_id)

    def _normalize_marketplace_source_location(self, location: str) -> str:
        normalized_location = _normalize_url_like_value(location)
        github = self._parse_github_repo_reference(normalized_location)
        if github is None:
            return normalized_location
        repo, ref, base_path = github
        if ref:
            tree_path = f"/{base_path}" if base_path else ""
            return f"https://github.com/{repo}/tree/{ref}{tree_path}"
        return f"https://github.com/{repo}"

    async def install_package_async(
        self,
        *,
        runner: str,
        package_input: str,
    ) -> dict[str, Any]:
        runner = runner.strip().lower()
        progress_payload: dict[str, Any] = {"runner": runner}
        try:
            package_info = self._parse_package_command(runner, package_input)
            progress_payload["display_name"] = package_info["display_name"]
            progress_payload["package_spec"] = package_info["package_spec"]
        except Exception:
            progress_payload["display_name"] = package_input.strip() or runner
        await manager.broadcast_json(
            "marketplace_install_started",
            progress_payload,
        )
        try:
            install = await asyncio.to_thread(
                self._install_package_sync,
                runner,
                package_input,
            )
            await self._connect_install_runtime_if_needed(install)
            install = await asyncio.to_thread(self.get_install, install["id"])
            await manager.broadcast_json(
                "marketplace_install_completed",
                {"install_id": install["id"], "status": install["status"]},
            )
            return install
        except Exception as exc:
            await manager.broadcast_json(
                "marketplace_install_failed",
                {**progress_payload, "error": str(exc)},
            )
            raise

    async def install_repo_async(
        self,
        *,
        repo_input: str,
    ) -> dict[str, Any]:
        repo_input = repo_input.strip()
        await manager.broadcast_json(
            "marketplace_install_started",
            {"repo_input": repo_input},
        )
        try:
            install = await asyncio.to_thread(
                self._install_repo_sync,
                repo_input,
            )
            await self._connect_install_runtime_if_needed(install)
            install = await asyncio.to_thread(self.get_install, install["id"])
            await manager.broadcast_json(
                "marketplace_install_completed",
                {"install_id": install["id"], "status": install["status"]},
            )
            return install
        except Exception as exc:
            await manager.broadcast_json(
                "marketplace_install_failed",
                {"repo_input": repo_input, "error": str(exc)},
            )
            raise

    def get_source(self, source_id: str) -> dict[str, Any]:
        with db._connect() as conn:
            row = conn.execute(
                """
                SELECT id, name, kind, location, enabled, builtin, manifest_json,
                       last_sync_at, last_error, created_at, updated_at
                FROM marketplace_sources
                WHERE id = ?
                """,
                (source_id,),
            ).fetchone()
        if row is None:
            raise ValueError(f"Unknown marketplace source: {source_id}")
        return self._row_to_source(row)

    def delete_source(self, source_id: str) -> None:
        source = self.get_source(source_id)
        if source["builtin"]:
            raise ValueError("Built-in marketplace sources cannot be removed")
        with db._connect() as conn:
            install_count = conn.execute(
                "SELECT COUNT(*) FROM marketplace_installs WHERE source_id = ?",
                (source_id,),
            ).fetchone()[0]
            if install_count:
                raise ValueError("Cannot remove a marketplace source with installed items")
            conn.execute("DELETE FROM marketplace_sources WHERE id = ?", (source_id,))
            conn.commit()

    async def refresh_source_async(self, source_id: str) -> dict[str, Any]:
        await manager.broadcast_json("marketplace_sync_started", {"source_id": source_id})
        try:
            source = await asyncio.to_thread(self._refresh_source_sync, source_id)
            await manager.broadcast_json(
                "marketplace_sync_completed",
                {"source_id": source_id, "last_sync_at": source["last_sync_at"]},
            )
            return source
        except Exception as exc:
            await manager.broadcast_json(
                "marketplace_sync_failed",
                {"source_id": source_id, "error": str(exc)},
            )
            raise

    def list_catalog(self) -> list[dict[str, Any]]:
        self.initialize()
        installs = {
            install["source_id"] + "::" + install["manifest_item_id"]: install
            for install in self.list_installs()
            if install.get("source_id")
        }
        catalog: list[dict[str, Any]] = []
        for source in self.list_sources():
            if not source["enabled"]:
                continue
            manifest = source.get("manifest") or {}
            for item in self._manifest_items(manifest):
                normalized = self._normalize_catalog_item(source, item)
                install_key = f"{source['id']}::{normalized['manifest_item_id']}"
                normalized["install"] = installs.get(install_key)
                catalog.append(normalized)
        return catalog

    def list_installs(self) -> list[dict[str, Any]]:
        with db._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, item_kind, source_id, manifest_item_id, display_name,
                       canonical_id, install_root, resolved_ref, status, enabled,
                       component_manifest_json, raw_source_json, last_error,
                       created_at, updated_at
                FROM marketplace_installs
                ORDER BY created_at DESC
                """
            ).fetchall()
        return [self._row_to_install(row) for row in rows]

    def get_install(self, install_id: str) -> dict[str, Any]:
        with db._connect() as conn:
            row = conn.execute(
                """
                SELECT id, item_kind, source_id, manifest_item_id, display_name,
                       canonical_id, install_root, resolved_ref, status, enabled,
                       component_manifest_json, raw_source_json, last_error,
                       created_at, updated_at
                FROM marketplace_installs
                WHERE id = ?
                """,
                (install_id,),
            ).fetchone()
        if row is None:
            raise ValueError(f"Unknown marketplace install: {install_id}")
        return self._row_to_install(row)

    async def install_item_async(
        self,
        *,
        source_id: str,
        manifest_item_id: str,
        secrets: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        await manager.broadcast_json(
            "marketplace_install_started",
            {"source_id": source_id, "manifest_item_id": manifest_item_id},
        )
        try:
            install = await asyncio.to_thread(
                self._install_item_sync,
                source_id,
                manifest_item_id,
                secrets or {},
            )
            await self._connect_install_runtime_if_needed(install)
            install = await asyncio.to_thread(self.get_install, install["id"])
            await manager.broadcast_json(
                "marketplace_install_completed",
                {"install_id": install["id"], "status": install["status"]},
            )
            return install
        except Exception as exc:
            await manager.broadcast_json(
                "marketplace_install_failed",
                {
                    "source_id": source_id,
                    "manifest_item_id": manifest_item_id,
                    "error": str(exc),
                },
            )
            raise

    async def enable_install_async(self, install_id: str) -> dict[str, Any]:
        install = await asyncio.to_thread(self._set_install_enabled_sync, install_id, True)
        await self._connect_install_runtime_if_needed(install)
        install = await asyncio.to_thread(self.get_install, install_id)
        await manager.broadcast_json(
            "marketplace_update_completed",
            {"install_id": install_id, "action": "enable", "status": install["status"]},
        )
        return install

    async def disable_install_async(self, install_id: str) -> dict[str, Any]:
        install_before = self.get_install(install_id)
        await self._disconnect_install_runtime_if_needed(install_before)
        install = await asyncio.to_thread(self._set_install_enabled_sync, install_id, False)
        await manager.broadcast_json(
            "marketplace_update_completed",
            {"install_id": install_id, "action": "disable", "status": install["status"]},
        )
        return install

    async def update_install_async(self, install_id: str) -> dict[str, Any]:
        install = self.get_install(install_id)
        refreshed: Optional[dict[str, Any]] = None
        replacement_connected = False
        old_runtime_disconnected = False

        await manager.broadcast_json("marketplace_update_started", {"install_id": install_id})
        try:
            secrets = self.get_install_secrets(install_id)
            refreshed = await asyncio.to_thread(
                self._reinstall_existing_install_sync,
                install_id,
                secrets,
            )
            await self._connect_install_runtime_if_needed(refreshed)
            replacement_connected = True
            if install["enabled"]:
                await self._disconnect_install_runtime_if_needed(install)
                old_runtime_disconnected = True
            await asyncio.to_thread(self._remove_install_artifacts_sync, install)
            await asyncio.to_thread(
                self._finalize_replacement_install_sync,
                refreshed["id"],
                install["manifest_item_id"],
            )
            refreshed = await asyncio.to_thread(self.get_install, refreshed["id"])
            await manager.broadcast_json(
                "marketplace_update_completed",
                {
                    "install_id": install_id,
                    "replacement_install_id": refreshed["id"],
                    "status": refreshed["status"],
                },
            )
            return refreshed
        except Exception as exc:
            if refreshed is not None:
                if replacement_connected:
                    try:
                        await self._disconnect_install_runtime_if_needed(refreshed)
                    except Exception:
                        logger.exception(
                            "Failed to disconnect replacement marketplace install %s during rollback",
                            refreshed["id"],
                        )
                try:
                    await asyncio.to_thread(self._remove_install_artifacts_sync, refreshed)
                except Exception:
                    logger.exception(
                        "Failed to remove replacement marketplace install %s during rollback",
                        refreshed["id"],
                    )
            if old_runtime_disconnected and install["enabled"]:
                try:
                    await self._connect_install_runtime_if_needed(install)
                except Exception:
                    logger.exception(
                        "Failed to reconnect original marketplace install %s after rollback",
                        install["id"],
                    )
            await manager.broadcast_json(
                "marketplace_update_failed",
                {"install_id": install_id, "error": str(exc)},
            )
            raise

    def _reinstall_existing_install_sync(
        self,
        install_id: str,
        secrets: dict[str, str],
    ) -> dict[str, Any]:
        install = self.get_install(install_id)
        source_id = install.get("source_id")
        if source_id:
            return self._install_item_sync(
                source_id,
                install["manifest_item_id"],
                secrets,
                enabled=install["enabled"],
                replacement_install_id=install_id,
            )

        raw_source = install.get("raw_source") or {}
        raw_kind = str(raw_source.get("kind") or "")
        if raw_kind == "direct_package":
            return self._install_package_sync(
                runner=str(raw_source.get("runner") or ""),
                package_input=str(raw_source.get("package_command") or ""),
                secrets_override=secrets,
                enabled=install["enabled"],
                replacement_install_id=install_id,
            )
        if raw_kind == "direct_repo":
            install_request = self._build_direct_repo_install_request(str(raw_source.get("repo_input") or ""))
            if install_request is None:
                raise ValueError("Marketplace install is missing a valid direct repo source")
            return self._install_direct_repo_request_sync(
                install_request,
                secrets=secrets,
                enabled=install["enabled"],
                replacement_install_id=install_id,
            )
        raise ValueError("Marketplace install is missing a source")

    async def uninstall_async(self, install_id: str) -> dict[str, Any]:
        await manager.broadcast_json("marketplace_uninstall_started", {"install_id": install_id})
        try:
            install = self.get_install(install_id)
            await self._disconnect_install_runtime_if_needed(install)
            removed = await asyncio.to_thread(self._uninstall_sync, install_id)
            await manager.broadcast_json("marketplace_uninstall_completed", {"install_id": install_id})
            return removed
        except Exception as exc:
            await manager.broadcast_json(
                "marketplace_uninstall_failed",
                {"install_id": install_id, "error": str(exc)},
            )
            raise

    def set_install_secrets(self, install_id: str, secrets: dict[str, str]) -> dict[str, Any]:
        for key, value in secrets.items():
            encrypted = key_manager.encrypt_key(value)
            db.set_setting(f"marketplace_secret:{install_id}:{key}", encrypted)
        install = self.get_install(install_id)
        return {
            "install_id": install_id,
            "required_secrets": install.get("required_secrets", []),
            "stored": sorted(secrets.keys()),
        }

    def get_install_secrets(self, install_id: str) -> dict[str, str]:
        with db._connect() as conn:
            row = conn.execute(
                """
                SELECT component_manifest_json, raw_source_json
                FROM marketplace_installs
                WHERE id = ?
                """,
                (install_id,),
            ).fetchone()
        if row is None:
            raise ValueError(f"Unknown marketplace install: {install_id}")
        component_manifest = json.loads(row[0]) if row[0] else {}
        raw_source = json.loads(row[1]) if row[1] else {}
        secret_names = self._install_secret_names(component_manifest, raw_source)
        values: dict[str, str] = {}
        for secret_name in secret_names:
            encrypted = db.get_setting(f"marketplace_secret:{install_id}:{secret_name}")
            if not encrypted:
                continue
            decrypted = key_manager.decrypt_key(encrypted)
            if decrypted is not None:
                values[secret_name] = decrypted
        return values

    async def reconnect_enabled_mcp_installs_async(self) -> None:
        installs = [
            install
            for install in self.list_installs()
            if install["enabled"] and self.build_runtime_server_config(install) is not None
        ]
        if not installs:
            return

        from ...mcp_integration.core.manager import mcp_manager

        connected = False
        for install in installs:
            for runtime in self.build_runtime_server_configs(install):
                if runtime.get("manual_auth_required"):
                    continue
                server_name = runtime["server_name"]
                if mcp_manager.is_server_connected(server_name):
                    continue
                try:
                    await mcp_manager.connect_server(
                        runtime["server_name"],
                        runtime["command"],
                        runtime["args"],
                        env=runtime.get("env"),
                        skip_embed=True,
                        tool_name_prefix=runtime.get("tool_name_prefix"),
                        display_name=runtime.get("display_name"),
                    )
                    await asyncio.to_thread(
                        self._set_install_runtime_state_sync,
                        install["id"],
                        status="connected",
                        last_error=None,
                    )
                    connected = True
                except Exception as exc:
                    logger.warning("Failed to reconnect marketplace install %s: %s", install["id"], exc)
                    await asyncio.to_thread(
                        self._set_install_runtime_state_sync,
                        install["id"],
                        status="error",
                        last_error=self._friendly_runtime_error(install, exc),
                    )

        if connected:
            mcp_manager.refresh_tool_embeddings()

    async def _connect_install_runtime_if_needed(self, install: dict[str, Any]) -> None:
        if not install["enabled"]:
            return

        from ..hooks_runtime import get_hooks_runtime
        from ...mcp_integration.core.manager import mcp_manager

        hooks_runtime = get_hooks_runtime()
        connected_servers: list[str] = []
        hooks_registered = False
        try:
            await hooks_runtime.register_install_async(install)
            hooks_registered = True
            for runtime in self.build_runtime_server_configs(install):
                if runtime.get("manual_auth_required"):
                    continue
                if mcp_manager.is_server_connected(runtime["server_name"]):
                    continue
                await mcp_manager.connect_server(
                    runtime["server_name"],
                    runtime["command"],
                    runtime["args"],
                    env=runtime.get("env"),
                    skip_embed=False,
                    tool_name_prefix=runtime.get("tool_name_prefix"),
                    display_name=runtime.get("display_name"),
                )
                connected_servers.append(runtime["server_name"])
            install = await asyncio.to_thread(self.get_install, install["id"])
            status = self._resolve_install_status(
                install,
                enabled=True,
                hooks_runtime=hooks_runtime,
            )
            install = await asyncio.to_thread(
                self._set_install_runtime_state_sync,
                install["id"],
                status=status,
                last_error=None,
            )
        except Exception as exc:
            for server_name in reversed(connected_servers):
                if not mcp_manager.is_server_connected(server_name):
                    continue
                try:
                    await mcp_manager.disconnect_server(server_name)
                except Exception as cleanup_exc:
                    logger.warning(
                        "Rollback disconnect failed for install '%s' server '%s': %s",
                        install["id"],
                        server_name,
                        cleanup_exc,
                    )
            if hooks_registered:
                try:
                    await hooks_runtime.unregister_install_async(str(install["id"]))
                except Exception as cleanup_exc:
                    logger.warning(
                        "Rollback hook unregister failed for install '%s': %s",
                        install["id"],
                        cleanup_exc,
                    )
            friendly_error = self._friendly_runtime_error(install, exc)
            await asyncio.to_thread(
                self._set_install_runtime_state_sync,
                install["id"],
                status="error",
                last_error=friendly_error,
            )
            raise ValueError(friendly_error) from exc

    async def _disconnect_install_runtime_if_needed(self, install: dict[str, Any]) -> None:
        from ..hooks_runtime import get_hooks_runtime
        from ...mcp_integration.core.manager import mcp_manager

        runtimes = self.build_runtime_server_configs(install)
        if not runtimes:
            component_manifest = install.get("component_manifest") or {}
            for index, mcp_manifest in enumerate(self._component_runtime_manifests(component_manifest)):
                runtimes.append(
                    self._build_runtime_from_mcp_manifest(
                        install["id"],
                        mcp_manifest,
                        install_root=install.get("install_root"),
                        config_index=index,
                    )
                )
        for runtime in runtimes:
            server_name = runtime["server_name"]
            if mcp_manager.is_server_connected(server_name):
                await mcp_manager.disconnect_server(server_name)
        await get_hooks_runtime().unregister_install_async(str(install["id"]))

    def _refresh_source_sync(self, source_id: str) -> dict[str, Any]:
        source = self.get_source(source_id)
        manifest = self._load_source_manifest(source)
        now = _utc_now()
        with db._connect() as conn:
            conn.execute(
                """
                UPDATE marketplace_sources
                SET manifest_json = ?, last_sync_at = ?, last_error = NULL, updated_at = ?
                WHERE id = ?
                """,
                (_json_dumps(manifest), now, now, source_id),
            )
            conn.commit()
        return self.get_source(source_id)

    def _load_source_manifest(self, source: dict[str, Any]) -> dict[str, Any]:
        location = self._normalize_marketplace_source_location(str(source["location"]))
        if location == "builtin://mcp-registry":
            return self._build_mcp_registry_manifest()
        if location == "builtin://xpdite-curated":
            return self._build_curated_manifest()
        package_source = self._detect_package_source(source)
        if package_source is not None:
            return self._build_package_manifest(
                package_source["runner"],
                package_source["command_input"],
            )
        if _is_http_url(location):
            manifest, _resolved_location = self._load_remote_manifest(location)
            return manifest

        manifest_path, _base_root = self._resolve_local_manifest_path(location)
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Marketplace manifest must be a JSON object")
        self._validate_installable_manifest(payload, source_location=location)
        return payload

    def _detect_package_source(self, source: dict[str, Any]) -> Optional[dict[str, str]]:
        location = str(source.get("location") or "").strip()
        source_name = str(source.get("name") or "").strip().lower()
        source_kind = str(source.get("kind") or "").strip().lower()

        if location.startswith("npx:"):
            return {"runner": "npx", "command_input": location.removeprefix("npx:").strip()}
        if location.startswith("uvx:"):
            return {"runner": "uvx", "command_input": location.removeprefix("uvx:").strip()}

        tokens = self._split_package_command(location)
        if tokens and tokens[0].lower() in _PACKAGE_RUNNERS:
            return {
                "runner": tokens[0].lower(),
                "command_input": " ".join(tokens[1:]).strip(),
            }

        if source_name in _PACKAGE_RUNNERS and location:
            return {"runner": source_name, "command_input": location}

        # Recover older misclassified package sources created before the
        # dedicated package installer existed.
        if source_kind in {"generated_manifest", "local_manifest", "manifest"}:
            inferred_runner: Optional[str] = None
            if "==" in location:
                inferred_runner = "uvx"
            elif location.startswith("@"):
                inferred_runner = "npx"
            if inferred_runner:
                return {"runner": inferred_runner, "command_input": location}

        return None

    def _resolve_local_manifest_path(self, location: str) -> tuple[Path, Path]:
        path = Path(location).expanduser()
        if not path.is_absolute():
            path = (PROJECT_ROOT / path).resolve()
        if not path.exists():
            raise ValueError(f"Marketplace manifest path not found: {path}")

        if path.is_dir():
            candidates = [
                path / ".claude-plugin" / "marketplace.json",
                path / "marketplace.json",
            ]
            for candidate in candidates:
                if candidate.exists():
                    base_root = path
                    return candidate, base_root
            raise ValueError(f"Marketplace manifest path not found: {path}")

        base_root = path.parent
        if path.name == "marketplace.json" and path.parent.name == ".claude-plugin":
            base_root = path.parent.parent
        return path, base_root

    def _build_curated_manifest(self) -> dict[str, Any]:
        return {
            "name": "Xpdite Curated",
            "items": [
                {
                    "id": "everything-demo",
                    "kind": "mcp",
                    "name": "Everything (Demo)",
                    "description": "Sample MCP server bundled as a curated marketplace item.",
                    "source": {
                        "source": "xpdite-inline",
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-everything"],
                        "server_name": "everything",
                        "display_name": "Everything (Demo)",
                    },
                    "services": ["Demo"],
                    "compatibility": ["Anthropic MCP", "Xpdite"],
                }
            ],
        }

    def _build_package_manifest(self, runner: str, package_command: str) -> dict[str, Any]:
        package_info = self._parse_package_command(runner, package_command)
        display_name = package_info["display_name"]
        item_id = package_info["item_id"]
        return {
            "name": f"{runner} Package",
            "items": [
                {
                    "id": item_id,
                    "kind": "mcp",
                    "name": display_name,
                    "description": f"Direct MCP package installed via {runner}.",
                    "source": package_info["descriptor"],
                    "package_manager": runner,
                    "package_command": package_info["command_input"],
                }
            ],
        }

    def _split_package_command(self, value: str) -> list[str]:
        value = value.strip()
        if not value:
            return []
        try:
            tokens = shlex.split(value, posix=os.name != "nt")
        except ValueError:
            tokens = value.split()
        return [_unwrap_quoted_token(token) for token in tokens if token and token.strip()]

    def _infer_package_spec(self, runner: str, args: list[str]) -> str:
        value_flags = _PACKAGE_FLAGS_WITH_VALUE.get(runner, set())
        no_value_flags = _PACKAGE_FLAGS_NO_VALUE.get(runner, set())
        pending_flag: Optional[str] = None

        for token in args:
            if pending_flag is not None:
                if pending_flag in {"-p", "--package", "--from"}:
                    return token
                pending_flag = None
                continue

            if token in value_flags:
                pending_flag = token
                continue
            if token in no_value_flags:
                continue
            if token.startswith("-"):
                continue
            return token

        raise ValueError(f"Could not determine the package name from the {runner} command")

    @staticmethod
    def _parse_env_assignment(token: str) -> tuple[str, str]:
        if "=" not in token:
            raise ValueError("Environment assignment must use NAME=value syntax")
        name, value = token.split("=", 1)
        normalized_name = name.strip()
        if not normalized_name or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", normalized_name):
            raise ValueError(f"Invalid environment variable name: {name}")
        return normalized_name, value

    def _extract_package_env(self, tokens: list[str]) -> tuple[dict[str, str], list[str]]:
        env: dict[str, str] = {}
        args: list[str] = []
        index = 0
        allow_leading_assignments = True

        while index < len(tokens):
            token = tokens[index]
            if token in {"--env", "-e"}:
                if index + 1 >= len(tokens):
                    raise ValueError("Expected NAME=value after --env")
                env_name, env_value = self._parse_env_assignment(tokens[index + 1])
                env[env_name] = env_value
                index += 2
                allow_leading_assignments = False
                continue
            if token.startswith("--env="):
                env_name, env_value = self._parse_env_assignment(token[len("--env="):])
                env[env_name] = env_value
                index += 1
                allow_leading_assignments = False
                continue
            if allow_leading_assignments and _ENV_ASSIGNMENT_RE.fullmatch(token):
                env_name, env_value = self._parse_env_assignment(token)
                env[env_name] = env_value
                index += 1
                continue

            allow_leading_assignments = False
            args.append(token)
            index += 1

        return env, args

    @staticmethod
    def _is_sensitive_arg_flag(flag: str) -> bool:
        normalized = flag.strip().lower().lstrip("-").replace("_", "-")
        parts = [part for part in re.split(r"[^a-z0-9]+", normalized) if part]
        if normalized in {"apikey", "api-key"}:
            return True
        return any(part in {"token", "secret", "password", "auth", "key"} for part in parts)

    def _normalize_direct_package_env(
        self,
        env: dict[str, str],
    ) -> tuple[dict[str, str], dict[str, str]]:
        descriptor_env: dict[str, str] = {}
        initial_secrets: dict[str, str] = {}

        for name, value in env.items():
            placeholder_name = _placeholder_only_name(value)
            if placeholder_name or _contains_placeholder(value):
                descriptor_env[name] = value
                continue
            descriptor_env[name] = f"${{{name}}}"
            initial_secrets[name] = value

        return descriptor_env, initial_secrets

    def _normalize_direct_package_args(
        self,
        args: list[str],
    ) -> tuple[list[str], dict[str, str]]:
        normalized_args: list[str] = []
        initial_secrets: dict[str, str] = {}
        index = 0

        while index < len(args):
            token = args[index]
            if token.startswith("-"):
                if "=" in token:
                    flag, value = token.split("=", 1)
                    if value and self._is_sensitive_arg_flag(flag) and not _contains_placeholder(value):
                        secret_name = _sanitize_secret_name(flag)
                        normalized_args.append(f"{flag}=${{{secret_name}}}")
                        initial_secrets.setdefault(secret_name, value)
                        index += 1
                        continue
                normalized_args.append(token)
                if (
                    self._is_sensitive_arg_flag(token)
                    and index + 1 < len(args)
                    and not args[index + 1].startswith("-")
                ):
                    raw_value = args[index + 1]
                    if _contains_placeholder(raw_value):
                        normalized_args.append(raw_value)
                    else:
                        secret_name = _sanitize_secret_name(token)
                        normalized_args.append(f"${{{secret_name}}}")
                        initial_secrets.setdefault(secret_name, raw_value)
                    index += 2
                    continue
                index += 1
                continue

            normalized_args.append(token)
            index += 1

        return normalized_args, initial_secrets

    @staticmethod
    def _format_package_command_input(env: dict[str, str], args: list[str]) -> str:
        tokens = [*(f"{name}={value}" for name, value in env.items()), *args]
        return _format_command_tokens(tokens)

    def _parse_package_command(self, runner: str, package_command: str) -> dict[str, Any]:
        normalized_runner = runner.strip().lower()
        if normalized_runner not in _PACKAGE_RUNNERS:
            raise ValueError("Package installs currently support only npx and uvx")

        tokens = self._split_package_command(package_command)
        if not tokens:
            raise ValueError(f"{normalized_runner} package source cannot be empty")

        if tokens[0].lower() in _PACKAGE_RUNNERS:
            if tokens[0].lower() != normalized_runner:
                raise ValueError(
                    f"Package installer runner mismatch: selected {normalized_runner}, but command starts with {tokens[0].lower()}"
                )
            tokens = tokens[1:]

        if not tokens:
            raise ValueError(f"{normalized_runner} package source cannot be empty")

        env, args = self._extract_package_env(tokens)
        if not args:
            raise ValueError(f"{normalized_runner} package source cannot be empty")
        descriptor_env, env_secrets = self._normalize_direct_package_env(env)
        args, arg_secrets = self._normalize_direct_package_args(args)
        if normalized_runner == "npx" and not any(token in {"-y", "--yes"} for token in args):
            args = ["-y", *args]

        package_spec = self._infer_package_spec(normalized_runner, args)
        display_name = package_spec
        item_id = _safe_slug(package_spec.replace("@", "").replace("/", "-"))
        return {
            "runner": normalized_runner,
            "args": args,
            "env": descriptor_env,
            "initial_secrets": {**env_secrets, **arg_secrets},
            "package_spec": package_spec,
            "display_name": display_name,
            "item_id": item_id,
            "command_input": self._format_package_command_input(descriptor_env, args),
            "descriptor": {
                "source": "xpdite-inline",
                "name": display_name,
                "display_name": display_name,
                "command": normalized_runner,
                "args": args,
                "server_name": display_name,
                **({"env": descriptor_env} if descriptor_env else {}),
            },
        }

    def _resolve_local_repo_input_path(self, repo_input: str) -> Optional[Path]:
        candidate = Path(repo_input).expanduser()
        if not candidate.is_absolute():
            candidate = (PROJECT_ROOT / candidate).resolve()
        return candidate if candidate.exists() else None

    def _parse_github_repo_reference(
        self,
        repo_input: str,
    ) -> Optional[tuple[str, Optional[str], str]]:
        value = repo_input.strip()
        if not value:
            return None

        if _GITHUB_REPO_RE.fullmatch(value):
            repo, _, ref = value.partition("#")
            return repo, ref or None, ""

        parsed = urlparse(value)
        if parsed.netloc != "github.com":
            return None

        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) < 2:
            return None

        repo = f"{parts[0]}/{parts[1].removesuffix('.git')}"
        ref: Optional[str] = None
        base_path = ""
        if len(parts) >= 4 and parts[2] == "tree":
            ref = parts[3]
            base_path = "/".join(parts[4:])
        elif len(parts) >= 4 and parts[2] == "blob":
            ref = parts[3]
            base_path = "/".join(parts[4:-1])

        normalized_base_path = _normalize_relative_path(base_path) if base_path else ""
        return repo, ref, normalized_base_path

    def _parse_direct_repo_input(self, repo_input: str) -> Optional[DirectRepoSpec]:
        normalized_input = repo_input.strip()
        if not normalized_input:
            return None

        github = self._parse_github_repo_reference(normalized_input)
        if github is not None:
            repo, ref, base_path = github
            return DirectRepoSpec(
                input=normalized_input,
                kind="github",
                label=repo.split("/")[-1],
                base_path=None,
                github_repo=repo,
                github_ref=ref,
                github_base_path=base_path,
            )

        local_path = self._resolve_local_repo_input_path(normalized_input)
        if local_path is None:
            return None

        if local_path.is_file():
            if local_path.name == "marketplace.json" and local_path.parent.name == ".claude-plugin":
                base_path = local_path.parent.parent
            elif local_path.name == "plugin.json" and local_path.parent.name == ".claude-plugin":
                base_path = local_path.parent.parent
            else:
                base_path = local_path.parent
        else:
            base_path = local_path

        return DirectRepoSpec(
            input=normalized_input,
            kind="local",
            label=base_path.name,
            base_path=base_path.resolve(),
            github_repo=None,
            github_ref=None,
            github_base_path="",
        )

    @staticmethod
    def _join_repo_path(base_path: str, relative_path: str) -> str:
        return "/".join(part for part in [base_path.strip("/"), relative_path.strip("/")] if part)

    def _fetch_optional_json(self, url: str) -> Optional[dict[str, Any]]:
        response = requests.get(url, timeout=30)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError(f"Expected a JSON object from {url}")
        return payload

    def _fetch_optional_text(self, url: str) -> Optional[str]:
        response = requests.get(url, timeout=30)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.text

    def _fetch_github_default_branch(self, repo: str) -> Optional[str]:
        try:
            response = requests.get(f"https://api.github.com/repos/{repo}", timeout=30)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict):
                branch = str(payload.get("default_branch") or "").strip()
                return branch or None
        except Exception:
            logger.debug("Unable to resolve default branch for %s", repo, exc_info=True)
        return None

    def _candidate_github_refs(self, repo: str, preferred_ref: Optional[str]) -> list[str]:
        refs: list[str] = []
        if preferred_ref:
            refs.append(preferred_ref)
        else:
            default_branch = self._fetch_github_default_branch(repo)
            for candidate in (default_branch, "main", "master"):
                if candidate and candidate not in refs:
                    refs.append(candidate)
        return refs or ["main", "master"]

    def _candidate_remote_manifest_urls(self, location: str) -> list[str]:
        parsed = urlparse(location)
        if parsed.netloc == "raw.githubusercontent.com":
            return [location]
        if parsed.netloc != "github.com":
            return [location]

        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) < 2:
            return [location]

        repo = f"{parts[0]}/{parts[1].removesuffix('.git')}"
        if len(parts) >= 5 and parts[2] in {"blob", "raw"}:
            ref = parts[3]
            raw_path = "/".join(parts[4:])
            return [_github_raw_url(repo, ref, raw_path)]

        preferred_ref: Optional[str] = None
        base_path = ""
        if len(parts) >= 4 and parts[2] == "tree":
            preferred_ref = parts[3]
            base_path = "/".join(parts[4:])

        manifest_paths: list[str] = []
        normalized_base_path = _normalize_relative_path(base_path) if base_path else ""
        if normalized_base_path.endswith("marketplace.json"):
            manifest_paths.append(normalized_base_path)
        elif normalized_base_path:
            manifest_paths.extend(
                self._join_repo_path(normalized_base_path, manifest_filename)
                for manifest_filename in _GITHUB_MANIFEST_FILENAMES
            )
        else:
            manifest_paths.extend(_GITHUB_MANIFEST_FILENAMES)

        candidates: list[str] = []
        for ref in self._candidate_github_refs(repo, preferred_ref):
            for manifest_path in manifest_paths:
                candidates.append(_github_raw_url(repo, ref, manifest_path))
        return list(dict.fromkeys(candidates)) or [location]

    @staticmethod
    def _manifest_item_has_install_descriptor(item: dict[str, Any]) -> bool:
        descriptor = item.get("source")
        if isinstance(descriptor, (str, dict)):
            return True
        for key in ("url", "path", "repo"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return True
        return False

    def _validate_installable_manifest(
        self,
        manifest: dict[str, Any],
        *,
        source_location: str,
    ) -> None:
        items = list(self._manifest_items(manifest))
        if not items:
            return
        if any(self._manifest_item_has_install_descriptor(item) for item in items):
            return
        raise ValueError(
            "This marketplace is a discovery/index list, not an installable Claude-compatible marketplace. "
            "Its items do not include `source`, `url`, `path`, or `repo` descriptors. "
            "Add the individual plugin repos from that list through Direct Claude Repos instead. "
            f"Source: {source_location}"
        )

    @staticmethod
    def _attach_manifest_source_metadata(
        manifest: dict[str, Any],
        manifest_location: str,
    ) -> None:
        manifest["_xpdite_manifest_location"] = manifest_location
        github_repo, github_ref, github_base_path = _parse_github_manifest_context(
            manifest_location
        )
        if github_repo:
            manifest["_xpdite_github_repo"] = github_repo
        if github_ref:
            manifest["_xpdite_github_ref"] = github_ref
        manifest["_xpdite_github_base_path"] = github_base_path

    def _load_remote_manifest(self, location: str) -> tuple[dict[str, Any], str]:
        location = self._normalize_marketplace_source_location(location)
        candidates = self._candidate_remote_manifest_urls(location)
        preferred_hint = (
            "Paste a GitHub repo URL, a blob URL to `marketplace.json`, or a raw `marketplace.json` URL."
            if urlparse(location).netloc == "github.com"
            else ""
        )
        last_error: Optional[Exception] = None

        for candidate in candidates:
            try:
                response = requests.get(candidate, timeout=30)
                if response.status_code == 404 and candidate != location:
                    continue
                response.raise_for_status()
            except requests.HTTPError as exc:
                if response.status_code == 404 and candidate != location:
                    continue
                last_error = ValueError(
                    f"Failed to download marketplace manifest from {candidate}: HTTP {response.status_code}"
                )
                if candidate == location:
                    raise last_error from exc
                continue
            except requests.RequestException as exc:
                last_error = ValueError(f"Failed to download marketplace manifest from {candidate}: {exc}")
                if candidate == location:
                    raise last_error from exc
                continue

            try:
                payload = response.json()
            except ValueError as exc:
                message = (
                    "Marketplace source must resolve to a raw JSON manifest. "
                    f"The response from {candidate} was not valid JSON."
                )
                if preferred_hint:
                    message = f"{message} {preferred_hint}"
                raise ValueError(message) from exc

            if not isinstance(payload, dict):
                raise ValueError("Marketplace manifest must be a JSON object")

            manifest = dict(payload)
            self._attach_manifest_source_metadata(manifest, candidate)
            self._validate_installable_manifest(manifest, source_location=location)
            return manifest, candidate

        if last_error is not None:
            raise last_error

        if urlparse(location).netloc == "github.com":
            raise ValueError(
                "No marketplace manifest was found in that GitHub repo. "
                "Xpdite looks for `.claude-plugin/marketplace.json` or `marketplace.json` "
                "on the default, `main`, or `master` branch."
            )
        raise ValueError(f"Marketplace manifest could not be loaded from {location}")

    def _build_source_context(
        self,
        *,
        source_id: str,
        name: str,
        kind: str,
        location: str,
        manifest_location: Optional[str] = None,
        manifest: dict[str, Any],
        base_path: Optional[Path],
        github_repo: Optional[str],
        github_ref: Optional[str],
        github_base_path: str,
    ) -> SourceContext:
        return SourceContext(
            source_id=source_id,
            name=name,
            kind=kind,
            location=location,
            manifest=manifest,
            manifest_location=manifest_location or location,
            base_path=base_path,
            github_repo=github_repo,
            github_ref=github_ref,
            github_base_path=github_base_path,
        )

    def _select_direct_repo_manifest_item(
        self,
        manifest: dict[str, Any],
        label: str,
    ) -> dict[str, Any]:
        items = [item for item in self._manifest_items(manifest)]
        if not items:
            raise ValueError("Marketplace repo did not contain any installable items")
        if len(items) == 1:
            return items[0]

        root_items = [
            item
            for item in items
            if str(item.get("source") or item.get("url") or item.get("path") or "").strip() in {"", ".", "./"}
        ]
        if len(root_items) == 1:
            return root_items[0]

        normalized_label = _safe_slug(label)
        matching_items = [
            item
            for item in items
            if _safe_slug(str(item.get("id") or item.get("name") or "")) == normalized_label
        ]
        if len(matching_items) == 1:
            return matching_items[0]

        raise ValueError(
            "This repository is a full marketplace with multiple items. Add its marketplace.json as a source instead."
        )

    @staticmethod
    def _synthetic_plugin_item(plugin_manifest: dict[str, Any]) -> dict[str, Any]:
        plugin_name = str(
            plugin_manifest.get("name")
            or plugin_manifest.get("id")
            or "plugin"
        ).strip() or "plugin"
        return {
            "id": plugin_name,
            "kind": "plugin",
            "name": plugin_name,
            "description": str(plugin_manifest.get("description") or ""),
            "source": "./",
        }

    def _synthetic_skill_item(self, skill_text: str, label: str) -> dict[str, Any]:
        meta, _body = _parse_simple_frontmatter(skill_text)
        skill_name = str(meta.get("name") or meta.get("command") or label or "skill").strip() or "skill"
        return {
            "id": skill_name,
            "kind": "skill",
            "name": skill_name,
            "description": str(meta.get("description") or ""),
            "source": "./",
        }

    @staticmethod
    def _synthetic_mcp_item(label: str) -> dict[str, Any]:
        server_name = label.strip() or "mcp-server"
        return {
            "id": server_name,
            "kind": "mcp",
            "name": server_name,
            "description": "Direct MCP bundle repository.",
            "source": "./",
            "risk_level": "custom",
        }

    def _build_local_direct_repo_install_request(
        self,
        spec: DirectRepoSpec,
    ) -> dict[str, Any]:
        if spec.base_path is None:
            raise ValueError("Local repo install is missing a base path")

        manifest_path = spec.base_path / ".claude-plugin" / "marketplace.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(manifest, dict):
                raise ValueError("Marketplace repo manifest must be a JSON object")
            manifest_item = self._select_direct_repo_manifest_item(manifest, spec.label)
            source_ctx = self._build_source_context(
                source_id="direct-repo",
                name="Direct Repo",
                kind="direct_repo",
                location=str(spec.base_path),
                manifest=manifest,
                base_path=spec.base_path,
                github_repo=None,
                github_ref=None,
                github_base_path="",
            )
        else:
            plugin_manifest_path = spec.base_path / ".claude-plugin" / "plugin.json"
            skill_path = spec.base_path / "SKILL.md"
            mcp_path = spec.base_path / ".mcp.json"
            if plugin_manifest_path.exists():
                plugin_manifest = json.loads(plugin_manifest_path.read_text(encoding="utf-8"))
                manifest_item = self._synthetic_plugin_item(plugin_manifest)
            elif skill_path.exists():
                manifest_item = self._synthetic_skill_item(skill_path.read_text(encoding="utf-8"), spec.label)
            elif mcp_path.exists():
                manifest_item = self._synthetic_mcp_item(spec.label)
            else:
                raise ValueError(
                    "Direct repo install expects a Claude marketplace, plugin repo, SKILL.md, or .mcp.json"
                )
            source_ctx = self._build_source_context(
                source_id="direct-repo",
                name="Direct Repo",
                kind="direct_repo",
                location=str(spec.base_path),
                manifest={},
                base_path=spec.base_path,
                github_repo=None,
                github_ref=None,
                github_base_path="",
            )

        return {
            "source_ctx": source_ctx,
            "source_record": {
                "id": "direct-repo",
                "kind": "direct_repo",
                "name": "Direct Repo",
                "location": str(spec.base_path),
                "enabled": True,
                "builtin": False,
            },
            "manifest_item": manifest_item,
            "raw_source": {
                "kind": "direct_repo",
                "repo_input": spec.input,
                "repo_kind": spec.kind,
                "display_name": spec.label,
            },
        }

    def _build_github_direct_repo_install_request(
        self,
        spec: DirectRepoSpec,
    ) -> Optional[dict[str, Any]]:
        if not spec.github_repo:
            raise ValueError("GitHub repo install is missing a repository identifier")

        for ref in self._candidate_github_refs(spec.github_repo, spec.github_ref):
            manifest_path = self._join_repo_path(spec.github_base_path, ".claude-plugin/marketplace.json")
            manifest = self._fetch_optional_json(_github_raw_url(spec.github_repo, ref, manifest_path))
            if manifest is not None:
                manifest_item = self._select_direct_repo_manifest_item(manifest, spec.label)
                source_ctx = self._build_source_context(
                    source_id="direct-repo",
                    name="Direct Repo",
                    kind="direct_repo",
                    location=spec.input,
                    manifest=manifest,
                    base_path=None,
                    github_repo=spec.github_repo,
                    github_ref=ref,
                    github_base_path=spec.github_base_path,
                )
                return {
                    "source_ctx": source_ctx,
                    "source_record": {
                        "id": "direct-repo",
                        "kind": "direct_repo",
                        "name": "Direct Repo",
                        "location": spec.input,
                        "enabled": True,
                        "builtin": False,
                    },
                    "manifest_item": manifest_item,
                    "raw_source": {
                        "kind": "direct_repo",
                        "repo_input": spec.input,
                        "repo_kind": spec.kind,
                        "display_name": spec.label,
                        "repo": spec.github_repo,
                        "ref": ref,
                        "path": spec.github_base_path,
                    },
                }

            plugin_manifest_path = self._join_repo_path(spec.github_base_path, ".claude-plugin/plugin.json")
            plugin_manifest = self._fetch_optional_json(_github_raw_url(spec.github_repo, ref, plugin_manifest_path))
            if plugin_manifest is not None:
                manifest_item = self._synthetic_plugin_item(plugin_manifest)
            else:
                skill_path = self._join_repo_path(spec.github_base_path, "SKILL.md")
                skill_text = self._fetch_optional_text(_github_raw_url(spec.github_repo, ref, skill_path))
                if skill_text is not None:
                    manifest_item = self._synthetic_skill_item(skill_text, spec.label)
                else:
                    mcp_path = self._join_repo_path(spec.github_base_path, ".mcp.json")
                    mcp_manifest = self._fetch_optional_json(_github_raw_url(spec.github_repo, ref, mcp_path))
                    if mcp_manifest is None:
                        continue
                    manifest_item = self._synthetic_mcp_item(spec.label)

            source_ctx = self._build_source_context(
                source_id="direct-repo",
                name="Direct Repo",
                kind="direct_repo",
                location=spec.input,
                manifest={},
                base_path=None,
                github_repo=spec.github_repo,
                github_ref=ref,
                github_base_path=spec.github_base_path,
            )
            return {
                "source_ctx": source_ctx,
                "source_record": {
                    "id": "direct-repo",
                    "kind": "direct_repo",
                    "name": "Direct Repo",
                    "location": spec.input,
                    "enabled": True,
                    "builtin": False,
                },
                "manifest_item": manifest_item,
                "raw_source": {
                    "kind": "direct_repo",
                    "repo_input": spec.input,
                    "repo_kind": spec.kind,
                    "display_name": spec.label,
                    "repo": spec.github_repo,
                    "ref": ref,
                    "path": spec.github_base_path,
                },
            }

        return None

    def _build_direct_repo_install_request(
        self,
        repo_input: str,
    ) -> Optional[dict[str, Any]]:
        spec = self._parse_direct_repo_input(repo_input)
        if spec is None:
            return None
        if spec.kind == "local":
            return self._build_local_direct_repo_install_request(spec)
        return self._build_github_direct_repo_install_request(spec)

    def _install_direct_repo_request_sync(
        self,
        install_request: dict[str, Any],
        *,
        secrets: Optional[dict[str, str]] = None,
        enabled: bool = True,
        replacement_install_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return self._install_manifest_item_sync(
            source_id=None,
            source_ctx=install_request["source_ctx"],
            source_record=install_request["source_record"],
            manifest_item=install_request["manifest_item"],
            secrets=secrets or {},
            raw_source=install_request["raw_source"],
            enabled=enabled,
            replacement_install_id=replacement_install_id,
        )

    def _install_repo_sync(self, repo_input: str) -> dict[str, Any]:
        spec = self._parse_direct_repo_input(repo_input)
        if spec is None:
            raise ValueError(
                "Direct repo install expects a GitHub repo, GitHub URL, or local path with marketplace.json, plugin.json, SKILL.md, or .mcp.json"
            )

        install_request = self._build_direct_repo_install_request(repo_input)
        if install_request is None:
            raise ValueError(
                "The repo did not contain a supported Claude marketplace, plugin manifest, SKILL.md, or .mcp.json"
            )
        return self._install_direct_repo_request_sync(install_request)

    def _build_mcp_registry_manifest(self) -> dict[str, Any]:
        cursor: Optional[str] = None
        items_by_id: dict[str, dict[str, Any]] = {}

        while True:
            params: dict[str, Any] = {"limit": 100}
            if cursor:
                params["cursor"] = cursor

            response = requests.get(_MCP_REGISTRY_URL, params=params, timeout=60)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("MCP registry payload must be a JSON object")

            for record in payload.get("servers") or []:
                if not isinstance(record, dict):
                    continue
                item = self._mcp_registry_record_to_item(record)
                if item is None:
                    continue
                items_by_id[item["id"]] = item

            metadata = payload.get("metadata") or {}
            cursor = metadata.get("nextCursor")
            if not cursor:
                break

        items = sorted(items_by_id.values(), key=lambda item: item["name"].lower())
        return {
            "name": "Official MCP Registry",
            "description": "Latest official/verified MCP servers from the official MCP Registry.",
            "mcp": items,
            "metadata": {
                "api": _MCP_REGISTRY_URL,
                "count": len(items),
            },
        }

    def _mcp_registry_record_to_item(self, record: dict[str, Any]) -> Optional[dict[str, Any]]:
        server = record.get("server") or {}
        if not isinstance(server, dict):
            return None

        official_meta = (record.get("_meta") or {}).get("io.modelcontextprotocol.registry/official") or {}
        if not isinstance(official_meta, dict) or not official_meta:
            return None
        status = str(official_meta.get("status") or "active").lower()
        is_latest = official_meta.get("isLatest")
        if status != "active" or is_latest is not True:
            return None

        server_name = str(server.get("name") or "").strip()
        if not server_name:
            return None

        descriptor = self._mcp_registry_descriptor(server)
        if descriptor is None:
            return None

        item_name = str(server.get("title") or server_name)
        item: dict[str, Any] = {
            "id": server_name,
            "kind": "mcp",
            "name": item_name,
            "description": str(server.get("description") or ""),
            "source": descriptor,
            "homepage": str(server.get("websiteUrl") or (server.get("repository") or {}).get("url") or ""),
            "registry_server": server,
            "services": ["Official MCP Registry"],
            "compatibility": ["Claude Code", "Claude.ai", "Xpdite"],
        }
        package_types = sorted(
            {
                str(pkg.get("registryType") or "").lower()
                for pkg in (server.get("packages") or [])
                if isinstance(pkg, dict) and pkg.get("registryType")
            }
        )
        if package_types:
            item["package_types"] = package_types
        return item

    def _mcp_registry_descriptor(self, server: dict[str, Any]) -> Optional[dict[str, Any]]:
        server_name = str(server.get("name") or "").strip()
        display_name = str(server.get("title") or server_name)

        remote_descriptor = self._mcp_registry_remote_descriptor(server, server_name, display_name)
        if remote_descriptor is not None:
            return remote_descriptor

        packages = server.get("packages") or []
        for package in packages:
            if not isinstance(package, dict):
                continue
            transport = package.get("transport") or {}
            if str(transport.get("type") or "").lower() != "stdio":
                continue
            registry_type = str(package.get("registryType") or "").lower()
            identifier = str(package.get("identifier") or "").strip()
            version = str(package.get("version") or "").strip()
            if registry_type == "npm" and identifier:
                package_spec = f"{identifier}@{version}" if version else identifier
                return self._inline_mcp_package_descriptor(
                    runner="npx",
                    package_spec=package_spec,
                    server_name=server_name,
                    display_name=display_name,
                )
            if registry_type == "pypi" and identifier:
                package_spec = f"{identifier}=={version}" if version else identifier
                return self._inline_mcp_package_descriptor(
                    runner="uvx",
                    package_spec=package_spec,
                    server_name=server_name,
                    display_name=display_name,
                )
        return None

    def _mcp_registry_remote_descriptor(
        self,
        server: dict[str, Any],
        server_name: str,
        display_name: str,
    ) -> Optional[dict[str, Any]]:
        remotes = server.get("remotes") or []
        preferred: Optional[dict[str, Any]] = None
        fallback: Optional[dict[str, Any]] = None
        for remote in remotes:
            if not isinstance(remote, dict):
                continue
            remote_type = str(remote.get("type") or "").lower()
            if remote_type == "streamable-http":
                preferred = remote
                break
            if remote_type == "sse" and fallback is None:
                fallback = remote
        remote = preferred or fallback
        if remote is None:
            return None

        transport = "sse" if str(remote.get("type") or "").lower() == "sse" else "http"
        remote_url = self._mcp_registry_interpolate_url_template(
            str(remote.get("url") or ""),
            remote.get("variables") or {},
        )
        headers = self._mcp_registry_headers_to_placeholders(remote.get("headers") or [], server_name)
        descriptor: dict[str, Any] = {
            "source": "xpdite-inline",
            "name": server_name,
            "display_name": display_name,
            "url": remote_url,
            "transport": transport,
        }
        if headers:
            descriptor["headers"] = headers
        return descriptor

    def _mcp_registry_interpolate_url_template(
        self,
        url_template: str,
        variables: dict[str, Any],
    ) -> str:
        resolved = url_template
        for variable_name, variable_spec in variables.items():
            placeholder = _sanitize_secret_name(str(variable_name))
            default_value = ""
            if isinstance(variable_spec, dict):
                default_value = str(variable_spec.get("default") or "")
            replacement = default_value or f"${{{placeholder}}}"
            resolved = resolved.replace(f"{{{variable_name}}}", replacement)
        return resolved

    def _mcp_registry_headers_to_placeholders(
        self,
        headers: list[Any],
        server_name: str,
    ) -> dict[str, str]:
        mapped: dict[str, str] = {}
        server_key = _sanitize_secret_name(server_name)
        for header in headers:
            if not isinstance(header, dict):
                continue
            header_name = str(header.get("name") or "").strip()
            if not header_name:
                continue
            placeholder = f"{server_key}_{_sanitize_secret_name(header_name)}"
            mapped[header_name] = f"${{{placeholder}}}"
        return mapped

    def _inline_mcp_package_descriptor(
        self,
        *,
        runner: str,
        package_spec: str,
        server_name: str,
        display_name: str,
    ) -> dict[str, Any]:
        args = [package_spec]
        if runner == "npx":
            args = ["-y", package_spec]
        return {
            "source": "xpdite-inline",
            "name": server_name,
            "display_name": display_name,
            "command": runner,
            "args": args,
            "server_name": server_name,
        }

    def _manifest_items(self, manifest: dict[str, Any]) -> Iterable[dict[str, Any]]:
        if isinstance(manifest.get("items"), list):
            for item in manifest["items"]:
                if isinstance(item, dict):
                    yield item
        for key in ("plugins", "skills", "mcp", "mcp_servers", "servers"):
            value = manifest.get(key)
            if not isinstance(value, list):
                continue
            for item in value:
                if not isinstance(item, dict):
                    continue
                clone = dict(item)
                clone.setdefault("kind", "mcp" if key in {"mcp", "mcp_servers", "servers"} else key[:-1])
                yield clone

    def _get_source_context(self, source_id: str) -> SourceContext:
        source = self.get_source(source_id)
        manifest = source.get("manifest")
        if not isinstance(manifest, dict):
            source = self._refresh_source_sync(source_id)
            manifest = source.get("manifest")
        if not isinstance(manifest, dict):
            raise ValueError(f"Marketplace source '{source_id}' has no manifest")

        location = self._normalize_marketplace_source_location(str(source["location"]))
        manifest_location = _normalize_url_like_value(
            str(manifest.get("_xpdite_manifest_location") or location)
        )
        base_path: Optional[Path] = None
        github_repo = str(manifest.get("_xpdite_github_repo") or "").strip() or None
        github_ref = str(manifest.get("_xpdite_github_ref") or "").strip() or None
        github_base_path = str(manifest.get("_xpdite_github_base_path") or "").strip()
        if github_repo or _is_http_url(manifest_location):
            if not github_repo:
                github_repo, github_ref, github_base_path = _parse_github_manifest_context(
                    manifest_location
                )
        elif location.startswith(("npx:", "uvx:", "builtin://")):
            base_path = None
        else:
            _manifest_path, base_path = self._resolve_local_manifest_path(location)

        return self._build_source_context(
            source_id=source["id"],
            name=source["name"],
            kind=source["kind"],
            location=location,
            manifest_location=manifest_location,
            manifest=manifest,
            base_path=base_path,
            github_repo=github_repo,
            github_ref=github_ref,
            github_base_path=github_base_path,
        )

    def _normalize_catalog_item(self, source: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
        kind = self._normalize_catalog_kind(source, item)
        manifest_item_id = str(item.get("id") or item.get("name") or uuid.uuid4().hex)
        display_name = str(item.get("name") or item.get("title") or manifest_item_id)
        description = str(item.get("description") or item.get("summary") or "")
        required_secrets = self._collect_required_secrets(item)
        components = self._estimate_component_counts(source, kind, item)
        compatibility_warnings = self._compatibility_warnings(kind, item)

        return {
            "source_id": source["id"],
            "manifest_item_id": manifest_item_id,
            "kind": kind,
            "display_name": display_name,
            "description": description,
            "required_secrets": required_secrets,
            "component_counts": components,
            "compatibility_warnings": compatibility_warnings,
            "raw": item,
        }

    def _normalize_catalog_kind(
        self, source: dict[str, Any], item: dict[str, Any]
    ) -> MarketplaceItemKind:
        return _guess_item_kind(item)

    @staticmethod
    def _descriptor_text(descriptor: Any) -> str:
        if isinstance(descriptor, str):
            return descriptor.lower()
        if isinstance(descriptor, dict):
            try:
                return json.dumps(descriptor, ensure_ascii=False).lower()
            except Exception:
                return str(descriptor).lower()
        return str(descriptor).lower()

    def _marketplace_plugin_root(self, manifest: dict[str, Any]) -> str:
        plugin_root = str(
            (manifest.get("metadata") or {}).get("pluginRoot")
            or manifest.get("pluginRoot")
            or ""
        ).strip()
        if not plugin_root:
            return ""
        return _normalize_relative_path(plugin_root)

    def _candidate_marketplace_relative_paths(
        self,
        source_ctx: SourceContext,
        descriptor: str,
    ) -> list[str]:
        normalized_relative = _normalize_relative_path(descriptor)
        candidates: list[str] = []
        plugin_root = self._marketplace_plugin_root(source_ctx.manifest)
        if plugin_root:
            if not normalized_relative:
                candidates.append(plugin_root)
            elif (
                normalized_relative != plugin_root
                and not normalized_relative.startswith(f"{plugin_root}/")
            ):
                candidates.append(self._join_repo_path(plugin_root, normalized_relative))
        candidates.append(normalized_relative)
        return list(dict.fromkeys(candidates))

    def _install_item_sync(
        self,
        source_id: str,
        manifest_item_id: str,
        secrets: dict[str, str],
        *,
        enabled: bool = True,
        replacement_install_id: Optional[str] = None,
    ) -> dict[str, Any]:
        source_ctx = self._get_source_context(source_id)
        manifest_item = next(
            (
                item
                for item in self._manifest_items(source_ctx.manifest)
                if str(item.get("id") or item.get("name") or "") == manifest_item_id
            ),
            None,
        )
        if manifest_item is None:
            raise ValueError(f"Marketplace item '{manifest_item_id}' not found")

        return self._install_manifest_item_sync(
            source_id=source_id,
            source_ctx=source_ctx,
            source_record=self.get_source(source_id),
            manifest_item=manifest_item,
            secrets=secrets,
            raw_source=manifest_item,
            enabled=enabled,
            replacement_install_id=replacement_install_id,
        )

    def _install_package_sync(
        self,
        runner: str,
        package_input: str,
        *,
        secrets_override: Optional[dict[str, str]] = None,
        enabled: bool = True,
        replacement_install_id: Optional[str] = None,
    ) -> dict[str, Any]:
        direct_repo_request = self._build_direct_repo_install_request(package_input)
        if direct_repo_request is not None:
            return self._install_direct_repo_request_sync(
                direct_repo_request,
                secrets=secrets_override or {},
                enabled=enabled,
                replacement_install_id=replacement_install_id,
            )

        package_info = self._parse_package_command(runner, package_input)
        direct_repo_request = self._build_direct_repo_install_request(package_info["package_spec"])
        if direct_repo_request is not None:
            return self._install_direct_repo_request_sync(
                direct_repo_request,
                secrets=secrets_override or {},
                enabled=enabled,
                replacement_install_id=replacement_install_id,
            )

        manifest_item = {
            "id": package_info["item_id"],
            "kind": "mcp",
            "name": package_info["display_name"],
            "description": f"Direct MCP package installed via {package_info['runner']}.",
            "source": package_info["descriptor"],
            "package_manager": package_info["runner"],
            "package_command": package_info["command_input"],
            "risk_level": "custom",
        }
        raw_source = {
            "kind": "direct_package",
            "runner": package_info["runner"],
            "package_command": package_info["command_input"],
            "package_spec": package_info["package_spec"],
            "display_name": package_info["display_name"],
            **({"env": package_info["env"]} if package_info.get("env") else {}),
            "auth_instructions": (
                "Direct MCP packages can reference secrets with placeholder names "
                "such as API_KEY "
                "in args or env values. Xpdite will prompt for any referenced secrets after install."
            ),
        }
        install_secrets = dict(package_info.get("initial_secrets") or {})
        if secrets_override:
            install_secrets.update(secrets_override)
        return self._install_direct_package_request_sync(
            {
                "manifest_item": manifest_item,
                "raw_source": raw_source,
            },
            secrets=install_secrets,
            enabled=enabled,
            replacement_install_id=replacement_install_id,
        )

    def _install_direct_package_request_sync(
        self,
        install_request: dict[str, Any],
        *,
        secrets: Optional[dict[str, str]] = None,
        enabled: bool = True,
        replacement_install_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return self._install_manifest_item_sync(
            source_id=None,
            source_ctx=None,
            source_record={
                "id": "direct-package",
                "kind": "generated_manifest",
                "name": "Direct Package",
                "location": "",
                "enabled": True,
                "builtin": False,
            },
            manifest_item=install_request["manifest_item"],
            secrets=secrets or {},
            raw_source=install_request["raw_source"],
            enabled=enabled,
            replacement_install_id=replacement_install_id,
        )

    def _reload_skill_cache(self) -> None:
        from ..skills_runtime.skills import get_skill_manager

        get_skill_manager().reload()

    def _install_manifest_item_sync(
        self,
        *,
        source_id: Optional[str],
        source_ctx: Optional[SourceContext],
        source_record: dict[str, Any],
        manifest_item: dict[str, Any],
        secrets: dict[str, str],
        raw_source: dict[str, Any],
        enabled: bool = True,
        replacement_install_id: Optional[str] = None,
    ) -> dict[str, Any]:
        normalized = self._normalize_catalog_item(source_record, manifest_item)
        manifest_item_id = normalized["manifest_item_id"]
        kind = normalized["kind"]
        install_id = str(uuid.uuid4())
        storage_manifest_item_id = (
            f"{manifest_item_id}__replacement__{install_id}"
            if replacement_install_id and source_id
            else manifest_item_id
        )
        install_root = _install_root_for(kind, install_id)
        install_root.mkdir(parents=True, exist_ok=True)
        persisted_secret_names: list[str] = []
        inserted_install = False
        try:
            descriptor = manifest_item.get("source") or manifest_item.get("url") or manifest_item.get("path") or manifest_item
            resolved_ref = self._materialize_install_root(source_ctx, install_root, descriptor, kind)
            component_manifest = self._inspect_install_root(
                kind,
                install_root,
                manifest_item,
                install_id,
            )
            canonical_id = self._resolve_canonical_id(kind, component_manifest, normalized["display_name"])
            conflict_exclusion = replacement_install_id or install_id
            if kind in {"skill", "plugin"}:
                self._ensure_no_skill_conflicts(conflict_exclusion, canonical_id)
            if kind == "plugin":
                self._ensure_no_plugin_skill_conflicts(conflict_exclusion, canonical_id, component_manifest)

            required_secrets = normalized["required_secrets"]
            if required_secrets:
                for secret_name in required_secrets:
                    secret_value = secrets.get(secret_name, "")
                    if secret_value:
                        encrypted = key_manager.encrypt_key(secret_value)
                        db.set_setting(f"marketplace_secret:{install_id}:{secret_name}", encrypted)
                        persisted_secret_names.append(secret_name)

            provided_secret_names = {
                name
                for name, value in secrets.items()
                if isinstance(name, str) and str(name).strip() and value not in (None, "")
            }
            status = self._resolve_install_status(
                {
                    "id": install_id,
                    "enabled": enabled,
                    "install_root": str(install_root),
                    "component_manifest": component_manifest,
                },
                enabled=enabled,
                provided_secret_names=provided_secret_names,
                secrets_override=secrets,
            )

            now = _utc_now()
            with db._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO marketplace_installs (
                        id, item_kind, source_id, manifest_item_id, display_name,
                        canonical_id, install_root, resolved_ref, status, enabled,
                        component_manifest_json, raw_source_json, last_error,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        install_id,
                        kind,
                        source_id,
                        storage_manifest_item_id,
                        normalized["display_name"],
                        canonical_id,
                        str(install_root),
                        resolved_ref,
                        status,
                        1 if enabled else 0,
                        _json_dumps(component_manifest),
                        _json_dumps(raw_source),
                        None,
                        now,
                        now,
                    ),
                )
                conn.commit()
            inserted_install = True

            install = self.get_install(install_id)
            if kind in {"skill", "plugin"}:
                self._reload_skill_cache()
            return install
        except Exception:
            if inserted_install:
                self._delete_install_row_sync(install_id)
            self._delete_install_secrets_sync(install_id, persisted_secret_names)
            self._delete_install_files_sync({"install_root": str(install_root)})
            raise

    def _uninstall_sync(self, install_id: str) -> dict[str, Any]:
        install = self.get_install(install_id)
        self._remove_install_artifacts_sync(install)
        return {"success": True, "install_id": install_id}

    def _remove_install_artifacts_sync(self, install: dict[str, Any]) -> None:
        self._delete_install_files_sync(install)
        self._delete_install_row_sync(str(install["id"]))
        self._delete_install_secrets_sync(
            str(install["id"]),
            self._install_secret_names(
                install.get("component_manifest") or {},
                install.get("raw_source") or {},
            ),
        )
        if install["item_kind"] in {"skill", "plugin"}:
            self._reload_skill_cache()

    def _finalize_replacement_install_sync(self, install_id: str, manifest_item_id: str) -> None:
        with db._connect() as conn:
            conn.execute(
                """
                UPDATE marketplace_installs
                SET manifest_item_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (manifest_item_id, _utc_now(), install_id),
            )
            conn.commit()

    def _delete_install_files_sync(self, install: dict[str, Any]) -> None:
        install_root = Path(install["install_root"])
        if install_root.exists():
            shutil.rmtree(install_root, ignore_errors=True)
        install_id = str(install.get("id") or "")
        if install_id:
            plugin_data_dir = MARKETPLACE_PLUGIN_DATA_DIR / install_id
            if plugin_data_dir.exists():
                shutil.rmtree(plugin_data_dir, ignore_errors=True)

    def _delete_install_row_sync(self, install_id: str) -> None:
        with db._connect() as conn:
            conn.execute("DELETE FROM marketplace_installs WHERE id = ?", (install_id,))
            conn.commit()

    def _delete_install_secrets_sync(self, install_id: str, secret_names: Iterable[str]) -> None:
        for secret_name in secret_names:
            db.delete_setting(f"marketplace_secret:{install_id}:{secret_name}")

    def _set_install_runtime_state_sync(
        self,
        install_id: str,
        *,
        status: str,
        last_error: Optional[str],
    ) -> dict[str, Any]:
        with db._connect() as conn:
            conn.execute(
                """
                UPDATE marketplace_installs
                SET status = ?, last_error = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, last_error, _utc_now(), install_id),
            )
            conn.commit()
        return self.get_install(install_id)

    def _friendly_runtime_error(self, install: dict[str, Any], exc: Exception) -> str:
        message = str(exc).strip()
        if "TaskGroup" in message or "JSONRPC" in message or "valid session" in message:
            return (
                "This command did not behave like an MCP stdio server. "
                "It likely printed normal CLI output, requires a setup/auth flow, or exited before the MCP handshake completed."
            )
        return message or "The MCP server failed to start correctly."

    def _resolve_install_status(
        self,
        install: dict[str, Any],
        *,
        enabled: Optional[bool] = None,
        provided_secret_names: Optional[set[str]] = None,
        secrets_override: Optional[dict[str, str]] = None,
        hooks_runtime: Optional[Any] = None,
    ) -> str:
        is_enabled = install["enabled"] if enabled is None else enabled
        if not is_enabled:
            return "disabled"

        component_manifest = install.get("component_manifest") or {}
        if provided_secret_names is None:
            install_id = str(install.get("id") or "")
            provided_secret_names = (
                set(self.get_install_secrets(install_id)) if install_id else set()
            )

        if self._missing_hook_secret_names(
            component_manifest,
            provided_secret_names=provided_secret_names,
        ):
            return "manual_auth_required"

        if self._component_has_mcp_runtime(component_manifest):
            if secrets_override is not None:
                runtimes = [
                    self._build_runtime_from_mcp_manifest(
                        str(install.get("id") or ""),
                        mcp_manifest,
                        install_root=install.get("install_root"),
                        secrets_override=secrets_override,
                        config_index=index,
                    )
                    for index, mcp_manifest in enumerate(
                        self._component_runtime_manifests(component_manifest)
                    )
                ]
            else:
                runtimes = self.build_runtime_server_configs(
                    {
                        **install,
                        "enabled": True,
                    }
                )
            return (
                "manual_auth_required"
                if any(runtime.get("manual_auth_required") for runtime in runtimes)
                else "connected"
            )

        if hooks_runtime is not None:
            hook_summary = hooks_runtime.build_runtime_summary(install)
            if hook_summary.get("has_hooks"):
                return "connected"

        return "installed"

    def _set_install_enabled_sync(self, install_id: str, enabled: bool) -> dict[str, Any]:
        install = self.get_install(install_id)
        status = self._resolve_install_status(install, enabled=enabled)

        with db._connect() as conn:
            conn.execute(
                """
                UPDATE marketplace_installs
                SET enabled = ?, status = ?, updated_at = ?
                WHERE id = ?
                """,
                (1 if enabled else 0, status, _utc_now(), install_id),
            )
            conn.commit()
        updated = self.get_install(install_id)
        if updated["item_kind"] in {"skill", "plugin"}:
            self._reload_skill_cache()
        return updated

    def _materialize_install_root(
        self,
        source_ctx: Optional[SourceContext],
        install_root: Path,
        descriptor: Any,
        kind: MarketplaceItemKind,
    ) -> str:
        if isinstance(descriptor, str):
            if source_ctx is None:
                raise ValueError("Relative or URL marketplace descriptors require a source context")
            return self._materialize_from_relative_or_url(source_ctx, install_root, descriptor, kind)
        if not isinstance(descriptor, dict):
            raise ValueError("Unsupported marketplace descriptor")

        source_kind = str(descriptor.get("source") or descriptor.get("type") or "").strip().lower()
        if source_kind == "xpdite-inline":
            (install_root / ".mcp.json").write_text(_json_dumps(descriptor), encoding="utf-8")
            return "builtin://xpdite-inline"
        if source_kind == "url":
            url = str(descriptor["url"])
            github_repo = _parse_github_repo_url(url)
            if github_repo:
                ref = str(descriptor.get("sha") or descriptor.get("ref") or "main")
                path = _normalize_relative_path(str(descriptor.get("path") or ""))
                return self._download_github_subdir(github_repo, ref, path, install_root)
            return self._download_url_to_root(url, install_root)
        if source_kind == "github":
            repo = str(descriptor["repo"])
            ref = str(descriptor.get("ref") or "main")
            path = _normalize_relative_path(str(descriptor.get("path") or ""))
            return self._download_github_subdir(repo, ref, path, install_root)
        if source_kind == "git-subdir":
            repo_url = str(descriptor.get("url") or "")
            repo, ref, path = self._parse_git_subdir_descriptor(repo_url, descriptor)
            return self._download_github_subdir(repo, ref, path, install_root)

        if "url" in descriptor:
            url = str(descriptor["url"])
            github_repo = _parse_github_repo_url(url)
            if github_repo:
                ref = str(descriptor.get("sha") or descriptor.get("ref") or "main")
                path = _normalize_relative_path(str(descriptor.get("path") or ""))
                return self._download_github_subdir(github_repo, ref, path, install_root)
            return self._download_url_to_root(url, install_root)
        if "repo" in descriptor:
            repo = str(descriptor["repo"])
            ref = str(descriptor.get("ref") or "main")
            path = _normalize_relative_path(str(descriptor.get("path") or ""))
            return self._download_github_subdir(repo, ref, path, install_root)

        raise ValueError("Unsupported marketplace descriptor")

    def _materialize_from_relative_or_url(
        self,
        source_ctx: SourceContext,
        install_root: Path,
        descriptor: str,
        kind: MarketplaceItemKind,
    ) -> str:
        descriptor = _normalize_url_like_value(descriptor)
        descriptor = descriptor.strip()
        if _is_http_url(descriptor):
            return self._download_url_to_root(descriptor, install_root)

        if source_ctx.base_path is not None:
            local_targets = [
                (source_ctx.base_path / candidate).resolve()
                for candidate in self._candidate_marketplace_relative_paths(source_ctx, descriptor)
            ]
            for target in local_targets:
                if target.exists():
                    self._copy_path_to_root(target, install_root)
                    return str(target)
            attempted = ", ".join(str(target) for target in local_targets)
            raise ValueError(f"Marketplace path not found. Attempted: {attempted}")

        if source_ctx.github_repo and source_ctx.github_ref:
            candidate_paths = [
                "/".join(part for part in [source_ctx.github_base_path, candidate] if part)
                for candidate in self._candidate_marketplace_relative_paths(source_ctx, descriptor)
            ]
            last_error: Optional[ValueError] = None
            for repo_path in list(dict.fromkeys(candidate_paths)):
                try:
                    return self._download_github_subdir(
                        source_ctx.github_repo,
                        source_ctx.github_ref,
                        repo_path,
                        install_root,
                    )
                except ValueError as exc:
                    last_error = exc
                    continue
            if last_error is not None:
                raise last_error

        raise ValueError(
            "Relative marketplace descriptors are only supported for local or GitHub-backed manifests"
        )

    def _copy_path_to_root(self, source_path: Path, install_root: Path) -> None:
        if source_path.is_dir():
            for child in source_path.iterdir():
                destination = install_root / child.name
                if child.is_dir():
                    shutil.copytree(child, destination, dirs_exist_ok=True)
                else:
                    shutil.copy2(child, destination)
            return
        shutil.copy2(source_path, install_root / source_path.name)

    def _download_url_to_root(self, url: str, install_root: Path) -> str:
        try:
            response = requests.get(url, timeout=60)
            response.raise_for_status()
        except requests.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else "unknown"
            raise ValueError(
                f"Failed to download marketplace content from {url}: HTTP {status_code}"
            ) from exc
        except requests.RequestException as exc:
            raise ValueError(f"Failed to download marketplace content from {url}: {exc}") from exc
        filename = os.path.basename(urlparse(url).path) or "download"
        destination = install_root / filename
        destination.write_bytes(response.content)
        if filename.lower().endswith(".zip"):
            try:
                self._extract_zip_bytes(response.content, install_root)
            except zipfile.BadZipFile as exc:
                raise ValueError(
                    f"Downloaded marketplace archive from {url} was not a valid zip file"
                ) from exc
            destination.unlink(missing_ok=True)
        return url

    def _parse_git_subdir_descriptor(self, repo_url: str, descriptor: dict[str, Any]) -> tuple[str, str, str]:
        parsed = urlparse(repo_url)
        parts = [part for part in parsed.path.split("/") if part]
        if parsed.netloc != "github.com" or len(parts) < 2:
            raise ValueError("Only GitHub git-subdir descriptors are supported in v1")
        repo = f"{parts[0]}/{parts[1].removesuffix('.git')}"
        ref = str(descriptor.get("ref") or "main")
        path = _normalize_relative_path(str(descriptor.get("path") or ""))
        return repo, ref, path

    def _download_github_subdir(self, repo: str, ref: str, subdir: str, install_root: Path) -> str:
        archive_url = _github_archive_url(repo, ref)
        try:
            response = requests.get(archive_url, timeout=120)
            response.raise_for_status()
        except requests.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else "unknown"
            if status_code == 404:
                raise ValueError(
                    f"Failed to download GitHub archive for {repo}@{ref}. "
                    "The referenced branch, tag, or commit could not be found."
                ) from exc
            raise ValueError(
                f"Failed to download GitHub archive for {repo}@{ref}: HTTP {status_code}"
            ) from exc
        except requests.RequestException as exc:
            raise ValueError(
                f"Failed to download GitHub archive for {repo}@{ref}: {exc}"
            ) from exc

        try:
            self._extract_zip_subdir(response.content, install_root, subdir)
        except zipfile.BadZipFile as exc:
            raise ValueError(
                f"GitHub archive for {repo}@{ref} was not a valid zip file"
            ) from exc
        except ValueError as exc:
            raise ValueError(
                f"{exc}. Repository: {repo}@{ref}"
            ) from exc
        return f"github://{repo}@{ref}/{subdir}"

    @staticmethod
    def _safe_install_destination(install_root: Path, relative_path: str) -> Path:
        root_resolved = install_root.resolve()
        destination = (install_root / relative_path).resolve()
        if destination != root_resolved and root_resolved not in destination.parents:
            raise ValueError(f"Archive entry escaped install root: {relative_path}")
        return destination

    def _extract_zip_bytes(self, payload: bytes, install_root: Path) -> None:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            for member in archive.infolist():
                normalized_member = _normalize_archive_member_path(member.filename)
                if not normalized_member:
                    continue
                destination = self._safe_install_destination(install_root, normalized_member)
                if member.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as src, open(destination, "wb") as dst:
                    shutil.copyfileobj(src, dst)

    def _extract_zip_subdir(self, payload: bytes, install_root: Path, subdir: str) -> None:
        normalized_subdir = _normalize_relative_path(subdir) if subdir else ""
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = archive.namelist()
            root_prefix = _normalize_archive_member_path(names[0]).split("/")[0] if names else ""
            prefix = f"{root_prefix}/{normalized_subdir}".rstrip("/")
            matched = False
            for member in names:
                normalized_member = _normalize_archive_member_path(member).rstrip("/")
                if not normalized_member.startswith(prefix):
                    continue
                matched = True
                relative = normalized_member[len(prefix):].lstrip("/")
                if not relative:
                    continue
                destination = self._safe_install_destination(install_root, relative)
                if member.endswith("/"):
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as src, open(destination, "wb") as dst:
                    shutil.copyfileobj(src, dst)
            if not matched:
                raise ValueError(f"GitHub archive did not contain subdirectory '{normalized_subdir}'")

    def _inspect_install_root(
        self,
        kind: MarketplaceItemKind,
        install_root: Path,
        manifest_item: dict[str, Any],
        install_id: str,
    ) -> dict[str, Any]:
        if kind == "plugin":
            plugin_manifest_path = install_root / ".claude-plugin" / "plugin.json"
            if not plugin_manifest_path.exists():
                listed_skills = manifest_item.get("skills")
                if not isinstance(listed_skills, list) or not listed_skills:
                    raise ValueError("Installed plugin is missing .claude-plugin/plugin.json")
                plugin_manifest = {
                    "name": manifest_item.get("name") or manifest_item.get("id") or "skill-bundle",
                    "id": manifest_item.get("id") or manifest_item.get("name") or "skill-bundle",
                    "version": manifest_item.get("version") or "1.0.0",
                    "description": manifest_item.get("description") or "",
                    "synthetic": True,
                }
                skills = self._discover_listed_skills(install_root, listed_skills)
                if not skills:
                    raise ValueError("Installed skill bundle did not contain any SKILL.md files")
            else:
                plugin_manifest = json.loads(plugin_manifest_path.read_text(encoding="utf-8"))
                skills = self._discover_native_skills(install_root / "skills")
            commands = self._discover_plugin_commands(install_root / "commands")
            mcp_manifest_path = install_root / ".mcp.json"
            raw_mcp_payload = (
                json.loads(mcp_manifest_path.read_text(encoding="utf-8"))
                if mcp_manifest_path.exists()
                else None
            )
            mcp_manifest, mcp_manifests = self._normalize_mcp_payload(raw_mcp_payload)
            from ..hooks_runtime import get_hooks_runtime

            normalized_hooks = get_hooks_runtime().normalize_plugin_hooks(
                plugin_manifest,
                install_root=install_root,
                install_id=install_id,
            )
            compatibility_warnings = self._plugin_component_compatibility_warnings(
                plugin_manifest,
                skills=skills,
                commands=commands,
                mcp_manifests=mcp_manifests,
                hooks=normalized_hooks,
            )
            return {
                "plugin_manifest": plugin_manifest,
                "skills": skills,
                "commands": commands,
                "mcp_manifest": mcp_manifest,
                "mcp_manifests": mcp_manifests,
                "hooks": normalized_hooks,
                "compatibility_warnings": compatibility_warnings,
                "required_secrets": self._collect_required_secrets(
                    manifest_item,
                    plugin_manifest,
                    raw_mcp_payload,
                    mcp_manifests,
                    normalized_hooks,
                ),
            }

        if kind == "skill":
            skill_file = self._find_first_file(install_root, "SKILL.md")
            if skill_file is None:
                raise ValueError("Installed skill is missing SKILL.md")
            meta, _body = _parse_simple_frontmatter(skill_file.read_text(encoding="utf-8"))
            return {
                "skill_manifest": meta,
                "skill_path": str(skill_file),
                "required_secrets": self._collect_required_secrets(manifest_item),
            }

        mcp_manifest_path = install_root / ".mcp.json"
        if not mcp_manifest_path.exists():
            mcp_manifest_path = self._find_first_file(install_root, ".mcp.json")
        if mcp_manifest_path is None:
            raise ValueError("Installed MCP bundle is missing .mcp.json")
        raw_mcp_payload = json.loads(mcp_manifest_path.read_text(encoding="utf-8"))
        mcp_manifest, mcp_manifests = self._normalize_mcp_payload(raw_mcp_payload)
        return {
            "mcp_manifest": mcp_manifest,
            "mcp_manifests": mcp_manifests,
            "required_secrets": self._collect_required_secrets(manifest_item, raw_mcp_payload, mcp_manifests),
        }

    def _normalize_mcp_payload(
        self,
        payload: Any,
    ) -> tuple[Optional[dict[str, Any]], list[dict[str, Any]]]:
        if not isinstance(payload, dict):
            return None, []

        def _to_manifest_list(server_map: dict[str, Any]) -> list[dict[str, Any]]:
            manifests: list[dict[str, Any]] = []
            for server_name, config in server_map.items():
                if not isinstance(config, dict):
                    continue
                manifest = dict(config)
                manifest.setdefault("name", str(server_name))
                manifests.append(manifest)
            return manifests

        for server_map_key in ("mcpServers", "servers"):
            server_map = payload.get(server_map_key)
            if isinstance(server_map, dict):
                manifests = _to_manifest_list(server_map)
                if not manifests:
                    return None, []
                return manifests[0], manifests

        runtime_keys = {"command", "args", "url", "http_url", "sse_url", "transport", "env", "headers"}
        if not any(key in payload for key in runtime_keys | {"name", "display_name", "server"}):
            named_manifests = _to_manifest_list(payload)
            if named_manifests and all(
                any(key in manifest for key in runtime_keys) for manifest in named_manifests
            ):
                return named_manifests[0], named_manifests

        return payload, [payload]

    def _find_first_file(self, root: Path, filename: str) -> Optional[Path]:
        for path in root.rglob(filename):
            if path.is_file():
                return path
        return None

    def _discover_listed_skills(
        self, install_root: Path, listed_skills: list[Any]
    ) -> list[dict[str, Any]]:
        skills: list[dict[str, Any]] = []
        for entry in listed_skills:
            if not isinstance(entry, str):
                continue
            relative = entry.strip().lstrip("./")
            if not relative:
                continue
            target = (install_root / relative).resolve()
            if not str(target).startswith(str(install_root.resolve())):
                continue
            if target.is_dir():
                skill_file = target / "SKILL.md"
            elif target.is_file() and target.name == "SKILL.md":
                skill_file = target
            else:
                continue
            if not skill_file.exists():
                continue
            skills.append(self._read_skill_entry(skill_file))
        return skills

    def _discover_native_skills(self, root: Path) -> list[dict[str, Any]]:
        if not root.exists():
            return []
        skills: list[dict[str, Any]] = []
        for path in root.rglob("SKILL.md"):
            skills.append(self._read_skill_entry(path))
        return skills

    def _discover_plugin_commands(self, root: Path) -> list[dict[str, Any]]:
        if not root.exists():
            return []
        commands: list[dict[str, Any]] = []
        for path in sorted(root.rglob("*.md")):
            commands.append(self._read_command_entry(path))
        return commands

    def _plugin_component_compatibility_warnings(
        self,
        plugin_manifest: dict[str, Any],
        *,
        skills: list[dict[str, Any]],
        commands: list[dict[str, Any]],
        mcp_manifests: list[dict[str, Any]],
        hooks: dict[str, Any],
    ) -> list[str]:
        warnings: list[str] = []
        warnings.extend(
            warning
            for warning in list(hooks.get("compatibility_warnings") or [])
            if isinstance(warning, str) and warning.strip()
        )
        if plugin_manifest.get("agents"):
            warnings.append("Claude plugin agents are not yet surfaced in Xpdite.")
        if plugin_manifest.get("outputStyles") or plugin_manifest.get("output_styles"):
            warnings.append("Claude output styles are preserved in metadata but not yet surfaced in Xpdite.")
        if (
            not skills
            and not commands
            and not mcp_manifests
            and int(hooks.get("handler_count") or 0) == 0
        ):
            warnings.append(
                "This plugin does not expose slash commands, skills, MCP servers, or hooks that Xpdite can run."
            )
        return list(dict.fromkeys(warnings))

    def _read_skill_entry(self, path: Path) -> dict[str, Any]:
        meta, _body = _parse_simple_frontmatter(path.read_text(encoding="utf-8"))
        name = str(meta.get("name") or path.parent.name)
        slash_command = str(meta.get("slash_command") or meta.get("command") or name)
        return {
            "name": name,
            "slash_command": slash_command,
            "description": str(meta.get("description") or ""),
            "path": str(path),
            "metadata": meta,
        }

    def _read_command_entry(self, path: Path) -> dict[str, Any]:
        meta, _body = _parse_simple_frontmatter(path.read_text(encoding="utf-8"))
        command_name = str(meta.get("slash_command") or meta.get("command") or path.stem)
        return {
            "name": command_name,
            "slash_command": command_name,
            "description": str(meta.get("description") or ""),
            "path": str(path),
            "metadata": meta,
            "kind": "command",
        }

    def _resolve_canonical_id(
        self,
        kind: MarketplaceItemKind,
        component_manifest: dict[str, Any],
        display_name: str,
    ) -> Optional[str]:
        if kind == "plugin":
            plugin_manifest = component_manifest.get("plugin_manifest") or {}
            candidates = [
                plugin_manifest.get("slash_command"),
                plugin_manifest.get("command"),
                plugin_manifest.get("canonical_id"),
                plugin_manifest.get("id"),
                plugin_manifest.get("name"),
                display_name,
            ]
        elif kind == "skill":
            skill_manifest = component_manifest.get("skill_manifest") or {}
            candidates = [
                skill_manifest.get("slash_command"),
                skill_manifest.get("command"),
                skill_manifest.get("canonical_id"),
                skill_manifest.get("name"),
                display_name,
            ]
        else:
            mcp_manifest = component_manifest.get("mcp_manifest") or {}
            candidates = [
                mcp_manifest.get("name"),
                mcp_manifest.get("server"),
                display_name,
            ]

        for candidate in candidates:
            canonical = str(candidate or "").strip()
            if not canonical:
                continue
            if kind not in {"plugin", "skill"}:
                return canonical
            if _CANONICAL_SKILL_RE.match(canonical):
                return canonical

        if kind in {"plugin", "skill"}:
            invalid = next((str(candidate or "").strip() for candidate in candidates if str(candidate or "").strip()), "")
            raise ValueError(
                f"Invalid canonical skill id '{invalid}'. Expected segment(:segment)* with [A-Za-z0-9_-]+."
            )
        return None

    def _ensure_no_skill_conflicts(self, install_id: str, canonical_id: Optional[str]) -> None:
        if not canonical_id:
            return
        from ..skills_runtime.skills import get_skill_manager

        skill_manager = get_skill_manager()
        skill = skill_manager.get_skill_by_slash_command(canonical_id)
        if skill is not None:
            raise ValueError(f"Slash command conflict: /{canonical_id} is already installed")

        existing_commands = self._collect_installed_marketplace_commands(exclude_install_id=install_id)
        if canonical_id in existing_commands:
            raise ValueError(f"Slash command conflict: /{canonical_id} is already installed")

        for install in self.list_installs():
            if install["id"] == install_id:
                continue
            if install.get("canonical_id") == canonical_id:
                raise ValueError(f"Marketplace item conflict: '{canonical_id}' is already installed")

    def _collect_installed_marketplace_commands(self, *, exclude_install_id: Optional[str] = None) -> set[str]:
        commands: set[str] = set()
        for install in self.list_installs():
            if exclude_install_id and install["id"] == exclude_install_id:
                continue
            component_manifest = install.get("component_manifest") or {}
            if install["item_kind"] == "skill" and install.get("canonical_id"):
                commands.add(str(install["canonical_id"]))

            plugin_id = str(
                install.get("canonical_id")
                or (component_manifest.get("plugin_manifest") or {}).get("name")
                or install.get("display_name")
                or ""
            ).strip()
            for item in component_manifest.get("skills") or []:
                metadata = item.get("metadata") or {}
                local_command = str(
                    item.get("slash_command")
                    or metadata.get("slash_command")
                    or metadata.get("command")
                    or item.get("name")
                    or ""
                ).strip()
                if not local_command:
                    continue
                commands.add(local_command if ":" in local_command else f"{plugin_id}:{local_command}")
            for item in component_manifest.get("commands") or []:
                metadata = item.get("metadata") or {}
                command = str(
                    item.get("slash_command")
                    or metadata.get("slash_command")
                    or metadata.get("command")
                    or item.get("name")
                    or ""
                ).strip()
                if command:
                    commands.add(command)
        return commands

    def _ensure_no_plugin_skill_conflicts(
        self,
        install_id: str,
        plugin_id: Optional[str],
        component_manifest: dict[str, Any],
    ) -> None:
        if not plugin_id:
            return
        from ..skills_runtime.skills import get_skill_manager

        skill_manager = get_skill_manager()
        existing_commands = self._collect_installed_marketplace_commands(exclude_install_id=install_id)
        for item in component_manifest.get("skills") or []:
            metadata = item.get("metadata") or {}
            local_command = str(
                item.get("slash_command")
                or metadata.get("slash_command")
                or metadata.get("command")
                or item.get("name")
                or ""
            ).strip()
            if not local_command:
                continue
            full_command = local_command if ":" in local_command else f"{plugin_id}:{local_command}"
            if skill_manager.get_skill_by_slash_command(full_command) is not None:
                raise ValueError(f"Slash command conflict: /{full_command} is already installed")
            if full_command in existing_commands:
                raise ValueError(f"Slash command conflict: /{full_command} is already installed")
        for item in component_manifest.get("commands") or []:
            metadata = item.get("metadata") or {}
            command = str(
                item.get("slash_command")
                or metadata.get("slash_command")
                or metadata.get("command")
                or item.get("name")
                or ""
            ).strip()
            if not command:
                continue
            if skill_manager.get_skill_by_slash_command(command) is not None:
                raise ValueError(f"Slash command conflict: /{command} is already installed")
            if command in existing_commands:
                raise ValueError(f"Slash command conflict: /{command} is already installed")

    def _collect_required_secrets(self, *payloads: Any) -> list[str]:
        names: set[str] = set()

        def _walk(value: Any) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    lowered = str(key).lower()
                    if lowered in {"required_secrets", "secrets", "secret_names"} and isinstance(child, list):
                        for item in child:
                            if isinstance(item, str) and item.strip():
                                names.add(item.strip())
                        continue
                    if lowered in {"header", "headers", "env", "environment"} and isinstance(child, dict):
                        for subvalue in child.values():
                            if isinstance(subvalue, str):
                                for match in re.findall(r"\$\{([^}]+)\}", subvalue):
                                    names.add(match.strip())
                    _walk(child)
            elif isinstance(value, list):
                for child in value:
                    _walk(child)
            elif isinstance(value, str):
                for match in re.findall(r"\$\{([^}]+)\}", value):
                    names.add(match.strip())

        for payload in payloads:
            _walk(payload)
        return sorted(name for name in names if name)

    def _install_secret_names(
        self,
        component_manifest: dict[str, Any],
        raw_source: dict[str, Any],
    ) -> list[str]:
        return self._collect_required_secrets(component_manifest, raw_source)

    def _missing_runtime_secret_names(
        self,
        mcp_manifest: dict[str, Any],
        *,
        provided_secret_names: set[str],
    ) -> list[str]:
        return [
            secret_name
            for secret_name in self._collect_required_secrets(mcp_manifest)
            if secret_name not in provided_secret_names
        ]

    def _estimate_hook_count(self, hooks_payload: Any) -> int:
        if not hooks_payload:
            return 0
        if isinstance(hooks_payload, str):
            return 1
        if isinstance(hooks_payload, list):
            return sum(self._estimate_hook_count(entry) for entry in hooks_payload)
        if not isinstance(hooks_payload, dict):
            return 0

        hooks_object = hooks_payload.get("hooks") if isinstance(hooks_payload.get("hooks"), dict) else hooks_payload
        if not isinstance(hooks_object, dict):
            return 1

        count = 0
        for groups in hooks_object.values():
            if not isinstance(groups, list):
                continue
            for group in groups:
                if isinstance(group, dict) and isinstance(group.get("hooks"), list):
                    count += len([hook for hook in group.get("hooks") or [] if isinstance(hook, dict)])
                elif isinstance(group, list):
                    count += len([hook for hook in group if isinstance(hook, dict)])
        return count or 1

    def _estimate_component_counts(
        self, source: dict[str, Any], kind: MarketplaceItemKind, item: dict[str, Any]
    ) -> dict[str, int]:
        skills_count = 0
        if isinstance(item.get("skills"), list):
            skills_count = len(item.get("skills") or [])
        elif kind == "skill":
            skills_count = 1

        explicit_mcp_servers = item.get("mcp_servers")
        mcp_count = (
            len(explicit_mcp_servers)
            if isinstance(explicit_mcp_servers, list)
            else 0
        )
        descriptor_text = self._descriptor_text(item.get("source"))
        name_text = str(item.get("name") or "").lower()
        description_text = str(item.get("description") or "").lower()
        has_mcp_hint = any(
            token in descriptor_text or token in name_text or token in description_text
            for token in (
                "external_plugins/",
                ".mcp.json",
                " mcp ",
                "-mcp",
                "/mcp",
                "mcp server",
                "mcp integration",
            )
        )
        if kind == "mcp":
            mcp_count = max(mcp_count, 1)
        elif mcp_count == 0 and has_mcp_hint:
            mcp_count = 1

        if (
            source["id"] == "builtin-claude-skills"
            and skills_count == 0
            and kind == "plugin"
        ):
            skills_count = 1

        hooks_count = self._estimate_hook_count(item.get("hooks"))

        return {"skills": skills_count, "mcp_servers": mcp_count, "hooks": hooks_count}

    def _compatibility_warnings(self, kind: MarketplaceItemKind, item: dict[str, Any]) -> list[str]:
        warnings: list[str] = []
        if item.get("agents"):
            warnings.append("Claude agents are not yet surfaced in Xpdite.")
        if kind == "mcp" and item.get("resources"):
            warnings.append("MCP resources are preserved in metadata but not yet surfaced in Xpdite.")
        if item.get("prompts"):
            warnings.append("MCP prompts are preserved in metadata but not yet surfaced in Xpdite.")
        if item.get("lsp") or item.get("language_server") or item.get("lspServers"):
            warnings.append("LSP-specific capabilities are not yet supported in Xpdite.")
        return warnings

    def build_runtime_server_config(self, install: dict[str, Any]) -> Optional[dict[str, Any]]:
        if not install["enabled"]:
            return None
        runtimes = self.build_runtime_server_configs(install)
        return runtimes[0] if runtimes else None

    def _component_has_mcp_runtime(self, component_manifest: dict[str, Any]) -> bool:
        return bool(self._component_runtime_manifests(component_manifest))

    def _component_hook_secret_names(self, component_manifest: dict[str, Any]) -> list[str]:
        hooks = component_manifest.get("hooks")
        if not isinstance(hooks, dict):
            return []
        required = hooks.get("required_secrets")
        if not isinstance(required, list):
            return []
        return [str(name).strip() for name in required if str(name).strip()]

    def _missing_hook_secret_names(
        self,
        component_manifest: dict[str, Any],
        *,
        provided_secret_names: set[str],
    ) -> list[str]:
        return [
            secret_name
            for secret_name in self._component_hook_secret_names(component_manifest)
            if secret_name not in provided_secret_names and not os.environ.get(secret_name)
        ]

    def _component_runtime_manifests(self, component_manifest: dict[str, Any]) -> list[dict[str, Any]]:
        manifests = component_manifest.get("mcp_manifests")
        if isinstance(manifests, list):
            return [manifest for manifest in manifests if isinstance(manifest, dict)]
        manifest = component_manifest.get("mcp_manifest")
        return [manifest] if isinstance(manifest, dict) else []

    def _normalize_runtime_command(self, command: str, args: list[str]) -> tuple[str, list[str]]:
        if os.name == "nt" and command.lower() == "npx":
            return "cmd", ["/c", command, *args]
        return command, args

    def build_runtime_server_configs(self, install: dict[str, Any]) -> list[dict[str, Any]]:
        if not install["enabled"]:
            return []
        component_manifest = install.get("component_manifest") or {}
        manifests = self._component_runtime_manifests(component_manifest)
        runtimes: list[dict[str, Any]] = []
        for index, mcp_manifest in enumerate(manifests):
            runtimes.append(
                self._build_runtime_from_mcp_manifest(
                    install["id"],
                    mcp_manifest,
                    install_root=install.get("install_root"),
                    config_index=index,
                )
            )
        return runtimes

    def _build_runtime_from_component(
        self,
        install_id: str,
        component_manifest: dict[str, Any],
        *,
        install_root: Optional[str] = None,
        secrets_override: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        manifests = self._component_runtime_manifests(component_manifest)
        if not manifests:
            raise ValueError("Unsupported MCP manifest. Expected stdio command or remote url.")
        return self._build_runtime_from_mcp_manifest(
            install_id,
            manifests[0],
            install_root=install_root,
            secrets_override=secrets_override,
            config_index=0,
        )

    def _build_runtime_from_mcp_manifest(
        self,
        install_id: str,
        mcp_manifest: dict[str, Any],
        *,
        install_root: Optional[str] = None,
        secrets_override: Optional[dict[str, str]] = None,
        config_index: int = 0,
    ) -> dict[str, Any]:
        secrets = secrets_override if secrets_override is not None else self.get_install_secrets(install_id)
        substitutions = dict(secrets)
        provided_secret_names = {
            name
            for name, value in substitutions.items()
            if isinstance(name, str) and str(name).strip() and value not in (None, "")
        }
        plugin_root_available = False
        if install_root:
            substitutions.setdefault("XPDITE_MARKETPLACE_ROOT", install_root)
            provided_secret_names.add("XPDITE_MARKETPLACE_ROOT")
            install_root_path = Path(install_root)
            serialized_manifest = _json_dumps(mcp_manifest)
            plugin_root_available = (install_root_path / ".claude-plugin" / "plugin.json").exists() or (
                "${CLAUDE_PLUGIN_ROOT}" in serialized_manifest
            )
            if plugin_root_available:
                substitutions.setdefault("CLAUDE_PLUGIN_ROOT", install_root)
                provided_secret_names.add("CLAUDE_PLUGIN_ROOT")
        server_name = str(mcp_manifest.get("name") or mcp_manifest.get("server") or install_id)
        server_display_name = str(mcp_manifest.get("display_name") or server_name)
        runtime_server_name = f"marketplace-{install_id[:8]}-{_safe_slug(server_name)}"
        if config_index > 0:
            runtime_server_name = f"{runtime_server_name}-{config_index + 1}"

        if isinstance(mcp_manifest.get("command"), str):
            env = {
                key: self._substitute_secret_placeholders(str(value), substitutions)
                for key, value in (mcp_manifest.get("env") or {}).items()
            }
            if plugin_root_available and install_root:
                env.setdefault("CLAUDE_PLUGIN_ROOT", install_root)
            command = str(mcp_manifest["command"])
            args = [
                self._substitute_secret_placeholders(str(arg), substitutions)
                for arg in list(mcp_manifest.get("args") or [])
            ]
            manual_auth_required = bool(
                self._missing_runtime_secret_names(
                    mcp_manifest,
                    provided_secret_names=provided_secret_names,
                )
            )
            command, args = self._normalize_runtime_command(command, args)
            return {
                "server_name": runtime_server_name,
                "display_name": server_display_name,
                "command": command,
                "args": args,
                "env": env or None,
                "tool_name_prefix": f"mcp__{_safe_slug(server_name)}__",
                "manual_auth_required": manual_auth_required,
            }

        remote_url = str(
            mcp_manifest.get("url")
            or mcp_manifest.get("http_url")
            or mcp_manifest.get("sse_url")
            or ""
        ).strip()
        if remote_url:
            remote_url = self._substitute_secret_placeholders(remote_url, substitutions)
            transport = "http-only"
            if str(mcp_manifest.get("transport") or "").lower() == "sse" or mcp_manifest.get("sse_url"):
                transport = "sse-only"
            args = ["-y", "mcp-remote@latest", remote_url, "--transport", transport]
            for header_name, header_value in (mcp_manifest.get("headers") or {}).items():
                resolved = self._substitute_secret_placeholders(str(header_value), substitutions)
                args.extend(["--header", f"{header_name}: {resolved}"])
            if remote_url.startswith("http://"):
                args.append("--allow-http")
            manual_auth_required = bool(
                self._missing_runtime_secret_names(
                    mcp_manifest,
                    provided_secret_names=provided_secret_names,
                )
            )
            command, args = self._normalize_runtime_command("npx", args)
            return {
                "server_name": runtime_server_name,
                "display_name": server_display_name,
                "command": command,
                "args": args,
                "env": None,
                "tool_name_prefix": f"mcp__{_safe_slug(server_name)}__",
                "manual_auth_required": manual_auth_required,
            }

        raise ValueError("Unsupported MCP manifest. Expected stdio command or remote url.")

    def _substitute_secret_placeholders(self, value: str, secrets: dict[str, str]) -> str:
        def _replace(match: re.Match[str]) -> str:
            name = match.group(1).strip()
            return secrets.get(name, match.group(0))

        return re.sub(r"\$\{([^}]+)\}", _replace, value)

    def _upsert_source_row(
        self,
        *,
        source_id: str,
        name: str,
        kind: str,
        location: str,
        enabled: bool,
        builtin: bool,
        manifest_json: Optional[str],
        last_sync_at: Optional[float],
        last_error: Optional[str],
    ) -> None:
        now = _utc_now()
        with db._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM marketplace_sources WHERE id = ?",
                (source_id,),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE marketplace_sources
                    SET name = ?, kind = ?, location = ?, enabled = ?, builtin = ?,
                        manifest_json = COALESCE(?, manifest_json),
                        last_sync_at = COALESCE(?, last_sync_at),
                        last_error = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        name,
                        kind,
                        location,
                        1 if enabled else 0,
                        1 if builtin else 0,
                        manifest_json,
                        last_sync_at,
                        last_error,
                        now,
                        source_id,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO marketplace_sources (
                        id, name, kind, location, enabled, builtin, manifest_json,
                        last_sync_at, last_error, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_id,
                        name,
                        kind,
                        location,
                        1 if enabled else 0,
                        1 if builtin else 0,
                        manifest_json,
                        last_sync_at,
                        last_error,
                        now,
                        now,
                    ),
                )
            conn.commit()

    def _row_to_source(self, row: Any) -> dict[str, Any]:
        manifest = json.loads(row[6]) if row[6] else None
        return {
            "id": row[0],
            "name": row[1],
            "kind": row[2],
            "location": row[3],
            "enabled": bool(row[4]),
            "builtin": bool(row[5]),
            "manifest": manifest,
            "last_sync_at": row[7],
            "last_error": row[8],
            "created_at": row[9],
            "updated_at": row[10],
        }

    def _row_to_install(self, row: Any) -> dict[str, Any]:
        component_manifest = json.loads(row[10]) if row[10] else {}
        raw_source = json.loads(row[11]) if row[11] else {}
        install_root = str(row[6] or "")
        install_root_path = Path(install_root) if install_root else None
        if (
            row[1] == "plugin"
            and isinstance(component_manifest, dict)
            and install_root_path is not None
            and install_root_path.exists()
            and "commands" not in component_manifest
        ):
            commands = self._discover_plugin_commands(install_root_path / "commands")
            if commands:
                component_manifest = dict(component_manifest)
                component_manifest["commands"] = commands
        all_secret_names = self._install_secret_names(component_manifest, raw_source)
        required_secrets = [
            secret_name
            for secret_name in all_secret_names
            if not db.get_setting(f"marketplace_secret:{row[0]}:{secret_name}")
        ]
        install = {
            "id": row[0],
            "item_kind": row[1],
            "source_id": row[2],
            "manifest_item_id": row[3],
            "display_name": row[4],
            "canonical_id": row[5],
            "install_root": install_root,
            "resolved_ref": row[7],
            "status": row[8],
            "enabled": bool(row[9]),
            "component_manifest": component_manifest,
            "raw_source": raw_source,
            "last_error": row[12],
            "created_at": row[13],
            "updated_at": row[14],
            "required_secrets": required_secrets,
        }
        from ..hooks_runtime import get_hooks_runtime

        install["hook_runtime"] = get_hooks_runtime().build_runtime_summary(install)
        return install


_instance: Optional[MarketplaceService] = None
_instance_lock = threading.Lock()


def get_marketplace_service() -> MarketplaceService:
    global _instance
    if _instance is not None:
        return _instance
    with _instance_lock:
        if _instance is None:
            _instance = MarketplaceService()
            _instance.initialize()
    return _instance
