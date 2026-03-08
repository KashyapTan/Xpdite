"""Tests for source/mcp_integration/terminal_executor.py — pure logic functions."""

import platform
from unittest.mock import patch


from source.mcp_integration.terminal_executor import (
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
        assert "find_files" in TERMINAL_TOOLS


class TestHandleFindFiles:
    """Test _handle_find_files synchronous logic."""

    def _call(self, fn_args):
        from source.mcp_integration.terminal_executor import _handle_find_files
        return _handle_find_files(fn_args)

    def test_finds_existing_files(self, tmp_path):
        # Create test files
        (tmp_path / "a.txt").write_text("hello")
        (tmp_path / "b.txt").write_text("world")

        with patch("os.getcwd", return_value=str(tmp_path)):
            result = self._call({"pattern": "*.txt", "directory": str(tmp_path)})
        assert "Found 2 file(s)" in result

    def test_no_matches(self, tmp_path):
        with patch("os.getcwd", return_value=str(tmp_path)):
            result = self._call({"pattern": "*.xyz", "directory": str(tmp_path)})
        assert "No files found" in result

    def test_nonexistent_directory(self):
        result = self._call({"pattern": "*.txt", "directory": "/nonexistent/dir/xyz"})
        assert "Error" in result
        assert "does not exist" in result

    def test_restricts_outside_cwd(self, tmp_path):
        """find_files should reject directories outside the CWD tree."""
        outside = tmp_path / "outside"
        outside.mkdir()
        cwd = tmp_path / "project"
        cwd.mkdir()

        with patch("os.getcwd", return_value=str(cwd)):
            result = self._call({"pattern": "*", "directory": str(outside)})
        assert "restricted" in result.lower() or "Error" in result

    def test_defaults_to_cwd(self, tmp_path):
        (tmp_path / "file.py").write_text("pass")
        with patch("os.getcwd", return_value=str(tmp_path)):
            result = self._call({"pattern": "*.py", "directory": ""})
        assert "Found" in result


class TestHandleGetEnvironment:
    def test_returns_environment_info(self):
        from source.mcp_integration.terminal_executor import _handle_get_environment
        result = _handle_get_environment()
        assert "OS:" in result
        assert "Python:" in result
        assert "Shell:" in result
        assert "CWD:" in result

    def test_contains_current_os(self):
        from source.mcp_integration.terminal_executor import _handle_get_environment
        result = _handle_get_environment()
        assert platform.system() in result
