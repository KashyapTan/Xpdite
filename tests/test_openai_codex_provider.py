from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

import source.llm.providers.openai_codex_provider as provider_module
from source.llm.providers.openai_codex_provider import stream_openai_codex_chat
from source.services.integrations.codex_app_server import CodexAppServerClient
from source.services.integrations.openai_codex import OpenAICodexService


FAKE_SERVER = Path(__file__).parent / "fixtures" / "fake_codex_app_server.py"


@pytest.fixture()
def provider_runtime(tmp_path, monkeypatch):
    transcript = tmp_path / "provider-transcript.jsonl"
    monkeypatch.setenv("XPDITE_CODEX_BINARY", str(FAKE_SERVER))
    monkeypatch.setenv("XPDITE_CHATGPT_SUBSCRIPTION_DIR", str(tmp_path / "connector"))
    client = CodexAppServerClient()
    original_build_env = client.build_process_env

    def build_test_env():
        env = original_build_env()
        env["XPDITE_FAKE_CODEX_TRANSCRIPT"] = str(transcript)
        for name in (
            "XPDITE_FAKE_FAILED_TURN",
            "XPDITE_FAKE_FORBIDDEN_ITEM",
            "XPDITE_FAKE_COLLIDE_BEFORE_TURN",
            "XPDITE_FAKE_RAW_REASONING",
            "XPDITE_FAKE_REASONING_FINAL_ONLY",
            "XPDITE_FAKE_EMPTY_OUTPUT",
            "XPDITE_FAKE_MULTIPLE_MESSAGES",
            "XPDITE_FAKE_TEXT_ONLY_MODEL",
        ):
            if __import__("os").environ.get(name):
                env[name] = "1"
        auth_error_marker = __import__("os").environ.get(
            "XPDITE_FAKE_AUTH_ERROR_ONCE_MARKER"
        )
        if auth_error_marker:
            env["XPDITE_FAKE_AUTH_ERROR_ONCE_MARKER"] = auth_error_marker
        return env

    monkeypatch.setattr(client, "build_process_env", build_test_env)
    service = OpenAICodexService(client)
    monkeypatch.setattr(provider_module, "openai_codex", service)
    yield service, transcript
    client.shutdown()


def _inbound(path: Path) -> list[dict]:
    entries = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
    ]
    return [entry["payload"] for entry in entries if entry["direction"] == "in"]


async def test_exact_prompt_history_current_input_and_stream_contract(
    provider_runtime, monkeypatch
):
    _, transcript_path = provider_runtime
    monkeypatch.setattr(
        "source.mcp_integration.core.manager.mcp_manager.get_tools", lambda: []
    )
    events: list[tuple[str, object]] = []

    async def emit(event_type, content):
        events.append((event_type, content))

    result = await stream_openai_codex_chat(
        "fixture-model",
        "current user",
        [],
        [
            {"role": "user", "content": "prior user"},
            {"role": "assistant", "content": "prior assistant"},
        ],
        allowed_tool_names=set(),
        system_prompt="BYTE-FOR-BYTE XPDITE PROMPT",
        reasoning_effort="low",
        event_broadcaster=emit,
    )

    assert result[0] == "Hello from ChatGPT"
    assert result[1]["prompt_eval_count"] == 6
    assert result[1]["cached_tokens"] == 2
    assert [content for kind, content in events if kind == "response_chunk"] == [
        "Hello ",
        "from ChatGPT",
    ]
    assert [kind for kind, _ in events if kind.startswith("thinking")] == [
        "thinking_chunk",
        "thinking_complete",
    ]
    assert [kind for kind, _ in events].index("thinking_complete") < [
        kind for kind, _ in events
    ].index("response_chunk")
    assert [kind for kind, _ in events][-2:] == ["response_complete", "token_usage"]
    assert result[3] and [block["type"] for block in result[3]] == [
        "thinking",
        "text",
    ]
    assert result[3][0]["content"] == "Checking. "

    inbound = _inbound(transcript_path)
    thread_start = next(
        message for message in inbound if message.get("method") == "thread/start"
    )
    params = thread_start["params"]
    assert params["model"] == "fixture-model"
    assert params["baseInstructions"] == "BYTE-FOR-BYTE XPDITE PROMPT"
    assert params["ephemeral"] is True
    assert params["environments"] == []
    assert params["dynamicTools"] == []
    assert params["config"]["project_doc_max_bytes"] == 0
    assert params["config"]["features.codex_hooks"] is False
    assert "include_apply_patch_tool" not in params["config"]
    assert "features.collab" not in params["config"]
    assert Path(params["cwd"]).name == "runtime-empty"

    injected = next(
        message for message in inbound if message.get("method") == "thread/inject_items"
    )
    assert [item["role"] for item in injected["params"]["items"]] == [
        "user",
        "assistant",
    ]
    assert "current user" not in json.dumps(injected)
    turn_start = next(
        message for message in inbound if message.get("method") == "turn/start"
    )
    assert turn_start["params"]["summary"] == "auto"
    assert turn_start["params"]["effort"] == "low"
    assert [
        item
        for item in turn_start["params"]["input"]
        if item.get("text") == "current user"
    ] == [{"type": "text", "text": "current user", "textElements": []}]
    assert sum(message.get("method") == "account/read" for message in inbound) == 1


