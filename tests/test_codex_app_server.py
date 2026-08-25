from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from source.services.integrations.codex_app_server import (
    CodexAppServerClient,
    CodexConnectorError,
    redact_diagnostic,
)
from source.services.integrations.openai_codex import OpenAICodexService


FAKE_SERVER = Path(__file__).parent / "fixtures" / "fake_codex_app_server.py"


@pytest.fixture()
def codex_client(tmp_path, monkeypatch):
    transcript = tmp_path / "transcript.jsonl"
    monkeypatch.setenv("XPDITE_CODEX_BINARY", str(FAKE_SERVER))
    monkeypatch.setenv("XPDITE_CHATGPT_SUBSCRIPTION_DIR", str(tmp_path / "connector"))
    client = CodexAppServerClient()
    original_build_env = client.build_process_env

    def build_test_env():
        env = original_build_env()
        env["XPDITE_FAKE_CODEX_TRANSCRIPT"] = str(transcript)
        for name in (
            "XPDITE_FAKE_COLLIDE_BEFORE_TURN",
            "XPDITE_FAKE_LARGE_FRAME",
            "XPDITE_FAKE_BAD_VERSION",
            "XPDITE_FAKE_MALFORMED_FRAME",
            "XPDITE_FAKE_STDERR_SECRETS",
            "XPDITE_FAKE_HANG_ACCOUNT",
            "XPDITE_FAKE_MISSING_PLATFORM",
        ):
            if __import__("os").environ.get(name):
                env[name] = "1"
        account_type = __import__("os").environ.get("XPDITE_FAKE_ACCOUNT_TYPE")
        if account_type:
            env["XPDITE_FAKE_ACCOUNT_TYPE"] = account_type
        crash_marker = __import__("os").environ.get("XPDITE_FAKE_CRASH_ONCE_MARKER")
        if crash_marker:
            env["XPDITE_FAKE_CRASH_ONCE_MARKER"] = crash_marker
        return env

    monkeypatch.setattr(client, "build_process_env", build_test_env)
    yield client, transcript
    client.shutdown()


