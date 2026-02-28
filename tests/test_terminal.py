"""Tests for TerminalService — escapes, ANSI stripping, session state."""

import asyncio

import pytest

from source.services.terminal import TerminalService, _strip_ansi, TerminalSession


class TestDecodeSafeEscapes:
    def test_newline(self):
        assert TerminalService._decode_safe_escapes("hello\\nworld") == "hello\nworld"

    def test_carriage_return(self):
        assert TerminalService._decode_safe_escapes("line\\r") == "line\r"

    def test_tab(self):
        assert TerminalService._decode_safe_escapes("col1\\tcol2") == "col1\tcol2"

    def test_backslash(self):
        assert TerminalService._decode_safe_escapes("foo\\\\bar") == "foo\\bar"

    def test_hex_escape(self):
        # \x03 = ETX (Ctrl-C)
        assert TerminalService._decode_safe_escapes("\\x03") == "\x03"

    def test_hex_escape_esc(self):
        # \x1b = ESC character
        assert TerminalService._decode_safe_escapes("\\x1b") == "\x1b"

    def test_hex_escape_uppercase(self):
        assert TerminalService._decode_safe_escapes("\\x4F") == "\x4f"

    def test_mixed_escapes(self):
        result = TerminalService._decode_safe_escapes("a\\nb\\tc\\\\d\\x41")
        assert result == "a\nb\tc\\d\x41"  # \x41 = 'A'

    def test_no_escapes(self):
        assert TerminalService._decode_safe_escapes("plain text") == "plain text"

    def test_empty_string(self):
        assert TerminalService._decode_safe_escapes("") == ""

    def test_non_whitelisted_escape_passes_through(self):
        """Escapes not in the whitelist should be left as-is."""
        result = TerminalService._decode_safe_escapes("\\a\\b")
        # \a and \b are NOT in the whitelist, so they stay literal
        assert result == "\\a\\b"

    def test_multiple_newlines(self):
        assert TerminalService._decode_safe_escapes("a\\n\\n\\nb") == "a\n\n\nb"


# ------------------------------------------------------------------
# _strip_ansi
# ------------------------------------------------------------------


class TestStripAnsi:
    def test_plain_text(self):
        assert _strip_ansi("hello world") == "hello world"

    def test_color_codes(self):
        assert _strip_ansi("\x1b[31mred\x1b[0m") == "red"

    def test_bold(self):
        assert _strip_ansi("\x1b[1mbold\x1b[0m") == "bold"

    def test_cursor_movement(self):
        assert _strip_ansi("\x1b[2Jhello") == "hello"

    def test_carriage_return(self):
        assert _strip_ansi("line1\rline2") == "line1line2"

    def test_osc_sequence(self):
        # OSC title sequence: ESC ] ... BEL
        assert _strip_ansi("\x1b]0;title\x07actual text") == "actual text"

    def test_empty_string(self):
        assert _strip_ansi("") == ""

    def test_mixed_content(self):
        result = _strip_ansi("\x1b[32mOK\x1b[0m: test passed\r")
        assert result == "OK: test passed"


# ------------------------------------------------------------------
# TerminalSession
# ------------------------------------------------------------------


class TestTerminalSession:
    def test_initial_state(self):
        session = TerminalSession("sid-1", "rid-1", "echo hi", "/tmp")
        assert session.session_id == "sid-1"
        assert session.request_id == "rid-1"
        assert session.command == "echo hi"
        assert session.cwd == "/tmp"
        assert session.is_alive is True
        assert session.exit_code is None
        assert session.process is None

    def test_duration_ms(self):
        import time
        session = TerminalSession("s", "r", "cmd", "/")
        time.sleep(0.05)
        assert session.duration_ms >= 30  # at least ~50ms elapsed, threshold loose for slow CI

    def test_get_recent_output(self):
        session = TerminalSession("s", "r", "cmd", "/")
        session.text_buffer = ["line1\n", "line2\n", "line3\n"]
        result = session.get_recent_output(2)
        lines = result.strip().split("\n")
        assert len(lines) <= 2

    def test_get_recent_output_empty(self):
        session = TerminalSession("s", "r", "cmd", "/")
        assert session.get_recent_output() == ""


