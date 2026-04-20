"""
Unified terminal tool execution.

Single source of truth for executing terminal tools (run_command,
request_session_mode, end_session_mode, send_input, read_output,
kill_process) with approval, PTY, streaming, and DB persistence.

Both handlers.py (Ollama) and cloud_tool_handlers.py (Anthropic/OpenAI/Gemini)
import from here to avoid duplicating the approval + execution + notice + DB
save logic.
"""

import asyncio
import logging
import os
import shlex
import shutil

from ...core.state import app_state
from ...core.thread_pool import run_in_thread
from ...services.shell.command_analysis import analyze_command, resolve_shell
from ...services.shell.terminal import terminal_service


logger = logging.getLogger(__name__)


# Tool names that must be intercepted (never reach the MCP subprocess)
TERMINAL_TOOLS = {
    "run_command",
    "request_session_mode",
    "end_session_mode",
    "send_input",
    "read_output",
    "kill_process",
    "get_environment",
}


def _looks_like_windows_drive_path(path: str) -> bool:
    normalized = path.strip().replace("\\", "/")
    return len(normalized) >= 3 and normalized[1] == ":" and normalized[2] == "/"


def is_terminal_tool(fn_name: str, server_name: str) -> bool:
    """Check if a tool call should be handled inline as a terminal tool."""
    return server_name == "terminal" and fn_name in TERMINAL_TOOLS


async def execute_terminal_tool(
    fn_name: str,
    fn_args: dict,
    server_name: str,
) -> str:
    """Execute a terminal tool with approval/session/PTY logic.

    This is the single entry point for ALL terminal tool execution,
    used by both Ollama and cloud provider tool loops.
    """
    if fn_name == "run_command":
        return await _handle_run_command(fn_name, fn_args, server_name)
    elif fn_name == "request_session_mode":
        reason = fn_args.get("reason", "Autonomous operation requested")
        approved = await terminal_service.request_session(reason)
        return "session started" if approved else "session request denied"
    elif fn_name == "end_session_mode":
        # Session auto-expires after each turn now, but we still handle
        # explicit calls gracefully.
        await terminal_service.end_session()
        return "session ended"
    elif fn_name == "send_input":
        return await _handle_send_input(fn_args)
    elif fn_name == "read_output":
        return await _handle_read_output(fn_args)
    elif fn_name == "kill_process":
        return await _handle_kill_process(fn_args)
    elif fn_name == "get_environment":
        return await run_in_thread(_handle_get_environment)
    return f"Unknown terminal tool: {fn_name}"


# ─── run_command ────────────────────────────────────────────────────────


async def _handle_run_command(fn_name: str, fn_args: dict, server_name: str) -> str:
    """Handle run_command with approval, PTY, streaming, and DB persistence."""
    command = fn_args.get("command", "")
    cwd = fn_args.get("cwd", "")
    timeout = fn_args.get("timeout", 120)
    use_pty = fn_args.get("pty", False)
    background = fn_args.get("background", False)
    yield_ms = fn_args.get("yield_ms", 10000)
    requested_shell = fn_args.get("shell")

    try:
        analysis = analyze_command(command, requested_shell)
    except ValueError as exc:
        _save_terminal_event(
            command=command,
            exit_code=-1,
            output=f"Error: {exc}",
            cwd=cwd,
            duration_ms=0,
            denied=True,
        )
        return f"Error: {exc}"

    execution_shell_name = analysis.shell.name
    if (
        requested_shell is None
        and _looks_like_windows_drive_path(cwd)
        and analysis.shell.name in {"sh", "bash"}
    ):
        execution_shell_name = "cmd"

    if analysis.hard_block_reason:
        blocked_message = f"BLOCKED: {analysis.hard_block_reason}"
        _save_terminal_event(
            command=command,
            exit_code=-1,
            output=blocked_message,
            cwd=cwd,
            duration_ms=0,
            denied=True,
        )
        return blocked_message

    # Check approval (blocks until user responds if needed)
    approved, request_id = await terminal_service.check_approval(
        command,
        cwd,
        shell=execution_shell_name,
        warning=analysis.destructive_warning,
    )

    if not approved:
        _save_terminal_event(
            command=command,
            exit_code=-1,
            output="Command denied by user",
            cwd=cwd,
            duration_ms=0,
            denied=True,
        )
        return "Command denied by user"

    # Track for running notice
    terminal_service.track_running_command(request_id, command)

    # Background task for 10s running notices — wrapped in try/finally
    # to guarantee cancellation even if execution raises.
    async def _notice_checker():
        try:
            while request_id in terminal_service._running_commands:
                await terminal_service.check_running_notices()
                await asyncio.sleep(2)
        except asyncio.CancelledError:
            pass

    notice_task = asyncio.create_task(_notice_checker())

    try:
        if use_pty:
            (
                result_str,
                exit_code,
                duration_ms,
                timed_out,
                session_id,
            ) = await terminal_service.execute_command_pty(
                command=command,
                cwd=cwd,
                timeout=timeout,
                request_id=request_id,
                background=background,
                yield_ms=yield_ms,
                shell=execution_shell_name,
            )
        else:
            (
                result_str,
                exit_code,
                duration_ms,
                timed_out,
            ) = await terminal_service.execute_command(
                command=command,
                cwd=cwd,
                timeout=timeout,
                request_id=request_id,
                shell=execution_shell_name,
            )
            session_id = None
    finally:
        # Always stop tracking and cancel notice task
        terminal_service.stop_tracking_command(request_id)
        notice_task.cancel()

    # Broadcast completion (only for non-background sessions)
    if session_id is None:
        await terminal_service.broadcast_complete(request_id, exit_code, duration_ms)

    # Save terminal event to database
    _save_terminal_event(
        command=command,
        exit_code=exit_code,
        output=result_str[:50000],
        cwd=cwd,
        duration_ms=duration_ms,
        pty=use_pty,
        background=background,
        timed_out=timed_out,
    )

    return result_str