async def test_dynamic_tool_server_request_uses_private_alias_map(
    provider_runtime, monkeypatch
):
    _, transcript_path = provider_runtime
    tool_schema = {
        "type": "function",
        "function": {
            "name": "invalid.tool/name",
            "description": "Fixture tool",
            "parameters": {
                "type": "object",
                "properties": {"value": {"type": "integer"}},
            },
        },
    }
    monkeypatch.setattr(
        "source.mcp_integration.core.manager.mcp_manager.get_tools",
        lambda: [tool_schema],
    )
    execute = AsyncMock(return_value="tool-result")
    monkeypatch.setattr(provider_module.xpdite_tool_executor, "execute", execute)

    async def emit(_event_type, _content):
        return None

    response, _, _, _ = await stream_openai_codex_chat(
        "fixture-model",
        "use a tool",
        [],
        [],
        allowed_tool_names={"invalid.tool/name"},
        system_prompt="prompt",
        event_broadcaster=emit,
    )
    assert response == "Hello from ChatGPT"
    execute.assert_awaited_once()
    assert execute.await_args.args[0] == "invalid.tool/name"

    inbound = _inbound(transcript_path)
    thread_start = next(
        message for message in inbound if message.get("method") == "thread/start"
    )
    alias = thread_start["params"]["dynamicTools"][0]["name"]
    assert alias.startswith("xpdite_")
    tool_response = next(
        message
        for message in inbound
        if message.get("id") is not None
        and "result" in message
        and "method" not in message
    )
    assert tool_response["result"] == {
        "contentItems": [{"type": "inputText", "text": "tool-result"}],
        "success": True,
    }


async def test_attachment_encoding_runs_off_event_loop(provider_runtime, monkeypatch):
    monkeypatch.setattr(
        "source.mcp_integration.core.manager.mcp_manager.get_tools", lambda: []
    )
    prepare = AsyncMock(
        return_value=([], [{"type": "text", "text": "hello", "textElements": []}])
    )
    monkeypatch.setattr(provider_module, "run_in_thread", prepare)

    async def emit(_event_type, _content):
        return None

    await stream_openai_codex_chat(
        "fixture-model", "hello", [], [], system_prompt="prompt", event_broadcaster=emit
    )

    prepare.assert_awaited_once_with(
        provider_module._prepare_codex_inputs, "hello", [], []
    )


async def test_cancel_interrupts_turn_without_success_terminal(
    provider_runtime, monkeypatch
):
    _, transcript_path = provider_runtime
    monkeypatch.setattr(
        "source.mcp_integration.core.manager.mcp_manager.get_tools", lambda: []
    )

    def cancelled_after_turn_start():
        return transcript_path.exists() and any(
            message.get("method") == "turn/start"
            for message in _inbound(transcript_path)
        )

    monkeypatch.setattr(
        provider_module, "is_current_request_cancelled", cancelled_after_turn_start
    )
    events = []

    async def emit(event_type, content):
        events.append((event_type, content))

    response, _, _, _ = await stream_openai_codex_chat(
        "fixture-model",
        "cancel",
        [],
        [],
        system_prompt="prompt",
        event_broadcaster=emit,
    )

    assert response == ""
    assert "response_complete" not in [event_type for event_type, _ in events]
    assert "error" not in [event_type for event_type, _ in events]
    assert any(
        message.get("method") == "turn/interrupt"
        for message in _inbound(transcript_path)
    )


