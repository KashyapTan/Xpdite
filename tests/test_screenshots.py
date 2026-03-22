"""Tests for the tab-aware screenshot system.

Covers:
- TabState.add_screenshot / remove_screenshot
- ScreenshotHandler._resolve_tab_state fallback chain
- Cross-tab isolation (removing from tab A doesn't affect tab B)
"""

import os
from unittest.mock import AsyncMock, patch

import pytest

from source.core.connection import reset_current_tab_id, set_current_tab_id
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
            ss_id = ts.add_screenshot(
                {"path": "/img1.png", "name": "img1.png", "thumbnail": "t1"}
            )
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
            id1 = ts.add_screenshot(
                {"path": "/a.png", "name": "a.png", "thumbnail": ""}
            )
            id2 = ts.add_screenshot(
                {"path": "/b.png", "name": "b.png", "thumbnail": ""}
            )
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

            ts.add_screenshot(
                {"path": str(real_file), "name": "real.png", "thumbnail": ""}
            )
            ts.add_screenshot(
                {"path": "/nonexistent.png", "name": "ghost.png", "thumbnail": ""}
            )

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
                    reset_current_tab_id(token)
        finally:
            app_state.active_tab_id = saved_tab


# ---------------------------------------------------------------------------
# ScreenshotHandler public API coverage
# ---------------------------------------------------------------------------


class TestCaptureFullscreen:
    @pytest.mark.asyncio
    async def test_capture_fullscreen_success_adds_screenshot(self, tmp_path):
        from source.services.screenshots import ScreenshotHandler
        from source.services.tab_manager import TabState

        image_path = tmp_path / "shot.png"
        image_path.write_bytes(b"\x89PNG")
        tab_state = TabState(tab_id="tab-cap")

        with (
            patch(
                "source.services.screenshots.broadcast_message", new_callable=AsyncMock
            ) as mock_broadcast,
            patch(
                "source.services.screenshots.asyncio.sleep", new_callable=AsyncMock
            ) as mock_sleep,
            patch(
                "source.core.thread_pool.run_in_thread",
                new_callable=AsyncMock,
                return_value=str(image_path),
            ) as mock_run,
            patch.object(
                ScreenshotHandler, "add_screenshot", new=AsyncMock(return_value="ss_42")
            ) as mock_add,
            patch("source.ss.take_fullscreen_screenshot") as mock_take,
        ):
            result = await ScreenshotHandler.capture_fullscreen(tab_state=tab_state)

        assert result == "ss_42"
        mock_broadcast.assert_awaited_once_with(
            "screenshot_start", "Taking fullscreen screenshot..."
        )
        mock_sleep.assert_awaited_once_with(0.4)
        from source.config import SCREENSHOT_FOLDER

        mock_run.assert_awaited_once_with(mock_take, SCREENSHOT_FOLDER)
        mock_add.assert_awaited_once_with(str(image_path), tab_state=tab_state)

    @pytest.mark.asyncio
    async def test_capture_fullscreen_returns_none_when_image_missing(self):
        from source.services.screenshots import ScreenshotHandler

        with (
            patch(
                "source.services.screenshots.broadcast_message", new_callable=AsyncMock
            ),
            patch("source.services.screenshots.asyncio.sleep", new_callable=AsyncMock),
            patch(
                "source.core.thread_pool.run_in_thread",
                new_callable=AsyncMock,
                return_value="/missing/path.png",
            ),
            patch.object(
                ScreenshotHandler, "add_screenshot", new=AsyncMock()
            ) as mock_add,
            patch("source.ss.take_fullscreen_screenshot"),
        ):
            result = await ScreenshotHandler.capture_fullscreen()

        assert result is None
        mock_add.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_capture_fullscreen_handles_threadpool_error(self):
        from source.services.screenshots import ScreenshotHandler

        with (
            patch(
                "source.services.screenshots.broadcast_message", new_callable=AsyncMock
            ),
            patch("source.services.screenshots.asyncio.sleep", new_callable=AsyncMock),
            patch(
                "source.core.thread_pool.run_in_thread",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
            ),
            patch("source.ss.take_fullscreen_screenshot"),
        ):
            result = await ScreenshotHandler.capture_fullscreen()

        assert result is None


