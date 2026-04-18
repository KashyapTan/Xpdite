from types import SimpleNamespace

import pytest

from mcp_servers.servers.terminal import server as terminal_server


@pytest.fixture(autouse=True)
def reset_tool_version_cache(monkeypatch):
    monkeypatch.setattr(terminal_server, "_TOOL_VERSION_CACHE", {})
    monkeypatch.setattr(terminal_server, "_TOOL_VERSION_CACHE_TIME", 0.0)


def test_get_shell_prefers_comspec_on_windows(monkeypatch):
    monkeypatch.setattr(terminal_server.platform, "system", lambda: "Windows")
    monkeypatch.setitem(terminal_server.os.environ, "COMSPEC", "C:/Windows/System32/cmd.exe")

    assert terminal_server._get_shell() == "C:/Windows/System32/cmd.exe"


def test_check_single_tool_version_returns_none_when_binary_missing(monkeypatch):
    monkeypatch.setattr(terminal_server.shutil, "which", lambda _name: None)

    name, version = terminal_server._check_single_tool_version("python", "python --version")

    assert name == "python"
    assert version is None


def test_check_single_tool_version_returns_first_output_line(monkeypatch):
    monkeypatch.setattr(terminal_server.shutil, "which", lambda _name: "python")
    monkeypatch.setattr(
        terminal_server.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout="Python 3.13.0\nextra line", stderr="", returncode=0
        ),
    )

    name, version = terminal_server._check_single_tool_version("python", "python --version")

    assert (name, version) == ("python", "Python 3.13.0")


def test_get_tool_versions_uses_cache(monkeypatch):
    calls: list[str] = []
    fixed_time = 1_000.0

    monkeypatch.setattr(
        terminal_server,
        "_check_single_tool_version",
        lambda name, _cmd: calls.append(name) or (name, f"{name} 1.0"),
    )
    monkeypatch.setattr(terminal_server.time, "time", lambda: fixed_time)

    first = terminal_server._get_tool_versions()
    second = terminal_server._get_tool_versions()

    assert first == second
    assert len(calls) == 9


def test_get_environment_renders_shells_and_tool_versions(monkeypatch):
    monkeypatch.setattr(
        terminal_server,
        "_get_tool_versions",
        lambda: {"git": "git version 2.0", "python": "Python 3.13.0"},
    )
    monkeypatch.setattr(terminal_server.platform, "system", lambda: "Windows")
    monkeypatch.setattr(terminal_server.platform, "release", lambda: "11")
    monkeypatch.setattr(terminal_server.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(terminal_server.os, "getcwd", lambda: "C:/repo")
    monkeypatch.setattr(terminal_server, "_get_shell", lambda: "pwsh.exe")

    def _resolve_shell(name: str):
        if name in {"cmd", "powershell"}:
            return SimpleNamespace(name=name, display_name=name.upper())
        raise ValueError("missing")

    monkeypatch.setattr(terminal_server, "resolve_shell", _resolve_shell)

    result = terminal_server.get_environment()

    assert "OS: Windows 11 (AMD64)" in result
    assert "Shell: pwsh.exe" in result
    assert "cmd: CMD" in result
    assert "python: Python 3.13.0" in result


def test_run_command_rejects_invalid_working_directory():
    result = terminal_server.run_command("echo hi", cwd="C:/missing")
    assert result == "Error: Working directory does not exist: C:/missing"


def test_run_command_rejects_unknown_shell(monkeypatch):
    monkeypatch.setattr(terminal_server.os.path, "isdir", lambda _path: True)
    monkeypatch.setattr(
        terminal_server,
        "resolve_shell",
        lambda _shell: (_ for _ in ()).throw(ValueError("unknown shell")),
    )

    result = terminal_server.run_command("echo hi", cwd="C:/repo")

    assert result == "Error: unknown shell"


def test_run_command_rejects_background_and_pty_modes(monkeypatch):
    monkeypatch.setattr(terminal_server.os.path, "isdir", lambda _path: True)
    monkeypatch.setattr(
        terminal_server,
        "resolve_shell",
        lambda shell: SimpleNamespace(name=shell, display_name=shell),
    )

    background_result = terminal_server.run_command(
        "echo hi", cwd="C:/repo", background=True
    )
    pty_result = terminal_server.run_command("echo hi", cwd="C:/repo", pty=True)

    assert "inline terminal runtime" in background_result
    assert "inline terminal runtime" in pty_result


def test_run_command_hard_blocks_high_risk_commands(monkeypatch):
    monkeypatch.setattr(terminal_server.os.path, "isdir", lambda _path: True)
    monkeypatch.setattr(
        terminal_server,
        "resolve_shell",
        lambda shell: SimpleNamespace(name=shell, display_name=shell),
    )
    monkeypatch.setattr(
        terminal_server,
        "analyze_command",
        lambda _command, _shell: SimpleNamespace(hard_block_reason="dangerous"),
    )

    result = terminal_server.run_command("rm -rf /", cwd="C:/repo")

    assert result == "BLOCKED: dangerous"


def test_run_command_respects_blocklist(monkeypatch):
    monkeypatch.setattr(terminal_server.os.path, "isdir", lambda _path: True)
    monkeypatch.setattr(
        terminal_server,
        "resolve_shell",
        lambda shell: SimpleNamespace(name=shell, display_name=shell),
    )
    monkeypatch.setattr(
        terminal_server,
        "analyze_command",
        lambda _command, _shell: SimpleNamespace(hard_block_reason=None),
    )
    monkeypatch.setattr(terminal_server, "check_blocklist", lambda _command: (True, "blocked path"))

    result = terminal_server.run_command("type C:/Windows/System32", cwd="C:/repo")

    assert result == "BLOCKED: blocked path"


def test_run_command_returns_output_and_semantic_hint(monkeypatch):
    monkeypatch.setattr(terminal_server.os.path, "isdir", lambda _path: True)
    monkeypatch.setattr(
        terminal_server,
        "resolve_shell",
        lambda shell: SimpleNamespace(name=shell, display_name=shell),
    )
    monkeypatch.setattr(
        terminal_server,
        "analyze_command",
        lambda _command, _shell: SimpleNamespace(hard_block_reason=None),
    )
    monkeypatch.setattr(terminal_server, "check_blocklist", lambda _command: (False, ""))
    monkeypatch.setattr(
        terminal_server,
        "build_subprocess_argv",
        lambda _spec, _command: ["pwsh", "-Command", "git diff --quiet"],
    )
    monkeypatch.setattr(
        terminal_server.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout="", stderr="", returncode=0
        ),
    )
    monkeypatch.setattr(
        terminal_server,
        "interpret_command_result",
        lambda _command, _code, _shell: SimpleNamespace(
            is_error=False, message="No changes made."
        ),
    )

    result = terminal_server.run_command("git diff --quiet", cwd="C:/repo")

    assert result == "No changes made."


