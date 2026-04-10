"""Tests for source/mcp_integration/executors/terminal_executor.py — pure logic functions."""

from unittest.mock import AsyncMock
import platform
from unittest.mock import patch

import pytest


from source.mcp_integration.executors.terminal_executor import (
    is_terminal_tool,
    TERMINAL_TOOLS,
)


class TestIsTerminalTool:
    def test_known_tools_on_terminal_server(self):
        for tool in TERMINAL_TOOLS:
            assert is_terminal_tool(tool, "terminal") is True

    def test_unknown_tool_on_terminal_server(self):
        assert is_terminal_tool("unknown_tool", "terminal") is False

    def test_known_tool_on_wrong_server(self):
        assert is_terminal_tool("run_command", "filesystem") is False

    def test_empty_strings(self):
        assert is_terminal_tool("", "") is False
        assert is_terminal_tool("", "terminal") is False


class TestTerminalToolSet:
    def test_run_command_present(self):
        assert "run_command" in TERMINAL_TOOLS

    def test_session_tools_present(self):
        assert "request_session_mode" in TERMINAL_TOOLS
        assert "end_session_mode" in TERMINAL_TOOLS

    def test_pty_tools_present(self):
        assert "send_input" in TERMINAL_TOOLS
        assert "read_output" in TERMINAL_TOOLS
        assert "kill_process" in TERMINAL_TOOLS

    def test_info_tools_present(self):
        assert "get_environment" in TERMINAL_TOOLS


class TestHandleGetEnvironment:
    def test_returns_environment_info(self):
        from source.mcp_integration.executors.terminal_executor import (
            _handle_get_environment,
        )

        result = _handle_get_environment()
        assert "OS:" in result
        assert "Python:" in result
        assert "Shell:" in result
        assert "CWD:" in result

    def test_contains_current_os(self):
        from source.mcp_integration.executors.terminal_executor import (
            _handle_get_environment,
        )

        result = _handle_get_environment()
        assert platform.system() in result


