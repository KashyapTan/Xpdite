"""Tests for source/core/thread_pool.py."""

import time
from types import SimpleNamespace

import pytest

from source.core.thread_pool import run_in_thread, shutdown_thread_pool


class TestRunInThread:
    @pytest.mark.asyncio
    async def test_basic_function(self):
        def add(a, b):
            return a + b

        result = await run_in_thread(add, 2, 3)
        assert result == 5

    @pytest.mark.asyncio
    async def test_blocking_function(self):
        """Verify that blocking functions run without blocking the event loop."""
        def slow():
            time.sleep(0.05)
            return "done"

        result = await run_in_thread(slow)
        assert result == "done"

    @pytest.mark.asyncio
    async def test_kwargs_passed(self):
        def greet(name, greeting="Hello"):
            return f"{greeting}, {name}!"

        result = await run_in_thread(greet, "World", greeting="Hi")
        assert result == "Hi, World!"

    @pytest.mark.asyncio
    async def test_exception_propagates(self):
        def fail():
            raise ValueError("test error")

        with pytest.raises(ValueError, match="test error"):
            await run_in_thread(fail)

    @pytest.mark.asyncio
    async def test_returns_none(self):
        def noop():
            pass

        result = await run_in_thread(noop)
        assert result is None


class TestShutdownThreadPool:
    def test_shutdown_thread_pool_forwards_flags(self, monkeypatch):
        calls = {}
        fake_executor = SimpleNamespace(
            shutdown=lambda **kwargs: calls.update(kwargs)
        )
        monkeypatch.setattr("source.core.thread_pool._app_executor", fake_executor)

        shutdown_thread_pool(wait=False, cancel_futures=True)

        assert calls == {"wait": False, "cancel_futures": True}