async def test_cancelled_before_entry_does_not_start_connector(
    provider_runtime, monkeypatch
):
    _, transcript_path = provider_runtime
    monkeypatch.setattr(provider_module, "is_current_request_cancelled", lambda: True)

    async def emit(_event_type, _content):
        raise AssertionError("pre-cancelled request must not broadcast")

    response, _, _, _ = await stream_openai_codex_chat(
        "fixture-model",
        "cancel",
        [],
        [],
        system_prompt="prompt",
        event_broadcaster=emit,
    )

    assert response == ""
    assert not transcript_path.exists()


async def test_failed_turn_emits_only_safe_error(provider_runtime, monkeypatch):
    monkeypatch.setenv("XPDITE_FAKE_FAILED_TURN", "1")
    monkeypatch.setattr(
        "source.mcp_integration.core.manager.mcp_manager.get_tools", lambda: []
    )
    events = []

    async def emit(event_type, content):
        events.append((event_type, content))

    response, _, _, _ = await stream_openai_codex_chat(
        "fixture-model", "fail", [], [], system_prompt="prompt", event_broadcaster=emit
    )

    assert response == ""
    assert events == [("error", "The ChatGPT model turn failed. Please try again.")]


async def test_forbidden_builtin_fails_closed_and_interrupts(
    provider_runtime, monkeypatch
):
    _, transcript_path = provider_runtime
    monkeypatch.setenv("XPDITE_FAKE_FORBIDDEN_ITEM", "1")
    monkeypatch.setattr(
        "source.mcp_integration.core.manager.mcp_manager.get_tools", lambda: []
    )
    events = []

    async def emit(event_type, content):
        events.append((event_type, content))

    await stream_openai_codex_chat(
        "fixture-model",
        "unsafe",
        [],
        [],
        system_prompt="prompt",
        event_broadcaster=emit,
    )

    assert events == [
        (
            "error",
            "The ChatGPT runtime attempted a tool outside Xpdite's allowed tool boundary.",
        )
    ]
    assert any(
        message.get("method") == "turn/interrupt"
        for message in _inbound(transcript_path)
    )


async def test_missing_image_fails_before_thread_creation(
    provider_runtime, monkeypatch
):
    _, transcript_path = provider_runtime
    monkeypatch.setattr(
        "source.mcp_integration.core.manager.mcp_manager.get_tools", lambda: []
    )
    events = []

    async def emit(event_type, content):
        events.append((event_type, content))

    await stream_openai_codex_chat(
        "fixture-model",
        "image",
        ["/definitely/missing/image.png"],
        [],
        system_prompt="prompt",
        event_broadcaster=emit,
    )

    assert events == [
        (
            "error",
            "An attached image could not be read by the ChatGPT connector.",
        )
    ]
    assert not any(
        message.get("method") == "thread/start" for message in _inbound(transcript_path)
    )


async def test_tool_request_before_turn_start_response_cannot_deadlock(
    provider_runtime, monkeypatch
):
    monkeypatch.setenv("XPDITE_FAKE_COLLIDE_BEFORE_TURN", "1")
    tool_schema = {
        "type": "function",
        "function": {
            "name": "echo",
            "description": "Echo",
            "parameters": {"type": "object"},
        },
    }
    monkeypatch.setattr(
        "source.mcp_integration.core.manager.mcp_manager.get_tools",
        lambda: [tool_schema],
    )
    monkeypatch.setattr(
        provider_module.xpdite_tool_executor, "execute", AsyncMock(return_value="ok")
    )

    async def emit(_event_type, _content):
        return None

    result = await __import__("asyncio").wait_for(
        stream_openai_codex_chat(
            "fixture-model",
            "tool",
            [],
            [],
            allowed_tool_names={"echo"},
            system_prompt="prompt",
            event_broadcaster=emit,
        ),
        timeout=2,
    )
    assert result[0] == "Hello from ChatGPT"