class TestExecuteTerminalTool:
    @pytest.mark.asyncio
    async def test_unknown_terminal_tool_returns_error(self):
        from source.mcp_integration import terminal_executor as terminal_executor

        result = await terminal_executor.execute_terminal_tool(
            "unsupported_tool", {}, "terminal"
        )

        assert result == "Unknown terminal tool: unsupported_tool"

    @pytest.mark.asyncio
    async def test_request_session_mode_and_end_session_mode(self):
        from source.mcp_integration import terminal_executor as terminal_executor

        with (
            patch.object(
                terminal_executor.terminal_service,
                "request_session",
                new=AsyncMock(side_effect=[True, False]),
            ) as mock_request,
            patch.object(
                terminal_executor.terminal_service,
                "end_session",
                new=AsyncMock(),
            ) as mock_end,
        ):
            approved = await terminal_executor.execute_terminal_tool(
                "request_session_mode", {"reason": "Need autonomy"}, "terminal"
            )
            denied = await terminal_executor.execute_terminal_tool(
                "request_session_mode", {"reason": "Need autonomy"}, "terminal"
            )
            ended = await terminal_executor.execute_terminal_tool(
                "end_session_mode", {}, "terminal"
            )

        assert approved == "session started"
        assert denied == "session request denied"
        assert ended == "session ended"
        mock_request.assert_any_await("Need autonomy")
        mock_end.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_session_helpers_require_session_id(self):
        from source.mcp_integration import terminal_executor as terminal_executor

        send_result = await terminal_executor.execute_terminal_tool(
            "send_input", {}, "terminal"
        )
        read_result = await terminal_executor.execute_terminal_tool(
            "read_output", {}, "terminal"
        )
        kill_result = await terminal_executor.execute_terminal_tool(
            "kill_process", {}, "terminal"
        )

        assert send_result == "Error: session_id is required"
        assert read_result == "Error: session_id is required"
        assert kill_result == "Error: session_id is required"

    @pytest.mark.asyncio
    async def test_run_command_denied_saves_denied_event(self):
        from source.mcp_integration import terminal_executor as terminal_executor

        with (
            patch.object(
                terminal_executor.terminal_service,
                "check_approval",
                new=AsyncMock(return_value=(False, "req-denied")),
            ),
            patch.object(terminal_executor, "_save_terminal_event") as mock_save,
        ):
            result = await terminal_executor.execute_terminal_tool(
                "run_command",
                {"command": "rm -rf /tmp/demo", "cwd": "C:/repo"},
                "terminal",
            )

        assert result == "Command denied by user"
        mock_save.assert_called_once()
        kwargs = mock_save.call_args.kwargs
        assert kwargs["command"] == "rm -rf /tmp/demo"
        assert kwargs["denied"] is True
        assert kwargs["exit_code"] == -1

    @pytest.mark.asyncio
    async def test_run_command_non_pty_executes_and_broadcasts_completion(self):
        from source.mcp_integration import terminal_executor as terminal_executor

        with (
            patch.object(
                terminal_executor.terminal_service,
                "check_approval",
                new=AsyncMock(return_value=(True, "req-1")),
            ),
            patch.object(terminal_executor.terminal_service, "track_running_command"),
            patch.object(terminal_executor.terminal_service, "stop_tracking_command"),
            patch.object(
                terminal_executor.terminal_service,
                "execute_command",
                new=AsyncMock(return_value=("ok output", 0, 25, False)),
            ) as mock_execute,
            patch.object(
                terminal_executor.terminal_service,
                "broadcast_complete",
                new=AsyncMock(),
            ) as mock_complete,
            patch.object(
                terminal_executor.terminal_service,
                "check_running_notices",
                new=AsyncMock(),
            ),
            patch.object(terminal_executor, "_save_terminal_event") as mock_save,
        ):
            result = await terminal_executor.execute_terminal_tool(
                "run_command",
                {"command": "echo hi", "cwd": "C:/repo", "timeout": 30},
                "terminal",
            )

        assert result == "ok output"
        mock_execute.assert_awaited_once_with(
            command="echo hi",
            cwd="C:/repo",
            timeout=30,
            request_id="req-1",
            shell="cmd",
        )
        mock_complete.assert_awaited_once_with("req-1", 0, 25)
        assert mock_save.call_args.kwargs["pty"] is False

    @pytest.mark.asyncio
    async def test_run_command_pty_background_skips_completion_broadcast(self):
        from source.mcp_integration import terminal_executor as terminal_executor

        with (
            patch.object(
                terminal_executor.terminal_service,
                "check_approval",
                new=AsyncMock(return_value=(True, "req-pty")),
            ),
            patch.object(terminal_executor.terminal_service, "track_running_command"),
            patch.object(terminal_executor.terminal_service, "stop_tracking_command"),
            patch.object(
                terminal_executor.terminal_service,
                "execute_command_pty",
                new=AsyncMock(return_value=("pty output", 0, 40, False, "session-1")),
            ) as mock_execute,
            patch.object(
                terminal_executor.terminal_service,
                "broadcast_complete",
                new=AsyncMock(),
            ) as mock_complete,
            patch.object(
                terminal_executor.terminal_service,
                "check_running_notices",
                new=AsyncMock(),
            ),
            patch.object(terminal_executor, "_save_terminal_event") as mock_save,
        ):
            result = await terminal_executor.execute_terminal_tool(
                "run_command",
                {
                    "command": "python long_task.py",
                    "cwd": "C:/repo",
                    "pty": True,
                    "background": True,
                    "yield_ms": 2500,
                },
                "terminal",
            )

        assert result == "pty output"
        mock_execute.assert_awaited_once_with(
            command="python long_task.py",
            cwd="C:/repo",
            timeout=120,
            request_id="req-pty",
            background=True,
            yield_ms=2500,
            shell="cmd",
        )
        mock_complete.assert_not_awaited()
        assert mock_save.call_args.kwargs["pty"] is True
        assert mock_save.call_args.kwargs["background"] is True

    @pytest.mark.asyncio
    async def test_get_environment_uses_run_in_thread(self):
        from source.mcp_integration import terminal_executor as terminal_executor

        with patch.object(
            terminal_executor,
            "run_in_thread",
            new=AsyncMock(return_value="ENV"),
        ) as mock_run:
            env_result = await terminal_executor.execute_terminal_tool(
                "get_environment", {}, "terminal"
            )

        assert env_result == "ENV"
        mock_run.assert_awaited_once()