class TestScreenshotLifecycle:
    @pytest.mark.asyncio
    async def test_add_screenshot_uses_global_state_when_no_tab(self, tmp_path):
        from source.services.screenshots import ScreenshotHandler

        image_path = tmp_path / "global.png"
        image_path.write_bytes(b"\x89PNG")

        saved_counter = app_state.screenshot_counter
        saved_list = list(app_state.screenshot_list)
        app_state.screenshot_counter = 0
        app_state.screenshot_list = []
        try:
            with (
                patch(
                    "source.ss.create_thumbnail", return_value="thumb-data"
                ) as mock_thumb,
                patch(
                    "source.services.screenshots.broadcast_message",
                    new_callable=AsyncMock,
                ) as mock_broadcast,
                patch(
                    "source.services.screenshots.ScreenshotHandler._get_active_tab_state",
                    return_value=None,
                ),
            ):
                ss_id = await ScreenshotHandler.add_screenshot(str(image_path))

            assert ss_id == "ss_1"
            assert len(app_state.screenshot_list) == 1
            assert app_state.screenshot_list[0]["id"] == "ss_1"
            assert app_state.screenshot_list[0]["name"] == "global.png"
            mock_thumb.assert_called_once_with(os.path.abspath(str(image_path)))
            mock_broadcast.assert_awaited_once_with(
                "screenshot_added",
                {"id": "ss_1", "name": "global.png", "thumbnail": "thumb-data"},
            )
        finally:
            app_state.screenshot_counter = saved_counter
            app_state.screenshot_list = saved_list

    @pytest.mark.asyncio
    async def test_remove_screenshot_deletion_error_still_removes_and_broadcasts(self):
        from source.services.screenshots import ScreenshotHandler
        from source.services.tab_manager import TabState

        tab_state = TabState(tab_id="tab-remove")
        tab_state.screenshot_list = [
            {"id": "ss_9", "path": "/tmp/fail.png", "name": "fail.png", "thumbnail": ""}
        ]

        with (
            patch("source.services.screenshots.os.path.exists", return_value=True),
            patch(
                "source.services.screenshots.os.remove",
                side_effect=OSError("cannot delete"),
            ),
            patch(
                "source.services.screenshots.broadcast_message", new_callable=AsyncMock
            ) as mock_broadcast,
        ):
            removed = await ScreenshotHandler.remove_screenshot(
                "ss_9", tab_state=tab_state
            )

        assert removed is True
        assert tab_state.screenshot_list == []
        mock_broadcast.assert_awaited_once_with("screenshot_removed", {"id": "ss_9"})

    @pytest.mark.asyncio
    async def test_remove_screenshot_not_found_returns_false(self):
        from source.services.screenshots import ScreenshotHandler
        from source.services.tab_manager import TabState

        tab_state = TabState(tab_id="tab-none")
        tab_state.screenshot_list = [
            {"id": "ss_1", "path": "/tmp/ok.png", "name": "ok.png", "thumbnail": ""}
        ]

        with patch(
            "source.services.screenshots.broadcast_message", new_callable=AsyncMock
        ) as mock_broadcast:
            removed = await ScreenshotHandler.remove_screenshot(
                "ss_999", tab_state=tab_state
            )

        assert removed is False
        assert len(tab_state.screenshot_list) == 1
        mock_broadcast.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_clear_screenshots_deletion_error_continues_and_clears(self):
        from source.services.screenshots import ScreenshotHandler
        from source.services.tab_manager import TabState

        tab_state = TabState(tab_id="tab-clear")
        tab_state.screenshot_list = [
            {"id": "ss_1", "path": "/tmp/a.png", "name": "a.png", "thumbnail": ""},
            {"id": "ss_2", "path": "/tmp/b.png", "name": "b.png", "thumbnail": ""},
        ]

        def _remove_side_effect(path):
            if path.endswith("a.png"):
                raise OSError("locked")

        with (
            patch("source.services.screenshots.os.path.exists", return_value=True),
            patch(
                "source.services.screenshots.os.remove", side_effect=_remove_side_effect
            ),
            patch(
                "source.services.screenshots.broadcast_message", new_callable=AsyncMock
            ) as mock_broadcast,
        ):
            await ScreenshotHandler.clear_screenshots(tab_state=tab_state)

        assert tab_state.screenshot_list == []
        mock_broadcast.assert_awaited_once_with("screenshots_cleared", "")


