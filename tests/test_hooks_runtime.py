"""Tests for Claude-compatible marketplace hook runtime."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from source.infrastructure.database import db
from source.services.chat.tab_manager import TabState
from source.services.hooks_runtime import runtime as hooks_runtime_module
from source.services.hooks_runtime.runtime import HookHandler
from source.services.marketplace import service as marketplace_module
from source.services.skills_runtime.skills import SkillManager


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


@pytest.fixture()
def anyio_backend():
    return "asyncio"


@pytest.fixture()
def hook_runtime_env(tmp_path, monkeypatch):
    db_path = tmp_path / "hooks-runtime.db"
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
    monkeypatch.setattr(marketplace_module.manager, "broadcast_json", AsyncMock())

    monkeypatch.setattr(hooks_runtime_module, "MARKETPLACE_PLUGIN_DATA_DIR", plugin_data_dir)
    monkeypatch.setattr(
        hooks_runtime_module,
        "MARKETPLACE_HOOK_TRANSCRIPTS_DIR",
        hook_transcripts_dir,
    )
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

    runtime = hooks_runtime_module.get_hooks_runtime()
    return service, runtime, tmp_path


@pytest.fixture()
def hook_plugins_root(tmp_path) -> dict[str, Path]:
    root = tmp_path / "hook-plugins"

    active_root = root / "active-hook-plugin"
    _write_json(
        active_root / ".claude-plugin" / "plugin.json",
        {
            "name": "active-hook-plugin",
            "version": "1.0.0",
            "description": "Simple hook-only plugin",
            "hooks": {
                "SessionStart": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "shell": "powershell",
                                "command": "Write-Output '{\"systemMessage\":\"ready\"}'",
                            }
                        ]
                    }
                ]
            },
        },
    )

    configurable_root = root / "configurable-hook-plugin"
    _write_json(
        configurable_root / ".claude-plugin" / "plugin.json",
        {
            "name": "configurable-hook-plugin",
            "version": "1.0.0",
            "description": "Hook plugin with user config",
            "userConfig": {
                "api_token": {
                    "description": "API token",
                    "sensitive": True,
                }
            },
            "hooks": {
                "SessionStart": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "shell": "powershell",
                                "command": "Write-Output '${user_config.api_token}'",
                            }
                        ]
                    }
                ]
            },
        },
    )

    merged_root = root / "merged-hook-plugin"
    _write_json(
        merged_root / ".claude-plugin" / "plugin.json",
        {
            "name": "merged-hook-plugin",
            "version": "1.0.0",
            "description": "Merged hook sources",
            "userConfig": {
                "api_token": {
                    "description": "Token",
                    "sensitive": True,
                }
            },
            "hooks": [
                "./hooks/security.json",
                {
                    "hooks": {
                        "SessionStart": [
                            {
                                "hooks": [
                                    {
                                        "type": "command",
                                        "shell": "powershell",
                                        "command": "Write-Output '${user_config.api_token}'",
                                        "allowedEnvVars": [
                                            "CLAUDE_PLUGIN_OPTION_API_TOKEN",
                                            "TRACE_TOKEN",
                                        ],
                                    }
                                ]
                            }
                        ]
                    }
                },
            ],
        },
    )
    _write_json(
        merged_root / "hooks" / "security.json",
        {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [
                            {
                                "type": "command",
                                "shell": "powershell",
                                "command": "Write-Output '${CLAUDE_PLUGIN_ROOT}'",
                            }
                        ],
                    }
                ]
            }
        },
    )

    return {
        "active": active_root,
        "configurable": configurable_root,
        "merged": merged_root,
    }


def test_normalize_plugin_hooks_merges_sources_and_user_config(
    hook_runtime_env,
    hook_plugins_root,
):
    _service, runtime, _tmp_path = hook_runtime_env
    plugin_root = hook_plugins_root["merged"]
    plugin_manifest = json.loads(
        (plugin_root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )

    normalized = runtime.normalize_plugin_hooks(
        plugin_manifest,
        install_root=plugin_root,
        install_id="install-merged",
    )

    assert normalized["handler_count"] == 2
    assert normalized["supported_event_count"] == 2
    assert normalized["unsupported_event_count"] == 0
    assert set(normalized["required_secrets"]) == {"api_token", "TRACE_TOKEN"}
    assert normalized["user_config"] == [
        {
            "key": "api_token",
            "description": "Token",
            "sensitive": True,
            "env_var": "CLAUDE_PLUGIN_OPTION_API_TOKEN",
        }
    ]


def test_normalize_plugin_hooks_only_requires_referenced_user_config(
    hook_runtime_env,
    tmp_path,
):
    _service, runtime, _tmp_path = hook_runtime_env
    plugin_root = tmp_path / "unused-config-plugin"
    normalized = runtime.normalize_plugin_hooks(
        {
            "name": "unused-config-plugin",
            "version": "1.0.0",
            "userConfig": {
                "api_token": {"description": "Token", "sensitive": True},
                "optional_label": {"description": "Optional", "sensitive": False},
            },
            "hooks": {
                "SessionStart": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "Write-Output '${user_config.api_token}'",
                            }
                        ]
                    }
                ]
            },
        },
        install_root=plugin_root,
        install_id="unused-config-install",
    )

    assert normalized["required_secrets"] == ["api_token"]


@pytest.mark.anyio
async def test_hook_registration_lifecycle_for_repo_installs(
    hook_runtime_env,
    hook_plugins_root,
):
    service, runtime, _tmp_path = hook_runtime_env

    install = await service.install_repo_async(repo_input=str(hook_plugins_root["active"]))
    assert install["id"] in runtime._registered_installs
    assert install["hook_runtime"]["status"] == "active"

    disabled = await service.disable_install_async(install["id"])
    assert install["id"] not in runtime._registered_installs
    assert disabled["enabled"] is False

    enabled = await service.enable_install_async(install["id"])
    assert enabled["enabled"] is True
    assert install["id"] in runtime._registered_installs

    await service.uninstall_async(install["id"])
    assert install["id"] not in runtime._registered_installs


@pytest.mark.anyio
async def test_supported_events_dispatch_and_apply_mutations(
    hook_runtime_env,
    tmp_path,
    monkeypatch,
):
    _service, runtime, _root = hook_runtime_env
    plugin_root = tmp_path / "dispatch-plugin"
    plugin_manifest = {
        "name": "dispatch-plugin",
        "version": "1.0.0",
        "hooks": {
            "SessionStart": [{"hooks": [{"type": "command", "command": "session"}]}],
            "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "prompt"}]}],
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [{"type": "command", "command": "pre"}],
                }
            ],
            "PostToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [{"type": "command", "command": "post"}],
                }
            ],
            "PostToolUseFailure": [
                {
                    "matcher": "Bash",
                    "hooks": [{"type": "command", "command": "postfail"}],
                }
            ],
            "Stop": [{"hooks": [{"type": "command", "command": "stop"}]}],
        },
    }
    normalized = runtime.normalize_plugin_hooks(
        plugin_manifest,
        install_root=plugin_root,
        install_id="dispatch-install",
    )
    install = {
        "id": "dispatch-install",
        "install_root": str(plugin_root),
        "enabled": True,
        "component_manifest": {"hooks": normalized},
    }
    await runtime.register_install_async(install)

    seen_events: list[str] = []

    async def fake_execute_command_hook(handler, payload, env_map):
        seen_events.append(str(payload["hook_event_name"]))
        assert env_map["CLAUDE_PLUGIN_ROOT"] == str(plugin_root)
        assert env_map["CLAUDE_PLUGIN_DATA"].endswith("dispatch-install")
        event_name = str(payload["hook_event_name"])
        if event_name == "SessionStart":
            return {
                "return_code": 0,
                "stderr": "",
                "json": {"systemMessage": "session-ready"},
            }
        if event_name == "UserPromptSubmit":
            return {
                "return_code": 0,
                "stderr": "",
                "json": {
                    "hookSpecificOutput": {
                        "hookEventName": "UserPromptSubmit",
                        "additionalContext": "prompt-context",
                    }
                },
            }
        if event_name == "PreToolUse":
            return {
                "return_code": 0,
                "stderr": "",
                "json": {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "allow",
                        "updatedInput": {"command": "echo patched"},
                    }
                },
            }
        if event_name == "PostToolUse":
            return {
                "return_code": 0,
                "stderr": "",
                "json": {
                    "hookSpecificOutput": {
                        "hookEventName": "PostToolUse",
                        "additionalContext": "tool-output-context",
                    }
                },
            }
        if event_name == "PostToolUseFailure":
            return {
                "return_code": 0,
                "stderr": "",
                "json": {
                    "hookSpecificOutput": {
                        "hookEventName": "PostToolUseFailure",
                        "decision": "block",
                        "reason": "tool failure blocked",
                    }
                },
            }
        if event_name == "Stop":
            return {
                "return_code": 0,
                "stderr": "",
                "json": {"decision": "block", "reason": "needs continuation"},
            }
        raise AssertionError(f"Unexpected event {event_name}")

    monkeypatch.setattr(runtime, "_execute_command_hook", fake_execute_command_hook)

    tab_state = TabState(tab_id="tab-hooks")
    session_result = await runtime.ensure_session_started(tab_state, source="startup")
    prompt_result = await runtime.dispatch_user_prompt_submit(
        tab_state,
        prompt="review repo",
        llm_prompt="review repo",
        action="chat",
        model="gpt-test",
    )
    pre_tool_result = await runtime.dispatch_pre_tool_use(
        "run_command",
        {"command": "echo hi"},
        server_name="terminal",
        tab_state=tab_state,
    )
    post_tool_result = await runtime.dispatch_post_tool_use(
        "run_command",
        {"command": "echo patched"},
        "ok",
        server_name="terminal",
        tab_state=tab_state,
    )
    post_tool_failure_result = await runtime.dispatch_post_tool_use_failure(
        "run_command",
        {"command": "echo patched"},
        "Error: failed",
        server_name="terminal",
        tab_state=tab_state,
    )
    stop_result = await runtime.dispatch_stop(
        tab_state,
        response_text="done",
        conversation_id="conv-1",
        tool_calls=[],
        action="chat",
        model="gpt-test",
    )

    assert session_result.system_messages == ["session-ready"]
    assert prompt_result.additional_context == ["prompt-context"]
    assert pre_tool_result.updated_input == {"command": "echo patched"}
    assert post_tool_result.additional_context == ["tool-output-context"]
    assert post_tool_failure_result.blocked is True
    assert post_tool_failure_result.reason == "tool failure blocked"
    assert stop_result.blocked is True
    assert stop_result.reason == "needs continuation"
    assert Path(tab_state.hook_session["transcript_path"]).exists()
    assert seen_events == [
        "SessionStart",
        "UserPromptSubmit",
        "PreToolUse",
        "PostToolUse",
        "PostToolUseFailure",
        "Stop",
    ]


@pytest.mark.anyio
async def test_dispatch_pre_tool_use_dedupes_per_install_not_globally(
    hook_runtime_env,
    tmp_path,
    monkeypatch,
):
    _service, runtime, _root = hook_runtime_env
    plugin_manifest = {
        "name": "shared-hook-plugin",
        "version": "1.0.0",
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [{"type": "command", "command": "same-command"}],
                }
            ]
        },
    }
    install_ids = ["shared-install-a", "shared-install-b"]
    for install_id in install_ids:
        normalized = runtime.normalize_plugin_hooks(
            plugin_manifest,
            install_root=tmp_path / install_id,
            install_id=install_id,
        )
        await runtime.register_install_async(
            {
                "id": install_id,
                "install_root": str(tmp_path / install_id),
                "enabled": True,
                "component_manifest": {"hooks": normalized},
            }
        )

    seen_installs: list[str] = []

    async def fake_execute_command_hook(handler, payload, env_map):
        seen_installs.append(handler.install_id)
        return {"return_code": 0, "stderr": "", "json": {"continue": True}}

    monkeypatch.setattr(runtime, "_execute_command_hook", fake_execute_command_hook)

    await runtime.dispatch_pre_tool_use(
        "run_command",
        {"command": "echo hi"},
        server_name="terminal",
    )

    assert seen_installs == install_ids


@pytest.mark.anyio
async def test_hook_timeout_is_non_blocking_and_updates_runtime_state(
    hook_runtime_env,
    tmp_path,
    monkeypatch,
):
    _service, runtime, _root = hook_runtime_env
    plugin_root = tmp_path / "timeout-plugin"
    normalized = runtime.normalize_plugin_hooks(
        {
            "name": "timeout-plugin",
            "version": "1.0.0",
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [{"type": "command", "command": "timeout"}],
                    }
                ]
            },
        },
        install_root=plugin_root,
        install_id="timeout-install",
    )
    install = {
        "id": "timeout-install",
        "install_root": str(plugin_root),
        "enabled": True,
        "component_manifest": {"hooks": normalized},
    }
    await runtime.register_install_async(install)

    async def fake_execute_command_hook(handler, payload, env_map):
        return {"timeout": True, "stderr": "Hook timed out after 1s."}

    monkeypatch.setattr(runtime, "_execute_command_hook", fake_execute_command_hook)

    result = await runtime.dispatch_pre_tool_use(
        "run_command",
        {"command": "echo hi"},
        server_name="terminal",
    )

    assert result.blocked is False
    assert result.runtime_messages == ["Hook timed out after 1s."]
    assert runtime.build_runtime_summary(install)["last_runtime_error"] == "Hook timed out after 1s."


@pytest.mark.anyio
async def test_http_hook_interpolates_allowed_env_vars(
    hook_runtime_env,
    monkeypatch,
):
    _service, runtime, _tmp_path = hook_runtime_env
    captured: dict[str, object] = {}

    class _Response:
        status_code = 200
        ok = True
        text = '{"continue": true}'

        def json(self):
            return {"continue": True}

    def fake_post(url, *, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr(hooks_runtime_module.requests, "post", fake_post)

    handler = HookHandler(
        install_id="http-install",
        hook_id="http-hook",
        event="SessionStart",
        matcher=None,
        condition=None,
        hook_type="http",
        command=None,
        url="https://example.test/${CLAUDE_PLUGIN_ROOT}",
        shell=None,
        timeout_seconds=7.0,
        status_message=None,
        headers={
            "Authorization": "Bearer $CLAUDE_PLUGIN_OPTION_API_TOKEN",
            "X-Unchanged": "$NOT_ALLOWED",
        },
        allowed_env_vars=["CLAUDE_PLUGIN_OPTION_API_TOKEN"],
        supported=True,
        unsupported_reasons=[],
        required_secrets=[],
        source="plugin.json",
        order=1,
        raw={},
    )

    result = await runtime._execute_http_hook(
        handler,
        {"hook_event_name": "SessionStart"},
        {
            "CLAUDE_PLUGIN_ROOT": "plugin-root",
            "CLAUDE_PLUGIN_OPTION_API_TOKEN": "secret-value",
        },
    )

    assert captured["url"] == "https://example.test/plugin-root"
    assert captured["headers"] == {
        "Authorization": "Bearer secret-value",
        "X-Unchanged": "$NOT_ALLOWED",
    }
    assert captured["timeout"] == 7.0
    assert result["http_ok"] is True


@pytest.mark.anyio
async def test_hook_plugin_user_config_requires_auth_until_secret_is_provided(
    hook_runtime_env,
    hook_plugins_root,
):
    service, _runtime, _tmp_path = hook_runtime_env

    install = await service.install_repo_async(
        repo_input=str(hook_plugins_root["configurable"])
    )

    assert install["status"] == "manual_auth_required"
    assert "api_token" in install["required_secrets"]
    assert install["hook_runtime"]["status"] == "blocked"
    assert install["hook_runtime"]["missing_secrets"] == ["api_token"]

    service.set_install_secrets(install["id"], {"api_token": "secret-token"})
    refreshed = await service.enable_install_async(install["id"])

    assert refreshed["hook_runtime"]["missing_secrets"] == []
    assert refreshed["hook_runtime"]["status"] == "active"
