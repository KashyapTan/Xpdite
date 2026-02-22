"""
Unified terminal tool execution.

Single source of truth for executing terminal tools (run_command,
request_session_mode, end_session_mode, send_input, read_output,
kill_process, find_files) with approval, PTY, streaming, and DB persistence.

Both handlers.py (Ollama) and cloud_tool_handlers.py (Anthropic/OpenAI/Gemini)
import from here to avoid duplicating the approval + execution + notice + DB
save logic.
"""

import asyncio
import glob
import json
import os
import shlex
from typing import Optional

from ..core.connection import broadcast_message
from ..core.state import app_state
from ..core.thread_pool import run_in_thread
from ..services.terminal import terminal_service


# Tool names that must be intercepted (never reach the MCP subprocess)
TERMINAL_TOOLS = {
    "run_command",
    "request_session_mode",
    "end_session_mode",
    "send_input",
    "read_output",
    "kill_process",
    "get_environment",
    "find_files",
}


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
    elif fn_name == "find_files":
        return await run_in_thread(_handle_find_files, fn_args)
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

    # Check approval (blocks until user responds if needed)
    approved, request_id = await terminal_service.check_approval(command, cwd)

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
    import shutil
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

    return (
        f"OS: {platform.system()} {platform.release()} ({platform.machine()})\n"
        f"Python: {sys.version.split()[0]}\n"
        f"Shell: {shell}\n"
        f"CWD: {os.getcwd()}\n"
        f"Available tools:\n{tools_str}"
    )


def _handle_find_files(fn_args: dict) -> str:
    """Find files matching a glob pattern — executed inline."""
    pattern = fn_args.get("pattern", "")
    directory = fn_args.get("directory", "") or os.getcwd()

    if not os.path.isabs(directory):
        directory = os.path.abspath(directory)
    if not os.path.isdir(directory):
        return f"Error: Directory does not exist: {directory}"

    # Path traversal protection: restrict to CWD subtree
    resolved = os.path.realpath(directory)
    cwd = os.path.realpath(os.getcwd())
    if not resolved.startswith(cwd):
        return "Error: find_files is restricted to the current working directory tree."

    search_pattern = os.path.join(directory, pattern)
    try:
        matches = glob.glob(search_pattern, recursive=True)
        if not matches:
            return f"No files found matching '{pattern}' in {directory}"
        if len(matches) > 200:
            return f"Found {len(matches)} files. Showing first 200:\n" + "\n".join(
                matches[:200]
            )
        return f"Found {len(matches)} file(s):\n" + "\n".join(matches)
    except Exception as e:
        return f"Error searching for files: {e}"


# ─── DB persistence helper ──────────────────────────────────────────────


def _save_terminal_event(**kwargs) -> None:
    """Save a terminal event, deferring if conversation_id isn't assigned yet."""
    event_data = dict(
        message_index=len(app_state.chat_history),
        **kwargs,
    )
    if app_state.conversation_id:
        from ..database import db
        db.save_terminal_event(
            conversation_id=app_state.conversation_id,
            **event_data,
        )
    else:
        terminal_service.queue_terminal_event(event_data)
