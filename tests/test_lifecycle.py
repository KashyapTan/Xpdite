"""Tests for source/core/lifecycle.py."""

import builtins
import types

from source.core.lifecycle import (
    _clear_folder,
    cleanup_resources,
    register_signal_handlers,
    signal_handler,
)


class TestClearFolder:
    def test_removes_files(self, tmp_path):
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("hello")
        f2.write_text("world")
        _clear_folder(str(tmp_path))
        assert not f1.exists()
        assert not f2.exists()

    def test_preserves_subdirectories(self, tmp_path):
        sub = tmp_path / "subdir"
        sub.mkdir()
        f = tmp_path / "file.txt"
        f.write_text("data")
        _clear_folder(str(tmp_path))
        assert not f.exists()
        assert sub.is_dir()  # directories are preserved

    def test_nonexistent_folder_is_noop(self):
        _clear_folder("/nonexistent/path/xyz")  # should not raise

    def test_empty_folder(self, tmp_path):
        _clear_folder(str(tmp_path))  # should not raise


class TestLifecycleHooks:
    def setup_method(self):
        import source.core.lifecycle as lifecycle

        lifecycle._cleanup_done = False

    def teardown_method(self):
        import source.core.lifecycle as lifecycle

        lifecycle._cleanup_done = False

    def test_cleanup_resources_early_returns_when_already_done(self):
        import source.core.lifecycle as lifecycle

        lifecycle._cleanup_done = True
        cleanup_resources()
        assert lifecycle._cleanup_done is True

    def test_cleanup_resources_handles_relative_import_fallback_failure(self, monkeypatch):
        import source.core.lifecycle as lifecycle

        monkeypatch.delitem(__import__("sys").modules, "source.core.state", raising=False)
        real_import = builtins.__import__
        monkeypatch.setattr(
            "builtins.__import__",
            lambda name, *args, **kwargs: (_ for _ in ()).throw(ImportError("boom"))
            if name in {".state", "..mcp_integration.core.manager", "..config"}
            else real_import(name, *args, **kwargs),
        )

        cleanup_resources()
        assert lifecycle._cleanup_done is True

    def test_cleanup_resources_executes_service_cleanup_paths(self, monkeypatch, tmp_path):
        import source.core.lifecycle as lifecycle

        class _FakeFuture:
            def result(self, timeout=None):
                return None

        class _FakeLoop:
            def is_running(self):
                return True

        class _FakeScreenshotService:
            def __init__(self):
                self.stopped = False

            def stop_listener(self):
                self.stopped = True

        class _FakeTabManager:
            async def close_all(self):
                return None

        fake_state = types.SimpleNamespace(
            server_loop_holder={"loop": _FakeLoop()},
            screenshot_service=_FakeScreenshotService(),
        )
        class _FakeMcpManager:
            async def cleanup(self):
                return None

        fake_mcp_manager = _FakeMcpManager()
        fake_config = types.SimpleNamespace(SCREENSHOT_FOLDER=str(tmp_path / "other"))
        fake_thread_pool = types.SimpleNamespace(shutdown_thread_pool=lambda: None)
        fake_tab_mgr_mod = types.SimpleNamespace(tab_manager=_FakeTabManager())

        screenshot_dir = tmp_path / "screenshots"
        screenshot_dir.mkdir()
        (screenshot_dir / "a.png").write_text("x")

        monkeypatch.chdir(tmp_path)
        monkeypatch.setitem(__import__("sys").modules, "source.core.state", types.SimpleNamespace(app_state=fake_state))
        monkeypatch.setitem(
            __import__("sys").modules,
            "source.mcp_integration.core.manager",
            types.SimpleNamespace(mcp_manager=fake_mcp_manager),
        )
        monkeypatch.setitem(__import__("sys").modules, "source.infrastructure.config", fake_config)
        monkeypatch.setitem(__import__("sys").modules, "source.core.thread_pool", fake_thread_pool)
        monkeypatch.setitem(
            __import__("sys").modules, "source.services.chat.tab_manager_instance", fake_tab_mgr_mod
        )

        def _fake_run_coroutine_threadsafe(coro, _loop):
            coro.close()
            return _FakeFuture()

        monkeypatch.setattr(
            lifecycle.asyncio, "run_coroutine_threadsafe", _fake_run_coroutine_threadsafe
        )

        cleanup_resources()
        assert fake_state.screenshot_service.stopped is True
        assert lifecycle._cleanup_done is True

    def test_signal_handler_calls_cleanup_and_exits(self, monkeypatch):
        called = {"cleanup": 0, "exit": None}
        monkeypatch.setattr("source.core.lifecycle.cleanup_resources", lambda: called.__setitem__("cleanup", 1))
        monkeypatch.setattr("source.core.lifecycle.sys.exit", lambda code: called.__setitem__("exit", code))

        signal_handler(2, None)
        assert called["cleanup"] == 1
        assert called["exit"] == 0

    def test_register_signal_handlers_registers_sigint_sigterm_and_atexit(self, monkeypatch):
        registered_signals = []
        registered_exit = []

        monkeypatch.setattr(
            "source.core.lifecycle.signal.signal",
            lambda sig, handler: registered_signals.append((sig, handler)),
        )
        monkeypatch.setattr("source.core.lifecycle.atexit.register", lambda fn: registered_exit.append(fn))

        register_signal_handlers()

        assert len(registered_signals) == 2
        assert registered_exit and registered_exit[0] is cleanup_resources
