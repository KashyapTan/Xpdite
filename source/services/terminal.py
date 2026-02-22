"""
Terminal Service.

Manages the approval flow, session mode, and direct command execution
for terminal commands. This runs in the main FastAPI process and intercepts
terminal tool calls before they reach the MCP server.

Two execution modes:
- **Standard**: asyncio.create_subprocess_shell for simple, non-interactive
  commands. Output streamed line-by-line.
- **PTY**: pywinpty PtyProcess for interactive CLIs (opencode, vim, etc).
  Raw ANSI output streamed to xterm.js for full TUI rendering. Supports
  send_input for LLM-driven interaction.

Background sessions: Long-running or interactive commands can outlive their
tool call via yield_ms. The LLM gets a session_id back and can later call
send_input / read_output / kill_process to interact with the running process.

The approval uses asyncio.Event to block the tool call until the user
responds via WebSocket.

Ask levels:
- 'always':  Prompt before every command
- 'on-miss': Prompt only for commands not previously approved
- 'off':     No prompts (auto-approve) — used during session mode
"""

import asyncio
import os
import platform
import re
import uuid
import time
import json
from typing import Optional

from ..core.connection import manager
from .approval_history import is_command_approved, remember_approval

# Import security checks from MCP terminal blocklist
from mcp_servers.servers.terminal.blocklist import check_blocklist

# Hard timeout ceiling (seconds)
_MAX_TIMEOUT = 120
_MAX_BACKGROUND_TIMEOUT = 1800

# Capture the user's PATH at startup to prevent LLM PATH injection
_ORIGINAL_PATH = os.environ.get("PATH", "")
_ORIGINAL_ENV = dict(os.environ)

# ANSI escape code stripper (for LLM-readable output from PTY)
_ANSI_RE = re.compile(
    r"\x1b\[[0-9;]*[a-zA-Z]"  # CSI sequences (colors, cursor)
    r"|\x1b\][^\x07]*\x07"  # OSC sequences (title, etc)
    r"|\x1b[()][AB012]"  # Character set selection
    r"|\x1b\[[\?0-9;]*[hlm]"  # Private mode set/reset
    r"|\x1b[=>]"  # Keypad modes
    r"|\r"  # Carriage returns
)


def _strip_ansi(text: str) -> str:
    """Strip ANSI escape codes from PTY output for LLM-readable text."""
    return _ANSI_RE.sub("", text)


def _kill_process_tree(pid: int) -> None:
    """Kill a process and all its children (process tree).

    On Windows, `process.kill()` only terminates the shell (cmd.exe), not
    the child processes it spawned. This uses `taskkill /F /T` to kill the
    entire tree. On Unix, kills the process group via `os.killpg`.
    """
    try:
        if platform.system() == "Windows":
            import subprocess as sp
            sp.run(
                f"taskkill /F /T /PID {pid}",
                shell=True,
                capture_output=True,
                timeout=5,
            )
        else:
            import signal
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                os.kill(pid, signal.SIGKILL)
    except Exception:
        # Last resort: basic kill
        try:
            os.kill(pid, 9)
        except (ProcessLookupError, PermissionError, OSError):
            pass