# ------------------------------------------------------------------
# TerminalService — state management
# ------------------------------------------------------------------


class TestTerminalServiceState:
    def _make_service(self):
        return TerminalService()

    def test_default_ask_level(self):
        ts = self._make_service()
        assert ts.ask_level == "on-miss"

    def test_set_valid_ask_level(self):
        ts = self._make_service()
        ts.ask_level = "always"
        assert ts.ask_level == "always"
        ts.ask_level = "off"
        assert ts.ask_level == "off"
        ts.ask_level = "on-miss"
        assert ts.ask_level == "on-miss"

    def test_set_invalid_ask_level_ignored(self):
        ts = self._make_service()
        ts.ask_level = "invalid_value"
        assert ts.ask_level == "on-miss"

    def test_session_mode_default_false(self):
        ts = self._make_service()
        assert ts.session_mode is False

    def test_queue_and_flush_pending_events(self):
        from unittest.mock import patch, MagicMock

        ts = self._make_service()
        ts.queue_terminal_event({
            "message_index": 0,
            "command": "echo hello",
            "exit_code": 0,
            "output": "hello",
            "cwd": "/home",
            "duration_ms": 50,
        })
        ts.queue_terminal_event({
            "message_index": 1,
            "command": "ls",
            "exit_code": 0,
            "output": "files",
            "cwd": "/home",
            "duration_ms": 30,
        })
        assert len(ts._pending_events) == 2

        mock_db = MagicMock()
        with patch("source.database.db", mock_db):
            ts.flush_pending_events("conv-123")
        assert mock_db.save_terminal_event.call_count == 2
        assert ts._pending_events == []

    def test_reset_clears_state(self):
        ts = self._make_service()
        ts._session_mode = True
        ts._running_commands["r1"] = {"command": "test"}
        ts._pending_events.append({"data": "x"})
        ts.reset()
        assert ts._session_mode is False
        assert ts._running_commands == {}
        assert ts._pending_events == []

    def test_resolve_approval(self):
        ts = self._make_service()
        event = asyncio.Event()
        ts._approval_events["req-1"] = event
        ts._approval_results["req-1"] = False
        ts._approval_remember["req-1"] = False

        ts.resolve_approval("req-1", True, remember=True)
        assert ts._approval_results["req-1"] is True
        assert ts._approval_remember["req-1"] is True
        assert event.is_set()

    def test_resolve_approval_unknown_request(self):
        ts = self._make_service()
        ts.resolve_approval("nonexistent", True)  # should not raise

    def test_resolve_session(self):
        ts = self._make_service()
        event = asyncio.Event()
        ts._session_event = event
        ts.resolve_session(True)
        assert ts._session_result is True
        assert event.is_set()

    def test_track_running_command(self):
        ts = self._make_service()
        ts.track_running_command("req-1", "npm install")
        assert "req-1" in ts._running_commands
        assert ts._running_commands["req-1"]["command"] == "npm install"
        ts.stop_tracking_command("req-1")
        assert "req-1" not in ts._running_commands

    def test_cleanup_approval(self):
        ts = self._make_service()
        ts._approval_events["r"] = asyncio.Event()
        ts._approval_results["r"] = True
        ts._approval_remember["r"] = True
        ts._cleanup_approval("r")
        assert "r" not in ts._approval_events
        assert "r" not in ts._approval_results
        assert "r" not in ts._approval_remember


# ------------------------------------------------------------------
# cancel_all_pending
# ------------------------------------------------------------------