class TestPrecisionModeBehavior:
    @pytest.mark.asyncio
    async def test_on_screenshot_start_ignores_non_precision(self):
        from source.services.screenshots import ScreenshotHandler

        saved_capture_mode = app_state.capture_mode
        app_state.capture_mode = "none"
        try:
            with patch(
                "source.services.screenshots.broadcast_message", new_callable=AsyncMock
            ) as mock_broadcast:
                await ScreenshotHandler.on_screenshot_start()
            mock_broadcast.assert_not_awaited()
        finally:
            app_state.capture_mode = saved_capture_mode

    @pytest.mark.asyncio
    async def test_on_screenshot_start_broadcasts_in_precision(self):
        from source.config import CaptureMode
        from source.services.screenshots import ScreenshotHandler

        saved_capture_mode = app_state.capture_mode
        app_state.capture_mode = CaptureMode.PRECISION
        try:
            with patch(
                "source.services.screenshots.broadcast_message", new_callable=AsyncMock
            ) as mock_broadcast:
                await ScreenshotHandler.on_screenshot_start()
            mock_broadcast.assert_awaited_once_with(
                "screenshot_start", "Screenshot capture starting"
            )
        finally:
            app_state.capture_mode = saved_capture_mode

    @pytest.mark.asyncio
    async def test_on_screenshot_captured_non_precision_deletes_file(self):
        from source.services.screenshots import ScreenshotHandler

        saved_capture_mode = app_state.capture_mode
        app_state.capture_mode = "fullscreen"
        try:
            with (
                patch("source.services.screenshots.os.path.exists", return_value=True),
                patch("source.services.screenshots.os.remove") as mock_remove,
                patch.object(
                    ScreenshotHandler, "add_screenshot", new=AsyncMock()
                ) as mock_add,
                patch(
                    "source.services.screenshots.broadcast_message",
                    new_callable=AsyncMock,
                ) as mock_broadcast,
            ):
                await ScreenshotHandler.on_screenshot_captured("/tmp/unused.png")

            mock_remove.assert_called_once_with("/tmp/unused.png")
            mock_add.assert_not_awaited()
            mock_broadcast.assert_not_awaited()
        finally:
            app_state.capture_mode = saved_capture_mode

    @pytest.mark.asyncio
    async def test_on_screenshot_captured_non_precision_handles_delete_error(self):
        from source.services.screenshots import ScreenshotHandler

        saved_capture_mode = app_state.capture_mode
        app_state.capture_mode = "fullscreen"
        try:
            with (
                patch("source.services.screenshots.os.path.exists", return_value=True),
                patch(
                    "source.services.screenshots.os.remove", side_effect=OSError("fail")
                ),
                patch.object(
                    ScreenshotHandler, "add_screenshot", new=AsyncMock()
                ) as mock_add,
            ):
                await ScreenshotHandler.on_screenshot_captured("/tmp/unused.png")

            mock_add.assert_not_awaited()
        finally:
            app_state.capture_mode = saved_capture_mode

    @pytest.mark.asyncio
    async def test_on_screenshot_captured_precision_adds_and_broadcasts_ready(self):
        from source.config import CaptureMode
        from source.services.screenshots import ScreenshotHandler

        saved_capture_mode = app_state.capture_mode
        app_state.capture_mode = CaptureMode.PRECISION
        try:
            with (
                patch.object(
                    ScreenshotHandler,
                    "add_screenshot",
                    new=AsyncMock(return_value="ss_1"),
                ) as mock_add,
                patch(
                    "source.services.screenshots.broadcast_message",
                    new_callable=AsyncMock,
                ) as mock_broadcast,
            ):
                await ScreenshotHandler.on_screenshot_captured("/tmp/precision.png")

            mock_add.assert_awaited_once_with("/tmp/precision.png")
            mock_broadcast.assert_awaited_once_with(
                "screenshot_ready",
                "Screenshot captured. Enter your query and press Enter.",
            )
        finally:
            app_state.capture_mode = saved_capture_mode
