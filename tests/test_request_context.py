"""Tests for RequestContext cancellation semantics."""

import asyncio

import pytest

from source.core.request_context import RequestContext


class TestRequestContext:
    def test_initial_state(self):
        ctx = RequestContext()
        assert ctx.cancelled is False
        assert ctx.is_done is False

    def test_cancel_sets_flag(self):
        ctx = RequestContext()
        ctx.cancel()
        assert ctx.cancelled is True

    def test_cancel_is_idempotent(self):
        """Calling cancel() twice should only fire callbacks once."""
        ctx = RequestContext()
        call_count = 0

        def cb():
            nonlocal call_count
            call_count += 1

        ctx.on_cancel(cb)
        ctx.cancel()
        ctx.cancel()
        assert call_count == 1

    def test_on_cancel_fires_callback(self):
        ctx = RequestContext()
        fired = []
        ctx.on_cancel(lambda: fired.append(True))
        ctx.cancel()
        assert fired == [True]

    def test_on_cancel_fires_immediately_if_already_cancelled(self):
        ctx = RequestContext()
        ctx.cancel()
        fired = []
        ctx.on_cancel(lambda: fired.append(True))
        assert fired == [True]

    def test_mark_done_sets_event(self):
        ctx = RequestContext()
        assert ctx.is_done is False
        ctx.mark_done()
        assert ctx.is_done is True

    def test_mark_done_clears_callbacks(self):
        ctx = RequestContext()
        fired = []
        ctx.on_cancel(lambda: fired.append(True))
        ctx.mark_done()
        ctx.cancel()
        # Callback list was cleared by mark_done, so callback should not fire
        assert fired == []

    def test_multiple_callbacks(self):
        ctx = RequestContext()
        results = []
        ctx.on_cancel(lambda: results.append("a"))
        ctx.on_cancel(lambda: results.append("b"))
        ctx.cancel()
        assert set(results) == {"a", "b"}

    def test_callback_exception_does_not_break_others(self):
        """A failing callback should not prevent others from running."""
        ctx = RequestContext()
        results = []

        def bad():
            raise RuntimeError("boom")

        ctx.on_cancel(bad)
        ctx.on_cancel(lambda: results.append("ok"))
        ctx.cancel()
        assert "ok" in results

    def test_forced_skills_default(self):
        ctx = RequestContext()
        assert ctx.forced_skills == []
