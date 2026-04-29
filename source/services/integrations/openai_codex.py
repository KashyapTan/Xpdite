"""
ChatGPT subscription auth integration.

The local Codex app-server is used only for the supported ChatGPT OAuth flows.
Actual chat generation is routed through LiteLLM's native ``chatgpt`` provider
so Xpdite keeps control of its system prompt, conversation state, and MCP tool
loop.
"""

from __future__ import annotations

import base64
import itertools
import json
import logging
import os
import platform
import queue
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from ...infrastructure.config import PROJECT_ROOT, RUNTIME_ROOT, USER_DATA_DIR

logger = logging.getLogger(__name__)

_RPC_TIMEOUT_SECONDS = 20.0
_CODEX_AUTH_FILENAME = "auth.json"
_LITELLM_AUTH_FILENAME = "auth.json"
_CHATGPT_MODEL_CONTEXT_WINDOW = 400_000
_CHATGPT_MODEL_FALLBACKS = [
    "gpt-5.4",
    "gpt-5.4-pro",
    "gpt-5.3-codex",
    "gpt-5.3-chat-latest",
    "gpt-5.3-instant",
    "gpt-5.2",
]

_PROCESS_ENV_ALLOWLIST = {
    "ALL_PROXY",
    "APPDATA",
    "COMSPEC",
    "CURL_CA_BUNDLE",
    "HOME",
    "HOMEDRIVE",
    "HOMEPATH",
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "LANG",
    "LOCALAPPDATA",
    "NO_PROXY",
    "PATH",
    "PATHEXT",
    "PROGRAMDATA",
    "PROCESSOR_ARCHITECTURE",
    "REQUESTS_CA_BUNDLE",
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "TMPDIR",
    "USER",
    "USERNAME",
    "USERPROFILE",
    "WINDIR",
}
_PROCESS_ENV_PREFIX_ALLOWLIST = ("LC_",)


def _platform_codex_details() -> tuple[str, str, str]:
    machine = platform.machine().lower()

    if sys.platform == "win32":
        if machine in {"arm64", "aarch64"}:
            return ("codex-win32-arm64", "aarch64-pc-windows-msvc", "codex.exe")
        return ("codex-win32-x64", "x86_64-pc-windows-msvc", "codex.exe")

    if sys.platform == "darwin":
        if machine in {"arm64", "aarch64"}:
            return ("codex-darwin-arm64", "aarch64-apple-darwin", "codex")
        return ("codex-darwin-x64", "x86_64-apple-darwin", "codex")

    if sys.platform in {"linux", "android"}:
        if machine in {"arm64", "aarch64"}:
            return ("codex-linux-arm64", "aarch64-unknown-linux-musl", "codex")
        return ("codex-linux-x64", "x86_64-unknown-linux-musl", "codex")

    raise RuntimeError(f"Unsupported platform for Codex runtime: {sys.platform}/{machine}")


