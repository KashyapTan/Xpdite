"""Tests for source/main.py entrypoint helpers."""

import asyncio
import sys
from types import SimpleNamespace

import pytest

import source.main as main_module


class _FakeThread:
    """Thread test-double that runs target immediately on start()."""

    def __init__(self, target, args=(), daemon=False):
        self.target = target
        self.args = args
        self.daemon = daemon
        self.started = False

    def start(self):
        self.started = True
        self.target(*self.args)


class _NoopThread:
    """Thread test-double that never executes target."""

    def __init__(self, target, args=(), daemon=False):
        self.target = target
        self.args = args
        self.daemon = daemon

    def start(self):
        return None


class TestMainModuleHelpers:
    def test_emit_boot_marker_prints_structured_prefix(self, monkeypatch):
        printed = []
        flushed = {"stdout": 0}

        def _fake_print(*args, **kwargs):
            printed.append((args, kwargs))

        monkeypatch.setattr("builtins.print", _fake_print)
        monkeypatch.setattr(
            main_module._sys.stdout, "flush", lambda: flushed.__setitem__("stdout", 1)
        )

        main_module._emit_boot_marker("loading", "Booting", 33)

        assert printed, "Expected _emit_boot_marker to print"
        args, kwargs = printed[0]
        assert args[0].startswith("XPDITE_BOOT ")
        assert '"phase": "loading"' in args[0]
        assert '"message": "Booting"' in args[0]
        assert '"progress": 33' in args[0]
        assert kwargs.get("flush") is True
        assert flushed["stdout"] == 1

    def test_find_available_port_skips_busy_ports(self, monkeypatch):
        attempts = {"count": 0}

        class _FakeSocket:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def bind(self, _addr):
                attempts["count"] += 1
                if attempts["count"] == 1:
                    raise OSError("busy")

        monkeypatch.setattr(main_module.socket, "socket", lambda *a, **k: _FakeSocket())

        port = main_module.find_available_port(start_port=9000, max_attempts=3)
        assert port == 9001

    def test_find_available_port_raises_when_no_ports(self, monkeypatch):
        class _AlwaysBusySocket:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def bind(self, _addr):
                raise OSError("busy")

        monkeypatch.setattr(
            main_module.socket, "socket", lambda *a, **k: _AlwaysBusySocket()
        )

        with pytest.raises(RuntimeError, match="Could not find available port"):
            main_module.find_available_port(start_port=7000, max_attempts=2)


class TestMainServices:
    def test_start_screenshot_service_initialises_listener_thread(self, monkeypatch):
        starts = {"count": 0}

        class _FakeScreenshotService:
            def __init__(self, process, process_start):
                self.process = process
                self.process_start = process_start

            def start_listener(self, _folder):
                starts["count"] += 1

        fake_state = SimpleNamespace(screenshot_service=None, service_thread=None)

        monkeypatch.setattr(main_module, "app_state", fake_state)
        monkeypatch.setattr("source.infrastructure.screenshot_runtime.ScreenshotService", _FakeScreenshotService)
        monkeypatch.setattr(main_module.threading, "Thread", _FakeThread)

        main_module.start_screenshot_service()

        assert fake_state.screenshot_service is not None
        assert fake_state.service_thread is not None
        assert fake_state.service_thread.started is True
        assert starts["count"] == 1

    def test_start_screenshot_service_handles_errors(self, monkeypatch):
        fake_state = SimpleNamespace(screenshot_service=None, service_thread=None)

        class _BrokenScreenshotService:
            def __init__(self, *_args, **_kwargs):
                raise RuntimeError("boom")

        monkeypatch.setattr(main_module, "app_state", fake_state)
        monkeypatch.setattr("source.infrastructure.screenshot_runtime.ScreenshotService", _BrokenScreenshotService)

        main_module.start_screenshot_service()
        assert fake_state.screenshot_service is None

    def test_start_transcription_service_initialises_service(self, monkeypatch):
        fake_state = SimpleNamespace(transcription_service=None)

        class _FakeTranscriptionService:
            pass

        monkeypatch.setattr(main_module, "app_state", fake_state)
        monkeypatch.setitem(
            sys.modules,
            "source.services.media.transcription",
            SimpleNamespace(TranscriptionService=_FakeTranscriptionService),
        )

        main_module.start_transcription_service()
        assert isinstance(fake_state.transcription_service, _FakeTranscriptionService)

    def test_start_transcription_service_handles_errors(self, monkeypatch):
        fake_state = SimpleNamespace(transcription_service=None)

        class _BrokenTranscriptionService:
            def __init__(self):
                raise RuntimeError("broken")

        monkeypatch.setattr(main_module, "app_state", fake_state)
        monkeypatch.setitem(
            sys.modules,
            "source.services.media.transcription",
            SimpleNamespace(TranscriptionService=_BrokenTranscriptionService),
        )

        main_module.start_transcription_service()
        assert fake_state.transcription_service is None


