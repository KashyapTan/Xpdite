"""Tests for source/services/integrations/google_auth.py."""

import json
import os
import sys
import types

from source.services.integrations import google_auth as ga


class _FakeCredentials:
    def __init__(
        self,
        *,
        valid=True,
        refresh_token=None,
        expired=False,
        token="access-token",
        json_payload=None,
        refresh_error=None,
    ):
        self.valid = valid
        self.refresh_token = refresh_token
        self.expired = expired
        self.token = token
        self._json_payload = json_payload or {"token": token}
        self._refresh_error = refresh_error

    def refresh(self, _request):
        if self._refresh_error:
            raise self._refresh_error
        self.expired = False
        self.valid = True

    def to_json(self):
        return json.dumps(self._json_payload)


def _install_google_core_stubs(monkeypatch, credentials_obj):
    class _Credentials:
        @staticmethod
        def from_authorized_user_file(_path, _scopes):
            return credentials_obj

    google_mod = types.ModuleType("google")
    oauth2_mod = types.ModuleType("google.oauth2")
    credentials_mod = types.ModuleType("google.oauth2.credentials")
    credentials_mod.Credentials = _Credentials

    auth_mod = types.ModuleType("google.auth")
    transport_mod = types.ModuleType("google.auth.transport")
    requests_mod = types.ModuleType("google.auth.transport.requests")
    requests_mod.Request = type("Request", (), {})

    monkeypatch.setitem(sys.modules, "google", google_mod)
    monkeypatch.setitem(sys.modules, "google.oauth2", oauth2_mod)
    monkeypatch.setitem(sys.modules, "google.oauth2.credentials", credentials_mod)
    monkeypatch.setitem(sys.modules, "google.auth", auth_mod)
    monkeypatch.setitem(sys.modules, "google.auth.transport", transport_mod)
    monkeypatch.setitem(sys.modules, "google.auth.transport.requests", requests_mod)