# ─── Session interaction helpers ────────────────────────────────────────


async def _handle_send_input(fn_args: dict) -> str:
    """Send text to a running PTY session."""
    session_id = fn_args.get("session_id", "")
    input_text = fn_args.get("input_text", "")
    press_enter = fn_args.get("press_enter", True)
    wait_ms = fn_args.get("wait_ms", 3000)

    if not session_id:
        return "Error: session_id is required"
    if not input_text and not press_enter:
        return "Error: input_text is required when press_enter is False"

    return await terminal_service.send_input(
        session_id,
        input_text,
        press_enter=press_enter,
        wait_ms=wait_ms,
    )


async def _handle_read_output(fn_args: dict) -> str:
    """Read recent output from a PTY session."""
    session_id = fn_args.get("session_id", "")
    lines = fn_args.get("lines", 50)
    if not session_id:
        return "Error: session_id is required"
    return await terminal_service.read_output(session_id, lines)


async def _handle_kill_process(fn_args: dict) -> str:
    """Terminate a PTY session."""
    session_id = fn_args.get("session_id", "")
    if not session_id:
        return "Error: session_id is required"
    return await terminal_service.kill_process(session_id)


# ─── Inline tools (no MCP subprocess needed) ───────────────────────────


def _handle_get_environment() -> str:
    """Return environment info without going through MCP subprocess."""
    import platform
    import subprocess
    import sys

    tools = {
        "python": "python --version",
        "node": "node --version",
        "npm": "npm --version",
        "git": "git --version",
        "pip": "pip --version",
        "uv": "uv --version",
        "cargo": "cargo --version",
        "docker": "docker --version",
    }
    results = {}
    for name, cmd in tools.items():
        if not shutil.which(name):
            continue
        try:
            result = subprocess.run(
                shlex.split(cmd),
                shell=False,
                capture_output=True,
                text=True,
                timeout=3,
                stdin=subprocess.DEVNULL,
            )
            version = (result.stdout.strip() or result.stderr.strip()).split("\n")[0]
            if version and result.returncode == 0:
                results[name] = version
        except Exception:
            pass

    tools_str = "\n".join(f"  {n}: {v}" for n, v in sorted(results.items()))
    if not tools_str:
        tools_str = "  (no common tools detected)"

    shell = (
        os.environ.get("COMSPEC", "cmd.exe")
        if platform.system() == "Windows"
        else os.environ.get("SHELL", "/bin/bash")
    )
    available_shells: list[str] = []
    for candidate in ("cmd", "powershell", "bash", "sh"):
        try:
            spec = resolve_shell(candidate)
        except ValueError:
            continue
        available_shells.append(f"  {candidate}: {spec.display_name}")

    shells_str = "\n".join(available_shells) if available_shells else "  (no alternate shells detected)"

    return (
        f"OS: {platform.system()} {platform.release()} ({platform.machine()})\n"
        f"Python: {sys.version.split()[0]}\n"
        f"Shell: {shell}\n"
        f"CWD: {os.getcwd()}\n"
        f"Runnable shells:\n{shells_str}\n"
        f"Available tools:\n{tools_str}"
    )


# ─── DB persistence helper ──────────────────────────────────────────────


def _save_terminal_event(**kwargs) -> None:
    """Save a terminal event, deferring if conversation_id isn't assigned yet."""
    event_data = dict(
        message_index=len(app_state.chat_history),
        **kwargs,
    )
    if app_state.conversation_id:
        from ...infrastructure.database import db

        db.save_terminal_event(
            conversation_id=app_state.conversation_id,
            **event_data,
        )
    else:
        terminal_service.queue_terminal_event(event_data)
