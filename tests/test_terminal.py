"""Tests for TerminalService — escapes, ANSI stripping, session state."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from source.services.terminal import TerminalService, TerminalSession, _strip_ansi


class _FakeStdout:
    def __init__(self, lines: list[bytes]):
        self._lines = list(lines)

    async def readline(self) -> bytes:
        if self._lines:
            return self._lines.pop(0)
        return b""


class _TimeoutStdout:
    async def readline(self) -> bytes:
        raise asyncio.TimeoutError


class _FakeProcess:
    def __init__(
        self,
        stdout: _FakeStdout | _TimeoutStdout,
        *,
        pid: int = 1234,
        wait_result: int = 0,
    ):
        self.stdout = stdout
        self.pid = pid
        self._wait_result = wait_result

    async def wait(self) -> int:
        return self._wait_result


async def _run_in_thread_now(func, *args, **kwargs):
    return func(*args, **kwargs)


async def _wait_for_timeout(awaitable, timeout):
    close = getattr(awaitable, "close", None)
    if callable(close):
        close()
    raise asyncio.TimeoutError


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
        with patch("source.services.terminal.time.time") as mock_time:
            mock_time.return_value = 100.0
            session = TerminalSession("s", "r", "cmd", "/")
            mock_time.return_value = 100.125
            assert session.duration_ms == 125

    def test_get_recent_output(self):
        session = TerminalSession("s", "r", "cmd", "/")
        session.text_buffer = ["line1\n", "line2\n", "line3"]
        result = session.get_recent_output(2)
        assert result == "line2\nline3"

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
        ts.queue_terminal_event(
            {
                "message_index": 0,
                "command": "echo hello",
                "exit_code": 0,
                "output": "hello",
                "cwd": "/home",
                "duration_ms": 50,
            }
        )
        ts.queue_terminal_event(
            {
                "message_index": 1,
                "command": "ls",
                "exit_code": 0,
                "output": "files",
                "cwd": "/home",
                "duration_ms": 30,
            }
        )
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
            patch(
                "source.services.terminal.broadcast_message", new_callable=AsyncMock
            ) as mock_bcast,
            patch(
                "source.services.terminal.asyncio.wait_for",
                side_effect=_wait_for_timeout,
            ),
        ):
            approved, request_id = await ts.check_approval("dangerous cmd", "/tmp")

        assert approved is False
        mock_bcast.assert_awaited_once()
        # Verify the correct message type and payload were broadcast
        assert mock_bcast.await_args_list[0].args[0] == "terminal_approval_request"
        payload = mock_bcast.await_args_list[0].args[1]
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
            patch(
                "source.services.terminal.broadcast_message", new_callable=AsyncMock
            ) as mock_bcast,
            patch(
                "source.services.terminal.asyncio.wait_for",
                side_effect=_wait_for_timeout,
            ),
        ):
            approved, _ = await ts.check_approval("echo hi", "/")

        assert approved is False
        mock_bcast.assert_awaited_once()
        assert mock_bcast.await_args_list[0].args[0] == "terminal_approval_request"
        payload = mock_bcast.await_args_list[0].args[1]
        assert payload["command"] == "echo hi"
        assert payload["cwd"] == "/"
        assert isinstance(payload["request_id"], str)

    @pytest.mark.asyncio
    async def test_on_miss_user_approves_and_remembers_command(self):
        ts = self._make_service()
        ts._ask_level = "on-miss"

        async def _fake_broadcast(message_type: str, payload: dict):
            if message_type == "terminal_approval_request":
                ts.resolve_approval(payload["request_id"], True, remember=True)

        with (
            patch("source.services.terminal.is_command_approved", return_value=False),
            patch(
                "source.services.terminal.broadcast_message", new_callable=AsyncMock
            ) as mock_bcast,
            patch("source.services.terminal.remember_approval") as mock_remember,
        ):
            mock_bcast.side_effect = _fake_broadcast
            approved, request_id = await ts.check_approval("echo hello", "/tmp")

        assert approved is True
        mock_remember.assert_called_once_with("echo hello")
        assert request_id not in ts._approval_events
        assert request_id not in ts._approval_results
        assert request_id not in ts._approval_remember


class TestSessionMode:
    @pytest.mark.asyncio
    async def test_request_session_approved_starts_session_mode(self):
        ts = TerminalService()

        async def _fake_broadcast(message_type: str, payload):
            if message_type == "terminal_session_request":
                ts.resolve_session(True)

        with patch(
            "source.services.terminal.broadcast_message", new_callable=AsyncMock
        ) as mock_bcast:
            mock_bcast.side_effect = _fake_broadcast
            approved = await ts.request_session("Need autonomous terminal control")

        assert approved is True
        assert ts.session_mode is True
        assert mock_bcast.await_count == 2
        assert mock_bcast.await_args_list[0].args[0] == "terminal_session_request"
        assert mock_bcast.await_args_list[1].args[0] == "terminal_session_started"

    @pytest.mark.asyncio
    async def test_request_session_timeout_returns_false(self):
        ts = TerminalService()

        with (
            patch("source.services.terminal.broadcast_message", new_callable=AsyncMock),
            patch(
                "source.services.terminal.asyncio.wait_for",
                side_effect=_wait_for_timeout,
            ),
        ):
            approved = await ts.request_session("Need session")

        assert approved is False
        assert ts.session_mode is False
        assert ts._session_event is None

    @pytest.mark.asyncio
    async def test_end_session_turns_off_session_mode(self):
        ts = TerminalService()
        ts._session_mode = True

        with patch(
            "source.services.terminal.broadcast_message", new_callable=AsyncMock
        ) as mock_bcast:
            await ts.end_session()

        assert ts.session_mode is False
        mock_bcast.assert_awaited_once_with("terminal_session_ended", "")


class TestRunningNotices:
    @pytest.mark.asyncio
    async def test_check_running_notices_broadcasts_only_once_after_threshold(self):
        ts = TerminalService()
        ts._running_commands["req-1"] = {
            "command": "npm run build",
            "start_time": 100.0,
            "notified": False,
        }

        with (
            patch("source.services.terminal.time.time", return_value=111.2),
            patch(
                "source.services.terminal.broadcast_message", new_callable=AsyncMock
            ) as mock_bcast,
        ):
            await ts.check_running_notices()
            await ts.check_running_notices()

        assert ts._running_commands["req-1"]["notified"] is True
        mock_bcast.assert_awaited_once()
        assert mock_bcast.await_args_list[0].args[0] == "terminal_running_notice"


class TestExecuteCommand:
    @pytest.mark.asyncio
    async def test_invalid_working_directory_short_circuits(self):
        ts = TerminalService()

        with patch("source.services.terminal.os.path.isdir", return_value=False):
            output, exit_code, duration_ms, timed_out = await ts.execute_command(
                "echo hi", "C:/missing/path"
            )

        assert "Working directory does not exist" in output
        assert exit_code == 1
        assert duration_ms == 0
        assert timed_out is False

    @pytest.mark.asyncio
    async def test_blocklisted_command_short_circuits_before_subprocess(self):
        ts = TerminalService()

        with (
            patch("source.services.terminal.os.path.isdir", return_value=True),
            patch(
                "source.services.terminal.check_blocklist",
                return_value=(True, "dangerous"),
            ),
            patch(
                "source.services.terminal.asyncio.create_subprocess_shell",
                new_callable=AsyncMock,
            ) as mock_create,
        ):
            output, exit_code, duration_ms, timed_out = await ts.execute_command(
                "rm -rf /", "C:/safe"
            )

        assert output == "BLOCKED: dangerous"
        assert exit_code == 1
        assert duration_ms == 0
        assert timed_out is False
        mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_streams_output_and_appends_exit_code_for_nonzero_result(self):
        ts = TerminalService()
        ts.broadcast_output = AsyncMock()

        fake_process = _FakeProcess(
            _FakeStdout([b"line one\n", b"line two\r\n", b""]),
            wait_result=2,
            pid=222,
        )

        with (
            patch("source.services.terminal.os.path.isdir", return_value=True),
            patch("source.services.terminal.check_blocklist", return_value=(False, "")),
            patch(
                "source.services.terminal.asyncio.create_subprocess_shell",
                new_callable=AsyncMock,
                return_value=fake_process,
            ),
        ):
            output, exit_code, duration_ms, timed_out = await ts.execute_command(
                "python script.py", "C:/repo", request_id="req-abc"
            )

        assert "line one" in output
        assert "line two" in output
        assert output.endswith("[exit code: 2]")
        assert exit_code == 2
        assert duration_ms >= 0
        assert timed_out is False
        assert ts._active_process is None
        assert ts._active_request_id is None
        ts.broadcast_output.assert_any_await("req-abc", "line one", stream=True)
        ts.broadcast_output.assert_any_await("req-abc", "line two", stream=True)

    @pytest.mark.asyncio
    async def test_successful_exit_zero_does_not_append_exit_code_suffix(self):
        ts = TerminalService()
        ts.broadcast_output = AsyncMock()

        fake_process = _FakeProcess(
            _FakeStdout([b"ok\n", b""]),
            wait_result=0,
            pid=223,
        )

        with (
            patch("source.services.terminal.os.path.isdir", return_value=True),
            patch("source.services.terminal.check_blocklist", return_value=(False, "")),
            patch(
                "source.services.terminal.asyncio.create_subprocess_shell",
                new_callable=AsyncMock,
                return_value=fake_process,
            ),
        ):
            output, exit_code, _, timed_out = await ts.execute_command(
                "echo ok", "C:/repo", request_id="req-zero"
            )

        assert output == "ok"
        assert exit_code == 0
        assert timed_out is False
        assert "[exit code:" not in output
        ts.broadcast_output.assert_any_await("req-zero", "ok", stream=True)

    @pytest.mark.asyncio
    async def test_read_timeout_kills_process_and_marks_timed_out(self):
        ts = TerminalService()
        ts.broadcast_output = AsyncMock()

        fake_process = _FakeProcess(_TimeoutStdout(), wait_result=0, pid=444)

        with (
            patch("source.services.terminal.os.path.isdir", return_value=True),
            patch("source.services.terminal.check_blocklist", return_value=(False, "")),
            patch(
                "source.services.terminal.asyncio.create_subprocess_shell",
                new_callable=AsyncMock,
                return_value=fake_process,
            ),
            patch("source.services.terminal._kill_process_tree") as mock_kill,
        ):
            output, exit_code, _, timed_out = await ts.execute_command(
                "sleep 999", "C:/repo", timeout=1, request_id="req-timeout"
            )

        assert timed_out is True
        assert isinstance(exit_code, int)
        assert "Command timed out after 1 seconds" in output
        mock_kill.assert_called_once_with(444)
        ts.broadcast_output.assert_any_await(
            "req-timeout",
            "\x1b[31mCommand timed out after 1 seconds\x1b[0m",
            stream=True,
        )

    @pytest.mark.asyncio
    async def test_subprocess_launch_exception_returns_error_output(self):
        ts = TerminalService()

        with (
            patch("source.services.terminal.os.path.isdir", return_value=True),
            patch("source.services.terminal.check_blocklist", return_value=(False, "")),
            patch(
                "source.services.terminal.asyncio.create_subprocess_shell",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
            ),
        ):
            output, exit_code, _, timed_out = await ts.execute_command(
                "run something", "C:/repo"
            )

        assert output.startswith("Error executing command:")
        assert exit_code == 1
        assert timed_out is False


class TestKillRunningCommand:
    @pytest.mark.asyncio
    async def test_kills_standard_process_and_background_sessions(self):
        ts = TerminalService()
        ts._active_process = MagicMock(pid=77)
        ts._active_request_id = "req-kill"
        session = TerminalSession("sid-1", "rid-1", "cmd", "C:/")
        ts._background_sessions["sid-1"] = session
        ts.broadcast_output = AsyncMock()
        ts._kill_session = AsyncMock()

        with patch("source.services.terminal._kill_process_tree") as mock_kill:
            killed = await ts.kill_running_command()

        assert killed is True
        mock_kill.assert_called_once_with(77)
        ts.broadcast_output.assert_awaited_once_with(
            "req-kill",
            "\x1b[31m[Process killed by user]\x1b[0m",
            stream=True,
        )
        ts._kill_session.assert_awaited_once_with("sid-1", "[Process killed by user]")

    @pytest.mark.asyncio
    async def test_returns_false_when_nothing_is_running(self):
        ts = TerminalService()

        killed = await ts.kill_running_command()

        assert killed is False


class TestSessionInteraction:
    @pytest.mark.asyncio
    async def test_send_input_missing_session(self):
        ts = TerminalService()

        result = await ts.send_input("missing", "help")

        assert "No active session" in result

    @pytest.mark.asyncio
    async def test_send_input_rejects_exited_session(self):
        ts = TerminalService()
        session = TerminalSession("sid", "rid", "cmd", "C:/")
        session._alive = False
        ts._background_sessions["sid"] = session

        result = await ts.send_input("sid", "help")

        assert "already exited" in result

    @pytest.mark.asyncio
    async def test_send_input_rejects_session_without_process(self):
        ts = TerminalService()
        session = TerminalSession("sid", "rid", "cmd", "C:/")
        session.process = None
        ts._background_sessions["sid"] = session

        result = await ts.send_input("sid", "help")

        assert "no active process" in result

    @pytest.mark.asyncio
    async def test_send_input_writes_decoded_text_and_appends_enter(self):
        ts = TerminalService()
        session = TerminalSession("sid", "rid", "cmd", "C:/")
        session.process = MagicMock()
        session.text_buffer = ["line one\nline two\n"]
        ts._background_sessions["sid"] = session

        with (
            patch(
                "source.services.terminal.asyncio.to_thread",
                side_effect=_run_in_thread_now,
            ),
            patch(
                "source.services.terminal.asyncio.sleep", new_callable=AsyncMock
            ) as mock_sleep,
        ):
            result = await ts.send_input("sid", "status", press_enter=True, wait_ms=250)

        session.process.write.assert_called_once_with("status\r")
        mock_sleep.assert_awaited_once_with(0.25)
        assert "Input sent. Session is running." in result

    @pytest.mark.asyncio
    async def test_send_input_without_enter_does_not_append_carriage_return(self):
        ts = TerminalService()
        session = TerminalSession("sid", "rid", "cmd", "C:/")
        session.process = MagicMock()
        ts._background_sessions["sid"] = session

        with patch(
            "source.services.terminal.asyncio.to_thread", side_effect=_run_in_thread_now
        ):
            result = await ts.send_input("sid", "status", press_enter=False, wait_ms=0)

        session.process.write.assert_called_once_with("status")
        assert "Input sent. Session is running." in result

    @pytest.mark.asyncio
    async def test_read_output_running_session(self):
        ts = TerminalService()
        session = TerminalSession("sid", "rid", "cmd", "C:/")
        session.text_buffer = ["first\n", "second"]
        ts._background_sessions["sid"] = session

        result = await ts.read_output("sid", lines=1)

        assert "RUNNING" in result
        assert "second" in result
        assert "sid" in ts._background_sessions

    @pytest.mark.asyncio
    async def test_read_output_exited_session_cleans_up_registry(self):
        ts = TerminalService()
        session = TerminalSession("sid", "rid", "cmd", "C:/")
        session.text_buffer = ["final output\n"]
        session._alive = False
        session.exit_code = 9
        ts._background_sessions["sid"] = session

        result = await ts.read_output("sid")

        assert "EXITED (exit code 9)" in result
        assert "Do NOT call read_output or kill_process again" in result
        assert "sid" not in ts._background_sessions

    @pytest.mark.asyncio
    async def test_kill_process_requires_existing_session(self):
        ts = TerminalService()

        result = await ts.kill_process("missing")

        assert "No active session" in result

    @pytest.mark.asyncio
    async def test_kill_process_delegates_to_internal_killer(self):
        ts = TerminalService()
        ts._background_sessions["sid"] = TerminalSession("sid", "rid", "cmd", "C:/")
        ts._kill_session = AsyncMock()

        result = await ts.kill_process("sid")

        ts._kill_session.assert_awaited_once_with(
            "sid", "Process killed by LLM request"
        )
        assert result == "Session sid terminated"


class TestPtyResizeAndCleanup:
    @pytest.mark.asyncio
    async def test_resize_pty_updates_single_alive_session(self):
        ts = TerminalService()
        session = TerminalSession("sid", "rid", "cmd", "C:/")
        session.process = MagicMock()
        ts._background_sessions["sid"] = session

        with patch(
            "source.services.terminal.asyncio.to_thread", side_effect=_run_in_thread_now
        ):
            await ts.resize_pty("sid", cols=90, rows=40)

        session.process.setwinsize.assert_called_once_with(40, 90)

    @pytest.mark.asyncio
    async def test_resize_all_pty_updates_only_alive_sessions(self):
        ts = TerminalService()
        alive = TerminalSession("sid-alive", "rid-1", "cmd", "C:/")
        alive.process = MagicMock()
        dead = TerminalSession("sid-dead", "rid-2", "cmd", "C:/")
        dead.process = MagicMock()
        dead._alive = False
        ts._background_sessions["sid-alive"] = alive
        ts._background_sessions["sid-dead"] = dead

        with patch(
            "source.services.terminal.asyncio.to_thread", side_effect=_run_in_thread_now
        ):
            await ts.resize_all_pty(cols=120, rows=50)

        assert ts._last_pty_size == (120, 50)
        alive.process.setwinsize.assert_called_once_with(50, 120)
        dead.process.setwinsize.assert_not_called()

    @pytest.mark.asyncio
    async def test_kill_session_broadcasts_and_cleans_state(self):
        ts = TerminalService()
        session = TerminalSession("sid", "rid", "cmd", "C:/")
        session.process = MagicMock()
        session.reader_task = MagicMock()
        session.reader_task.done.return_value = False
        ts._background_sessions["sid"] = session
        ts.broadcast_output = AsyncMock()
        ts.broadcast_complete = AsyncMock()

        with patch(
            "source.services.terminal.asyncio.to_thread", side_effect=_run_in_thread_now
        ):
            await ts._kill_session("sid", "Manually stopped")

        session.reader_task.cancel.assert_called_once()
        session.process.terminate.assert_called_once()
        assert session.exit_code == -1
        assert session.is_alive is False
        ts.broadcast_output.assert_awaited_once_with(
            "rid",
            "\x1b[31m[Manually stopped]\x1b[0m",
            stream=True,
            raw=True,
        )
        ts.broadcast_complete.assert_awaited_once()
        assert "sid" not in ts._background_sessions


class TestCancelAllPendingAdvanced:
    def test_cancels_active_process_and_background_sessions(self):
        ts = TerminalService()
        approval_event = asyncio.Event()
        session_event = asyncio.Event()

        ts._approval_events["req-1"] = approval_event
        ts._approval_results["req-1"] = True
        ts._session_event = session_event
        ts._active_process = MagicMock(pid=999)

        session = TerminalSession("sid", "rid", "cmd", "C:/")
        session.reader_task = MagicMock()
        session.reader_task.done.return_value = False
        session.process = MagicMock()
        ts._background_sessions["sid"] = session

        with patch("source.services.terminal._kill_process_tree") as mock_kill:
            ts.cancel_all_pending()

        assert approval_event.is_set()
        assert ts._approval_results["req-1"] is False
        assert session_event.is_set()
        assert ts._session_result is False
        mock_kill.assert_called_once_with(999)
        session.reader_task.cancel.assert_called_once()
        session.process.terminate.assert_called_once()
        assert session._alive is False
        assert ts._background_sessions == {}