class TestStartServer:
    def _patch_uvicorn(self, monkeypatch, served):
        class _FakeConfig:
            def __init__(self, app, host, port, log_level, loop):
                self.app = app
                self.host = host
                self.port = port
                self.log_level = log_level
                self.loop = loop

        class _FakeServer:
            def __init__(self, config):
                self.config = config

            async def serve(self):
                served.append(self.config.port)
                await asyncio.sleep(0)
                await asyncio.sleep(0)

        monkeypatch.setattr(main_module.uvicorn, "Config", _FakeConfig)
        monkeypatch.setattr(main_module.uvicorn, "Server", _FakeServer)

    def test_start_server_returns_early_when_no_port(self, monkeypatch):
        fake_state = SimpleNamespace(server_loop_holder={})
        monkeypatch.setattr(main_module, "app_state", fake_state)
        monkeypatch.setattr(
            main_module, "find_available_port", lambda: (_ for _ in ()).throw(RuntimeError("no port"))
        )

        main_module.start_server()
        assert fake_state.server_loop_holder == {}

    def test_start_server_runs_boot_sequence_and_serves(self, monkeypatch):
        served = []
        tab_init = {"count": 0}
        markers = []
        created_loops = []

        fake_state = SimpleNamespace(server_loop_holder={})
        monkeypatch.setattr(main_module, "app_state", fake_state)
        monkeypatch.setattr(main_module, "find_available_port", lambda: 8123)
        monkeypatch.setattr(main_module, "_emit_boot_marker", lambda p, m, pr: markers.append((p, m, pr)))
        monkeypatch.setattr(
            "source.services.chat.tab_manager_instance.init_tab_manager",
            lambda: tab_init.__setitem__("count", tab_init["count"] + 1),
        )

        async def _fake_init_mcp():
            return None

        monkeypatch.setattr(main_module, "init_mcp_servers", _fake_init_mcp)
        monkeypatch.setattr("os.path.exists", lambda _path: False)

        real_new_event_loop = asyncio.new_event_loop

        def _fake_new_event_loop():
            loop = real_new_event_loop()
            created_loops.append(loop)
            return loop

        monkeypatch.setattr(main_module.asyncio, "new_event_loop", _fake_new_event_loop)
        self._patch_uvicorn(monkeypatch, served)

        try:
            main_module.start_server()
        finally:
            for loop in created_loops:
                loop.close()

        assert tab_init["count"] == 1
        assert fake_state.server_loop_holder["port"] == 8123
        assert "loop" in fake_state.server_loop_holder
        assert served == [8123]
        assert [phase for phase, _msg, _progress in markers] == [
            "loading_runtime",
            "initializing_mcp",
            "starting_http",
        ]

    def test_start_server_attempts_google_connection_when_token_exists(self, monkeypatch):
        served = []
        connected = {"count": 0}
        created_loops = []
        fake_state = SimpleNamespace(server_loop_holder={})

        monkeypatch.setattr(main_module, "app_state", fake_state)
        monkeypatch.setattr(main_module, "find_available_port", lambda: 9009)
        monkeypatch.setattr("source.services.chat.tab_manager_instance.init_tab_manager", lambda: None)
        monkeypatch.setattr(main_module, "_emit_boot_marker", lambda *_args: None)

        async def _fake_init_mcp():
            return None

        async def _fake_connect_google():
            connected["count"] += 1

        monkeypatch.setattr(main_module, "init_mcp_servers", _fake_init_mcp)
        monkeypatch.setattr("os.path.exists", lambda _path: True)
        monkeypatch.setattr(
            "source.mcp_integration.core.manager.mcp_manager",
            SimpleNamespace(connect_google_servers=_fake_connect_google),
            raising=False,
        )

        real_new_event_loop = asyncio.new_event_loop

        def _fake_new_event_loop():
            loop = real_new_event_loop()
            created_loops.append(loop)
            return loop

        monkeypatch.setattr(main_module.asyncio, "new_event_loop", _fake_new_event_loop)
        self._patch_uvicorn(monkeypatch, served)

        try:
            main_module.start_server()
        finally:
            for loop in created_loops:
                loop.close()

        assert connected["count"] == 1
        assert served == [9009]

    def test_start_server_continues_when_mcp_init_fails(self, monkeypatch):
        served = []
        created_loops = []
        fake_state = SimpleNamespace(server_loop_holder={})

        monkeypatch.setattr(main_module, "app_state", fake_state)
        monkeypatch.setattr(main_module, "find_available_port", lambda: 8011)
        monkeypatch.setattr("source.services.chat.tab_manager_instance.init_tab_manager", lambda: None)
        monkeypatch.setattr(main_module, "_emit_boot_marker", lambda *_args: None)
        monkeypatch.setattr("os.path.exists", lambda _path: False)

        async def _failing_mcp_init():
            raise RuntimeError("mcp failed")

        monkeypatch.setattr(main_module, "init_mcp_servers", _failing_mcp_init)

        real_new_event_loop = asyncio.new_event_loop

        def _fake_new_event_loop():
            loop = real_new_event_loop()
            created_loops.append(loop)
            return loop

        monkeypatch.setattr(main_module.asyncio, "new_event_loop", _fake_new_event_loop)
        self._patch_uvicorn(monkeypatch, served)

        try:
            main_module.start_server()
        finally:
            for loop in created_loops:
                loop.close()

        assert served == [8011]