def test_existing_image_data_url_is_preserved_without_filesystem_access():
    data_url = "data:image/png;base64,aGVsbG8="
    history, current = provider_module._prepare_codex_inputs(
        "image",
        [data_url],
        [{"role": "user", "content": "prior", "images": [data_url]}],
    )
    assert history[0]["content"][1]["image_url"] == data_url
    assert current[0]["url"] == data_url


def test_text_history_and_tool_schemas_are_bounded(monkeypatch):
    monkeypatch.setattr(provider_module, "_MAX_TEXT_INPUT_BYTES", 8)
    with pytest.raises(provider_module.CodexConnectorError) as history_error:
        provider_module._prepare_codex_inputs(
            "current", [], [{"role": "user", "content": "prior history"}]
        )
    assert history_error.value.code == "chatgpt_context_limit"

    deeply_nested = {"type": "object", "properties": {}}
    cursor = deeply_nested["properties"]
    for index in range(provider_module._MAX_SCHEMA_DEPTH + 2):
        nested = {"type": "object", "properties": {}}
        cursor[str(index)] = nested
        cursor = nested["properties"]
    with pytest.raises(provider_module.CodexConnectorError) as schema_error:
        provider_module.build_dynamic_tools(
            [
                {
                    "type": "function",
                    "function": {
                        "name": "deep",
                        "description": "deep",
                        "parameters": deeply_nested,
                    },
                }
            ],
            {"deep"},
        )
    assert schema_error.value.code == "chatgpt_tool_protocol_error"


def test_context_window_exceeded_failure_is_normalized():
    code, message = provider_module._safe_turn_error(
        {"error": {"codexErrorInfo": "ContextWindowExceeded"}}, None
    )
    assert code == "chatgpt_context_limit"
    assert "context limit" in message


async def test_pre_turn_auth_expiry_forces_one_managed_refresh_and_retries(
    provider_runtime, monkeypatch, tmp_path
):
    _, transcript_path = provider_runtime
    monkeypatch.setenv(
        "XPDITE_FAKE_AUTH_ERROR_ONCE_MARKER", str(tmp_path / "auth-error-seen")
    )
    monkeypatch.setattr(
        "source.mcp_integration.core.manager.mcp_manager.get_tools", lambda: []
    )

    async def emit(_event_type, _content):
        return None

    result = await stream_openai_codex_chat(
        "fixture-model",
        "refresh",
        [],
        [],
        system_prompt="prompt",
        event_broadcaster=emit,
    )
    assert result[0] == "Hello from ChatGPT"
    inbound = _inbound(transcript_path)
    assert sum(message.get("method") == "model/list" for message in inbound) == 3
    assert any(
        message.get("method") == "account/read"
        and message.get("params", {}).get("refreshToken") is True
        for message in inbound
    )


async def test_raw_reasoning_is_not_broadcast_without_explicit_policy(
    provider_runtime, monkeypatch
):
    monkeypatch.setenv("XPDITE_FAKE_RAW_REASONING", "1")
    monkeypatch.setattr(
        "source.mcp_integration.core.manager.mcp_manager.get_tools", lambda: []
    )
    events = []

    async def emit(event_type, content):
        events.append((event_type, content))

    await stream_openai_codex_chat(
        "fixture-model",
        "reason",
        [],
        [],
        system_prompt="prompt",
        event_broadcaster=emit,
    )
    thinking = "".join(
        str(content) for kind, content in events if kind == "thinking_chunk"
    )
    assert thinking == "Checking. "
    assert "PRIVATE" not in json.dumps(events)


async def test_completed_reasoning_item_supplies_summary_when_delta_was_missed(
    provider_runtime, monkeypatch
):
    monkeypatch.setenv("XPDITE_FAKE_REASONING_FINAL_ONLY", "1")
    monkeypatch.setattr(
        "source.mcp_integration.core.manager.mcp_manager.get_tools", lambda: []
    )
    events = []

    async def emit(event_type, content):
        events.append((event_type, content))

    result = await stream_openai_codex_chat(
        "fixture-model",
        "reason",
        [],
        [],
        system_prompt="prompt",
        event_broadcaster=emit,
    )

    assert [event for event in events if event[0].startswith("thinking")] == [
        ("thinking_chunk", "Checking. "),
        ("thinking_complete", ""),
    ]
    assert result[3] and result[3][0] == {
        "type": "thinking",
        "content": "Checking. ",
    }