class TerminalSession:
    """
    Manages a single PTY process with async output streaming.

    Created when a command runs with pty=True. Output is streamed
    raw to xterm.js and buffered (ANSI-stripped) for LLM consumption.
    """

    def __init__(self, session_id: str, request_id: str, command: str, cwd: str):
        self.session_id = session_id
        self.request_id = request_id
        self.command = command
        self.cwd = cwd
        self.process: Optional[object] = None  # PtyProcess
        self.output_buffer: list[str] = []  # Raw output chunks
        self.text_buffer: list[str] = []  # ANSI-stripped for LLM
        self.reader_task: Optional[asyncio.Task] = None
        self.start_time: float = time.time()
        self.exit_code: Optional[int] = None
        self._alive = True
        self._done_event = asyncio.Event()

    @property
    def is_alive(self) -> bool:
        return self._alive

    @property
    def duration_ms(self) -> int:
        return int((time.time() - self.start_time) * 1000)

    def get_recent_output(self, lines: int = 50) -> str:
        """Get recent LLM-readable output (ANSI stripped)."""
        full = "".join(self.text_buffer)
        output_lines = full.split("\n")
        return "\n".join(output_lines[-lines:])

    async def wait_for_completion(self, timeout: float) -> bool:
        """Wait for the process to finish, up to timeout seconds.
        Returns True if the process finished, False if still running."""
        try:
            await asyncio.wait_for(self._done_event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False


class TerminalService:
    """
    Handles terminal command approval and session mode.

    This service intercepts terminal tool calls at the handler layer,
    checks if approval is needed, and blocks until the user responds.
    """

    def __init__(self):
        # Approval state
        self._approval_events: dict[str, asyncio.Event] = {}
        self._approval_results: dict[str, bool] = {}
        self._approval_remember: dict[str, bool] = {}

        # Session mode state
        self._session_mode: bool = False
        self._session_event: Optional[asyncio.Event] = None
        self._session_result: Optional[bool] = None

        # Ask level: 'always' | 'on-miss' | 'off'
        self._ask_level: str = "on-miss"

        # Running command tracking (for 10s notice)
        self._running_commands: dict[str, dict] = {}

        # Active subprocess (for kill support — standard mode)
        self._active_process: Optional[asyncio.subprocess.Process] = None
        self._active_request_id: Optional[str] = None

        # Background/interactive PTY sessions
        self._background_sessions: dict[str, TerminalSession] = {}

        # Last known terminal size from frontend (cols, rows)
        self._last_pty_size: tuple[int, int] = (120, 24)

        # Deferred terminal events (saved once conversation_id is assigned)
        self._pending_events: list[dict] = []

    @property
    def ask_level(self) -> str:
        return self._ask_level

    @ask_level.setter
    def ask_level(self, value: str):
        if value in ("always", "on-miss", "off"):
            self._ask_level = value

    @property
    def session_mode(self) -> bool:
        return self._session_mode

    async def check_approval(self, command: str, cwd: str) -> tuple[bool, str]:
        """
        Check if a command needs approval and wait for user response if needed.

        Returns:
            (approved: bool, request_id: str)
        """
        request_id = str(uuid.uuid4())

        # Session mode or ask=off: auto-approve
        if self._session_mode or self._ask_level == "off":
            return True, request_id

        # Ask=on-miss: check history
        if self._ask_level == "on-miss":
            if is_command_approved(command):
                return True, request_id

        # Need user approval — broadcast request and wait
        event = asyncio.Event()
        self._approval_events[request_id] = event
        self._approval_results[request_id] = False
        self._approval_remember[request_id] = False

        # Broadcast approval request to frontend
        await manager.broadcast(
            json.dumps(
                {
                    "type": "terminal_approval_request",
                    "content": json.dumps(
                        {
                            "command": command,
                            "cwd": cwd,
                            "request_id": request_id,
                        }
                    ),
                }
            )
        )

        # Block until user responds (timeout = 120s)
        try:
            await asyncio.wait_for(event.wait(), timeout=120.0)
        except asyncio.TimeoutError:
            self._cleanup_approval(request_id)
            return False, request_id

        approved = self._approval_results.get(request_id, False)
        should_remember = self._approval_remember.get(request_id, False)

        # Save to approval history if "Allow & Remember"
        if approved and should_remember:
            remember_approval(command)

        self._cleanup_approval(request_id)
        return approved, request_id

    def resolve_approval(self, request_id: str, approved: bool, remember: bool = False):
        """
        Called when the user responds to an approval request.
        Resolves the asyncio.Event to unblock the waiting tool call.
        """
        if request_id not in self._approval_events:
            return

        self._approval_results[request_id] = approved
        self._approval_remember[request_id] = remember
        self._approval_events[request_id].set()

    async def request_session(self, reason: str) -> bool:
        """
        Request session mode (autonomous operation).
        Broadcasts to frontend and waits for user response.
        """
        request_id = str(uuid.uuid4())
        self._session_event = asyncio.Event()
        self._session_result = None

        await manager.broadcast(
            json.dumps(
                {
                    "type": "terminal_session_request",
                    "content": json.dumps(
                        {
                            "reason": reason,
                            "request_id": request_id,
                        }
                    ),
                }
            )
        )

        try:
            await asyncio.wait_for(self._session_event.wait(), timeout=120.0)
        except asyncio.TimeoutError:
            self._session_event = None
            return False

        approved = self._session_result or False
        self._session_event = None

        if approved:
            self._session_mode = True
            await manager.broadcast(
                json.dumps({"type": "terminal_session_started", "content": ""})
            )

        return approved

    def resolve_session(self, approved: bool):
        """Called when user responds to session mode request."""
        self._session_result = approved
        if self._session_event:
            self._session_event.set()

    async def end_session(self):
        """End session mode."""
        self._session_mode = False
        await manager.broadcast(
            json.dumps({"type": "terminal_session_ended", "content": ""})
        )

    def track_running_command(self, request_id: str, command: str):
        """Start tracking a running command for the 10s notice."""
        self._running_commands[request_id] = {
            "command": command,
            "start_time": time.time(),
            "notified": False,
        }

    async def check_running_notices(self):
        """
        Check if any running commands have exceeded 10s and broadcast notices.
        Called periodically by the terminal tool handler.
        """
        now = time.time()
        for request_id, info in list(self._running_commands.items()):
            elapsed_ms = int((now - info["start_time"]) * 1000)
            if elapsed_ms >= 10000 and not info["notified"]:
                info["notified"] = True
                await manager.broadcast(
                    json.dumps(
                        {
                            "type": "terminal_running_notice",
                            "content": json.dumps(
                                {
                                    "request_id": request_id,
                                    "command": info["command"],
                                    "elapsed_ms": elapsed_ms,
                                }
                            ),
                        }
                    )
                )

    def stop_tracking_command(self, request_id: str):
        """Stop tracking a running command."""
        self._running_commands.pop(request_id, None)

    async def broadcast_output(
        self, request_id: str, text: str, stream: bool = False, raw: bool = False
    ):
        """Broadcast terminal output to frontend.

        Args:
            request_id: Execution request ID
            text: Output text (raw ANSI for PTY, plain for standard)
            stream: Whether this is streaming (partial) output
            raw: If True, frontend uses term.write() (raw ANSI for PTY/TUI).
                 If False, frontend uses term.writeln() (line-by-line).
        """
        await manager.broadcast(
            json.dumps(
                {
                    "type": "terminal_output",
                    "content": json.dumps(
                        {
                            "text": text,
                            "request_id": request_id,
                            "stream": stream,
                            "raw": raw,
                        }
                    ),
                }
            )
        )

    async def broadcast_complete(
        self, request_id: str, exit_code: int, duration_ms: int
    ):
        """Broadcast command completion to frontend."""
        await manager.broadcast(
            json.dumps(
                {
                    "type": "terminal_command_complete",
                    "content": json.dumps(
                        {
                            "request_id": request_id,
                            "exit_code": exit_code,
                            "duration_ms": duration_ms,
                        }
                    ),
                }
            )
        )

    # ── Direct Command Execution ────────────────────────────────────────

    async def execute_command(
        self,
        command: str,
        cwd: str,
        timeout: int = 120,
        request_id: Optional[str] = None,
    ) -> tuple[str, int, int, bool]:
        """
        Execute a command directly using asyncio subprocess with real-time
        output streaming. Replaces the MCP server's subprocess.run() to
        enable live output and process kill support.

        Security checks (blocklist, PATH injection prevention) are applied
        here since we bypass the MCP server.

        Args:
            command: Shell command to execute
            cwd: Working directory
            timeout: Timeout in seconds (capped at _MAX_TIMEOUT)
            request_id: ID for this execution (for tracking/kill)

        Returns:
            (full_output, exit_code, duration_ms, timed_out)
        """
        # Enforce timeout ceiling
        effective_timeout = min(timeout, _MAX_TIMEOUT)

        # Resolve working directory
        work_dir = cwd or os.getcwd()
        if not os.path.isabs(work_dir):
            work_dir = os.path.abspath(work_dir)
        if not os.path.isdir(work_dir):
            return f"Error: Working directory does not exist: {work_dir}", 1, 0, False

        # Security: check blocklist
        blocked, reason = check_blocklist(command)
        if blocked:
            return f"BLOCKED: {reason}", 1, 0, False

        # Build safe environment (prevent PATH injection)
        env = dict(_ORIGINAL_ENV)
        env["PATH"] = _ORIGINAL_PATH

        if not request_id:
            request_id = str(uuid.uuid4())

        start_time = time.time()
        output_lines: list[str] = []
        timed_out = False

        try:
            # Use asyncio subprocess for non-blocking I/O
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                stdin=asyncio.subprocess.DEVNULL,
                cwd=work_dir,
                env=env,
            )

            self._active_process = process
            self._active_request_id = request_id

            # Read output line-by-line and stream to frontend
            assert process.stdout is not None
            try:
                while True:
                    # Compute remaining time from the original capped timeout
                    elapsed = time.time() - start_time
                    remaining = max(0.1, effective_timeout - elapsed)

                    try:
                        line_bytes = await asyncio.wait_for(
                            process.stdout.readline(), timeout=remaining
                        )
                    except asyncio.TimeoutError:
                        # Timeout reading — kill the process tree
                        timed_out = True
                        _kill_process_tree(process.pid)
                        break

                    if not line_bytes:
                        # EOF — process has finished writing
                        break

                    line = (
                        line_bytes.decode("utf-8", errors="replace")
                        .rstrip("\n")
                        .rstrip("\r")
                    )
                    output_lines.append(line)

                    # Stream this line to the frontend immediately
                    await self.broadcast_output(request_id, line, stream=True)

            except asyncio.CancelledError:
                _kill_process_tree(process.pid)
                raise

            # Wait for process to finish (short timeout for cleanup)
            try:
                exit_code = await asyncio.wait_for(process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                _kill_process_tree(process.pid)
                exit_code = -1
                timed_out = True

        except Exception as e:
            output_lines.append(f"Error executing command: {e}")
            exit_code = 1
        finally:
            self._active_process = None
            self._active_request_id = None

        duration_ms = int((time.time() - start_time) * 1000)

        full_output = "\n".join(output_lines) if output_lines else "(no output)"

        if timed_out:
            timeout_msg = f"Command timed out after {effective_timeout} seconds"
            output_lines.append(timeout_msg)
            full_output += f"\n{timeout_msg}"
            await self.broadcast_output(
                request_id, f"\x1b[31m{timeout_msg}\x1b[0m", stream=True
            )

        if exit_code != 0 and not timed_out:
            full_output += f"\n[exit code: {exit_code}]"

        return full_output, exit_code, duration_ms, timed_out

    async def kill_running_command(self) -> bool:
        """
        Kill the currently running command subprocess.
        Called when user clicks the Kill button in the terminal panel.

        Returns True if a process was killed, False if nothing was running.
        """
        killed = False

        # Kill standard subprocess
        process = self._active_process
        request_id = self._active_request_id

        if process is not None:
            _kill_process_tree(process.pid)
            if request_id:
                await self.broadcast_output(
                    request_id,
                    "\x1b[31m[Process killed by user]\x1b[0m",
                    stream=True,
                )
            killed = True

        # Kill all active PTY sessions
        for sid, session in list(self._background_sessions.items()):
            if session.is_alive:
                await self._kill_session(sid, "[Process killed by user]")
                killed = True

        return killed

    # ── PTY Execution (Interactive CLIs) ────────────────────────────────

    async def execute_command_pty(
        self,
        command: str,
        cwd: str,
        timeout: int = 120,
        request_id: Optional[str] = None,
        background: bool = False,
        yield_ms: int = 10000,
    ) -> tuple[str, int, int, bool, Optional[str]]:
        """
        Execute a command in a PTY for full interactive TUI support.

        Creates a Windows ConPTY via pywinpty and streams raw ANSI output
        to xterm.js on the frontend. The PTY gives interactive CLIs
        (opencode, vim, htop, etc.) a real terminal to render into.

        Args:
            command: Shell command to execute
            cwd: Working directory
            timeout: Timeout seconds (capped at _MAX_TIMEOUT for foreground,
                     _MAX_BACKGROUND_TIMEOUT for background)
            request_id: Tracking ID for this execution
            background: If True, return a session_id after yield_ms without
                        waiting for completion. LLM can later interact via
                        send_input/read_output/kill_process.
            yield_ms: Time to wait (ms) before returning for background processes.
                      The LLM gets recent output and a session_id to interact with.

        Returns:
            (output_text, exit_code, duration_ms, timed_out, session_id)
            session_id is non-None only for background processes still running.
        """
        try:
            from winpty import PtyProcess
        except ImportError:
            return (
                "Error: pywinpty is not installed. PTY mode requires pywinpty "
                "(pip install pywinpty). Falling back to standard execution.",
                1,
                0,
                False,
                None,
            )

        max_timeout = _MAX_BACKGROUND_TIMEOUT if background else _MAX_TIMEOUT
        timeout = min(timeout, max_timeout)

        # Resolve working directory
        work_dir = cwd or os.getcwd()
        if not os.path.isabs(work_dir):
            work_dir = os.path.abspath(work_dir)
        if not os.path.isdir(work_dir):
            return (
                f"Error: Working directory does not exist: {work_dir}",
                1,
                0,
                False,
                None,
            )

        # Security: check blocklist
        blocked, reason = check_blocklist(command)
        if blocked:
            return f"BLOCKED: {reason}", 1, 0, False, None

        # Build safe environment
        env = dict(_ORIGINAL_ENV)
        env["PATH"] = _ORIGINAL_PATH
        # Tell programs they're in a real terminal
        env["TERM"] = "xterm-256color"

        if not request_id:
            request_id = str(uuid.uuid4())

        session_id = str(uuid.uuid4())
        session = TerminalSession(session_id, request_id, command, cwd)

        try:
            # Build the command for ConPTY.
            # On Windows, we use cmd /c to run the command so things like
            # PATH resolution, pipes, and redirects work.
            if platform.system() == "Windows":
                spawn_cmd = f"cmd /c {command}"
            else:
                spawn_cmd = command

            # Create PTY process
            # Use last known terminal size from frontend
            cols, rows = self._last_pty_size

            pty_proc = await asyncio.to_thread(
                PtyProcess.spawn,
                spawn_cmd,
                cwd=work_dir,
                env=env,
                dimensions=(rows, cols),
            )

            session.process = pty_proc

            # Start the async reader loop
            async def _pty_reader():
                """Read PTY output in a loop, broadcast raw ANSI to frontend."""
                while True:
                    try:
                        # PtyProcess.read() blocks — run in thread
                        data = await asyncio.to_thread(pty_proc.read, 4096)
                        if not data:
                            break
                        session.output_buffer.append(data)
                        session.text_buffer.append(_strip_ansi(data))
                        await self.broadcast_output(
                            request_id, data, stream=True, raw=True
                        )
                    except EOFError:
                        break
                    except Exception:
                        break

                # Process is done
                session._alive = False
                try:
                    session.exit_code = (
                        pty_proc.exitstatus if hasattr(pty_proc, "exitstatus") else 0
                    )
                except Exception:
                    session.exit_code = 0
                session._done_event.set()

                # Broadcast completion so the frontend terminal block
                # transitions from "running" to "completed"
                exit_code = session.exit_code or 0
                duration_ms = session.duration_ms
                await self.broadcast_complete(request_id, exit_code, duration_ms)

                # Clean up session from registry
                self._background_sessions.pop(session_id, None)

            session.reader_task = asyncio.create_task(_pty_reader())

            # Register this session
            self._background_sessions[session_id] = session

            if background:
                # Wait yield_ms for the process to possibly finish quickly
                yield_seconds = yield_ms / 1000.0
                finished = await session.wait_for_completion(yield_seconds)

                if finished:
                    # Process completed within yield time
                    output = session.get_recent_output(100)
                    exit_code = session.exit_code or 0
                    duration_ms = session.duration_ms

                    # Broadcast completion
                    await self.broadcast_complete(request_id, exit_code, duration_ms)

                    # Clean up
                    self._background_sessions.pop(session_id, None)

                    return output, exit_code, duration_ms, False, None
                else:
                    # Still running — return session_id to LLM
                    output = session.get_recent_output(100)
                    return (
                        f"Process running (session_id: {session_id}).\n"
                        f"--- Recent Output ---\n{output}",
                        0,
                        session.duration_ms,
                        False,
                        session_id,
                    )
            else:
                # Foreground: wait for completion up to timeout
                finished = await session.wait_for_completion(timeout)

                if finished:
                    output = session.get_recent_output(200)
                    exit_code = session.exit_code or 0
                    duration_ms = session.duration_ms

                    await self.broadcast_complete(request_id, exit_code, duration_ms)
                    self._background_sessions.pop(session_id, None)

                    return output, exit_code, duration_ms, False, None
                else:
                    # Timed out — kill the process
                    await self._kill_session(
                        session_id, f"Command timed out after {timeout}s"
                    )

                    output = session.get_recent_output(200)
                    duration_ms = session.duration_ms

                    return (
                        output + f"\n[Timed out after {timeout}s]",
                        -1,
                        duration_ms,
                        True,
                        None,
                    )

        except Exception as e:
            # Cleanup on error
            self._background_sessions.pop(session_id, None)
            if session.reader_task:
                session.reader_task.cancel()
            return f"Error launching PTY: {e}", 1, 0, False, None

    # ── Session Interaction (send_input / read_output / kill_process) ──

    async def send_input(
        self,
        session_id: str,
        text: str,
        press_enter: bool = True,
        wait_ms: int = 3000,
    ) -> str:
        """
        Send input text to a running PTY session.

        Decodes escape sequences (\\r\\n, \\x03, etc.) so the LLM can
        use them naturally in JSON strings.  When press_enter=True,
        appends \\r if the text doesn't already end with one.

        After sending, waits wait_ms milliseconds for the CLI to
        respond, then returns recent output so the LLM can see the
        effect of its input in a single tool call.
        """
        session = self._background_sessions.get(session_id)
        if not session:
            return f"Error: No active session with ID {session_id}"
        if not session.is_alive:
            return f"Error: Session {session_id} has already exited"
        if not session.process:
            return f"Error: Session {session_id} has no active process"

        try:
            # Decode JSON escape sequences (\r\n → actual CR LF, \x03 → Ctrl-C, etc.)
            decoded = text.encode("raw_unicode_escape").decode("unicode_escape")

            # Auto-append Enter if requested and not already present
            if press_enter and not decoded.endswith(("\r", "\n")):
                decoded += "\r"

            # PtyProcess.write() may block — run in thread
            await asyncio.to_thread(session.process.write, decoded)

            # Wait for the CLI to process the input
            if wait_ms > 0:
                await asyncio.sleep(wait_ms / 1000.0)

            # Return recent output so the LLM sees the result
            output = session.get_recent_output(50)
            alive = "running" if session.is_alive else "exited"
            return f"Input sent. Session is {alive}.\n--- Recent Output ---\n{output}"
        except Exception as e:
            return f"Error sending input: {e}"

    async def read_output(self, session_id: str, lines: int = 50) -> str:
        """
        Read recent output from a background PTY session.

        Returns ANSI-stripped text suitable for LLM consumption.
        The frontend gets raw ANSI via WebSocket for xterm.js rendering.
        """
        session = self._background_sessions.get(session_id)
        if not session:
            return (
                f"Error: No active session with ID {session_id}. "
                f"The process has already exited and been cleaned up. "
                f"No further action is needed — do NOT call read_output or "
                f"kill_process on this session_id again."
            )

        output = session.get_recent_output(lines)
        elapsed = session.duration_ms // 1000

        if session.is_alive:
            return (
                f"[Session {session_id} — RUNNING, {elapsed}s elapsed]\n"
                f"--- Output ({lines} lines) ---\n"
                f"{output}"
            )
        else:
            exit_code = session.exit_code if session.exit_code is not None else 0
            # Clean up finished session from registry
            self._background_sessions.pop(session_id, None)
            return (
                f"[Session {session_id} — EXITED (exit code {exit_code}), {elapsed}s elapsed]\n"
                f"The process has finished. Do NOT call read_output or kill_process again.\n"
                f"--- Final Output ({lines} lines) ---\n"
                f"{output}"
            )

    async def kill_process(self, session_id: str) -> str:
        """
        Kill a specific background PTY session by session_id.
        """
        if session_id not in self._background_sessions:
            return f"Error: No active session with ID {session_id}"

        await self._kill_session(session_id, "Process killed by LLM request")
        return f"Session {session_id} terminated"

    async def resize_pty(self, session_id: str, cols: int, rows: int):
        """Resize a PTY session to match the xterm.js viewport."""
        session = self._background_sessions.get(session_id)
        if not session or not session.process or not session.is_alive:
            return
        try:
            await asyncio.to_thread(session.process.setwinsize, rows, cols)
        except Exception:
            pass

    async def resize_all_pty(self, cols: int, rows: int):
        """Resize ALL active PTY sessions to match the frontend viewport."""
        self._last_pty_size = (cols, rows)
        for session in self._background_sessions.values():
            if session.process and session.is_alive:
                try:
                    await asyncio.to_thread(session.process.setwinsize, rows, cols)
                except Exception:
                    pass

    async def _kill_session(self, session_id: str, reason: str):
        """Internal: kill a PTY session, broadcast notification, clean up."""
        session = self._background_sessions.get(session_id)
        if not session:
            return

        # Cancel reader task
        if session.reader_task and not session.reader_task.done():
            session.reader_task.cancel()

        # Kill PTY process
        if session.process and session.is_alive:
            try:
                await asyncio.to_thread(session.process.terminate)
            except Exception:
                pass
            session._alive = False
            session.exit_code = -1

        # Broadcast killed message
        await self.broadcast_output(
            session.request_id,
            f"\x1b[31m[{reason}]\x1b[0m",
            stream=True,
            raw=True,
        )

        # Broadcast completion
        await self.broadcast_complete(
            session.request_id,
            exit_code=-1,
            duration_ms=session.duration_ms,
        )

        # Remove from registry
        self._background_sessions.pop(session_id, None)

    def _cleanup_approval(self, request_id: str):
        """Clean up approval state for a request."""
        self._approval_events.pop(request_id, None)
        self._approval_results.pop(request_id, None)
        self._approval_remember.pop(request_id, None)

    def queue_terminal_event(self, event_data: dict):
        """
        Queue a terminal event for deferred save.
        Called when conversation_id is not yet assigned (first message).
        """
        self._pending_events.append(event_data)

    def flush_pending_events(self, conversation_id: str):
        """
        Save all queued terminal events now that conversation_id is known.
        Called from conversations.py after conversation creation.
        """
        from ..database import db

        for event in self._pending_events:
            db.save_terminal_event(
                conversation_id=conversation_id,
                message_index=event["message_index"],
                command=event["command"],
                exit_code=event["exit_code"],
                output=event["output"],
                cwd=event["cwd"],
                duration_ms=event["duration_ms"],
                pty=event.get("pty", False),
                background=event.get("background", False),
                timed_out=event.get("timed_out", False),
                denied=event.get("denied", False),
            )
        self._pending_events.clear()

    def cancel_all_pending(self):
        """
        Cancel all pending approval and session events.
        Called when stop_streaming is triggered so that any blocking
        check_approval() / request_session() calls unblock immediately.
        Also kills any running command subprocess and background sessions.
        """
        # Deny all pending approvals
        for request_id, event in list(self._approval_events.items()):
            self._approval_results[request_id] = False
            event.set()

        # Cancel pending session request
        if self._session_event and not self._session_event.is_set():
            self._session_result = False
            self._session_event.set()

        # Kill any running standard subprocess
        if self._active_process:
            try:
                self._active_process.kill()
            except ProcessLookupError:
                pass

        # Kill all PTY sessions
        for sid, session in list(self._background_sessions.items()):
            if session.reader_task and not session.reader_task.done():
                session.reader_task.cancel()
            if session.process and session.is_alive:
                try:
                    session.process.terminate()
                except Exception:
                    pass
                session._alive = False
        self._background_sessions.clear()

    def reset(self):
        """Reset terminal service state (on conversation clear)."""
        self.cancel_all_pending()
        self._session_mode = False
        self._session_event = None
        self._session_result = None
        self._running_commands.clear()
        self._pending_events.clear()
        self._active_process = None
        self._active_request_id = None
        self._background_sessions.clear()


# Global singleton
terminal_service = TerminalService()