class TestGoogleAuthService:
    def test_has_token_and_get_status_without_token(self, tmp_path, monkeypatch):
        token_file = tmp_path / "token.json"
        monkeypatch.setattr(ga, "GOOGLE_TOKEN_FILE", str(token_file))
        service = ga.GoogleAuthService()

        assert service.has_token() is False
        assert service.get_status() == {
            "connected": False,
            "email": None,
            "auth_in_progress": False,
        }

    def test_get_status_connected_with_email(self, tmp_path, monkeypatch):
        token_file = tmp_path / "token.json"
        token_file.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(ga, "GOOGLE_TOKEN_FILE", str(token_file))

        service = ga.GoogleAuthService()
        monkeypatch.setattr(
            service,
            "_load_credentials",
            lambda: _FakeCredentials(valid=True, refresh_token="refresh", token="abc"),
        )
        monkeypatch.setattr(
            service, "_get_email_from_token", lambda _creds: "user@example.com"
        )

        assert service.get_status() == {
            "connected": True,
            "email": "user@example.com",
            "auth_in_progress": False,
        }

    def test_load_credentials_refresh_success_writes_new_token(
        self, tmp_path, monkeypatch
    ):
        token_file = tmp_path / "token.json"
        token_file.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(ga, "GOOGLE_TOKEN_FILE", str(token_file))

        creds = _FakeCredentials(
            valid=False,
            refresh_token="refresh-token",
            expired=True,
            json_payload={"token": "new-token"},
        )
        _install_google_core_stubs(monkeypatch, creds)

        service = ga.GoogleAuthService()
        loaded = service._load_credentials()

        assert loaded is creds
        saved = json.loads(token_file.read_text(encoding="utf-8"))
        assert saved["token"] == "new-token"

    def test_load_credentials_refresh_failure_removes_invalid_token(
        self, tmp_path, monkeypatch
    ):
        token_file = tmp_path / "token.json"
        token_file.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(ga, "GOOGLE_TOKEN_FILE", str(token_file))

        creds = _FakeCredentials(
            valid=False,
            refresh_token="refresh-token",
            expired=True,
            refresh_error=RuntimeError("refresh failed"),
        )
        _install_google_core_stubs(monkeypatch, creds)

        service = ga.GoogleAuthService()
        assert service._load_credentials() is None
        assert token_file.exists() is False

    def test_start_oauth_flow_in_progress_guard(self):
        service = ga.GoogleAuthService()
        service._auth_in_progress = True

        result = service.start_oauth_flow()

        assert result == {
            "success": False,
            "error": "Authentication already in progress",
        }

    def test_start_oauth_flow_success(self, tmp_path, monkeypatch):
        token_file = tmp_path / "token.json"
        monkeypatch.setattr(ga, "GOOGLE_TOKEN_FILE", str(token_file))

        fake_creds = _FakeCredentials(json_payload={"token": "saved-token"})

        class _Flow:
            def run_local_server(self, **_kwargs):
                return fake_creds

        class _InstalledAppFlow:
            @staticmethod
            def from_client_config(_client_config, _scopes):
                return _Flow()

        monkeypatch.setitem(
            sys.modules,
            "google_auth_oauthlib.flow",
            types.SimpleNamespace(InstalledAppFlow=_InstalledAppFlow),
        )
        monkeypatch.setattr(
            ga.GoogleAuthService,
            "_get_email_from_token",
            lambda *_args: "ok@example.com",
        )

        service = ga.GoogleAuthService()
        result = service.start_oauth_flow()

        assert result == {"success": True, "email": "ok@example.com"}
        assert service._auth_in_progress is False
        assert (
            json.loads(token_file.read_text(encoding="utf-8"))["token"] == "saved-token"
        )

    def test_start_oauth_flow_failure_resets_state(self, monkeypatch):
        class _Flow:
            def run_local_server(self, **_kwargs):
                raise RuntimeError("oauth exploded")

        class _InstalledAppFlow:
            @staticmethod
            def from_client_config(_client_config, _scopes):
                return _Flow()

        monkeypatch.setitem(
            sys.modules,
            "google_auth_oauthlib.flow",
            types.SimpleNamespace(InstalledAppFlow=_InstalledAppFlow),
        )

        service = ga.GoogleAuthService()
        result = service.start_oauth_flow()

        assert result["success"] is False
        assert isinstance(result.get("error"), str)
        assert result["error"] != ""
        assert service._auth_in_progress is False

    def test_disconnect_revokes_and_removes_token(self, tmp_path, monkeypatch):
        token_file = tmp_path / "token.json"
        token_file.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(ga, "GOOGLE_TOKEN_FILE", str(token_file))

        service = ga.GoogleAuthService()
        monkeypatch.setattr(
            service, "_load_credentials", lambda: _FakeCredentials(token="tok-1")
        )

        calls = []

        def _post(url, params=None, headers=None):
            calls.append((url, params, headers))
            return object()

        monkeypatch.setitem(sys.modules, "requests", types.SimpleNamespace(post=_post))

        result = service.disconnect()

        assert result == {"success": True}
        assert token_file.exists() is False
        assert len(calls) == 1
        assert calls[0][0] == "https://oauth2.googleapis.com/revoke"
        assert calls[0][1] == {"token": "tok-1"}

    def test_disconnect_returns_error_when_remove_fails(self, tmp_path, monkeypatch):
        token_file = tmp_path / "token.json"
        token_file.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(ga, "GOOGLE_TOKEN_FILE", str(token_file))

        service = ga.GoogleAuthService()
        monkeypatch.setattr(service, "_load_credentials", lambda: None)
        monkeypatch.setattr(
            ga.os, "remove", lambda _path: (_ for _ in ()).throw(OSError("nope"))
        )

        result = service.disconnect()

        assert result == {"success": False, "error": "nope"}

    def test_get_email_from_token_falls_back_to_token_json(self, tmp_path, monkeypatch):
        token_file = tmp_path / "token.json"
        token_file.write_text(
            json.dumps({"email": "fallback@example.com"}), encoding="utf-8"
        )
        monkeypatch.setattr(ga, "GOOGLE_TOKEN_FILE", str(token_file))

        class _BrokenService:
            def userinfo(self):
                return self

            def get(self):
                return self

            def execute(self):
                raise RuntimeError("userinfo failure")

        monkeypatch.setitem(
            sys.modules,
            "googleapiclient.discovery",
            types.SimpleNamespace(build=lambda *_args, **_kwargs: _BrokenService()),
        )

        service = ga.GoogleAuthService()
        email = service._get_email_from_token(_FakeCredentials())

        assert email == "fallback@example.com"

    def test_disconnect_no_token_file_is_success(self, tmp_path, monkeypatch):
        token_file = tmp_path / "missing.json"
        monkeypatch.setattr(ga, "GOOGLE_TOKEN_FILE", str(token_file))
        service = ga.GoogleAuthService()

        assert service.disconnect() == {"success": True}
        assert os.path.exists(token_file) is False