def _transcript(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_python_runtime_override_uses_current_interpreter(tmp_path, monkeypatch):
    fixture = tmp_path / "fixture.py"
    fixture.write_text("print('fixture')\n", encoding="utf-8")
    monkeypatch.setenv("XPDITE_CODEX_BINARY", str(fixture))

    client = CodexAppServerClient()

    assert client.get_launch_command() == [sys.executable, str(fixture.resolve())]


async def test_canonical_handshake_and_bidirectional_id_collision(
    codex_client, monkeypatch
):
    client, transcript_path = codex_client
    monkeypatch.setenv("XPDITE_FAKE_COLLIDE_BEFORE_TURN", "1")
    account = await client.account_read()
    assert account["account"]["type"] == "chatgpt"

    thread = await client.thread_start(
        {
            "model": "fixture-model",
            "cwd": str(client.get_isolated_cwd()),
            "baseInstructions": "exact",
            "ephemeral": True,
            "environments": [],
            "dynamicTools": [
                {
                    "name": "echo",
                    "description": "Echo",
                    "inputSchema": {"type": "object"},
                    "deferLoading": False,
                }
            ],
        }
    )
    thread_id = thread["thread"]["id"]
    stream = await client.create_turn_event_stream(thread_id)
    turn_task = __import__("asyncio").create_task(
        client.turn_start(
            thread_id,
            {"input": [{"type": "text", "text": "hello", "textElements": []}]},
        )
    )
    server_request = await stream.get(timeout=2)
    assert server_request["method"] == "item/tool/call"
    await client.respond_server_request(
        server_request["server_request_id"],
        generation=server_request["generation"],
        result={"contentItems": [{"type": "inputText", "text": "ok"}], "success": True},
    )
    turn = await turn_task
    turn_id = turn["turn"]["id"]
    await stream.set_turn_id(turn_id)

    methods = []
    while "turn/completed" not in methods:
        methods.append((await stream.get(timeout=2))["method"])
    await stream.close()
    assert "item/agentMessage/delta" in methods

    inbound = [
        entry["payload"]
        for entry in _transcript(transcript_path)
        if entry["direction"] == "in"
    ]
    initialize = next(
        message for message in inbound if message.get("method") == "initialize"
    )
    initialized = next(
        message for message in inbound if message.get("method") == "initialized"
    )
    assert initialize["params"]["capabilities"] == {"experimentalApi": True}
    assert "params" not in initialized


async def test_service_uses_account_and_paginated_catalog_without_context_window(
    codex_client,
):
    client, _ = codex_client
    service = OpenAICodexService(client)
    status = await service.get_status_async()
    models = await service.list_models_async(refresh=True)

    assert status["connected"] is True
    assert status["account_type"] == "chatgpt"
    assert status["runtime_version"] == "codex-cli/0.149.1"
    assert [model["id"] for model in models] == ["fixture-model"]
    assert "contextWindow" not in models[0]
    assert models[0]["isDefault"] is True
    assert models[0]["supportedReasoningEfforts"][0]["reasoningEffort"] == "medium"


async def test_rate_limits_request_omits_params(codex_client):
    client, transcript_path = codex_client
    result = await client.rate_limits_read()
    assert result["rateLimits"]["primary"]["usedPercent"] == 12
    inbound = [
        entry["payload"]
        for entry in _transcript(transcript_path)
        if entry["direction"] == "in"
    ]
    request = next(
        message
        for message in inbound
        if message.get("method") == "account/rateLimits/read"
    )
    assert "params" not in request


async def test_protocol_frames_can_exceed_asyncio_default_line_limit(
    codex_client, monkeypatch
):
    client, _ = codex_client
    monkeypatch.setenv("XPDITE_FAKE_LARGE_FRAME", "1")
    result = await client.account_read()
    assert len(result["padding"]) == 128 * 1024


async def test_process_crash_fails_request_once_and_next_request_restarts(
    codex_client, monkeypatch, tmp_path
):
    client, _ = codex_client
    monkeypatch.setenv("XPDITE_FAKE_CRASH_ONCE_MARKER", str(tmp_path / "crashed"))
    with pytest.raises(CodexConnectorError, match="stopped unexpectedly"):
        await client.account_read()
    crashed_generation = client.generation

    result = await client.account_read()

    assert result["account"]["type"] == "chatgpt"
    assert client.generation == crashed_generation + 1


def test_diagnostics_redact_tokens_and_oauth_query_values():
    diagnostic = redact_diagnostic(
        "authorization: Bearer-secret refresh_token=refresh-secret "
        "https://example.test/oauth?code=private"
    )
    assert "Bearer-secret" not in diagnostic
    assert "refresh-secret" not in diagnostic
    assert "code=private" not in diagnostic
    assert diagnostic.count("[REDACTED]") == 3

    json_diagnostic = redact_diagnostic(
        '{"Authorization":"Bearer bearer-secret","access_token":"json-secret",'
        '"nested":{"Cookie":"session=private"}}'
    )
    assert "bearer-secret" not in json_diagnostic
    assert "json-secret" not in json_diagnostic
    assert "session=private" not in json_diagnostic


def test_initialize_accepts_private_home_with_different_path_spelling(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("XPDITE_CHATGPT_SUBSCRIPTION_DIR", str(tmp_path / "Xpdite"))
    client = CodexAppServerClient()
    expected_home = client.get_codex_home()
    reported_home = str(expected_home).replace("Xpdite", "xpdite")
    compared_paths = []

    def samefile(first, second):
        compared_paths.append((first, second))
        return True

    monkeypatch.setattr(
        "source.services.integrations.codex_app_server.os.path.samefile", samefile
    )

    client._validate_initialize_result(
        {
            "userAgent": "Xpdite/0.149.1 (test)",
            "codexHome": reported_home,
            "platformFamily": "unix",
            "platformOs": "test",
        }
    )

    assert compared_paths == [(reported_home, expected_home)]


def test_initialize_rejects_different_private_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XPDITE_CHATGPT_SUBSCRIPTION_DIR", str(tmp_path / "connector"))
    client = CodexAppServerClient()
    monkeypatch.setattr(
        "source.services.integrations.codex_app_server.os.path.samefile",
        lambda _first, _second: False,
    )

    with pytest.raises(CodexConnectorError, match="private connector home") as exc_info:
        client._validate_initialize_result(
            {
                "userAgent": "Xpdite/0.149.1 (test)",
                "codexHome": str(tmp_path / "different-home"),
                "platformFamily": "unix",
                "platformOs": "test",
            }
        )

    assert exc_info.value.code == "codex_protocol_mismatch"


async def test_initialize_rejects_runtime_outside_pinned_protocol(
    codex_client, monkeypatch
):
    client, _ = codex_client
    monkeypatch.setenv("XPDITE_FAKE_BAD_VERSION", "1")
    with pytest.raises(CodexConnectorError, match="version does not match") as exc_info:
        await client.account_read()
    assert exc_info.value.code == "codex_protocol_mismatch"


async def test_initialize_rejects_incomplete_pinned_response(codex_client, monkeypatch):
    client, _ = codex_client
    monkeypatch.setenv("XPDITE_FAKE_MISSING_PLATFORM", "1")
    with pytest.raises(
        CodexConnectorError, match="incomplete initialization"
    ) as exc_info:
        await client.account_read()
    assert exc_info.value.code == "codex_protocol_mismatch"


async def test_concurrent_client_requests_share_one_initialized_process(codex_client):
    client, transcript_path = codex_client
    import asyncio

    results = await asyncio.gather(*(client.account_read() for _ in range(8)))
    assert all(result["account"]["type"] == "chatgpt" for result in results)
    inbound = [
        entry["payload"]
        for entry in _transcript(transcript_path)
        if entry["direction"] == "in"
    ]
    assert sum(message.get("method") == "initialize" for message in inbound) == 1


async def test_timeout_removes_pending_request(codex_client, monkeypatch):
    client, _ = codex_client
    monkeypatch.setenv("XPDITE_FAKE_HANG_ACCOUNT", "1")
    with pytest.raises(CodexConnectorError, match="Timed out"):
        await client.request("account/read", {"refreshToken": False}, timeout=0.05)
    pending_count = await client._run_async(client._pending_count())
    assert pending_count == 0


async def test_malformed_frame_is_ignored_before_valid_handshake(
    codex_client, monkeypatch
):
    client, _ = codex_client
    monkeypatch.setenv("XPDITE_FAKE_MALFORMED_FRAME", "1")
    assert (await client.account_read())["account"]["type"] == "chatgpt"


async def test_stderr_tail_is_bounded_and_structurally_redacted(
    codex_client, monkeypatch
):
    client, _ = codex_client
    monkeypatch.setenv("XPDITE_FAKE_STDERR_SECRETS", "1")
    await client.account_read()
    for _ in range(50):
        if len(client.stderr_tail) == 40:
            break
        await __import__("asyncio").sleep(0.01)
    assert len(client.stderr_tail) == 40
    assert all("secret-" not in line for line in client.stderr_tail)


async def test_non_chatgpt_account_is_not_connected(codex_client, monkeypatch):
    client, _ = codex_client
    monkeypatch.setenv("XPDITE_FAKE_ACCOUNT_TYPE", "apiKey")
    status = await OpenAICodexService(client).get_status_async()
    assert status["connected"] is False
    assert status["account_type"] == "apiKey"


async def test_stale_server_response_is_rejected_by_generation(codex_client):
    client, _ = codex_client
    await client.account_read()
    with pytest.raises(CodexConnectorError, match="stale"):
        await client.respond_server_request(
            1, generation=client.generation - 1, result={}
        )
    assert (await client.account_read())["account"]["type"] == "chatgpt"


def test_browser_and_device_login_state_shapes(codex_client):
    client, _ = codex_client
    service = OpenAICodexService(client)
    browser = service.start_browser_login()
    assert browser["connection_state"] == "authenticating"
    assert browser["auth_url"].startswith("https://example.test/login")

    service.cancel_login()
    device = service.start_device_login()
    assert device["verification_url"] == "https://example.test/device"
    assert device["user_code"] == "ABCD-EFGH"

    service.disconnect()
    inbound = [
        entry["payload"]
        for entry in _transcript(codex_client[1])
        if entry["direction"] == "in"
    ]
    logout = next(
        message for message in inbound if message.get("method") == "account/logout"
    )
    assert "params" not in logout