class TestCancelAllPending:
    def _make_service(self):
        return TerminalService()

    def test_denies_all_pending_approvals(self):
        ts = self._make_service()
        ev1, ev2 = asyncio.Event(), asyncio.Event()
        ts._approval_events["a"] = ev1
        ts._approval_events["b"] = ev2
        ts._approval_results["a"] = True
        ts._approval_results["b"] = True

        ts.cancel_all_pending()

        assert ts._approval_results["a"] is False
        assert ts._approval_results["b"] is False
        assert ev1.is_set()
        assert ev2.is_set()

    def test_cancels_pending_session(self):
        ts = self._make_service()
        ev = asyncio.Event()
        ts._session_event = ev
        ts._session_result = None

        ts.cancel_all_pending()

        assert ts._session_result is False
        assert ev.is_set()

    def test_no_session_event_no_error(self):
        ts = self._make_service()
        ts._session_event = None
        ts.cancel_all_pending()  # should not raise

    def test_clears_background_sessions(self):
        ts = self._make_service()
        # Add a fake session with minimal attributes
        from unittest.mock import MagicMock
        fake_session = MagicMock()
        fake_session.reader_task = None
        fake_session.process = None
        fake_session.is_alive = False
        ts._background_sessions["s1"] = fake_session
        ts.cancel_all_pending()
        assert ts._background_sessions == {}


# ------------------------------------------------------------------
# check_approval — async
# ------------------------------------------------------------------


class TestCheckApproval:
    def _make_service(self):
        return TerminalService()

    @pytest.mark.asyncio
    async def test_session_mode_auto_approves(self):
        ts = self._make_service()
        ts._session_mode = True
        approved, request_id = await ts.check_approval("rm -rf /tmp/test", "/tmp")
        assert approved is True
        assert isinstance(request_id, str)

    @pytest.mark.asyncio
    async def test_ask_off_auto_approves(self):
        ts = self._make_service()
        ts._ask_level = "off"
        approved, request_id = await ts.check_approval("echo hi", "/home")
        assert approved is True

    @pytest.mark.asyncio
    async def test_on_miss_already_approved(self):
        from unittest.mock import patch
        ts = self._make_service()
        ts._ask_level = "on-miss"
        with patch("source.services.terminal.is_command_approved", return_value=True):
            approved, _ = await ts.check_approval("echo hello", "/home")
        assert approved is True

    @pytest.mark.asyncio
    async def test_on_miss_not_approved_prompts_user_and_times_out(self):
        """When history has no match, broadcasts approval request and times out."""
        from unittest.mock import patch, AsyncMock
        ts = self._make_service()
        ts._ask_level = "on-miss"
        with (
            patch("source.services.terminal.is_command_approved", return_value=False),
            patch("source.services.terminal.broadcast_message", new_callable=AsyncMock) as mock_bcast,
            patch("asyncio.wait_for", side_effect=asyncio.TimeoutError),
        ):
            approved, request_id = await ts.check_approval("dangerous cmd", "/tmp")

        assert approved is False
        mock_bcast.assert_called_once()
        # Verify the correct message type and payload were broadcast
        assert mock_bcast.call_args[0][0] == "terminal_approval_request"
        payload = mock_bcast.call_args[0][1]
        assert payload["command"] == "dangerous cmd"
        assert payload["cwd"] == "/tmp"
        assert isinstance(payload["request_id"], str)

    @pytest.mark.asyncio
    async def test_always_prompts_user(self):
        """ask_level='always' always asks, even for known-good commands."""
        from unittest.mock import patch, AsyncMock
        ts = self._make_service()
        ts._ask_level = "always"
        with (
            patch("source.services.terminal.broadcast_message", new_callable=AsyncMock) as mock_bcast,
            patch("asyncio.wait_for", side_effect=asyncio.TimeoutError),
        ):
            approved, _ = await ts.check_approval("echo hi", "/")

        assert approved is False
        mock_bcast.assert_called_once()
        assert mock_bcast.call_args[0][0] == "terminal_approval_request"
        payload = mock_bcast.call_args[0][1]
        assert payload["command"] == "echo hi"
        assert payload["cwd"] == "/"
        assert isinstance(payload["request_id"], str)