async def test_multiple_agent_items_reconcile_independently(
    provider_runtime, monkeypatch
):
    monkeypatch.setenv("XPDITE_FAKE_MULTIPLE_MESSAGES", "1")
    monkeypatch.setattr(
        "source.mcp_integration.core.manager.mcp_manager.get_tools", lambda: []
    )

    async def emit(_event_type, _content):
        return None

    result = await stream_openai_codex_chat(
        "fixture-model",
        "multiple",
        [],
        [],
        system_prompt="prompt",
        event_broadcaster=emit,
    )
    assert result[0] == "FirstSecond"


async def test_empty_completed_output_becomes_safe_error(provider_runtime, monkeypatch):
    monkeypatch.setenv("XPDITE_FAKE_EMPTY_OUTPUT", "1")
    monkeypatch.setattr(
        "source.mcp_integration.core.manager.mcp_manager.get_tools", lambda: []
    )
    events = []

    async def emit(event_type, content):
        events.append((event_type, content))

    result = await stream_openai_codex_chat(
        "fixture-model", "empty", [], [], system_prompt="prompt", event_broadcaster=emit
    )
    assert result[0] == ""
    assert events[-1] == (
        "error",
        "The ChatGPT model completed without a supported text response.",
    )


async def test_history_images_require_image_capability(provider_runtime, monkeypatch):
    monkeypatch.setenv("XPDITE_FAKE_TEXT_ONLY_MODEL", "1")
    monkeypatch.setattr(
        "source.mcp_integration.core.manager.mcp_manager.get_tools", lambda: []
    )
    events = []

    async def emit(event_type, content):
        events.append((event_type, content))

    await stream_openai_codex_chat(
        "fixture-model",
        "history image",
        [],
        [
            {
                "role": "user",
                "content": "prior",
                "images": ["data:image/png;base64,aGk="],
            }
        ],
        system_prompt="prompt",
        event_broadcaster=emit,
    )
    assert events == [
        ("error", "The selected ChatGPT model does not accept image input.")
    ]


async def test_active_tool_uses_tool_timeout_not_shorter_stream_idle_timeout(
    provider_runtime, monkeypatch
):
    tool_schema = {
        "type": "function",
        "function": {
            "name": "slow",
            "description": "Slow",
            "parameters": {"type": "object"},
        },
    }
    monkeypatch.setattr(
        "source.mcp_integration.core.manager.mcp_manager.get_tools",
        lambda: [tool_schema],
    )
    monkeypatch.setattr(provider_module, "_TURN_IDLE_TIMEOUT", 0.01)

    async def slow_execute(*_args, **_kwargs):
        await __import__("asyncio").sleep(0.05)
        return "done"

    monkeypatch.setattr(provider_module.xpdite_tool_executor, "execute", slow_execute)

    async def emit(_event_type, _content):
        return None

    result = await stream_openai_codex_chat(
        "fixture-model",
        "slow",
        [],
        [],
        allowed_tool_names={"slow"},
        system_prompt="prompt",
        event_broadcaster=emit,
    )
    assert result[0] == "Hello from ChatGPT"


async def test_tool_round_budget_blocks_execution_and_interrupts(
    provider_runtime, monkeypatch
):
    _, transcript_path = provider_runtime
    tool_schema = {
        "type": "function",
        "function": {
            "name": "echo",
            "description": "Echo",
            "parameters": {"type": "object"},
        },
    }
    monkeypatch.setattr(
        "source.mcp_integration.core.manager.mcp_manager.get_tools",
        lambda: [tool_schema],
    )
    monkeypatch.setattr(provider_module, "MAX_MCP_TOOL_ROUNDS", 0)
    execute = AsyncMock(return_value="must-not-run")
    monkeypatch.setattr(provider_module.xpdite_tool_executor, "execute", execute)

    async def emit(_event_type, _content):
        return None

    await stream_openai_codex_chat(
        "fixture-model",
        "budget",
        [],
        [],
        allowed_tool_names={"echo"},
        system_prompt="prompt",
        event_broadcaster=emit,
    )
    execute.assert_not_awaited()
    assert any(
        message.get("method") == "turn/interrupt"
        for message in _inbound(transcript_path)
    )
