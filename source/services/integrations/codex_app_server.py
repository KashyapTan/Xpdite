"""Full-duplex client for Xpdite's bundled OpenAI Codex app-server.

The client owns one long-lived subprocess on a dedicated asyncio loop thread.
Callers may use the async API from FastAPI/provider tasks or the small sync API
from settings helpers without binding the subprocess to either caller's loop.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import itertools
import json
import logging
import os
import platform
import re
import shutil
import sys
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ...infrastructure.config import PROJECT_ROOT, RUNTIME_ROOT, USER_DATA_DIR

logger = logging.getLogger(__name__)

DEFAULT_RPC_TIMEOUT = 20.0
DEFAULT_TURN_QUEUE_SIZE = 512
MAX_PROTOCOL_FRAME_BYTES = 16 * 1024 * 1024
_STDERR_TAIL_LINES = 40
_CODEX_AUTH_FILENAME = "auth.json"
_PINNED_CODEX_VERSION = "0.149.1"

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
_SENSITIVE_VALUE_RE = re.compile(
    r"(?i)(access[_ -]?token|refresh[_ -]?token|id[_ -]?token|"
    r"client[_ -]?secret|cookie)\s*[:=]\s*([^\s,;]+)"
)
_AUTHORIZATION_RE = re.compile(r"(?i)(authorization)\s*[:=]\s*(?:bearer\s+)?[^\s,;]+")
_QUOTED_SECRET_RE = re.compile(
    r"""(?i)(["']?(?:authorization|access[_ -]?token|refresh[_ -]?token|id[_ -]?token|client[_ -]?secret|cookie)["']?\s*:\s*)["'][^"']*["']"""
)
_URL_QUERY_RE = re.compile(r"(https?://[^\s?]+)\?[^\s]+", re.IGNORECASE)
_SENSITIVE_JSON_KEY_PARTS = ("authorization", "cookie", "secret", "token")
_USER_AGENT_VERSION_RE = re.compile(r"(?:^|[/\s])v?(\d+\.\d+\.\d+)(?:$|[+\s-])")


class CodexConnectorError(RuntimeError):
    """Structured internal connector failure with a stable error code."""

    def __init__(
        self, code: str, message: str, *, details: dict[str, Any] | None = None
    ):
        super().__init__(message)
        self.code = code
        self.details = details or {}


class CodexProtocolError(CodexConnectorError):
    """App-server returned an invalid or explicit JSON-RPC protocol error."""


def platform_codex_details() -> tuple[str, str, str]:
    """Return npm package name, target triple, and binary name for this host."""
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
    raise CodexConnectorError(
        "codex_runtime_unavailable",
        f"Unsupported platform for the bundled Codex runtime: {sys.platform}/{machine}",
    )


def restrict_path_permissions(path: Path) -> None:
    if os.name != "posix":
        return
    try:
        path.chmod(0o700 if path.is_dir() else 0o600)
    except OSError as exc:
        logger.debug(
            "Could not restrict connector path permissions: %s", type(exc).__name__
        )


def ensure_private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    restrict_path_permissions(path)
    return path


def write_private_text(path: Path, content: str) -> None:
    ensure_private_dir(path.parent)
    if os.name == "posix":
        fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
    else:
        path.write_text(content, encoding="utf-8")
    restrict_path_permissions(path)


def get_connector_storage_root() -> Path:
    """Return the private, repo-independent ChatGPT connector state root."""
    override_text = os.environ.get("XPDITE_CHATGPT_SUBSCRIPTION_DIR", "").strip()
    if override_text:
        root = Path(override_text)
    elif os.environ.get("XPDITE_USER_DATA_DIR", "").strip():
        root = USER_DATA_DIR / "openai-chatgpt-subscription"
    elif sys.platform == "win32":
        base = Path(
            os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
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
        base = Path(
            os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state")
        )
        root = base / "xpdite" / "openai-chatgpt-subscription"
    return ensure_private_dir(root)


def minimal_process_env() -> dict[str, str]:
    """Build a token-free environment for the connector subprocess."""
    env: dict[str, str] = {}
    for key, value in os.environ.items():
        upper_key = key.upper()
        if upper_key in _PROCESS_ENV_ALLOWLIST or any(
            upper_key.startswith(prefix) for prefix in _PROCESS_ENV_PREFIX_ALLOWLIST
        ):
            env[key] = value
    if not any(key.upper() == "PATH" for key in env):
        env["PATH"] = os.defpath
    return env


def redact_diagnostic(value: str) -> str:
    """Redact token-like values and sensitive URL query strings."""
    redacted = value
    try:
        parsed = json.loads(value)

        def scrub(item: Any) -> Any:
            if isinstance(item, dict):
                return {
                    key: (
                        "[REDACTED]"
                        if any(
                            part in str(key).lower()
                            for part in _SENSITIVE_JSON_KEY_PARTS
                        )
                        else scrub(nested)
                    )
                    for key, nested in item.items()
                }
            if isinstance(item, list):
                return [scrub(nested) for nested in item]
            return item

        redacted = json.dumps(scrub(parsed), ensure_ascii=False, separators=(",", ":"))
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    redacted = _QUOTED_SECRET_RE.sub(
        lambda match: f'{match.group(1)}"[REDACTED]"', redacted
    )
    redacted = _AUTHORIZATION_RE.sub(
        lambda match: f"{match.group(1)}=[REDACTED]", redacted
    )
    redacted = _SENSITIVE_VALUE_RE.sub(
        lambda match: f"{match.group(1)}=[REDACTED]", redacted
    )
    return _URL_QUERY_RE.sub(r"\1?[REDACTED]", redacted)


def connector_code_from_rpc_error(error: dict[str, Any]) -> str:
    """Map app-server errors to stable UI-safe connector categories."""
    data = error.get("data")
    info = data if isinstance(data, dict) else {}
    combined = " ".join(
        str(value or "").lower()
        for value in (
            error.get("message"),
            info.get("codexErrorInfo"),
            info.get("type"),
        )
    )
    if any(
        term in combined for term in ("unauthorized", "authentication", "refresh token")
    ):
        return "chatgpt_auth_expired"
    if any(term in combined for term in ("rate limit", "usage limit", "quota")):
        return "chatgpt_usage_limit"
    if any(term in combined for term in ("workspace", "permission", "forbidden")):
        return "chatgpt_workspace_denied"
    if any(term in combined for term in ("model", "not found")):
        return "chatgpt_model_unavailable"
    return "chatgpt_upstream_unavailable"


@dataclass
class _PendingRequest:
    generation: int
    method: str
    future: asyncio.Future[dict[str, Any]]


@dataclass
class _Subscription:
    generation: int
    thread_id: str
    turn_id: str | None
    target_loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue[dict[str, Any]]


class CodexTurnEventStream:
    """Async event stream for one ephemeral Codex thread/turn."""

    def __init__(
        self,
        client: "CodexAppServerClient",
        subscription_id: int,
        queue: asyncio.Queue[dict[str, Any]],
    ) -> None:
        self._client = client
        self._subscription_id = subscription_id
        self._queue = queue
        self._closed = False

    @property
    def subscription_id(self) -> int:
        return self._subscription_id

    async def set_turn_id(self, turn_id: str) -> None:
        await self._client._run_async(
            self._client._set_subscription_turn(self._subscription_id, turn_id)
        )

    async def get(self, timeout: float | None = None) -> dict[str, Any]:
        if timeout is None:
            return await self._queue.get()
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise CodexConnectorError(
                "chatgpt_stream_disconnected",
                "Timed out waiting for the ChatGPT model stream.",
            ) from exc

    def __aiter__(self) -> "CodexTurnEventStream":
        return self

    async def __anext__(self) -> dict[str, Any]:
        if self._closed:
            raise StopAsyncIteration
        return await self.get()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._client._run_async(
            self._client._remove_subscription(self._subscription_id)
        )


class CodexAppServerClient:
    """Managed full-duplex newline-delimited JSON-RPC app-server client."""

    def __init__(self) -> None:
        self._thread_lock = threading.RLock()
        self._state_lock = threading.RLock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._loop_ready = threading.Event()
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._wait_task: asyncio.Task[None] | None = None
        self._write_lock: asyncio.Lock | None = None
        self._startup_lock: asyncio.Lock | None = None
        self._pending: dict[int, _PendingRequest] = {}
        self._subscriptions: dict[int, _Subscription] = {}
        self._request_ids = itertools.count(1)
        self._subscription_ids = itertools.count(1)
        self._generation = 0
        self._initialized = False
        self._initialize_result: dict[str, Any] = {}
        self._binary_path: Path | None = None
        self._stderr_tail: deque[str] = deque(maxlen=_STDERR_TAIL_LINES)
        self._notification_listeners: list[Callable[[str, dict[str, Any]], None]] = []

    @property
    def generation(self) -> int:
        with self._state_lock:
            return self._generation

    @property
    def initialize_result(self) -> dict[str, Any]:
        with self._state_lock:
            return dict(self._initialize_result)

    @property
    def binary_path(self) -> Path | None:
        with self._state_lock:
            return self._binary_path

    @property
    def stderr_tail(self) -> list[str]:
        with self._state_lock:
            return list(self._stderr_tail)

    def get_codex_home(self) -> Path:
        return ensure_private_dir(get_connector_storage_root() / "codex-app-server")

    def get_isolated_cwd(self) -> Path:
        return ensure_private_dir(get_connector_storage_root() / "runtime-empty")

    def _uses_storage_override(self) -> bool:
        return bool(os.environ.get("XPDITE_CHATGPT_SUBSCRIPTION_DIR", "").strip())

    def migrate_legacy_auth_once(self) -> None:
        """Copy only the legacy canonical Codex auth record on first migration."""
        if self._uses_storage_override():
            return
        legacy_auth = USER_DATA_DIR / "openai-codex" / _CODEX_AUTH_FILENAME
        destination = self.get_codex_home() / _CODEX_AUTH_FILENAME
        if not legacy_auth.exists() or destination.exists():
            return
        try:
            write_private_text(destination, legacy_auth.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as exc:
            logger.debug("Legacy Codex auth migration failed: %s", type(exc).__name__)

    def _codex_binary_candidates(self) -> list[Path]:
        package_dir_name, target_triple, binary_name = platform_codex_details()
        bundled_rels = [
            Path("codex-runtime") / target_triple / "bin" / binary_name,
            Path("codex-runtime") / target_triple / "codex" / binary_name,
        ]
        executable_dir = Path(sys.executable).resolve().parent
        package_root = (
            PROJECT_ROOT
            / "node_modules"
            / "@openai"
            / package_dir_name
            / "vendor"
            / target_triple
        )
        return [
            PROJECT_ROOT / "dist-codex-runtime" / target_triple / "bin" / binary_name,
            PROJECT_ROOT / "dist-codex-runtime" / target_triple / "codex" / binary_name,
            *(RUNTIME_ROOT.parent / bundled_rel for bundled_rel in bundled_rels),
            *(
                executable_dir / ".." / ".." / bundled_rel
                for bundled_rel in bundled_rels
            ),
            *(executable_dir / ".." / bundled_rel for bundled_rel in bundled_rels),
            package_root / "bin" / binary_name,
            package_root / "codex" / binary_name,
        ]

    def get_codex_binary_path(self) -> Path:
        with self._state_lock:
            if self._binary_path and self._binary_path.exists():
                return self._binary_path
        override_text = os.environ.get("XPDITE_CODEX_BINARY", "").strip()
        if override_text:
            override = Path(override_text).expanduser()
            if not override.exists():
                raise FileNotFoundError(
                    f"Configured Codex binary does not exist: {override}"
                )
            resolved = override.resolve()
        else:
            resolved = next(
                (
                    path.resolve()
                    for path in self._codex_binary_candidates()
                    if path.exists()
                ),
                None,
            )
            if resolved is None:
                raise FileNotFoundError(
                    "OpenAI Codex runtime was not found. Run `bun install` and rebuild "
                    "the app; a global Codex installation is not required."
                )
        with self._state_lock:
            self._binary_path = resolved
        return resolved

    def get_launch_command(self) -> list[str]:
        try:
            return [str(self.get_codex_binary_path())]
        except FileNotFoundError as native_error:
            wrapper = (
                PROJECT_ROOT / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
            )
            if wrapper.exists():
                for runner in (
                    os.environ.get("XPDITE_CODEX_NODE", "").strip() or None,
                    shutil.which("node"),
                    shutil.which("bun"),
                ):
                    if runner:
                        return [runner, str(wrapper.resolve())]
            raise native_error

    def build_process_env(self) -> dict[str, str]:
        self.migrate_legacy_auth_once()
        env = minimal_process_env()
        env["CODEX_HOME"] = str(self.get_codex_home())
        env["NO_COLOR"] = "1"
        return env

    def add_notification_listener(
        self, listener: Callable[[str, dict[str, Any]], None]
    ) -> None:
        with self._state_lock:
            if listener not in self._notification_listeners:
                self._notification_listeners.append(listener)

    def remove_notification_listener(
        self, listener: Callable[[str, dict[str, Any]], None]
    ) -> None:
        with self._state_lock:
            if listener in self._notification_listeners:
                self._notification_listeners.remove(listener)

    def _ensure_loop_thread(self) -> asyncio.AbstractEventLoop:
        with self._thread_lock:
            if (
                self._loop
                and self._loop.is_running()
                and self._loop_thread
                and self._loop_thread.is_alive()
            ):
                return self._loop
            self._loop_ready.clear()
            self._loop_thread = threading.Thread(
                target=self._loop_thread_main,
                name="xpdite-codex-app-server",
                daemon=True,
            )
            self._loop_thread.start()
        if not self._loop_ready.wait(timeout=5.0):
            raise CodexConnectorError(
                "codex_runtime_unavailable",
                "Could not start the ChatGPT connector runtime loop.",
            )
        assert self._loop is not None
        return self._loop

    def _loop_thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._write_lock = asyncio.Lock()
        self._startup_lock = asyncio.Lock()
        self._loop_ready.set()
        try:
            loop.run_forever()
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
            loop.close()
            self._loop = None

    def _submit(self, coro: Any) -> concurrent.futures.Future[Any]:
        loop = self._ensure_loop_thread()
        return asyncio.run_coroutine_threadsafe(coro, loop)

    async def _run_async(self, coro: Any) -> Any:
        return await asyncio.wrap_future(self._submit(coro))

    def request_sync(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = DEFAULT_RPC_TIMEOUT,
    ) -> dict[str, Any]:
        future = self._submit(self._request(method, params, timeout=timeout))
        try:
            return future.result(timeout=timeout + 5.0)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise CodexConnectorError(
                "chatgpt_upstream_unavailable",
                f"Timed out waiting for Codex app-server method {method}.",
            ) from exc

    async def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = DEFAULT_RPC_TIMEOUT,
    ) -> dict[str, Any]:
        return await self._run_async(self._request(method, params, timeout=timeout))

    async def create_turn_event_stream(
        self,
        thread_id: str,
        *,
        max_queue_size: int = DEFAULT_TURN_QUEUE_SIZE,
    ) -> CodexTurnEventStream:
        target_loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=max_queue_size)
        subscription_id = await self._run_async(
            self._add_subscription(thread_id, target_loop, queue)
        )
        return CodexTurnEventStream(self, subscription_id, queue)

    async def respond_server_request(
        self,
        request_id: int | str,
        *,
        generation: int,
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> None:
        await self._run_async(
            self._respond_server_request(
                request_id, generation=generation, result=result, error=error
            )
        )

    async def account_read(self, *, refresh_token: bool = False) -> dict[str, Any]:
        return await self.request("account/read", {"refreshToken": refresh_token})

    async def rate_limits_read(self) -> dict[str, Any]:
        return await self.request("account/rateLimits/read")

    async def model_list_page(
        self,
        *,
        cursor: str | None = None,
        include_hidden: bool = False,
        limit: int = 100,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"includeHidden": include_hidden, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        return await self.request("model/list", params)

    async def thread_start(self, params: dict[str, Any]) -> dict[str, Any]:
        return await self.request("thread/start", params, timeout=30.0)

    async def thread_inject_items(
        self, thread_id: str, items: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return await self.request(
            "thread/inject_items",
            {"threadId": thread_id, "items": items},
            timeout=30.0,
        )

    async def turn_start(
        self, thread_id: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        return await self.request(
            "turn/start", {"threadId": thread_id, **params}, timeout=30.0
        )

    async def turn_interrupt(self, thread_id: str, turn_id: str) -> dict[str, Any]:
        return await self.request(
            "turn/interrupt",
            {"threadId": thread_id, "turnId": turn_id},
            timeout=10.0,
        )

    async def _ensure_initialized(self, timeout: float) -> None:
        assert self._startup_lock is not None
        async with self._startup_lock:
            if self._process and self._process.returncode is None and self._initialized:
                return
            await self._start_process()
            try:
                result = await self._send_request_no_ensure(
                    "initialize",
                    {
                        "clientInfo": {"name": "Xpdite", "version": "0.0.0"},
                        "capabilities": {"experimentalApi": True},
                    },
                    timeout=timeout,
                )
                self._validate_initialize_result(result)
                await self._write_message({"method": "initialized"})
            except Exception:
                await self._shutdown_process("Codex initialization failed.")
                raise
            self._initialized = True
            with self._state_lock:
                self._initialize_result = dict(result)

    def _validate_initialize_result(self, result: dict[str, Any]) -> None:
        user_agent = str(result.get("userAgent") or "")
        codex_home = str(result.get("codexHome") or "")
        version_match = _USER_AGENT_VERSION_RE.search(user_agent)
        if not version_match or version_match.group(1) != _PINNED_CODEX_VERSION:
            raise CodexProtocolError(
                "codex_protocol_mismatch",
                "The bundled Codex runtime version does not match Xpdite's supported protocol.",
            )
        home_matches = False
        if codex_home:
            try:
                # Compare the directories themselves instead of their path strings.
                # Case-insensitive filesystems may preserve different casing in the
                # runtime response even though both paths identify the same directory.
                home_matches = os.path.samefile(codex_home, self.get_codex_home())
            except (OSError, ValueError):
                home_matches = False
        if not codex_home or not home_matches:
            raise CodexProtocolError(
                "codex_protocol_mismatch",
                "The bundled Codex runtime did not accept Xpdite's private connector home.",
            )
        if (
            not str(result.get("platformFamily") or "").strip()
            or not str(result.get("platformOs") or "").strip()
        ):
            raise CodexProtocolError(
                "codex_protocol_mismatch",
                "The bundled Codex runtime returned an incomplete initialization response.",
            )

    async def _request(
        self, method: str, params: dict[str, Any] | None, *, timeout: float
    ) -> dict[str, Any]:
        await self._ensure_initialized(timeout)
        return await self._send_request_no_ensure(method, params, timeout=timeout)

    async def _send_request_no_ensure(
        self, method: str, params: dict[str, Any] | None, *, timeout: float
    ) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        request_id = next(self._request_ids)
        pending = _PendingRequest(self._generation, method, future)
        self._pending[request_id] = pending
        try:
            payload: dict[str, Any] = {"id": request_id, "method": method}
            if params is not None:
                payload["params"] = params
            await self._write_message(payload)
            try:
                response = await asyncio.wait_for(future, timeout=timeout)
            except asyncio.TimeoutError as exc:
                raise CodexConnectorError(
                    "chatgpt_upstream_unavailable",
                    f"Timed out waiting for Codex app-server method {method}.",
                ) from exc
        finally:
            self._pending.pop(request_id, None)
        error = response.get("error")
        if error is not None:
            if isinstance(error, dict):
                message = str(
                    error.get("message") or "Codex app-server request failed."
                )
                details = {"rpc_code": error.get("code")} if "code" in error else {}
            else:
                message = str(error)
                details = {}
            raise CodexProtocolError(
                connector_code_from_rpc_error(error)
                if isinstance(error, dict)
                else "chatgpt_upstream_unavailable",
                redact_diagnostic(message)[:300],
                details=details,
            )
        result = response.get("result")
        return result if isinstance(result, dict) else {}

    async def _start_process(self) -> None:
        await self._shutdown_process("Codex app-server restarted.")
        try:
            command = self.get_launch_command()
        except FileNotFoundError as exc:
            raise CodexConnectorError("codex_runtime_unavailable", str(exc)) from exc
        self._generation += 1
        logger.info("Starting Codex app-server generation %d", self._generation)
        with self._state_lock:
            self._initialize_result = {}
            self._stderr_tail.clear()
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                "app-server",
                "--listen",
                "stdio://",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.get_isolated_cwd()),
                env=self.build_process_env(),
                limit=MAX_PROTOCOL_FRAME_BYTES,
            )
        except (OSError, ValueError) as exc:
            raise CodexConnectorError(
                "codex_runtime_unavailable",
                "Could not launch the bundled OpenAI Codex runtime.",
            ) from exc
        if process.stdin is None or process.stdout is None or process.stderr is None:
            process.kill()
            await process.wait()
            raise CodexConnectorError(
                "codex_runtime_unavailable",
                "Could not open the Codex app-server transport.",
            )
        self._process = process
        generation = self._generation
        self._reader_task = asyncio.create_task(self._stdout_loop(process, generation))
        self._stderr_task = asyncio.create_task(self._stderr_loop(process, generation))
        self._wait_task = asyncio.create_task(self._wait_for_exit(process, generation))

    async def _write_message(self, payload: dict[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None or process.returncode is not None:
            raise CodexConnectorError(
                "chatgpt_stream_disconnected", "Codex app-server is not running."
            )
        assert self._write_lock is not None
        encoded = (
            json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode(
                "utf-8"
            )
            + b"\n"
        )
        async with self._write_lock:
            try:
                process.stdin.write(encoded)
                await process.stdin.drain()
            except (BrokenPipeError, ConnectionError, RuntimeError) as exc:
                raise CodexConnectorError(
                    "chatgpt_stream_disconnected",
                    "Lost the Codex app-server transport while writing a request.",
                ) from exc

    async def _stdout_loop(
        self, process: asyncio.subprocess.Process, generation: int
    ) -> None:
        assert process.stdout is not None
        try:
            while True:
                raw_line = await process.stdout.readline()
                if not raw_line:
                    break
                try:
                    payload = json.loads(raw_line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    logger.debug("Ignoring malformed Codex app-server stdout frame")
                    continue
                if not isinstance(payload, dict):
                    logger.debug("Ignoring non-object Codex app-server stdout frame")
                    continue
                await self._handle_message(payload, generation)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "Codex stdout reader stopped for generation %d (%s)",
                generation,
                type(exc).__name__,
            )
            if process is self._process and generation == self._generation:
                await self._shutdown_process(
                    "Codex app-server sent an invalid or oversized protocol frame."
                )

    async def _stderr_loop(
        self, process: asyncio.subprocess.Process, generation: int
    ) -> None:
        assert process.stderr is not None
        try:
            while True:
                raw_line = await process.stderr.readline()
                if not raw_line:
                    break
                if generation != self._generation:
                    continue
                line = redact_diagnostic(
                    raw_line.decode("utf-8", errors="replace").rstrip()
                )[:1000]
                if not line:
                    continue
                with self._state_lock:
                    self._stderr_tail.append(line)
                logger.debug("Codex app-server stderr: %s", line)
        except asyncio.CancelledError:
            raise

    async def _wait_for_exit(
        self, process: asyncio.subprocess.Process, generation: int
    ) -> None:
        return_code = await process.wait()
        if process is not self._process or generation != self._generation:
            return
        message = f"Codex app-server stopped unexpectedly (exit {return_code})."
        await self._mark_disconnected(generation, message)

    async def _handle_message(self, payload: dict[str, Any], generation: int) -> None:
        if generation != self._generation:
            return
        method = payload.get("method")
        request_id = payload.get("id")

        # JSON-RPC is bidirectional. Classify by shape, never by numeric ID.
        if isinstance(method, str) and request_id is not None:
            await self._dispatch_server_request(
                request_id, method, payload.get("params"), generation
            )
            return
        if isinstance(method, str) and request_id is None:
            params = payload.get("params")
            normalized_params = params if isinstance(params, dict) else {}
            self._notify_listeners(method, normalized_params)
            self._dispatch_notification(method, normalized_params, generation)
            return
        if request_id is not None and ("result" in payload or "error" in payload):
            pending = self._pending.get(request_id)
            if (
                pending
                and pending.generation == generation
                and not pending.future.done()
            ):
                pending.future.set_result(payload)
            return
        logger.debug("Ignoring malformed Codex app-server protocol message")

    def _notify_listeners(self, method: str, params: dict[str, Any]) -> None:
        with self._state_lock:
            listeners = list(self._notification_listeners)
        for listener in listeners:
            try:
                listener(method, params)
            except Exception as exc:
                logger.debug(
                    "Codex notification listener failed: %s", type(exc).__name__
                )

    @staticmethod
    def _message_thread_turn(params: dict[str, Any]) -> tuple[str | None, str | None]:
        thread_id = params.get("threadId")
        turn_id = params.get("turnId")
        thread = params.get("thread")
        turn = params.get("turn")
        if not thread_id and isinstance(thread, dict):
            thread_id = thread.get("id")
        if not turn_id and isinstance(turn, dict):
            turn_id = turn.get("id")
        return (
            str(thread_id) if thread_id is not None else None,
            str(turn_id) if turn_id is not None else None,
        )

    def _matching_subscriptions(
        self, params: dict[str, Any], generation: int
    ) -> list[_Subscription]:
        thread_id, turn_id = self._message_thread_turn(params)
        if not thread_id:
            return []
        return [
            subscription
            for subscription in self._subscriptions.values()
            if subscription.generation == generation
            and subscription.thread_id == thread_id
            and (
                subscription.turn_id is None
                or turn_id is None
                or subscription.turn_id == turn_id
            )
        ]

    @staticmethod
    def _deliver_to_subscription(
        subscription: _Subscription, event: dict[str, Any]
    ) -> None:
        def deliver() -> None:
            try:
                subscription.queue.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    subscription.queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                failure = {
                    "method": "_transport/error",
                    "params": {
                        "code": "chatgpt_stream_disconnected",
                        "message": "The ChatGPT event queue exceeded its safety limit.",
                    },
                }
                try:
                    subscription.queue.put_nowait(failure)
                except asyncio.QueueFull:
                    pass

        subscription.target_loop.call_soon_threadsafe(deliver)

    def _dispatch_notification(
        self, method: str, params: dict[str, Any], generation: int
    ) -> None:
        event = {"method": method, "params": params, "generation": generation}
        for subscription in self._matching_subscriptions(params, generation):
            self._deliver_to_subscription(subscription, event)

    async def _dispatch_server_request(
        self,
        request_id: int | str,
        method: str,
        raw_params: Any,
        generation: int,
    ) -> None:
        params = raw_params if isinstance(raw_params, dict) else {}
        subscriptions = self._matching_subscriptions(params, generation)
        if method == "item/tool/call" and subscriptions:
            event = {
                "method": method,
                "params": params,
                "server_request_id": request_id,
                "generation": generation,
            }
            # One ephemeral thread has one provider subscription; avoid duplicate execution.
            self._deliver_to_subscription(subscriptions[0], event)
            return
        await self._respond_server_request(
            request_id,
            generation=generation,
            error={
                "code": -32601,
                "message": f"Unsupported server request method: {method}",
            },
        )

    async def _respond_server_request(
        self,
        request_id: int | str,
        *,
        generation: int,
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> None:
        if generation != self._generation or self._process is None:
            raise CodexConnectorError(
                "chatgpt_stream_disconnected",
                "Discarded a stale Codex server-request response after runtime restart.",
            )
        payload: dict[str, Any] = {"id": request_id}
        if error is not None:
            payload["error"] = error
        else:
            payload["result"] = result or {}
        await self._write_message(payload)

    async def _add_subscription(
        self,
        thread_id: str,
        target_loop: asyncio.AbstractEventLoop,
        queue: asyncio.Queue[dict[str, Any]],
    ) -> int:
        subscription_id = next(self._subscription_ids)
        self._subscriptions[subscription_id] = _Subscription(
            generation=self._generation,
            thread_id=thread_id,
            turn_id=None,
            target_loop=target_loop,
            queue=queue,
        )
        return subscription_id

    async def _set_subscription_turn(self, subscription_id: int, turn_id: str) -> None:
        subscription = self._subscriptions.get(subscription_id)
        if subscription:
            subscription.turn_id = turn_id

    async def _remove_subscription(self, subscription_id: int) -> None:
        self._subscriptions.pop(subscription_id, None)

    async def _pending_count(self) -> int:
        """Test/diagnostic snapshot without exposing pending payloads."""
        return len(self._pending)

    async def _mark_disconnected(self, generation: int, message: str) -> None:
        if generation != self._generation:
            return
        logger.warning(
            "Codex app-server generation %d disconnected: %s", generation, message
        )
        error = CodexConnectorError("chatgpt_stream_disconnected", message)
        for pending in list(self._pending.values()):
            if pending.generation == generation and not pending.future.done():
                pending.future.set_exception(error)
        self._pending = {
            request_id: pending
            for request_id, pending in self._pending.items()
            if pending.generation != generation
        }
        failure = {
            "method": "_transport/error",
            "params": {"code": error.code, "message": str(error)},
            "generation": generation,
        }
        for subscription in list(self._subscriptions.values()):
            if subscription.generation == generation:
                self._deliver_to_subscription(subscription, failure)
        self._subscriptions = {
            subscription_id: subscription
            for subscription_id, subscription in self._subscriptions.items()
            if subscription.generation != generation
        }
        self._process = None
        self._initialized = False
        self._initialize_result = {}

    async def _shutdown_process(self, message: str) -> None:
        process = self._process
        if process is None:
            return
        generation = self._generation
        self._process = None
        self._initialized = False
        if process.stdin:
            try:
                process.stdin.close()
                await process.stdin.wait_closed()
            except (BrokenPipeError, ConnectionError, RuntimeError):
                pass
        if process.returncode is None:
            try:
                await asyncio.wait_for(process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
        for task in (self._reader_task, self._stderr_task, self._wait_task):
            if task and task is not asyncio.current_task() and not task.done():
                task.cancel()
        await self._mark_disconnected(generation, message)

    def shutdown(self) -> None:
        """Stop only this managed child and release its private loop thread."""
        with self._thread_lock:
            loop = self._loop
            loop_thread = self._loop_thread
        if loop and loop.is_running():
            future = asyncio.run_coroutine_threadsafe(
                self._shutdown_process("Codex app-server shut down."), loop
            )
            try:
                future.result(timeout=6.0)
            except Exception as exc:
                logger.debug(
                    "Codex shutdown did not finish cleanly: %s", type(exc).__name__
                )
            loop.call_soon_threadsafe(loop.stop)
        if loop_thread and loop_thread is not threading.current_thread():
            loop_thread.join(timeout=3.0)
        with self._thread_lock:
            self._loop_thread = None


codex_app_server = CodexAppServerClient()
