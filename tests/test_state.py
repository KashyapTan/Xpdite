"""Tests for source/core/state.py — AppState fields and helpers."""


class TestAppState:
    """Test AppState in isolation by creating fresh instances."""

    def _make_state(self):
        """Create a fresh AppState for each test."""
        from source.core.state import AppState

        return AppState()

    def test_initial_state(self):
        state = self._make_state()
        assert state.screenshot_counter == 0
        assert state.chat_history == []
        assert state.conversation_id is None
        assert state.is_streaming is False
        assert state.stop_streaming is False
        assert state.capture_mode == "fullscreen"
        assert state.active_tab_id == "default"

    def test_reset_conversation(self):
        state = self._make_state()
        state.chat_history = [{"role": "user", "content": "hi"}]
        state.conversation_id = "abc-123"
        state.reset_conversation()
        assert state.chat_history == []
        assert state.conversation_id is None

    def test_selected_model_has_default(self):
        state = self._make_state()
        assert isinstance(state.selected_model, str)
        assert len(state.selected_model) > 0
