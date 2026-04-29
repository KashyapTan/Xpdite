"""Tests for ChatGPT subscription auth integration."""

import base64
import json
import os
from unittest.mock import MagicMock

import source.services.integrations.openai_codex as openai_codex_module
from source.services.integrations.openai_codex import OpenAICodexService


def _fake_jwt(payload: dict) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode(
        "ascii"
    )
    encoded = encoded.rstrip("=")
    return f"header.{encoded}.signature"


def test_configure_litellm_environment_converts_codex_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("XPDITE_CHATGPT_SUBSCRIPTION_DIR", str(tmp_path))
    service = OpenAICodexService()

    access_token = _fake_jwt(
        {
            "exp": 2_000_000_000,
            "https://api.openai.com/auth": {"chatgpt_account_id": "acct_123"},
        }
    )
    id_token = _fake_jwt({"email": "user@example.test"})
    codex_auth = service.get_codex_home() / "auth.json"
    codex_auth.write_text(
        json.dumps(
            {
                "auth_mode": "chatgpt",
                "tokens": {
                    "access_token": access_token,
                    "refresh_token": "refresh-token",
                    "id_token": id_token,
                },
            }
        ),
        encoding="utf-8",
    )

    token_dir = service.configure_litellm_environment()

    assert token_dir == tmp_path / "litellm-chatgpt"
    assert token_dir == service.get_chatgpt_token_dir()
    assert service.get_litellm_auth_file().exists()
    litellm_auth = json.loads(service.get_litellm_auth_file().read_text())
    assert litellm_auth["access_token"] == access_token
    assert litellm_auth["refresh_token"] == "refresh-token"
    assert litellm_auth["id_token"] == id_token
    assert litellm_auth["expires_at"] == 2_000_000_000
    assert litellm_auth["account_id"] == "acct_123"


def test_get_status_reads_local_auth_without_starting_app_server(tmp_path, monkeypatch):
    monkeypatch.setenv("XPDITE_CHATGPT_SUBSCRIPTION_DIR", str(tmp_path))
    service = OpenAICodexService()
    service._call = MagicMock(side_effect=AssertionError("should not start app-server"))
    service.get_codex_binary_path = MagicMock(
        side_effect=AssertionError("should not inspect Codex binary on status")
    )

    id_token = _fake_jwt({"email": "user@example.test"})
    service.get_litellm_auth_file().write_text(
        json.dumps(
            {
                "access_token": _fake_jwt({"exp": 2_000_000_000}),
                "refresh_token": "refresh-token",
                "id_token": id_token,
                "expires_at": 2_000_000_000,
                "account_id": "acct_123",
            }
        ),
        encoding="utf-8",
    )

    status = service.get_status()

    assert status["connected"] is True
    assert status["available"] is True
    assert status["account_type"] == "chatgpt"
    assert status["email"] == "user@example.test"
    service._call.assert_not_called()
    service.get_codex_binary_path.assert_not_called()


def test_get_status_disconnected_does_not_inspect_codex_binary(tmp_path, monkeypatch):
    monkeypatch.setenv("XPDITE_CHATGPT_SUBSCRIPTION_DIR", str(tmp_path))
    service = OpenAICodexService()
    service.get_codex_binary_path = MagicMock(
        side_effect=AssertionError("should not inspect Codex binary on status")
    )

    status = service.get_status()

    assert status["connected"] is False
    assert status["available"] is True
    assert status["binary_path"] is None
    service.get_codex_binary_path.assert_not_called()


def test_list_models_does_not_start_or_probe_codex_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("XPDITE_CHATGPT_SUBSCRIPTION_DIR", str(tmp_path))
    service = OpenAICodexService()
    service._call = MagicMock(side_effect=AssertionError("should not start app-server"))
    service.get_codex_binary_path = MagicMock(
        side_effect=AssertionError("should not inspect Codex binary while listing models")
    )

    models = service.list_models()

    assert models
    service._call.assert_not_called()
    service.get_codex_binary_path.assert_not_called()


def test_disconnect_removes_legacy_auth_without_remigration(tmp_path, monkeypatch):
    user_data = tmp_path / "user_data"
    monkeypatch.setenv("XPDITE_USER_DATA_DIR", str(user_data))
    monkeypatch.setattr(openai_codex_module, "USER_DATA_DIR", user_data)
    service = OpenAICodexService()
    service._call = MagicMock(side_effect=AssertionError("should not start app-server"))

    id_token = _fake_jwt({"email": "user@example.test"})
    auth_payload = {
        "access_token": _fake_jwt({"exp": 2_000_000_000}),
        "refresh_token": "refresh-token",
        "id_token": id_token,
    }
    legacy_auth = service._legacy_codex_home() / "auth.json"
    codex_auth = service.get_codex_home() / "auth.json"
    litellm_auth = service.get_litellm_auth_file()
    for path in (legacy_auth, codex_auth, litellm_auth):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(auth_payload), encoding="utf-8")

    status = service.disconnect()

    assert status["connected"] is False
    assert not legacy_auth.exists()
    assert not codex_auth.exists()
    assert not litellm_auth.exists()


def test_helper_process_env_strips_application_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("XPDITE_CHATGPT_SUBSCRIPTION_DIR", str(tmp_path))
    monkeypatch.setenv("XPDITE_SERVER_TOKEN", "server-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    service = OpenAICodexService()

    env = service.build_process_env()

    assert "XPDITE_SERVER_TOKEN" not in env
    assert "OPENAI_API_KEY" not in env
    assert env["CODEX_HOME"] == str(service.get_codex_home())
    assert env["CHATGPT_TOKEN_DIR"] == str(service.get_chatgpt_token_dir())
    assert env["CHATGPT_AUTH_FILE"] == "auth.json"


def test_unexpected_helper_exit_returns_sanitized_pending_error():
    service = OpenAICodexService()
    process = object()
    response_queue = openai_codex_module.queue.Queue(maxsize=1)
    service._process = process  # type: ignore[assignment]
    service._pending[1] = response_queue
    service._recent_stderr = ["internal path C:\\Users\\secret\\auth.json"]

    service._handle_process_end(process)  # type: ignore[arg-type]

    response = response_queue.get_nowait()
    assert response["error"]["message"] == "Codex app-server stopped unexpectedly."
    assert "secret" not in response["error"]["message"]


def test_auth_files_are_private_on_posix(tmp_path, monkeypatch):
    if os.name != "posix":
        return

    monkeypatch.setenv("XPDITE_CHATGPT_SUBSCRIPTION_DIR", str(tmp_path))
    service = OpenAICodexService()
    auth_file = service.get_litellm_auth_file()

    openai_codex_module._write_json_file(auth_file, {"refresh_token": "refresh-token"})

    assert oct(service.get_storage_root().stat().st_mode & 0o777) == "0o700"
    assert oct(service.get_chatgpt_token_dir().stat().st_mode & 0o777) == "0o700"
    assert oct(auth_file.stat().st_mode & 0o777) == "0o600"
