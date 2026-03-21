"""Tests for source/api/websocket.py endpoint behavior."""

import json
from types import SimpleNamespace

import pytest
from fastapi import WebSocketDisconnect

import source.api.websocket as websocket_api
from source.core.state import app_state


class _FakeWebSocket:
    def __init__(self, incoming=None, *, fail_error_send: bool = False):
        self._incoming = list(incoming or [])
        self.fail_error_send = fail_error_send
        self.sent: list[str] = []

    async def send_text(self, message: str):
        if self.fail_error_send and '"type": "error"' in message:
            raise RuntimeError("send failure")
        self.sent.append(message)

    async def receive_text(self) -> str:
        if not self._incoming:
            raise WebSocketDisconnect()
        next_item = self._incoming.pop(0)
        if isinstance(next_item, Exception):
            raise next_item
        return next_item


class _FakeManager:
    def __init__(self):
        self.connected = []
        self.disconnected = []

    async def connect(self, websocket):
        self.connected.append(websocket)

    def disconnect(self, websocket):
        self.disconnected.append(websocket)


class TestWebsocketEndpoint:
    @pytest.mark.asyncio
    async def test_endpoint_sends_ready_and_routes_messages(self, monkeypatch):
        manager = _FakeManager()
        handled_messages: list[dict] = []
        adopted_sessions = []

        class _Handler:
            def __init__(self, websocket):
                self.websocket = websocket

            async def handle(self, data):
                handled_messages.append(data)

        fake_tab_state = SimpleNamespace(
            screenshot_list=[{"id": "ss-tab", "name": "tab.png", "thumbnail": "thumb"}]
        )
        fake_tab_manager = SimpleNamespace(
            get_or_create=lambda _tab_id: SimpleNamespace(state=SimpleNamespace(screenshot_list=[])),
            get_all_tab_ids=lambda: ["tab-1"],
            get_state=lambda _tab_id: fake_tab_state,
        )

        saved_screenshots = list(app_state.screenshot_list)
        saved_active_tab = app_state.active_tab_id
        app_state.screenshot_list = [
            {"id": "ss-global", "name": "global.png", "thumbnail": "global-thumb"}
        ]
        app_state.active_tab_id = "tab-1"

        def _adopt_global(session):
            adopted_sessions.append(session)
            app_state.screenshot_list = []
            return 1

        monkeypatch.setattr(websocket_api, "manager", manager)
        monkeypatch.setattr(websocket_api, "MessageHandler", _Handler)
        monkeypatch.setattr(
            "source.services.tab_manager_instance.tab_manager", fake_tab_manager, raising=False
        )
        monkeypatch.setattr(
            "source.services.tab_manager_instance._adopt_global_screenshots",
            _adopt_global,
            raising=False,
        )

        ws = _FakeWebSocket(
            incoming=[json.dumps({"type": "tab_activated", "tab_id": "tab-1"}), WebSocketDisconnect()]
        )
        try:
            await websocket_api.websocket_endpoint(ws)
        finally:
            app_state.screenshot_list = saved_screenshots
            app_state.active_tab_id = saved_active_tab

        assert manager.connected == [ws]
        assert manager.disconnected == [ws]
        assert handled_messages == [{"type": "tab_activated", "tab_id": "tab-1"}]
        assert len(adopted_sessions) == 1

        decoded = [json.loads(msg) for msg in ws.sent]
        assert decoded[0]["type"] == "ready"
        assert any(
            msg["type"] == "screenshot_added" and msg["tab_id"] == "tab-1"
            for msg in decoded
        )

    @pytest.mark.asyncio
    async def test_endpoint_ignores_malformed_and_sends_error_on_handler_exception(
        self, monkeypatch
    ):
        manager = _FakeManager()

        class _Handler:
            def __init__(self, websocket):
                self.websocket = websocket

            async def handle(self, data):
                raise RuntimeError(f"boom: {data.get('type')}")

        monkeypatch.setattr(websocket_api, "manager", manager)
        monkeypatch.setattr(websocket_api, "MessageHandler", _Handler)
        monkeypatch.setattr("source.services.tab_manager_instance.tab_manager", None, raising=False)

        ws = _FakeWebSocket(
            incoming=[
                "{not-json",
                json.dumps({"type": "submit_query"}),
                WebSocketDisconnect(),
            ]
        )

        await websocket_api.websocket_endpoint(ws)

        decoded = [json.loads(msg) for msg in ws.sent]
        assert decoded[0]["type"] == "ready"
        assert any(
            msg["type"] == "error" and "Internal error: boom: submit_query" in msg["content"]
            for msg in decoded
        )
        assert manager.disconnected == [ws]

    @pytest.mark.asyncio
    async def test_endpoint_swallows_send_error_during_error_reporting(self, monkeypatch):
        manager = _FakeManager()

        class _Handler:
            def __init__(self, websocket):
                self.websocket = websocket

            async def handle(self, _data):
                raise RuntimeError("kaboom")

        monkeypatch.setattr(websocket_api, "manager", manager)
        monkeypatch.setattr(websocket_api, "MessageHandler", _Handler)
        monkeypatch.setattr("source.services.tab_manager_instance.tab_manager", None, raising=False)

        ws = _FakeWebSocket(
            incoming=[json.dumps({"type": "x"}), WebSocketDisconnect()],
            fail_error_send=True,
        )

        # Should complete without raising despite send failure in nested error handler.
        await websocket_api.websocket_endpoint(ws)
        assert manager.disconnected == [ws]

