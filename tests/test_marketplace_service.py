"""Tests for the Anthropic-compatible marketplace service."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import requests

from source.infrastructure.database import db
from source.services.hooks_runtime import runtime as hooks_runtime_module
from source.services.marketplace import service as marketplace_module
from source.services.skills_runtime.skills import SkillManager


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


class _FakeResponse:
    def __init__(self, status_code: int, payload=None, *, content: bytes = b"", url: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload) if payload is not None else ""
        self.content = content
        self.url = url

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def test_parse_github_manifest_context_supports_refs_heads_raw_urls():
    repo, ref, base_path = marketplace_module._parse_github_manifest_context(
        "https://raw.githubusercontent.com/example/demo/refs/heads/main/plugins/.claude-plugin/marketplace.json"
    )

    assert repo == "example/demo"
    assert ref == "main"
    assert base_path == "plugins"


def test_normalize_marketplace_source_location_supports_bare_github_repo(marketplace_env):
    service, _, _ = marketplace_env

    normalized = service._normalize_marketplace_source_location(
        "jeremylongshore/claude-code-plugins-plus-skills"
    )

    assert normalized == "https://github.com/jeremylongshore/claude-code-plugins-plus-skills"


def test_normalize_marketplace_source_location_fixes_backslash_urls(marketplace_env):
    service, _, _ = marketplace_env

    normalized = service._normalize_marketplace_source_location(
        r"https:\github.com\jeremylongshore\claude-code-plugins-plus-skills"
    )

    assert normalized == "https://github.com/jeremylongshore/claude-code-plugins-plus-skills"


@pytest.fixture()
def marketplace_env(tmp_path, monkeypatch):
    db_path = tmp_path / "marketplace.db"
    monkeypatch.setattr(db, "database_path", str(db_path))
    db._init_db()

    plugins_dir = tmp_path / "user_data" / "marketplace" / "plugins"
    skills_dir = tmp_path / "user_data" / "marketplace" / "skills"
    mcp_dir = tmp_path / "user_data" / "marketplace" / "mcp"
    plugin_data_dir = tmp_path / "user_data" / "marketplace" / "plugin-data"
    hook_transcripts_dir = tmp_path / "user_data" / "marketplace" / "hook-transcripts"
    for path in (plugins_dir, skills_dir, mcp_dir, plugin_data_dir, hook_transcripts_dir):
        path.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(marketplace_module, "MARKETPLACE_PLUGINS_DIR", plugins_dir)
    monkeypatch.setattr(marketplace_module, "MARKETPLACE_SKILLS_DIR", skills_dir)
    monkeypatch.setattr(marketplace_module, "MARKETPLACE_MCP_DIR", mcp_dir)
    monkeypatch.setattr(marketplace_module, "MARKETPLACE_PLUGIN_DATA_DIR", plugin_data_dir)
    monkeypatch.setattr(marketplace_module, "_instance", None)
    monkeypatch.setattr(hooks_runtime_module, "MARKETPLACE_PLUGIN_DATA_DIR", plugin_data_dir)
    monkeypatch.setattr(hooks_runtime_module, "MARKETPLACE_HOOK_TRANSCRIPTS_DIR", hook_transcripts_dir)
    monkeypatch.setattr(hooks_runtime_module, "_instance", None)

    skill_manager = SkillManager(
        skills_dir=tmp_path / "skills",
        builtin_dir=tmp_path / "skills" / "builtin",
        user_dir=tmp_path / "skills" / "user",
        seed_dir=tmp_path / "skills_seed",
        preferences_file=tmp_path / "skills" / "preferences.json",
    )
    skill_manager.initialize()
    monkeypatch.setattr(
        "source.services.skills_runtime.skills.get_skill_manager",
        lambda: skill_manager,
    )

    service = marketplace_module.MarketplaceService()
    service.initialize()
    monkeypatch.setattr(
        "source.services.marketplace.service.get_marketplace_service",
        lambda: service,
    )
    return service, skill_manager, tmp_path


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture()
def local_manifest_root(tmp_path) -> Path:
    root = tmp_path / "catalog-root"

    standalone_skill = root / "standalone-skill" / "SKILL.md"
    standalone_skill.parent.mkdir(parents=True, exist_ok=True)
    standalone_skill.write_text(
        "---\nname: planner\ncommand: planner:triage\ndescription: Planner skill\n---\n# Planner\n",
        encoding="utf-8",
    )

    plugin_root = root / "demo-plugin"
    _write_json(
        plugin_root / ".claude-plugin" / "plugin.json",
        {
            "name": "ops",
            "version": "1.0.0",
            "description": "Ops plugin",
        },
    )
    (plugin_root / "skills" / "triage").mkdir(parents=True, exist_ok=True)
    (plugin_root / "skills" / "triage" / "SKILL.md").write_text(
        "---\nname: triage\ncommand: triage\ndescription: Incident triage\n---\n# Triage\n",
        encoding="utf-8",
    )

    command_plugin_root = root / "command-plugin"
    _write_json(
        command_plugin_root / ".claude-plugin" / "plugin.json",
        {
            "name": "code-review",
            "version": "1.0.0",
            "description": "Code review command plugin",
        },
    )
    (command_plugin_root / "commands").mkdir(parents=True, exist_ok=True)
    (command_plugin_root / "commands" / "code-review.md").write_text(
        "---\ndescription: Review a pull request\n---\nReview the supplied pull request.\n",
        encoding="utf-8",
    )

    hook_plugin_root = root / "hook-plugin"
    _write_json(
        hook_plugin_root / ".claude-plugin" / "plugin.json",
        {
            "name": "caveman",
            "version": "1.0.0",
            "description": "Hook-only plugin",
            "hooks": {
                "SessionStart": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "node ${CLAUDE_PLUGIN_ROOT}/hooks/caveman-activate.js",
                            }
                        ]
                    }
                ]
            },
        },
    )

    skills_bundle_root = root / "skills-bundle"
    (skills_bundle_root / "skills" / "alpha").mkdir(parents=True, exist_ok=True)
    (skills_bundle_root / "skills" / "alpha" / "SKILL.md").write_text(
        "---\nname: alpha\ncommand: alpha\ndescription: Alpha skill\n---\n# Alpha\n",
        encoding="utf-8",
    )
    (skills_bundle_root / "skills" / "beta").mkdir(parents=True, exist_ok=True)
    (skills_bundle_root / "skills" / "beta" / "SKILL.md").write_text(
        "---\nname: beta\ncommand: beta\ndescription: Beta skill\n---\n# Beta\n",
        encoding="utf-8",
    )

    mcp_root = root / "remote-mcp"
    _write_json(
        mcp_root / ".mcp.json",
        {
            "name": "context7",
            "url": "https://example.com/mcp",
            "headers": {"Authorization": "Bearer ${CONTEXT7_TOKEN}"},
        },
    )

    named_map_mcp_root = root / "named-map-mcp"
    _write_json(
        named_map_mcp_root / ".mcp.json",
        {
            "context7": {
                "command": "npx",
                "args": ["-y", "@upstash/context7-mcp"],
            }
        },
    )

    _write_json(
        root / "marketplace.json",
        {
            "items": [
                {
                    "id": "planner-skill",
                    "kind": "skill",
                    "name": "Planner Skill",
                    "description": "Standalone native skill",
                    "source": "standalone-skill",
                },
                {
                    "id": "ops-plugin",
                    "kind": "plugin",
                    "name": "Ops Plugin",
                    "description": "Plugin with bundled skills",
                    "source": "demo-plugin",
                },
                {
                    "id": "skills-bundle",
                    "kind": "plugin",
                    "name": "Skills Bundle",
                    "description": "Plugin-like skills bundle with no plugin.json",
                    "source": "skills-bundle",
                    "skills": ["./skills/alpha", "./skills/beta"],
                },
                {
                    "id": "code-review-plugin",
                    "kind": "plugin",
                    "name": "Code Review",
                    "description": "Plugin with Anthropic-style commands",
                    "source": "command-plugin",
                },
                {
                    "id": "context7-mcp",
                    "kind": "mcp",
                    "name": "Context7 MCP",
                    "description": "Remote MCP bundle",
                    "required_secrets": ["CONTEXT7_TOKEN"],
                    "source": "remote-mcp",
                },
                {
                    "id": "context7-bundle",
                    "kind": "mcp",
                    "name": "Context7 Bundle",
                    "description": "Named-map MCP bundle",
                    "source": "named-map-mcp",
                },
            ]
        },
    )
    return root


class TestMarketplaceService:
    def test_refresh_local_source_and_catalog(self, marketplace_env, local_manifest_root):
        service, _, _ = marketplace_env
        source = service.create_source("Local Catalog", str(local_manifest_root / "marketplace.json"))
        refreshed = service._refresh_source_sync(source["id"])

        assert refreshed["manifest"]["items"][0]["id"] == "planner-skill"

        catalog = service.list_catalog()
        assert {item["kind"] for item in catalog} == {"skill", "plugin", "mcp"}
        context7_item = next(item for item in catalog if item["manifest_item_id"] == "context7-mcp")
        assert context7_item["required_secrets"] == ["CONTEXT7_TOKEN"]

    def test_installing_marketplace_items_populates_skill_runtime(self, marketplace_env, local_manifest_root):
        service, skill_manager, _ = marketplace_env
        source = service.create_source("Local Catalog", str(local_manifest_root / "marketplace.json"))
        service._refresh_source_sync(source["id"])

        standalone = service._install_item_sync(source["id"], "planner-skill", {})
        plugin = service._install_item_sync(source["id"], "ops-plugin", {})

        assert standalone["canonical_id"] == "planner:triage"
        assert plugin["canonical_id"] == "ops"

        skill_manager._reload_cache()
        assert skill_manager.get_skill_by_slash_command("planner:triage") is not None
        plugin_skill = skill_manager.get_skill_by_slash_command("ops:triage")
        assert plugin_skill is not None
        assert plugin_skill.source == "marketplace"
        assert plugin_skill.install_id == plugin["id"]

    def test_remote_mcp_install_builds_manual_auth_runtime(self, marketplace_env, local_manifest_root):
        service, _, _ = marketplace_env
        source = service.create_source("Local Catalog", str(local_manifest_root / "marketplace.json"))
        service._refresh_source_sync(source["id"])

        install = service._install_item_sync(source["id"], "context7-mcp", {})
        runtime = service.build_runtime_server_config(install)

        assert install["status"] == "manual_auth_required"
        assert runtime is not None
        assert runtime["command"] in {"npx", "cmd"}
        assert "--transport" in runtime["args"]
        assert runtime["tool_name_prefix"].startswith("mcp__context7__")

        service.set_install_secrets(install["id"], {"CONTEXT7_TOKEN": "secret-token"})
        hydrated_install = service.get_install(install["id"])
        runtime = service.build_runtime_server_config(hydrated_install)
        assert runtime is not None
        assert runtime.get("manual_auth_required") is False
        assert "Authorization: Bearer secret-token" in runtime["args"]

    def test_named_map_mcp_bundle_installs_and_builds_runtime(self, marketplace_env, local_manifest_root):
        service, _, _ = marketplace_env
        source = service.create_source("Local Catalog", str(local_manifest_root / "marketplace.json"))
        service._refresh_source_sync(source["id"])

        install = service._install_item_sync(source["id"], "context7-bundle", {})
        runtime = service.build_runtime_server_config(install)

        assert install["status"] == "connected"
        assert runtime is not None
        assert runtime["command"] in {"npx", "cmd"}
        assert "@upstash/context7-mcp" in " ".join(runtime["args"])

    def test_skills_only_bundle_without_plugin_manifest_installs(self, marketplace_env, local_manifest_root):
        service, skill_manager, _ = marketplace_env
        source = service.create_source("Local Catalog", str(local_manifest_root / "marketplace.json"))
        service._refresh_source_sync(source["id"])

        install = service._install_item_sync(source["id"], "skills-bundle", {})
        skill_manager._reload_cache()

        assert install["item_kind"] == "plugin"
        assert skill_manager.get_skill_by_slash_command("skills-bundle:alpha") is not None
        assert skill_manager.get_skill_by_slash_command("skills-bundle:beta") is not None

    def test_plugin_commands_are_imported_as_marketplace_skills(self, marketplace_env, local_manifest_root):
        service, skill_manager, _ = marketplace_env
        source = service.create_source("Local Catalog", str(local_manifest_root / "marketplace.json"))
        service._refresh_source_sync(source["id"])

        install = service._install_item_sync(source["id"], "code-review-plugin", {})

        command_skill = skill_manager.get_skill_by_slash_command("code-review")
        assert install["item_kind"] == "plugin"
        assert command_skill is not None
        assert command_skill.source == "marketplace"
        assert "Review the supplied pull request." in command_skill.read_content()

    def test_uninstall_removes_install_root_and_db_row(self, marketplace_env, local_manifest_root):
        service, _, _ = marketplace_env
        source = service.create_source("Local Catalog", str(local_manifest_root / "marketplace.json"))
        service._refresh_source_sync(source["id"])

        install = service._install_item_sync(source["id"], "planner-skill", {})
        install_root = Path(install["install_root"])
        assert install_root.exists()

        result = service._uninstall_sync(install["id"])
        assert result["success"] is True
        assert not install_root.exists()
        with pytest.raises(ValueError):
            service.get_install(install["id"])

    def test_github_marketplace_relative_paths_resolve_from_repo_root(self, marketplace_env, tmp_path):
        service, _, _ = marketplace_env
        manifest = {
            "plugins": [
                {
                    "id": "discord",
                    "name": "discord",
                    "source": "./external_plugins/discord",
                }
            ]
        }
        service._upsert_source_row(
            source_id="github-source",
            name="Anthropic Plugins",
            kind="remote_manifest",
            location="https://raw.githubusercontent.com/anthropics/claude-plugins-official/main/.claude-plugin/marketplace.json",
            enabled=True,
            builtin=False,
            manifest_json=json.dumps(manifest),
            last_sync_at=None,
            last_error=None,
        )
        source_ctx = service._get_source_context("github-source")
        install_root = tmp_path / "install"
        install_root.mkdir(parents=True, exist_ok=True)

        with patch.object(service, "_download_github_subdir", return_value="ok") as download:
            resolved = service._materialize_from_relative_or_url(
                source_ctx,
                install_root,
                "./external_plugins/discord",
                "plugin",
            )

        assert resolved == "ok"
        download.assert_called_once_with(
            "anthropics/claude-plugins-official",
            "main",
            "external_plugins/discord",
            install_root,
        )

    def test_github_marketplace_refs_heads_manifest_uses_branch_name(self, marketplace_env, tmp_path):
        service, _, _ = marketplace_env
        manifest = {
            "plugins": [
                {
                    "id": "sample",
                    "name": "sample",
                    "source": "./plugins/sample",
                }
            ],
            "_xpdite_manifest_location": (
                "https://raw.githubusercontent.com/example/demo/refs/heads/main/.claude-plugin/marketplace.json"
            ),
        }
        service._upsert_source_row(
            source_id="github-raw-refs",
            name="Demo Marketplace",
            kind="remote_manifest",
            location="https://raw.githubusercontent.com/example/demo/refs/heads/main/.claude-plugin/marketplace.json",
            enabled=True,
            builtin=False,
            manifest_json=json.dumps(manifest),
            last_sync_at=None,
            last_error=None,
        )
        source_ctx = service._get_source_context("github-raw-refs")
        install_root = tmp_path / "install-refs"
        install_root.mkdir(parents=True, exist_ok=True)

        with patch.object(service, "_download_github_subdir", return_value="ok") as download:
            resolved = service._materialize_from_relative_or_url(
                source_ctx,
                install_root,
                "./plugins/sample",
                "plugin",
            )

        assert resolved == "ok"
        download.assert_called_once_with(
            "example/demo",
            "main",
            "plugins/sample",
            install_root,
        )

    def test_marketplace_plugin_root_does_not_duplicate_prefixed_source_paths(self, marketplace_env, tmp_path):
        service, _, _ = marketplace_env
        manifest = {
            "metadata": {"pluginRoot": "./plugins"},
            "plugins": [
                {
                    "id": "bottleneck-detector",
                    "name": "bottleneck-detector",
                    "source": "./plugins/performance/bottleneck-detector",
                }
            ],
            "_xpdite_manifest_location": (
                "https://raw.githubusercontent.com/jeremylongshore/claude-code-plugins-plus-skills/main/.claude-plugin/marketplace.json"
            ),
        }
        service._upsert_source_row(
            source_id="plugin-root-source",
            name="Claude Plugins Plus",
            kind="remote_manifest",
            location="https://github.com/jeremylongshore/claude-code-plugins-plus-skills",
            enabled=True,
            builtin=False,
            manifest_json=json.dumps(manifest),
            last_sync_at=None,
            last_error=None,
        )
        source_ctx = service._get_source_context("plugin-root-source")
        install_root = tmp_path / "install-plugin-root"
        install_root.mkdir(parents=True, exist_ok=True)

        with patch.object(service, "_download_github_subdir", return_value="ok") as download:
            resolved = service._materialize_from_relative_or_url(
                source_ctx,
                install_root,
                "./plugins/performance/bottleneck-detector",
                "plugin",
            )

        assert resolved == "ok"
        download.assert_called_once_with(
            "jeremylongshore/claude-code-plugins-plus-skills",
            "main",
            "plugins/performance/bottleneck-detector",
            install_root,
        )

    def test_marketplace_plugin_root_applies_to_unprefixed_source_paths(self, marketplace_env, tmp_path):
        service, _, _ = marketplace_env
        manifest = {
            "metadata": {"pluginRoot": "./plugins"},
            "plugins": [
                {
                    "id": "bottleneck-detector",
                    "name": "bottleneck-detector",
                    "source": "./performance/bottleneck-detector",
                }
            ],
            "_xpdite_manifest_location": (
                "https://raw.githubusercontent.com/jeremylongshore/claude-code-plugins-plus-skills/main/.claude-plugin/marketplace.json"
            ),
        }
        service._upsert_source_row(
            source_id="plugin-root-relative-source",
            name="Claude Plugins Plus",
            kind="remote_manifest",
            location="https://github.com/jeremylongshore/claude-code-plugins-plus-skills",
            enabled=True,
            builtin=False,
            manifest_json=json.dumps(manifest),
            last_sync_at=None,
            last_error=None,
        )
        source_ctx = service._get_source_context("plugin-root-relative-source")
        install_root = tmp_path / "install-plugin-root-relative"
        install_root.mkdir(parents=True, exist_ok=True)

        with patch.object(service, "_download_github_subdir", return_value="ok") as download:
            resolved = service._materialize_from_relative_or_url(
                source_ctx,
                install_root,
                "./performance/bottleneck-detector",
                "plugin",
            )

        assert resolved == "ok"
        download.assert_called_once_with(
            "jeremylongshore/claude-code-plugins-plus-skills",
            "main",
            "plugins/performance/bottleneck-detector",
            install_root,
        )

    def test_local_marketplace_directory_resolves_paths_from_repo_root(self, marketplace_env, tmp_path):
        service, _, _ = marketplace_env
        repo_root = tmp_path / "local-repo"
        plugin_root = repo_root / "external_plugins" / "discord"
        _write_json(
            plugin_root / ".claude-plugin" / "plugin.json",
            {"name": "discord", "version": "1.0.0", "description": "Discord plugin"},
        )
        _write_json(
            repo_root / ".claude-plugin" / "marketplace.json",
            {"plugins": [{"id": "discord", "name": "discord", "source": "./external_plugins/discord"}]},
        )

        source = service.create_source("Local Repo", str(repo_root))
        refreshed = service._refresh_source_sync(source["id"])
        assert refreshed["manifest"]["plugins"][0]["id"] == "discord"

        install = service._install_item_sync(source["id"], "discord", {})
        assert install["display_name"] == "discord"

    def test_github_repo_source_resolves_to_raw_marketplace_manifest(self, marketplace_env):
        service, _, _ = marketplace_env
        source = service.create_source(
            "Composio",
            "https://github.com/ComposioHQ/awesome-claude-plugins",
        )
        root_manifest_url = (
            "https://raw.githubusercontent.com/ComposioHQ/awesome-claude-plugins/master/marketplace.json"
        )

        def fake_get(url: str, timeout: int = 30):
            if url.endswith("/master/.claude-plugin/marketplace.json"):
                return _FakeResponse(404)
            if url == root_manifest_url:
                return _FakeResponse(
                    200,
                    {
                        "plugins": [
                            {
                                "id": "demo-plugin",
                                "name": "Demo Plugin",
                                "description": "Installable demo",
                                "source": {"url": "https://example.com/demo-plugin.zip"},
                            }
                        ]
                    },
                )
            raise AssertionError(f"Unexpected URL requested: {url}")

        with (
            patch.object(service, "_candidate_github_refs", return_value=["master"]),
            patch.object(marketplace_module.requests, "get", side_effect=fake_get),
        ):
            refreshed = service._refresh_source_sync(source["id"])

        assert refreshed["manifest"]["_xpdite_manifest_location"] == root_manifest_url
        catalog = service.list_catalog()
        assert any(item["manifest_item_id"] == "demo-plugin" for item in catalog)

    def test_discovery_only_marketplace_manifest_raises_clear_error(self, marketplace_env):
        service, _, _ = marketplace_env
        source = service.create_source(
            "Composio",
            "https://raw.githubusercontent.com/ComposioHQ/awesome-claude-plugins/master/marketplace.json",
        )

        with patch.object(
            marketplace_module.requests,
            "get",
            return_value=_FakeResponse(
                200,
                {
                    "name": "Claude Code Plugin Marketplace",
                    "plugins": [
                        {
                            "name": "code-review",
                            "description": "Curated listing entry only",
                        }
                    ],
                },
            ),
        ):
            with pytest.raises(ValueError, match="discovery/index list"):
                service._refresh_source_sync(source["id"])

    def test_download_github_subdir_wraps_http_errors(self, marketplace_env, tmp_path):
        service, _, _ = marketplace_env

        with patch.object(
            marketplace_module.requests,
            "get",
            return_value=_FakeResponse(404),
        ):
            with pytest.raises(ValueError, match="Failed to download GitHub archive for example/demo@main"):
                service._download_github_subdir(
                    "example/demo",
                    "main",
                    "plugins/sample",
                    tmp_path / "install",
                )

    def test_generated_npx_and_uvx_sources_build_single_item_manifests(self, marketplace_env):
        service, _, _ = marketplace_env

        npx_source = service.create_source("npx", "@modelcontextprotocol/server-everything")
        npx_manifest = service._refresh_source_sync(npx_source["id"])["manifest"]
        assert npx_manifest["items"][0]["source"]["command"] == "npx"
        assert npx_manifest["items"][0]["source"]["args"] == ["-y", "@modelcontextprotocol/server-everything"]

        uvx_source = service.create_source("uvx", "acme-mcp")
        uvx_manifest = service._refresh_source_sync(uvx_source["id"])["manifest"]
        assert uvx_manifest["items"][0]["source"]["command"] == "uvx"
        assert uvx_manifest["items"][0]["source"]["args"] == ["acme-mcp"]

        quoted_npx_source = service.create_source("Packages", 'npx "@modelcontextprotocol/server-everything" --debug')
        quoted_manifest = service._refresh_source_sync(quoted_npx_source["id"])["manifest"]
        assert quoted_manifest["items"][0]["source"]["args"] == ["-y", "@modelcontextprotocol/server-everything", "--debug"]

        env_source = service.create_source("npx", 'OPENAI_API_KEY=${OPENAI_API_KEY} mcp-server-demo --debug')
        env_manifest = service._refresh_source_sync(env_source["id"])["manifest"]
        assert env_manifest["items"][0]["source"]["env"] == {"OPENAI_API_KEY": "${OPENAI_API_KEY}"}
        assert env_manifest["items"][0]["source"]["args"] == ["-y", "mcp-server-demo", "--debug"]

    def test_direct_package_install_uses_null_source_id(self, marketplace_env):
        service, _, _ = marketplace_env

        install = service._install_package_sync("npx", '@modelcontextprotocol/server-everything --debug')
        runtime = service.build_runtime_server_config(install)

        assert install["source_id"] is None
        assert install["raw_source"]["kind"] == "direct_package"
        assert runtime is not None
        assert runtime["command"] in {"npx", "cmd"}
        assert "@modelcontextprotocol/server-everything" in " ".join(runtime["args"])

    def test_direct_package_install_supports_env_placeholders_and_args(self, marketplace_env):
        service, _, _ = marketplace_env

        install = service._install_package_sync(
            "uvx",
            'SQLITE_PATH=${SQLITE_PATH} mcp-server-sqlite --db-path /tmp/test.db',
        )
        runtime = service.build_runtime_server_config(install)

        assert install["source_id"] is None
        assert install["status"] == "manual_auth_required"
        assert install["required_secrets"] == ["SQLITE_PATH"]
        assert runtime is not None
        assert runtime["manual_auth_required"] is True
        assert runtime["env"] == {"SQLITE_PATH": "${SQLITE_PATH}"}
        assert runtime["args"] == ["mcp-server-sqlite", "--db-path", "/tmp/test.db"]

    def test_direct_package_install_redacts_inline_env_values_and_stores_them_as_secrets(self, marketplace_env):
        service, _, _ = marketplace_env

        install = service._install_package_sync(
            "uvx",
            'SQLITE_PATH=/tmp/test.db mcp-server-sqlite --db-path ${SQLITE_PATH}',
        )
        runtime = service.build_runtime_server_config(install)

        assert install["required_secrets"] == []
        assert install["raw_source"]["package_command"] == 'SQLITE_PATH=${SQLITE_PATH} mcp-server-sqlite --db-path ${SQLITE_PATH}'
        assert install["component_manifest"]["mcp_manifest"]["env"] == {"SQLITE_PATH": "${SQLITE_PATH}"}
        persisted_manifest = json.loads((Path(install["install_root"]) / ".mcp.json").read_text(encoding="utf-8"))
        assert persisted_manifest["env"] == {"SQLITE_PATH": "${SQLITE_PATH}"}
        assert runtime is not None
        assert runtime["env"] == {"SQLITE_PATH": "/tmp/test.db"}
        assert service.get_install_secrets(install["id"]) == {"SQLITE_PATH": "/tmp/test.db"}

    def test_direct_package_runtime_does_not_inject_claude_plugin_root(self, marketplace_env):
        service, _, _ = marketplace_env

        install = service._install_package_sync("npx", "@modelcontextprotocol/server-everything")
        runtime = service.build_runtime_server_config(install)

        assert runtime is not None
        assert runtime["env"] in (None, {})
        assert runtime["manual_auth_required"] is False

    def test_runtime_treats_auto_injected_plugin_root_as_satisfied(self, marketplace_env, tmp_path):
        service, _, _ = marketplace_env

        runtime = service._build_runtime_from_mcp_manifest(
            "install-123",
            {
                "name": "plugin-root-demo",
                "command": "npx",
                "args": ["-y", "demo", "${CLAUDE_PLUGIN_ROOT}/config.json"],
            },
            install_root=str(tmp_path / "plugin-root-demo"),
            secrets_override={},
        )

        assert runtime["manual_auth_required"] is False
        assert Path(runtime["args"][-1]).name == "config.json"
        assert "plugin-root-demo" in runtime["args"][-1]

    def test_direct_repo_install_loads_hook_only_plugin_and_registers_hook_metadata(self, marketplace_env, local_manifest_root):
        service, skill_manager, _ = marketplace_env

        install = service._install_repo_sync(str(local_manifest_root / "hook-plugin"))
        skill_manager._reload_cache()

        assert install["item_kind"] == "plugin"
        assert install["source_id"] is None
        assert install["raw_source"]["kind"] == "direct_repo"
        assert skill_manager.get_skill_by_slash_command("caveman") is None
        hooks_manifest = install["component_manifest"]["hooks"]
        assert hooks_manifest["handler_count"] == 1
        assert hooks_manifest["supported_event_count"] == 1
        assert hooks_manifest["required_secrets"] == []
        hook_runtime = install["hook_runtime"]
        assert hook_runtime["has_hooks"] is True
        assert hook_runtime["registered_handler_count"] == 1
        assert hook_runtime["status"] == "active"
        warnings = install["component_manifest"]["compatibility_warnings"]
        assert warnings == []

    def test_direct_package_install_routes_repo_like_inputs_to_repo_installer(
        self,
        marketplace_env,
        local_manifest_root,
        monkeypatch,
    ):
        service, _, _ = marketplace_env
        direct_request = service._build_local_direct_repo_install_request(
            marketplace_module.DirectRepoSpec(
                input="JuliusBrussee/caveman",
                kind="local",
                label="caveman",
                base_path=(local_manifest_root / "hook-plugin").resolve(),
                github_repo=None,
                github_ref=None,
                github_base_path="",
            )
        )

        original_builder = service._build_direct_repo_install_request

        def fake_builder(value: str):
            if value == "JuliusBrussee/caveman":
                return direct_request
            return original_builder(value)

        monkeypatch.setattr(service, "_build_direct_repo_install_request", fake_builder)

        install = service._install_package_sync("npx", "JuliusBrussee/caveman")
        assert install["item_kind"] == "plugin"
        assert install["raw_source"]["kind"] == "direct_repo"

    def test_normalize_named_server_map_mcp_payload(self, marketplace_env):
        service, _, _ = marketplace_env

        manifest, manifests = service._normalize_mcp_payload(
            {
                "context7": {
                    "command": "npx",
                    "args": ["-y", "@upstash/context7-mcp"],
                }
            }
        )

        assert manifest is not None
        assert manifest["name"] == "context7"
        assert manifests[0]["args"] == ["-y", "@upstash/context7-mcp"]

    def test_extract_zip_subdir_rejects_path_traversal(self, marketplace_env, tmp_path):
        service, _, _ = marketplace_env
        archive_buffer = io.BytesIO()
        with zipfile.ZipFile(archive_buffer, "w") as archive:
            archive.writestr("repo-main/pkg/.mcp.json", "{}")
            archive.writestr("repo-main/pkg/../escape.txt", "bad")

        with pytest.raises(ValueError):
            service._extract_zip_subdir(archive_buffer.getvalue(), tmp_path / "install", "pkg")

    @pytest.mark.anyio
    async def test_update_install_keeps_existing_install_when_reinstall_fails(self, marketplace_env, local_manifest_root):
        service, _, _ = marketplace_env
        source = service.create_source("Local Catalog", str(local_manifest_root / "marketplace.json"))
        service._refresh_source_sync(source["id"])
        install = service._install_item_sync(source["id"], "planner-skill", {})

        with (
            patch.object(service, "_reinstall_existing_install_sync", side_effect=ValueError("boom")),
            patch.object(marketplace_module.manager, "broadcast_json", new=AsyncMock()),
        ):
            with pytest.raises(ValueError, match="boom"):
                await service.update_install_async(install["id"])

        existing = service.get_install(install["id"])
        assert existing["display_name"] == install["display_name"]

    @pytest.mark.anyio
    async def test_update_install_rolls_back_replacement_when_activation_fails(self, marketplace_env, local_manifest_root):
        service, _, _ = marketplace_env
        source = service.create_source("Local Catalog", str(local_manifest_root / "marketplace.json"))
        service._refresh_source_sync(source["id"])
        install = service._install_item_sync(source["id"], "context7-bundle", {})

        with (
            patch.object(service, "_connect_install_runtime_if_needed", new=AsyncMock(side_effect=ValueError("boom"))),
            patch.object(marketplace_module.manager, "broadcast_json", new=AsyncMock()),
        ):
            with pytest.raises(ValueError, match="boom"):
                await service.update_install_async(install["id"])

        installs = service.list_installs()
        assert len(installs) == 1
        assert installs[0]["id"] == install["id"]
        assert installs[0]["display_name"] == install["display_name"]

    @pytest.mark.anyio
    async def test_connect_install_runtime_rolls_back_partial_activation_on_failure(
        self,
        marketplace_env,
    ):
        service, _, _ = marketplace_env
        install = {"id": "install-1", "enabled": True}
        connected_servers: set[str] = set()
        fake_hooks = SimpleNamespace(
            register_install_async=AsyncMock(),
            unregister_install_async=AsyncMock(),
        )

        async def fake_connect(server_name, *_args, **_kwargs):
            if server_name == "server-a":
                connected_servers.add(server_name)
                return None
            raise RuntimeError("boom")

        async def fake_disconnect(server_name):
            connected_servers.discard(server_name)

        with (
            patch.object(
                service,
                "build_runtime_server_configs",
                return_value=[
                    {
                        "server_name": "server-a",
                        "command": "cmd-a",
                        "args": [],
                    },
                    {
                        "server_name": "server-b",
                        "command": "cmd-b",
                        "args": [],
                    },
                ],
            ),
            patch.object(
                service,
                "_set_install_runtime_state_sync",
                return_value=install,
            ),
            patch(
                "source.services.hooks_runtime.get_hooks_runtime",
                return_value=fake_hooks,
            ),
            patch(
                "source.mcp_integration.core.manager.mcp_manager.is_server_connected",
                side_effect=lambda name: name in connected_servers,
            ),
            patch(
                "source.mcp_integration.core.manager.mcp_manager.connect_server",
                new=AsyncMock(side_effect=fake_connect),
            ),
            patch(
                "source.mcp_integration.core.manager.mcp_manager.disconnect_server",
                new=AsyncMock(side_effect=fake_disconnect),
            ) as disconnect_server,
        ):
            with pytest.raises(ValueError, match="boom"):
                await service._connect_install_runtime_if_needed(install)

        fake_hooks.register_install_async.assert_awaited_once_with(install)
        fake_hooks.unregister_install_async.assert_awaited_once_with("install-1")
        disconnect_server.assert_awaited_once_with("server-a")
        assert connected_servers == set()

    def test_mcp_registry_manifest_prefers_remote_then_maps_pypi_to_uvx(self, marketplace_env, monkeypatch):
        service, _, _ = marketplace_env
        payload = {
            "servers": [
                {
                    "server": {
                        "name": "io.github.example/demo-remote",
                        "title": "Demo Remote",
                        "description": "Remote registry entry",
                        "remotes": [
                            {
                                "type": "streamable-http",
                                "url": "https://{tenant}.example.com/mcp",
                                "variables": {"tenant": {"isRequired": True}},
                                "headers": [{"name": "Authorization", "isRequired": True, "isSecret": True}],
                            }
                        ],
                    },
                    "_meta": {"io.modelcontextprotocol.registry/official": {"status": "active", "isLatest": True}},
                },
                {
                    "server": {
                        "name": "io.github.example/demo-pypi",
                        "title": "Demo PyPI",
                        "description": "PyPI registry entry",
                        "packages": [
                            {
                                "registryType": "pypi",
                                "identifier": "demo-mcp",
                                "version": "1.2.3",
                                "transport": {"type": "stdio"},
                            }
                        ],
                    },
                    "_meta": {"io.modelcontextprotocol.registry/official": {"status": "active", "isLatest": True}},
                },
                {
                    "server": {
                        "name": "io.github.example/unverified",
                        "title": "Unverified",
                        "description": "Should not be listed",
                        "packages": [
                            {
                                "registryType": "npm",
                                "identifier": "unverified-mcp",
                                "transport": {"type": "stdio"},
                            }
                        ],
                    },
                },
            ],
            "metadata": {},
        }

        class DummyResponse:
            def __init__(self, body):
                self._body = body

            def raise_for_status(self):
                return None

            def json(self):
                return self._body

        monkeypatch.setattr(
            marketplace_module.requests,
            "get",
            lambda *args, **kwargs: DummyResponse(payload),
        )

        manifest = service._build_mcp_registry_manifest()
        assert len(manifest["mcp"]) == 2

        remote_item = next(item for item in manifest["mcp"] if item["id"] == "io.github.example/demo-remote")
        assert remote_item["source"]["url"] == "https://${TENANT}.example.com/mcp"
        assert remote_item["source"]["headers"]["Authorization"] == "${IO_GITHUB_EXAMPLE_DEMO_REMOTE_AUTHORIZATION}"

        pypi_item = next(item for item in manifest["mcp"] if item["id"] == "io.github.example/demo-pypi")
        assert pypi_item["source"]["command"] == "uvx"
        assert pypi_item["source"]["args"] == ["demo-mcp==1.2.3"]

    def test_runtime_substitutes_remote_url_variables(self, marketplace_env):
        service, _, _ = marketplace_env
        runtime = service._build_runtime_from_component(
            "install-1",
            {
                "mcp_manifest": {
                    "name": "demo",
                    "url": "https://${TENANT}.example.com/mcp",
                    "headers": {"Authorization": "Bearer ${TOKEN}"},
                }
            },
            secrets_override={"TENANT": "acme", "TOKEN": "secret"},
        )

        joined_args = " ".join(runtime["args"])
        assert "https://acme.example.com/mcp" in joined_args
        assert "Authorization: Bearer secret" in joined_args
