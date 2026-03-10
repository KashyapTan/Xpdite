"""Tests for source/core/state.py — AppState methods."""

import os
from unittest.mock import patch


class TestAppState:
    """Test AppState in isolation by creating fresh instances."""

    def _make_state(self):
        """Create a fresh AppState for each test."""
        with patch("source.core.state.ScreenshotService"):
            from source.core.state import AppState
            return AppState()

    def test_initial_state(self):
        state = self._make_state()
        assert state.screenshot_list == []
        assert state.screenshot_counter == 0
        assert state.chat_history == []
        assert state.conversation_id is None
        assert state.is_streaming is False
        assert state.stop_streaming is False
        assert state.capture_mode == "fullscreen"
        assert state.active_tab_id == "default"

    def test_add_screenshot(self):
        state = self._make_state()
        ss_data = {"path": "/tmp/test.png", "name": "test.png", "thumbnail": "abc"}
        ss_id = state.add_screenshot(ss_data)
        assert ss_id == "ss_1"
        assert state.screenshot_counter == 1
        assert len(state.screenshot_list) == 1
        assert state.screenshot_list[0]["id"] == "ss_1"
        assert state.screenshot_list[0]["path"] == "/tmp/test.png"

    def test_add_multiple_screenshots(self):
        state = self._make_state()
        id1 = state.add_screenshot({"path": "a.png"})
        id2 = state.add_screenshot({"path": "b.png"})
        assert id1 == "ss_1"
        assert id2 == "ss_2"
        assert state.screenshot_counter == 2
        assert len(state.screenshot_list) == 2

    def test_remove_screenshot_success(self):
        state = self._make_state()
        state.add_screenshot({"path": "a.png"})
        state.add_screenshot({"path": "b.png"})
        removed = state.remove_screenshot("ss_1")
        assert removed is True
        assert len(state.screenshot_list) == 1
        assert state.screenshot_list[0]["id"] == "ss_2"

    def test_remove_screenshot_not_found(self):
        state = self._make_state()
        state.add_screenshot({"path": "a.png"})
        removed = state.remove_screenshot("ss_999")
        assert removed is False
        assert len(state.screenshot_list) == 1

    def test_get_image_paths_existing_files(self, tmp_path):
        state = self._make_state()
        # Create a temp file that exists
        img = tmp_path / "img.png"
        img.write_text("fake image")
        state.add_screenshot({"path": str(img)})
        paths = state.get_image_paths()
        assert len(paths) == 1
        assert os.path.basename(paths[0]) == "img.png"

    def test_get_image_paths_missing_files(self):
        state = self._make_state()
        state.add_screenshot({"path": "/nonexistent/file.png"})
        paths = state.get_image_paths()
        assert paths == []

    def test_reset_conversation(self):
        state = self._make_state()
        state.chat_history = [{"role": "user", "content": "hi"}]
        state.conversation_id = "abc-123"
        state.add_screenshot({"path": "test.png"})
        state.reset_conversation()
        assert state.chat_history == []
        assert state.conversation_id is None
        assert state.screenshot_list == []

    def test_selected_model_has_default(self):
        state = self._make_state()
        assert isinstance(state.selected_model, str)
        assert len(state.selected_model) > 0