def _decode_jwt_claims(token: str | None) -> dict[str, Any]:
    if not token:
        return {}
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        payload = json.loads(payload_bytes.decode("utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _extract_account_id(token: str | None) -> str | None:
    claims = _decode_jwt_claims(token)
    auth_claims = claims.get("https://api.openai.com/auth")
    if isinstance(auth_claims, dict):
        account_id = auth_claims.get("chatgpt_account_id")
        if isinstance(account_id, str) and account_id.strip():
            return account_id.strip()
    return None


def _extract_expires_at(token: str | None) -> int | None:
    claims = _decode_jwt_claims(token)
    exp = claims.get("exp")
    if isinstance(exp, (int, float)):
        return int(exp)
    return None


def _read_json_file(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _restrict_path_permissions(path: Path) -> None:
    if os.name != "posix":
        return
    try:
        path.chmod(0o700 if path.is_dir() else 0o600)
    except OSError as exc:
        logger.debug("Failed to restrict ChatGPT auth path permissions for %s: %s", path, exc)


def _ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _restrict_path_permissions(path)


def _write_text_file_private(path: Path, content: str) -> None:
    _ensure_private_dir(path.parent)
    if os.name == "posix":
        fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
    else:
        path.write_text(content, encoding="utf-8")
    _restrict_path_permissions(path)


def _write_json_file(path: Path, payload: dict[str, Any]) -> None:
    _write_text_file_private(path, json.dumps(payload, separators=(",", ":")))


def _copy_file_private(source: Path, destination: Path) -> None:
    _write_text_file_private(destination, source.read_text(encoding="utf-8"))


def _minimal_process_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for key, value in os.environ.items():
        upper_key = key.upper()
        if (
            upper_key in _PROCESS_ENV_ALLOWLIST
            or any(upper_key.startswith(prefix) for prefix in _PROCESS_ENV_PREFIX_ALLOWLIST)
        ):
            env[key] = value

    if not any(key.upper() == "PATH" for key in env):
        env["PATH"] = os.defpath
    return env


def _display_name_for_model(model: str) -> str:
    return model.replace("-", " ").replace("gpt", "GPT", 1).title().replace("Gpt", "GPT")


class OpenAICodexService:
    """Manage ChatGPT OAuth state and LiteLLM-compatible subscription tokens."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._startup_lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._pending: dict[int, queue.Queue[dict[str, Any]]] = {}
        self._request_ids = itertools.count(1)
        self._initialized = False
        self._binary_path: Path | None = None
        self._auth_in_progress = False
        self._login_method: str | None = None
        self._login_id: str | None = None
        self._auth_url: str | None = None
        self._verification_url: str | None = None
        self._user_code: str | None = None
        self._last_error: str | None = None
        self._auth_mode: str | None = None
        self._plan_type: str | None = None
        self._recent_stderr: list[str] = []

    def get_storage_root(self) -> Path:
        override_text = os.environ.get("XPDITE_CHATGPT_SUBSCRIPTION_DIR", "").strip()
        if override_text:
            root = Path(override_text)
        elif os.environ.get("XPDITE_USER_DATA_DIR", "").strip():
            root = USER_DATA_DIR / "openai-chatgpt-subscription"
        elif sys.platform == "win32":
            base = Path(
                os.environ.get("LOCALAPPDATA")
                or (Path.home() / "AppData" / "Local")
            )
            root = base / "Xpdite" / "openai-chatgpt-subscription"
        elif sys.platform == "darwin":
            root = (
                Path.home()
                / "Library"
                / "Application Support"
                / "Xpdite"
                / "openai-chatgpt-subscription"
            )
        else:
            base = Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state"))
            root = base / "xpdite" / "openai-chatgpt-subscription"

        root.mkdir(parents=True, exist_ok=True)
        _restrict_path_permissions(root)
        return root

    def _uses_storage_override(self) -> bool:
        return bool(os.environ.get("XPDITE_CHATGPT_SUBSCRIPTION_DIR", "").strip())

    def get_codex_home(self) -> Path:
        codex_home = self.get_storage_root() / "codex-app-server"
        _ensure_private_dir(codex_home)
        return codex_home

    def get_chatgpt_token_dir(self) -> Path:
        token_dir = self.get_storage_root() / "litellm-chatgpt"
        _ensure_private_dir(token_dir)
        return token_dir

    def get_litellm_auth_file(self) -> Path:
        return self.get_chatgpt_token_dir() / _LITELLM_AUTH_FILENAME

    def configure_litellm_environment(self) -> Path:
        """Point LiteLLM's ChatGPT provider at Xpdite's token store."""
        self._ensure_auth_migrated()
        token_dir = self.get_chatgpt_token_dir()
        os.environ["CHATGPT_TOKEN_DIR"] = str(token_dir)
        os.environ["CHATGPT_AUTH_FILE"] = _LITELLM_AUTH_FILENAME
        if not os.environ.get("CHATGPT_DEFAULT_INSTRUCTIONS", "").strip():
            os.environ["CHATGPT_DEFAULT_INSTRUCTIONS"] = (
                "Use the application-provided instructions and tool results."
            )
        return token_dir

    def _codex_binary_candidates(
        self,
        package_dir_name: str,
        target_triple: str,
        binary_name: str,
    ) -> list[Path]:
        bundled_rel = Path("codex-runtime") / target_triple / "codex" / binary_name
        return [
            PROJECT_ROOT
            / "node_modules"
            / "@openai"
            / package_dir_name
            / "vendor"
            / target_triple
            / "codex"
            / binary_name,
            RUNTIME_ROOT.parent / bundled_rel,
            Path(sys.executable).resolve().parent / ".." / ".." / bundled_rel,
            Path(sys.executable).resolve().parent / ".." / bundled_rel,
        ]

    def get_codex_binary_path(self) -> Path:
        with self._lock:
            if self._binary_path and self._binary_path.exists():
                return self._binary_path

            env_override_text = os.environ.get("XPDITE_CODEX_BINARY", "").strip()
            if env_override_text:
                env_override = Path(env_override_text)
                if env_override.exists():
                    self._binary_path = env_override.resolve()
                    return self._binary_path
                raise FileNotFoundError(
                    f"Configured Codex binary does not exist: {env_override}"
                )

            package_dir_name, target_triple, binary_name = _platform_codex_details()
            candidates = self._codex_binary_candidates(
                package_dir_name,
                target_triple,
                binary_name,
            )
            for candidate in candidates:
                resolved = candidate.resolve()
                if resolved.exists():
                    self._binary_path = resolved
                    return self._binary_path

            raise FileNotFoundError(
                "OpenAI Codex binary was not found. Reinstall dependencies or rebuild "
                "the packaged app so the Codex auth helper is bundled."
            )

    def build_process_env(self) -> dict[str, str]:
        self.configure_litellm_environment()
        env = _minimal_process_env()
        env["CODEX_HOME"] = str(self.get_codex_home())
        env["CHATGPT_TOKEN_DIR"] = str(self.get_chatgpt_token_dir())
        env["CHATGPT_AUTH_FILE"] = _LITELLM_AUTH_FILENAME
        env["NO_COLOR"] = "1"
        return env

    def get_status(self, refresh_token: bool = False) -> dict[str, Any]:
        del refresh_token
        self.configure_litellm_environment()

        auth = self._read_litellm_auth()
        account = self._account_from_litellm_auth(auth)
        connected = account is not None

        if connected:
            with self._lock:
                self._auth_in_progress = False
                self._last_error = None

        return self._build_status_payload(
            available=True,
            account=account,
            requires_openai_auth=not connected,
            binary_path=str(self._binary_path) if self._binary_path else None,
        )

    def start_browser_login(self) -> dict[str, Any]:
        result = self._call(
            "account/login/start",
            {"type": "chatgpt"},
            timeout=_RPC_TIMEOUT_SECONDS,
        )
        with self._lock:
            self._auth_in_progress = True
            self._login_method = "chatgpt"
            self._login_id = str(result.get("loginId") or "").strip() or None
            self._auth_url = str(result.get("authUrl") or "").strip() or None
            self._verification_url = None
            self._user_code = None
            self._last_error = None
        return self.get_status(refresh_token=False)

    def start_device_login(self) -> dict[str, Any]:
        result = self._call(
            "account/login/start",
            {"type": "chatgptDeviceCode"},
            timeout=_RPC_TIMEOUT_SECONDS,
        )
        with self._lock:
            self._auth_in_progress = True
            self._login_method = "chatgptDeviceCode"
            self._login_id = str(result.get("loginId") or "").strip() or None
            self._auth_url = None
            self._verification_url = str(result.get("verificationUrl") or "").strip() or None
            self._user_code = str(result.get("userCode") or "").strip() or None
            self._last_error = None
        return self.get_status(refresh_token=False)

    def cancel_login(self) -> dict[str, Any]:
        with self._lock:
            login_id = self._login_id
            process_running = self._process is not None and self._process.poll() is None

        if login_id and process_running:
            self._call(
                "account/login/cancel",
                {"loginId": login_id},
                timeout=_RPC_TIMEOUT_SECONDS,
            )

        with self._lock:
            self._reset_login_state_locked()

        return self.get_status(refresh_token=False)

    def disconnect(self) -> dict[str, Any]:
        with self._lock:
            process_running = self._process is not None and self._process.poll() is None

        if process_running:
            try:
                self._call("account/logout", {}, timeout=_RPC_TIMEOUT_SECONDS)
            except Exception as exc:
                logger.debug("Codex app-server logout failed; clearing local auth: %s", exc)

        for path in (
            self.get_litellm_auth_file(),
            self.get_codex_home() / _CODEX_AUTH_FILENAME,
            self._legacy_codex_home() / _CODEX_AUTH_FILENAME,
        ):
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("Failed to remove ChatGPT auth file %s: %s", path, exc)

        with self._lock:
            self._reset_login_state_locked()
            self._auth_mode = None
            self._plan_type = None
            self._last_error = None
        return self.get_status(refresh_token=False)

    def list_models(self, include_hidden: bool = False) -> list[dict[str, Any]]:
        del include_hidden
        self.configure_litellm_environment()
        model_names = self._litellm_chatgpt_model_names()
        return [
            {
                "id": model,
                "model": model,
                "displayName": _display_name_for_model(model),
                "contextWindow": _CHATGPT_MODEL_CONTEXT_WINDOW,
            }
            for model in model_names
        ]

    def _build_status_payload(
        self,
        *,
        available: bool,
        account: dict[str, Any] | None,
        requires_openai_auth: bool,
        binary_path: str | None,
    ) -> dict[str, Any]:
        account_type = str(account.get("type") or "").strip() if account else ""
        email = str(account.get("email") or "").strip() if account else ""
        account_plan_type = account.get("planType") if account else None
        plan_type = str(account_plan_type or self._plan_type or "").strip()

        with self._lock:
            return {
                "available": available,
                "connected": bool(account_type),
                "account_type": account_type or None,
                "email": email or None,
                "plan_type": plan_type or None,
                "requires_openai_auth": requires_openai_auth,
                "auth_in_progress": self._auth_in_progress,
                "login_method": self._login_method,
                "login_id": self._login_id,
                "auth_url": self._auth_url,
                "verification_url": self._verification_url,
                "user_code": self._user_code,
                "auth_mode": self._auth_mode or (account_type or None),
                "last_error": self._last_error,
                "binary_path": binary_path,
            }

    def _call(
        self,
        method: str,
        params: dict[str, Any],
        *,
        timeout: float,
    ) -> dict[str, Any]:
        self._ensure_initialized(timeout=timeout)
        response_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)

        with self._lock:
            request_id = next(self._request_ids)
            self._pending[request_id] = response_queue
            self._write_locked(
                {
                    "id": request_id,
                    "method": method,
                    "params": params,
                }
            )

        response = self._wait_for_response(
            request_id,
            response_queue,
            timeout=timeout,
            method=method,
        )
        return self._response_result(response)

    def _ensure_initialized(self, *, timeout: float) -> None:
        with self._startup_lock:
            with self._lock:
                if (
                    self._process is not None
                    and self._process.poll() is None
                    and self._initialized
                ):
                    return

                self._start_process_locked()
                response_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
                request_id = next(self._request_ids)
                self._pending[request_id] = response_queue
                self._write_locked(
                    {
                        "id": request_id,
                        "method": "initialize",
                        "params": {
                            "clientInfo": {
                                "name": "Xpdite",
                                "version": "0.0.0",
                            },
                            "capabilities": {},
                        },
                    }
                )

            try:
                response = self._wait_for_response(
                    request_id,
                    response_queue,
                    timeout=timeout,
                    method="initialize",
                )
                initialize_result = self._response_result(response)
            except Exception:
                with self._lock:
                    self._teardown_locked()
                raise

            with self._lock:
                self._write_locked({"method": "initialized", "params": {}})
                self._initialized = True

            logger.debug("Codex app-server initialized: %s", initialize_result)

    def _start_process_locked(self) -> None:
        self._teardown_locked()

        binary_path = self.get_codex_binary_path()
        process = subprocess.Popen(
            [str(binary_path), "app-server", "--listen", "stdio://"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
            cwd=str(PROJECT_ROOT),
            env=self.build_process_env(),
        )

        if process.stdin is None or process.stdout is None or process.stderr is None:
            process.kill()
            raise RuntimeError("Failed to open stdio pipes for Codex app-server")

        self._process = process
        self._initialized = False
        self._stdout_thread = threading.Thread(
            target=self._stdout_loop,
            args=(process,),
            name="openai-codex-stdout",
            daemon=True,
        )
        self._stderr_thread = threading.Thread(
            target=self._stderr_loop,
            args=(process,),
            name="openai-codex-stderr",
            daemon=True,
        )
        self._stdout_thread.start()
        self._stderr_thread.start()

    def _wait_for_response(
        self,
        request_id: int,
        response_queue: queue.Queue[dict[str, Any]],
        *,
        timeout: float,
        method: str,
    ) -> dict[str, Any]:
        try:
            return response_queue.get(timeout=timeout)
        except queue.Empty as exc:
            with self._lock:
                self._pending.pop(request_id, None)
            raise TimeoutError(
                f"Timed out waiting for Codex app-server response to {method}"
            ) from exc

    def _response_result(self, response: dict[str, Any]) -> dict[str, Any]:
        if "error" in response:
            error_obj = response.get("error")
            if isinstance(error_obj, dict):
                message = str(error_obj.get("message") or error_obj)
            else:
                message = str(error_obj)
            raise RuntimeError(message[:300])

        result = response.get("result")
        if isinstance(result, dict):
            return result
        return {}

    def _write_locked(self, payload: dict[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None or process.poll() is not None:
            raise RuntimeError("Codex app-server is not running")

        try:
            process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
            process.stdin.flush()
        except Exception as exc:
            self._teardown_locked()
            raise RuntimeError("Failed to write to Codex app-server") from exc

    def _stdout_loop(self, process: subprocess.Popen[str]) -> None:
        if process.stdout is None:
            return

        try:
            for raw_line in process.stdout:
                line = raw_line.strip()
                if not line:
                    continue

                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    logger.debug("Ignoring non-JSON Codex app-server stdout line: %s", line[:200])
                    continue

                self._handle_message(process, payload)
        finally:
            self._handle_process_end(process)

    def _stderr_loop(self, process: subprocess.Popen[str]) -> None:
        if process.stderr is None:
            return

        for raw_line in process.stderr:
            line = raw_line.rstrip()
            if not line:
                continue
            with self._lock:
                self._recent_stderr.append(line)
                self._recent_stderr = self._recent_stderr[-30:]
            logger.debug("Codex app-server stderr: %s", line[:500])

    def _handle_message(
        self,
        process: subprocess.Popen[str],
        payload: dict[str, Any],
    ) -> None:
        with self._lock:
            if process is not self._process:
                return

            request_id = payload.get("id")
            if isinstance(request_id, int):
                pending = self._pending.pop(request_id, None)
                if pending is not None:
                    pending.put(payload)
                return

            method = payload.get("method")
            params = payload.get("params")
            if isinstance(method, str):
                self._apply_notification_locked(method, params if isinstance(params, dict) else {})

    def _apply_notification_locked(
        self,
        method: str,
        params: dict[str, Any],
    ) -> None:
        if method == "account/login/completed":
            success = bool(params.get("success"))
            error_message = str(params.get("error") or "").strip() or None
            self._auth_in_progress = False
            if success:
                self._last_error = None
                self._reset_login_state_locked(clear_error=False)
            else:
                self._last_error = error_message or "ChatGPT sign-in failed."
                self._reset_login_state_locked(clear_error=False)
        elif method == "account/updated":
            auth_mode = str(params.get("authMode") or "").strip()
            plan_type = str(params.get("planType") or "").strip()
            self._auth_mode = auth_mode or None
            self._plan_type = plan_type or None

        if method in {"account/login/completed", "account/updated"}:
            try:
                self._sync_litellm_auth_from_codex()
            except Exception as exc:
                logger.debug("Failed to sync ChatGPT auth for LiteLLM: %s", exc)

    def _handle_process_end(self, process: subprocess.Popen[str]) -> None:
        with self._lock:
            if process is not self._process:
                return

            disconnect_message = "Codex app-server stopped unexpectedly."
            stderr_tail = "\n".join(self._recent_stderr[-5:]).strip()
            if stderr_tail:
                logger.debug("Codex app-server stderr before unexpected stop: %s", stderr_tail[:1000])

            for pending in self._pending.values():
                pending.put(
                    {
                        "error": {
                            "message": disconnect_message,
                        }
                    }
                )
            self._pending.clear()
            self._process = None
            self._initialized = False

    def _reset_login_state_locked(self, *, clear_error: bool = True) -> None:
        self._auth_in_progress = False
        self._login_method = None
        self._login_id = None
        self._auth_url = None
        self._verification_url = None
        self._user_code = None
        if clear_error:
            self._last_error = None

    def _teardown_locked(self) -> None:
        process = self._process
        self._process = None
        self._initialized = False

        for pending in self._pending.values():
            pending.put(
                {
                    "error": {
                        "message": "Codex app-server connection reset.",
                    }
                }
            )
        self._pending.clear()

        if process is None:
            return

        try:
            if process.stdin:
                process.stdin.close()
        except Exception:
            pass

        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=3)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass

    def _legacy_codex_home(self) -> Path:
        return USER_DATA_DIR / "openai-codex"

    def _ensure_auth_migrated(self) -> None:
        legacy_auth = self._legacy_codex_home() / _CODEX_AUTH_FILENAME
        codex_auth = self.get_codex_home() / _CODEX_AUTH_FILENAME
        if (
            not self._uses_storage_override()
            and legacy_auth.exists()
            and not codex_auth.exists()
        ):
            try:
                _copy_file_private(legacy_auth, codex_auth)
            except (OSError, UnicodeDecodeError) as exc:
                logger.debug("Failed to migrate legacy Codex auth file: %s", exc)

        self._sync_litellm_auth_from_codex()

    def _read_litellm_auth(self) -> dict[str, Any] | None:
        return _read_json_file(self.get_litellm_auth_file())

    def _sync_litellm_auth_from_codex(self) -> None:
        sources = [self.get_codex_home() / _CODEX_AUTH_FILENAME]
        if not self._uses_storage_override():
            sources.append(self._legacy_codex_home() / _CODEX_AUTH_FILENAME)
        existing_sources = [path for path in sources if path.exists()]
        if not existing_sources:
            return

        source = max(existing_sources, key=lambda path: path.stat().st_mtime)
        destination = self.get_litellm_auth_file()
        if destination.exists() and destination.stat().st_mtime >= source.stat().st_mtime:
            return

        source_payload = _read_json_file(source)
        record = self._litellm_auth_record_from_codex_payload(source_payload)
        if not record:
            return

        _write_json_file(destination, record)

    def _litellm_auth_record_from_codex_payload(
        self,
        payload: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if not payload:
            return None

        tokens = payload.get("tokens")
        if not isinstance(tokens, dict):
            tokens = payload

        access_token = tokens.get("access_token")
        refresh_token = tokens.get("refresh_token")
        id_token = tokens.get("id_token")

        if not isinstance(access_token, str) and not isinstance(refresh_token, str):
            return None

        account_id = tokens.get("account_id")
        if not isinstance(account_id, str) or not account_id.strip():
            account_id = _extract_account_id(
                id_token if isinstance(id_token, str) else None
            ) or _extract_account_id(
                access_token if isinstance(access_token, str) else None
            )

        expires_at = payload.get("expires_at")
        if not isinstance(expires_at, (int, float)):
            expires_at = _extract_expires_at(
                access_token if isinstance(access_token, str) else None
            )

        return {
            "access_token": access_token if isinstance(access_token, str) else None,
            "refresh_token": refresh_token if isinstance(refresh_token, str) else None,
            "id_token": id_token if isinstance(id_token, str) else None,
            "expires_at": int(expires_at) if isinstance(expires_at, (int, float)) else None,
            "account_id": account_id if isinstance(account_id, str) else None,
        }

    def _account_from_litellm_auth(
        self,
        auth: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if not auth:
            return None

        access_token = auth.get("access_token")
        refresh_token = auth.get("refresh_token")
        if not isinstance(access_token, str) and not isinstance(refresh_token, str):
            return None

        id_token = auth.get("id_token")
        claims = _decode_jwt_claims(id_token if isinstance(id_token, str) else access_token)
        email = claims.get("email")

        return {
            "type": "chatgpt",
            "email": email if isinstance(email, str) else None,
            "planType": self._plan_type,
        }

    def _litellm_chatgpt_model_names(self) -> list[str]:
        try:
            import litellm

            raw_models = getattr(litellm, "chatgpt_models", set()) or set()
            model_names = {
                str(model).removeprefix("chatgpt/").strip()
                for model in raw_models
                if str(model).strip()
            }
            if model_names:
                return sorted(model_names)
        except Exception as exc:
            logger.debug("Unable to read LiteLLM ChatGPT model registry: %s", exc)

        return list(_CHATGPT_MODEL_FALLBACKS)


openai_codex = OpenAICodexService()
