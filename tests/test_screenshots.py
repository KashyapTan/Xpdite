"""Tests for the tab-aware screenshot system.

Covers:
- TabState.add_screenshot / remove_screenshot
- ScreenshotHandler._resolve_tab_state fallback chain
- Cross-tab isolation (removing from tab A doesn't affect tab B)
"""

import asyncio
import os
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from source.core.state import app_state


# ---------------------------------------------------------------------------
# TabState screenshot methods
# ---------------------------------------------------------------------------


class TestTabStateScreenshots:
    """Test TabState.add_screenshot and remove_screenshot."""

    def _make_tab_state(self, tab_id: str = "test-tab"):
        from source.services.tab_manager import TabState
        return TabState(tab_id=tab_id)

    def test_add_screenshot_assigns_unique_id(self):
        saved = app_state.screenshot_counter
        app_state.screenshot_counter = 0
        try:
            ts = self._make_tab_state()
            ss_id = ts.add_screenshot({"path": "/img1.png", "name": "img1.png", "thumbnail": "t1"})
            assert ss_id == "ss_1"
            assert len(ts.screenshot_list) == 1
            assert ts.screenshot_list[0]["id"] == "ss_1"
        finally:
            app_state.screenshot_counter = saved

    def test_add_multiple_screenshots_increments_counter(self):
        saved = app_state.screenshot_counter
        app_state.screenshot_counter = 5
        try:
            ts = self._make_tab_state()
            id1 = ts.add_screenshot({"path": "/a.png", "name": "a.png", "thumbnail": ""})
            id2 = ts.add_screenshot({"path": "/b.png", "name": "b.png", "thumbnail": ""})
            assert id1 == "ss_6"
            assert id2 == "ss_7"
            assert app_state.screenshot_counter == 7
        finally:
            app_state.screenshot_counter = saved

    def test_remove_screenshot_success(self):
        saved = app_state.screenshot_counter
        app_state.screenshot_counter = 0
        try:
            ts = self._make_tab_state()
            ts.add_screenshot({"path": "/x.png", "name": "x.png", "thumbnail": ""})
            assert ts.remove_screenshot("ss_1") is True
            assert len(ts.screenshot_list) == 0
        finally:
            app_state.screenshot_counter = saved

    def test_remove_screenshot_not_found(self):
        ts = self._make_tab_state()
        assert ts.remove_screenshot("ss_999") is False

    def test_get_image_paths_filters_missing(self, tmp_path):
        saved = app_state.screenshot_counter
        app_state.screenshot_counter = 0
        try:
            ts = self._make_tab_state()
            real_file = tmp_path / "real.png"
            real_file.write_bytes(b"\x89PNG")

            ts.add_screenshot({"path": str(real_file), "name": "real.png", "thumbnail": ""})
            ts.add_screenshot({"path": "/nonexistent.png", "name": "ghost.png", "thumbnail": ""})

            paths = ts.get_image_paths()
            assert len(paths) == 1
            assert paths[0] == os.path.abspath(str(real_file))
        finally:
            app_state.screenshot_counter = saved


# ---------------------------------------------------------------------------
# Cross-tab isolation
# ---------------------------------------------------------------------------


class TestCrossTabIsolation:
    """Verify screenshots on one tab don't leak to another."""

    def test_tabs_have_separate_screenshot_lists(self):
        saved = app_state.screenshot_counter
        app_state.screenshot_counter = 0
        try:
            from source.services.tab_manager import TabState

            tab_a = TabState(tab_id="a")
            tab_b = TabState(tab_id="b")

            tab_a.add_screenshot({"path": "/a.png", "name": "a.png", "thumbnail": ""})
            tab_b.add_screenshot({"path": "/b.png", "name": "b.png", "thumbnail": ""})

            assert len(tab_a.screenshot_list) == 1
            assert len(tab_b.screenshot_list) == 1

            tab_a.remove_screenshot("ss_1")
            assert len(tab_a.screenshot_list) == 0
            assert len(tab_b.screenshot_list) == 1  # unaffected
        finally:
            app_state.screenshot_counter = saved


# ---------------------------------------------------------------------------
# _resolve_tab_state fallback chain
# ---------------------------------------------------------------------------


class TestResolveTabState:
    """Test ScreenshotHandler._resolve_tab_state fallback logic."""

    def test_explicit_tab_state_wins(self):
        from source.services.screenshots import ScreenshotHandler
        from source.services.tab_manager import TabState

        explicit = TabState(tab_id="explicit")
        result = ScreenshotHandler._resolve_tab_state(explicit)
        assert result is explicit

    @patch("source.services.screenshots.ScreenshotHandler._get_active_tab_state")
    def test_falls_back_to_active_tab(self, mock_get_active):
        from source.services.screenshots import ScreenshotHandler
        from source.services.tab_manager import TabState

        active_ts = TabState(tab_id="active")
        mock_get_active.return_value = active_ts

        result = ScreenshotHandler._resolve_tab_state(None)
        assert result is active_ts

    @patch("source.services.screenshots.ScreenshotHandler._get_active_tab_state")
    def test_returns_none_when_no_tab(self, mock_get_active):
        from source.services.screenshots import ScreenshotHandler

        mock_get_active.return_value = None
        result = ScreenshotHandler._resolve_tab_state(None)
        assert result is None


# ---------------------------------------------------------------------------
# _get_active_tab_state — contextvar vs global fallback
# ---------------------------------------------------------------------------


class TestGetActiveTabState:
    """Test _get_active_tab_state prefers contextvar over app_state.active_tab_id."""

    def test_prefers_contextvar(self):
        from source.services.screenshots import ScreenshotHandler
        from source.services.tab_manager import TabManager
        from source.core.connection import set_current_tab_id

        # Build a minimal tab manager with two tabs
        async def _noop(q):
            return None

        async def _noop_bc(tid, mt, c):
            pass

        tm = TabManager(process_fn=_noop, broadcast_fn=_noop_bc)
        ctx_tab = tm.create_tab("ctx-tab")
        global_tab = tm.create_tab("global-tab")

        saved_tab = app_state.active_tab_id
        app_state.active_tab_id = "global-tab"

        try:
            with patch("source.services.tab_manager_instance.tab_manager", tm):
                # No contextvar set — should fall back to global
                result = ScreenshotHandler._get_active_tab_state()
                assert result is global_tab.state

                # Set contextvar — should prefer it
                token = set_current_tab_id("ctx-tab")
                try:
                    result = ScreenshotHandler._get_active_tab_state()
                    assert result is ctx_tab.state
                finally:
                    set_current_tab_id(None)
        finally:
            app_state.active_tab_id = saved_tab
