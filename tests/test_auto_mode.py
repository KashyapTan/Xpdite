"""Tests for Auto Mode (Instant Answer).

Covers the three backend seams the feature adds:
  - Settings handlers (persist + arm/disarm the gate immediately).
  - The submit-query capture condition (auto_mode forces a capture even when the
    target tab already has history — i.e. keep-context mode).
  - The auto_mode service: payload resolution + trigger/mini broadcasts.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import source.api.handlers as handlers
import source.services.media.auto_mode as auto_mode
from source.core.state import app_state
from source.infrastructure.database import db
from source.infrastructure.config import (
    AUTO_MODE_ENABLED_KEY,
    AUTO_MODE_PROMPT_KEY,
    AUTO_MODE_PINNED_MODEL_KEY,
    AUTO_MODE_KEEP_CONTEXT_KEY,
    AUTO_MODE_FLASH_KEY,
    DEFAULT_AUTO_MODE_PROMPT,
)


class _FakeWebSocket:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_text(self, message: str):
        self.sent.append(json.loads(message))


class _FakeSettingsStore:
    """In-memory stand-in for the settings key/value table."""

    def __init__(self, initial=None):
        self.data = dict(initial or {})

    def get_setting(self, key):
        return self.data.get(key)

    def set_setting(self, key, value):
        self.data[key] = value


def _make_session(chat_history=None):
    queue = SimpleNamespace(enqueue=AsyncMock())
    state = SimpleNamespace(
        screenshot_list=[],
        chat_history=list(chat_history or []),
    )
    return SimpleNamespace(state=state, queue=queue)


class _FakeTabManager:
    def __init__(self, session):
        self.session = session

    def get_or_create(self, _tab_id):
        return self.session


@pytest.fixture(autouse=True)
def _restore_auto_state():
    saved_enabled = app_state.auto_mode_enabled
    saved_model = app_state.selected_model
    yield
    app_state.auto_mode_enabled = saved_enabled
    app_state.selected_model = saved_model


@pytest.fixture()
def websocket():
    return _FakeWebSocket()


@pytest.fixture()
def handler(websocket):
    return handlers.MessageHandler(websocket)


@pytest.fixture()
def store(monkeypatch):
    """Patch the settings-table accessors with an in-memory store."""
    s = _FakeSettingsStore()
    monkeypatch.setattr(db, "get_setting", s.get_setting)
    monkeypatch.setattr(db, "set_setting", s.set_setting)
    return s


class TestAutoModeSettingsHandlers:
    async def test_get_returns_defaults(self, handler, websocket, store):
        await handler._handle_auto_mode_get_settings({})

        msg = websocket.sent[-1]
        assert msg["type"] == "auto_mode_settings"
        content = msg["content"]
        assert content["enabled"] is False
        assert content["prompt"] == DEFAULT_AUTO_MODE_PROMPT
        assert content["pinned_model"] == ""
        assert content["keep_context"] is False
        assert content["flash"] is False

    async def test_update_persists_and_arms_gate(self, handler, websocket, store):
        app_state.auto_mode_enabled = False

        await handler._handle_auto_mode_update_settings(
            {
                "settings": {
                    "enabled": True,
                    "prompt": "Explain the error",
                    "pinned_model": "openai/gpt-4o",
                    "keep_context": True,
                    "flash": True,
                }
            }
        )

        # app_state is armed immediately so the hotkey listener sees it.
        assert app_state.auto_mode_enabled is True
        assert store.data[AUTO_MODE_ENABLED_KEY] == "true"
        assert store.data[AUTO_MODE_PROMPT_KEY] == "Explain the error"
        assert store.data[AUTO_MODE_PINNED_MODEL_KEY] == "openai/gpt-4o"
        assert store.data[AUTO_MODE_KEEP_CONTEXT_KEY] == "true"
        assert store.data[AUTO_MODE_FLASH_KEY] == "true"

        echoed = websocket.sent[-1]["content"]
        assert echoed["enabled"] is True
        assert echoed["prompt"] == "Explain the error"

    async def test_update_disable_disarms_immediately(self, handler, store):
        app_state.auto_mode_enabled = True
        store.data[AUTO_MODE_ENABLED_KEY] = "true"

        await handler._handle_auto_mode_update_settings(
            {"settings": {"enabled": False}}
        )

        assert app_state.auto_mode_enabled is False
        assert store.data[AUTO_MODE_ENABLED_KEY] == "false"

    async def test_update_ignores_non_dict_settings(self, handler, store):
        app_state.auto_mode_enabled = True

        await handler._handle_auto_mode_update_settings({"settings": "nope"})

        # Nothing written, gate unchanged, still echoes current settings.
        assert store.data == {}
        assert app_state.auto_mode_enabled is True

    async def test_partial_update_leaves_other_keys(self, handler, store):
        store.data[AUTO_MODE_PROMPT_KEY] = "keep me"

        await handler._handle_auto_mode_update_settings(
            {"settings": {"flash": True}}
        )

        assert store.data[AUTO_MODE_FLASH_KEY] == "true"
        assert store.data[AUTO_MODE_PROMPT_KEY] == "keep me"


class TestAutoModeSubmitCapture:
    """The auto_mode flag forces a capture even when the tab has history."""

    async def _run_submit(self, handler, session, payload):
        manager = _FakeTabManager(session)
        handler._get_tab_manager = lambda: manager
        with (
            patch.object(
                handlers.ConversationService,
                "extract_skill_slash_commands",
                new=AsyncMock(return_value=([], "look")),
            ),
            patch.object(
                handlers.ScreenshotHandler, "capture_fullscreen", new=AsyncMock()
            ) as mock_capture,
            patch.object(handlers, "set_current_tab_id", return_value=object()),
            patch.object(handlers, "reset_current_tab_id"),
        ):
            await handler._handle_submit_query(payload)
        return mock_capture

    async def test_auto_mode_captures_despite_history(self, handler):
        session = _make_session(chat_history=[{"role": "user", "content": "prev"}])
        mock_capture = await self._run_submit(
            handler,
            session,
            {
                "tab_id": "t-auto",
                "content": "look",
                "capture_mode": "fullscreen",
                "auto_mode": True,
            },
        )
        mock_capture.assert_awaited_once_with(tab_state=session.state)
        session.queue.enqueue.assert_awaited_once()

    async def test_manual_submit_skips_capture_with_history(self, handler):
        session = _make_session(chat_history=[{"role": "user", "content": "prev"}])
        mock_capture = await self._run_submit(
            handler,
            session,
            {
                "tab_id": "t-manual",
                "content": "look",
                "capture_mode": "fullscreen",
            },
        )
        mock_capture.assert_not_awaited()
        session.queue.enqueue.assert_awaited_once()


class TestAutoModeService:
    def test_resolve_payload_defaults_to_current_model(self, store):
        app_state.selected_model = "current-model"

        payload = auto_mode._resolve_auto_mode_payload()

        assert payload["prompt"] == DEFAULT_AUTO_MODE_PROMPT
        assert payload["model"] == "current-model"
        assert payload["keep_context"] is False
        assert payload["flash"] is False

    def test_resolve_payload_uses_pinned_model_and_settings(self, store):
        store.data.update(
            {
                AUTO_MODE_PINNED_MODEL_KEY: "pinned-vision",
                AUTO_MODE_PROMPT_KEY: "Summarize",
                AUTO_MODE_KEEP_CONTEXT_KEY: "true",
                AUTO_MODE_FLASH_KEY: "true",
            }
        )
        app_state.selected_model = "current-model"

        payload = auto_mode._resolve_auto_mode_payload()

        assert payload["model"] == "pinned-vision"
        assert payload["prompt"] == "Summarize"
        assert payload["keep_context"] is True
        assert payload["flash"] is True

    def test_resolve_payload_blank_prompt_falls_back(self, store):
        store.data[AUTO_MODE_PROMPT_KEY] = "   "
        payload = auto_mode._resolve_auto_mode_payload()
        assert payload["prompt"] == DEFAULT_AUTO_MODE_PROMPT

    async def test_trigger_broadcasts_when_enabled(self, store, monkeypatch):
        app_state.auto_mode_enabled = True
        app_state.selected_model = "m"
        mock_bcast = AsyncMock()
        monkeypatch.setattr(auto_mode, "broadcast_message", mock_bcast)

        await auto_mode.AutoModeHandler.on_auto_mode_trigger()

        mock_bcast.assert_awaited_once()
        msg_type, content = mock_bcast.await_args.args
        assert msg_type == "auto_mode_trigger"
        assert content["model"] == "m"

    async def test_trigger_noop_when_disabled(self, monkeypatch):
        app_state.auto_mode_enabled = False
        mock_bcast = AsyncMock()
        monkeypatch.setattr(auto_mode, "broadcast_message", mock_bcast)

        await auto_mode.AutoModeHandler.on_auto_mode_trigger()

        mock_bcast.assert_not_awaited()

    async def test_mini_toggle_broadcasts(self, monkeypatch):
        mock_bcast = AsyncMock()
        monkeypatch.setattr(auto_mode, "broadcast_message", mock_bcast)

        await auto_mode.AutoModeHandler.on_mini_toggle()

        mock_bcast.assert_awaited_once()
        assert mock_bcast.await_args.args[0] == "toggle_mini_mode"


class TestAutoModeGating:
    def test_is_auto_mode_enabled_reflects_state(self):
        # screenshot_runtime imports tkinter at module load; skip if unavailable.
        pytest.importorskip("tkinter")
        from source.infrastructure import screenshot_runtime as sr

        app_state.auto_mode_enabled = True
        assert sr._is_auto_mode_enabled() is True
        app_state.auto_mode_enabled = False
        assert sr._is_auto_mode_enabled() is False