class TestMainEntrypoint:
    def test_main_starts_and_cleans_up_on_keyboard_interrupt(self, monkeypatch):
        fake_state = SimpleNamespace(server_loop_holder={}, server_thread=None)
        register_calls = {"count": 0}
        screenshot_calls = {"count": 0}
        transcription_calls = {"count": 0}
        cleanup_calls = {"count": 0}

        def _fake_start_server():
            fake_state.server_loop_holder["loop"] = object()
            fake_state.server_loop_holder["port"] = 8555

        def _fake_sleep(seconds):
            if seconds == 1:
                raise KeyboardInterrupt()

        monkeypatch.setattr(main_module, "app_state", fake_state)
        monkeypatch.setattr(main_module, "register_signal_handlers", lambda: register_calls.__setitem__("count", 1))
        monkeypatch.setattr(main_module, "start_server", _fake_start_server)
        monkeypatch.setattr(
            main_module,
            "start_screenshot_service",
            lambda: screenshot_calls.__setitem__("count", 1),
        )
        monkeypatch.setattr(
            main_module,
            "start_transcription_service",
            lambda: transcription_calls.__setitem__("count", 1),
        )
        monkeypatch.setattr(main_module.threading, "Thread", _FakeThread)
        monkeypatch.setattr(main_module.time, "sleep", _fake_sleep)
        monkeypatch.setattr(
            "source.core.lifecycle.cleanup_resources",
            lambda: cleanup_calls.__setitem__("count", 1),
        )

        main_module.main()

        assert register_calls["count"] == 1
        assert screenshot_calls["count"] == 1
        assert transcription_calls["count"] == 1
        assert cleanup_calls["count"] == 1

    def test_main_exits_when_server_loop_never_initialises(self, monkeypatch):
        fake_state = SimpleNamespace(server_loop_holder={}, server_thread=None)

        class _NeverReadyEvent:
            def set(self):
                return None

            def wait(self, timeout=None):
                return False

        monkeypatch.setattr(main_module, "app_state", fake_state)
        monkeypatch.setattr(main_module, "register_signal_handlers", lambda: None)
        monkeypatch.setattr(main_module, "start_server", lambda: None)
        monkeypatch.setattr(main_module.threading, "Thread", _NoopThread)
        monkeypatch.setattr(main_module.threading, "Event", _NeverReadyEvent)

        with pytest.raises(SystemExit) as exc:
            main_module.main()

        assert exc.value.code == 1

