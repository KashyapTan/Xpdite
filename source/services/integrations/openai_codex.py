"""Authoritative ChatGPT subscription account and model-catalog facade."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from .codex_app_server import (
    CodexAppServerClient,
    CodexConnectorError,
    codex_app_server,
    get_connector_storage_root,
)

logger = logging.getLogger(__name__)

_RPC_TIMEOUT_SECONDS = 20.0
_MODEL_CACHE_SECONDS = 60.0
_MAX_MODEL_PAGES = 20


def _string(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _runtime_version(initialize_result: dict[str, Any]) -> str | None:
    server_info = initialize_result.get("serverInfo")
    candidates = [
        initialize_result.get("version"),
        server_info.get("version") if isinstance(server_info, dict) else None,
        initialize_result.get("userAgent"),
    ]
    return next((str(value) for value in candidates if value), None)


class OpenAICodexService:
    """Expose Codex-owned ChatGPT account/catalog state to Xpdite."""

    def __init__(self, client: CodexAppServerClient | None = None) -> None:
        self.client = client or codex_app_server
        self._lock = threading.RLock()
        self._auth_in_progress = False
        self._login_method: str | None = None
        self._login_id: str | None = None
        self._auth_url: str | None = None
        self._verification_url: str | None = None
        self._user_code: str | None = None
        self._last_error: str | None = None
        self._error_code: str | None = None
        self._connection_state = "disconnected"
        self._account: dict[str, Any] | None = None
        self._rate_limits: dict[str, Any] | None = None
        self._model_cache: dict[bool, tuple[str, int, float, list[dict[str, Any]]]] = {}
        self._models_refreshed_at: float | None = None
        self.client.add_notification_listener(self._handle_notification)

    def get_storage_root(self):
        return get_connector_storage_root()

    def get_codex_home(self):
        return self.client.get_codex_home()

    def get_codex_binary_path(self):
        return self.client.get_codex_binary_path()

    def get_codex_launch_command(self) -> list[str]:
        return self.client.get_launch_command()

    def build_process_env(self) -> dict[str, str]:
        return self.client.build_process_env()

    @staticmethod
    def _account_from_result(result: dict[str, Any]) -> dict[str, Any] | None:
        account = result.get("account")
        return account if isinstance(account, dict) else None

    @staticmethod
    def _account_cache_key(account: dict[str, Any] | None) -> str:
        if not account:
            return "none"
        for key in ("id", "accountId", "email"):
            value = _string(account.get(key))
            if value:
                return f"{account.get('type')}:{value}"
        return str(account.get("type") or "unknown")

    @staticmethod
    def _error_state(exc: Exception) -> tuple[str, str, str]:
        code = str(getattr(exc, "code", None) or "chatgpt_upstream_unavailable")
        message = str(exc).strip() or "The ChatGPT connector is unavailable."
        if isinstance(exc, FileNotFoundError) or code == "codex_runtime_unavailable":
            return "runtime_unavailable", "codex_runtime_unavailable", message
        if code in {"chatgpt_auth_expired", "chatgpt_not_connected"}:
            return "reconnect_required", code, message
        if code == "chatgpt_usage_limit":
            return "rate_limited", code, message
        return "degraded", code, message

    def _set_account(self, account: dict[str, Any] | None) -> None:
        with self._lock:
            old_key = self._account_cache_key(self._account)
            new_key = self._account_cache_key(account)
            self._account = dict(account) if account else None
            if old_key != new_key:
                self._invalidate_models_locked()

    def _status_from_account_result(self, result: dict[str, Any]) -> dict[str, Any]:
        account = self._account_from_result(result)
        self._set_account(account)
        account_type = _string(account.get("type")) if account else None
        connected = account_type == "chatgpt"
        requires_openai_auth = bool(result.get("requiresOpenaiAuth", not connected))
        with self._lock:
            if connected:
                self._auth_in_progress = False
                if self._connection_state != "rate_limited":
                    self._connection_state = "connected"
                    self._last_error = None
                    self._error_code = None
                self._clear_login_locked(clear_error=False)
            elif self._auth_in_progress:
                self._connection_state = "authenticating"
            else:
                self._connection_state = "disconnected"
            return self._build_status_locked(
                available=True,
                connected=connected,
                account=account,
                requires_openai_auth=requires_openai_auth,
            )

    def _status_for_error(self, exc: Exception) -> dict[str, Any]:
        state, code, message = self._error_state(exc)
        logger.warning("ChatGPT connector status failed (%s)", type(exc).__name__)
        with self._lock:
            self._connection_state = state
            self._error_code = code
            self._last_error = message[:300]
            return self._build_status_locked(
                available=state != "runtime_unavailable",
                connected=False,
                account=None,
                requires_openai_auth=True,
            )

    def get_status(self, refresh_token: bool = False) -> dict[str, Any]:
        with self._lock:
            if refresh_token:
                self._connection_state = "refreshing"
        try:
            result = self.client.request_sync(
                "account/read",
                {"refreshToken": refresh_token},
                timeout=_RPC_TIMEOUT_SECONDS,
            )
            return self._status_from_account_result(result)
        except Exception as exc:
            return self._status_for_error(exc)

    async def get_status_async(self, refresh_token: bool = False) -> dict[str, Any]:
        with self._lock:
            if refresh_token:
                self._connection_state = "refreshing"
        try:
            result = await self.client.account_read(refresh_token=refresh_token)
            return self._status_from_account_result(result)
        except Exception as exc:
            return self._status_for_error(exc)

    def _build_status_locked(
        self,
        *,
        available: bool,
        connected: bool,
        account: dict[str, Any] | None,
        requires_openai_auth: bool,
    ) -> dict[str, Any]:
        runtime_info = self.client.initialize_result
        return {
            "available": available,
            "connected": connected,
            "connection_state": self._connection_state,
            "account_type": _string(account.get("type")) if account else None,
            "email": _string(account.get("email")) if account else None,
            "plan_type": _string(account.get("planType")) if account else None,
            "requires_openai_auth": requires_openai_auth,
            "auth_in_progress": self._auth_in_progress,
            "login_method": self._login_method,
            "login_id": self._login_id,
            "auth_url": self._auth_url,
            "verification_url": self._verification_url,
            "user_code": self._user_code,
            "auth_mode": _string(account.get("type")) if account else None,
            "last_error": self._last_error,
            "error_code": self._error_code,
            "binary_path": str(self.client.binary_path) if self.client.binary_path else None,
            "runtime_version": _runtime_version(runtime_info),
            "runtime_generation": self.client.generation,
            "models_refreshed_at": self._models_refreshed_at,
            "rate_limits": self._rate_limits,
        }

    def start_browser_login(self) -> dict[str, Any]:
        result = self.client.request_sync(
            "account/login/start", {"type": "chatgpt"}, timeout=_RPC_TIMEOUT_SECONDS
        )
        with self._lock:
            self._auth_in_progress = True
            self._connection_state = "authenticating"
            self._login_method = "chatgpt"
            self._login_id = _string(result.get("loginId"))
            self._auth_url = _string(result.get("authUrl"))
            self._verification_url = None
            self._user_code = None
            self._last_error = None
            self._error_code = None
        return self._current_status_without_rpc()

    def start_device_login(self) -> dict[str, Any]:
        result = self.client.request_sync(
            "account/login/start",
            {"type": "chatgptDeviceCode"},
            timeout=_RPC_TIMEOUT_SECONDS,
        )
        with self._lock:
            self._auth_in_progress = True
            self._connection_state = "authenticating"
            self._login_method = "chatgptDeviceCode"
            self._login_id = _string(result.get("loginId"))
            self._auth_url = None
            self._verification_url = _string(result.get("verificationUrl"))
            self._user_code = _string(result.get("userCode"))
            self._last_error = None
            self._error_code = None
        return self._current_status_without_rpc()

    def cancel_login(self) -> dict[str, Any]:
        with self._lock:
            login_id = self._login_id
        if login_id:
            self.client.request_sync(
                "account/login/cancel", {"loginId": login_id}, timeout=_RPC_TIMEOUT_SECONDS
            )
        with self._lock:
            self._clear_login_locked()
            self._connection_state = "disconnected"
        return self.get_status(refresh_token=False)

    def disconnect(self) -> dict[str, Any]:
        # Codex owns and clears the canonical OAuth record.
        self.client.request_sync("account/logout", None, timeout=_RPC_TIMEOUT_SECONDS)
        with self._lock:
            self._account = None
            self._rate_limits = None
            self._connection_state = "disconnected"
            self._clear_login_locked()
            self._invalidate_models_locked()
        return self.get_status(refresh_token=False)

    def _current_status_without_rpc(self) -> dict[str, Any]:
        with self._lock:
            account = dict(self._account) if self._account else None
            connected = bool(account and account.get("type") == "chatgpt")
            return self._build_status_locked(
                available=True,
                connected=connected,
                account=account,
                requires_openai_auth=not connected,
            )

    def _clear_login_locked(self, *, clear_error: bool = True) -> None:
        self._auth_in_progress = False
        self._login_method = None
        self._login_id = None
        self._auth_url = None
        self._verification_url = None
        self._user_code = None
        if clear_error:
            self._last_error = None
            self._error_code = None

    def _invalidate_models_locked(self) -> None:
        self._model_cache.clear()
        self._models_refreshed_at = None

    def invalidate_models(self) -> None:
        with self._lock:
            self._invalidate_models_locked()

    def _handle_notification(self, method: str, params: dict[str, Any]) -> None:
        with self._lock:
            if method == "account/login/completed":
                notification_login_id = _string(params.get("loginId"))
                if notification_login_id and notification_login_id != self._login_id:
                    return
                success = bool(params.get("success"))
                self._clear_login_locked(clear_error=False)
                if success:
                    self._connection_state = "refreshing"
                    self._last_error = None
                    self._error_code = None
                else:
                    self._connection_state = "disconnected"
                    self._last_error = "ChatGPT sign-in failed. Please try again."
                    self._error_code = "chatgpt_not_connected"
                self._invalidate_models_locked()
            elif method == "account/updated":
                self._account = None
                self._invalidate_models_locked()
            elif method == "account/rateLimits/updated":
                snapshot = params.get("rateLimits") or params
                self._rate_limits = dict(snapshot) if isinstance(snapshot, dict) else None

    def record_connector_error(self, code: str, message: str) -> None:
        """Retain the last turn failure for settings diagnostics and recovery UX."""
        with self._lock:
            if code == "chatgpt_usage_limit":
                self._connection_state = "rate_limited"
            elif code in {"chatgpt_auth_expired", "chatgpt_not_connected"}:
                self._connection_state = "reconnect_required"
                self._account = None
                self._invalidate_models_locked()
            else:
                self._connection_state = "degraded"
            self._error_code = code
            self._last_error = message[:300]

    def record_connector_success(self) -> None:
        """Clear transient turn diagnostics after a confirmed completed turn."""
        with self._lock:
            if self._account and self._account.get("type") == "chatgpt":
                self._connection_state = "connected"
                self._error_code = None
                self._last_error = None

    @staticmethod
    def _normalize_model(raw_model: dict[str, Any]) -> dict[str, Any] | None:
        picker_id = _string(raw_model.get("id"))
        underlying_model = _string(raw_model.get("model"))
        if not picker_id:
            return None
        supported_efforts = raw_model.get("supportedReasoningEfforts")
        modalities = raw_model.get("inputModalities")
        return {
            "id": picker_id,
            "model": underlying_model or picker_id,
            "displayName": _string(raw_model.get("displayName")) or picker_id,
            "description": _string(raw_model.get("description")),
            "hidden": bool(raw_model.get("hidden", False)),
            "isDefault": bool(raw_model.get("isDefault", False)),
            "supportedReasoningEfforts": supported_efforts if isinstance(supported_efforts, list) else [],
            "defaultReasoningEffort": raw_model.get("defaultReasoningEffort"),
            "inputModalities": modalities if isinstance(modalities, list) else [],
            "upgrade": raw_model.get("upgrade"),
            "upgradeInfo": raw_model.get("upgradeInfo"),
            "availabilityNux": raw_model.get("availabilityNux"),
            "supportsPersonality": raw_model.get("supportsPersonality"),
            "additionalSpeedTiers": raw_model.get("additionalSpeedTiers")
            if isinstance(raw_model.get("additionalSpeedTiers"), list)
            else [],
        }

    def _cached_models(
        self, include_hidden: bool, account_key: str, refresh: bool
    ) -> list[dict[str, Any]] | None:
        now = time.monotonic()
        with self._lock:
            cached = self._model_cache.get(include_hidden)
            if (
                not refresh
                and cached
                and cached[0] == account_key
                and cached[1] == self.client.generation
                and now - cached[2] < _MODEL_CACHE_SECONDS
            ):
                return [dict(model) for model in cached[3]]
        return None

    def _store_models(
        self, include_hidden: bool, account_key: str, models: list[dict[str, Any]]
    ) -> None:
        with self._lock:
            self._model_cache[include_hidden] = (
                account_key,
                self.client.generation,
                time.monotonic(),
                [dict(model) for model in models],
            )
            self._models_refreshed_at = time.time()

    async def _fetch_models_async(
        self,
        account_key: str,
        *,
        include_hidden: bool,
        use_public_client_api: bool,
    ) -> list[dict[str, Any]]:
        models: list[dict[str, Any]] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        for _ in range(_MAX_MODEL_PAGES):
            if use_public_client_api:
                page = await self.client.model_list_page(
                    cursor=cursor, include_hidden=include_hidden, limit=100
                )
            else:
                params: dict[str, Any] = {"includeHidden": include_hidden, "limit": 100}
                if cursor:
                    params["cursor"] = cursor
                page = await self.client._request(
                    "model/list", params, timeout=_RPC_TIMEOUT_SECONDS
                )
            raw_models = page.get("data") or page.get("models") or []
            if not isinstance(raw_models, list):
                raise CodexConnectorError(
                    "codex_protocol_mismatch",
                    "Codex app-server returned an invalid model catalog.",
                )
            for raw_model in raw_models:
                normalized = self._normalize_model(raw_model) if isinstance(raw_model, dict) else None
                if normalized and (include_hidden or not normalized["hidden"]):
                    models.append(normalized)
            next_cursor = _string(page.get("nextCursor"))
            if not next_cursor:
                self._store_models(include_hidden, account_key, models)
                logger.info(
                    "Loaded %d ChatGPT model(s) from Codex generation %d",
                    len(models),
                    self.client.generation,
                )
                return models
            if next_cursor in seen_cursors:
                raise CodexConnectorError(
                    "codex_protocol_mismatch", "Codex app-server repeated a model catalog cursor."
                )
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        raise CodexConnectorError(
            "codex_protocol_mismatch",
            "Codex app-server model catalog exceeded the page safety limit.",
        )

    async def list_models_async(
        self,
        include_hidden: bool = False,
        *,
        refresh: bool = False,
        account_already_verified: bool = False,
    ) -> list[dict[str, Any]]:
        if not account_already_verified:
            status = await self.get_status_async(refresh_token=False)
            if not status.get("connected"):
                if status.get("error_code"):
                    raise CodexConnectorError(
                        str(status["error_code"]),
                        str(status.get("last_error") or "The ChatGPT connector is unavailable."),
                    )
                return []
        elif not self._account or self._account.get("type") != "chatgpt":
            return []
        account_key = self._account_cache_key(self._account)
        cached = self._cached_models(include_hidden, account_key, refresh)
        if cached is not None:
            return cached
        return await self._fetch_models_async(
            account_key, include_hidden=include_hidden, use_public_client_api=True
        )

    def list_models(
        self, include_hidden: bool = False, *, refresh: bool = False
    ) -> list[dict[str, Any]]:
        future = self.client._submit(
            self._list_models_on_client_loop(include_hidden=include_hidden, refresh=refresh)
        )
        return future.result(timeout=_RPC_TIMEOUT_SECONDS * 3)

    async def _list_models_on_client_loop(
        self, *, include_hidden: bool, refresh: bool
    ) -> list[dict[str, Any]]:
        result = await self.client._request(
            "account/read", {"refreshToken": False}, timeout=_RPC_TIMEOUT_SECONDS
        )
        status = self._status_from_account_result(result)
        if not status.get("connected"):
            return []
        account_key = self._account_cache_key(self._account)
        cached = self._cached_models(include_hidden, account_key, refresh)
        if cached is not None:
            return cached
        return await self._fetch_models_async(
            account_key, include_hidden=include_hidden, use_public_client_api=False
        )

    async def get_rate_limits_async(self) -> dict[str, Any] | None:
        try:
            result = await self.client.rate_limits_read()
        except CodexConnectorError:
            return None
        snapshot = result.get("rateLimits") or result
        with self._lock:
            self._rate_limits = dict(snapshot) if isinstance(snapshot, dict) else None
            return dict(self._rate_limits) if self._rate_limits else None

    def shutdown(self) -> None:
        self.client.shutdown()


openai_codex = OpenAICodexService()