def test_run_command_appends_exit_code_for_real_failures(monkeypatch):
    monkeypatch.setattr(terminal_server.os.path, "isdir", lambda _path: True)
    monkeypatch.setattr(
        terminal_server,
        "resolve_shell",
        lambda shell: SimpleNamespace(name=shell, display_name=shell),
    )
    monkeypatch.setattr(
        terminal_server,
        "analyze_command",
        lambda _command, _shell: SimpleNamespace(hard_block_reason=None),
    )
    monkeypatch.setattr(terminal_server, "check_blocklist", lambda _command: (False, ""))
    monkeypatch.setattr(
        terminal_server,
        "build_subprocess_argv",
        lambda _spec, _command: ["pwsh", "-Command", "bad"],
    )
    monkeypatch.setattr(
        terminal_server.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout="",
            stderr="failed",
            returncode=12,
        ),
    )
    monkeypatch.setattr(
        terminal_server,
        "interpret_command_result",
        lambda _command, _code, _shell: SimpleNamespace(is_error=True, message=""),
    )

    result = terminal_server.run_command("bad", cwd="C:/repo")

    assert result == "failed\n[exit code: 12]"


def test_run_command_reports_timeout(monkeypatch):
    monkeypatch.setattr(terminal_server.os.path, "isdir", lambda _path: True)
    monkeypatch.setattr(
        terminal_server,
        "resolve_shell",
        lambda shell: SimpleNamespace(name=shell, display_name=shell),
    )
    monkeypatch.setattr(
        terminal_server,
        "analyze_command",
        lambda _command, _shell: SimpleNamespace(hard_block_reason=None),
    )
    monkeypatch.setattr(terminal_server, "check_blocklist", lambda _command: (False, ""))
    monkeypatch.setattr(
        terminal_server,
        "build_subprocess_argv",
        lambda _spec, _command: ["pwsh", "-Command", "sleep"],
    )

    def _raise_timeout(*args, **kwargs):
        raise terminal_server.subprocess.TimeoutExpired("sleep", kwargs["timeout"])

    monkeypatch.setattr(terminal_server.subprocess, "run", _raise_timeout)

    result = terminal_server.run_command("sleep", cwd="C:/repo", timeout=5)

    assert result == "Error: Command timed out after 5 seconds"


def test_run_command_reports_unexpected_errors(monkeypatch):
    monkeypatch.setattr(terminal_server.os.path, "isdir", lambda _path: True)
    monkeypatch.setattr(
        terminal_server,
        "resolve_shell",
        lambda shell: SimpleNamespace(name=shell, display_name=shell),
    )
    monkeypatch.setattr(
        terminal_server,
        "analyze_command",
        lambda _command, _shell: SimpleNamespace(hard_block_reason=None),
    )
    monkeypatch.setattr(terminal_server, "check_blocklist", lambda _command: (False, ""))
    monkeypatch.setattr(
        terminal_server,
        "build_subprocess_argv",
        lambda _spec, _command: ["pwsh", "-Command", "bad"],
    )
    monkeypatch.setattr(
        terminal_server.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    result = terminal_server.run_command("bad", cwd="C:/repo")

    assert result == "Error executing command: boom"


def test_placeholder_terminal_tools_return_marker_strings():
    assert terminal_server.request_session_mode("Need autonomy") == "session_mode_requested"
    assert terminal_server.end_session_mode() == "session_mode_ended"
    assert terminal_server.send_input("sid", "help") == "send_input_handled"
    assert terminal_server.read_output("sid") == "read_output_handled"
    assert terminal_server.kill_process("sid") == "kill_process_handled"
