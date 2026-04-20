"""
MCP Terminal Server.

Provides shell command execution tools to the LLM via MCP protocol.
This server handles the actual command execution with security checks.

The approval flow is handled by the main FastAPI process (in the terminal
service layer), which intercepts tool calls before they reach this server.
This server provides defense-in-depth via the OS blocklist.

Tools:
- get_environment: Reports OS, shell, cwd, available tools
- run_command: Execute a shell command (sync, with optional PTY)
- request_session_mode: Request autonomous operation (routed via main process)
- end_session_mode: End autonomous session (routed via main process)
"""

import os
import sys
import shutil
import platform
import subprocess
import time
import threading
import concurrent.futures
from typing import Optional

from mcp.server.fastmcp import FastMCP

from source.services.shell.command_analysis import (
    analyze_command,
    build_subprocess_argv,
    interpret_command_result,
    resolve_shell,
)
from mcp_servers.servers.terminal.blocklist import check_blocklist
from mcp_servers.servers.terminal.terminal_descriptions import (
    GET_ENVIRONMENT_DESCRIPTION,
    RUN_COMMAND_DESCRIPTION,
    REQUEST_SESSION_MODE_DESCRIPTION,
    END_SESSION_MODE_DESCRIPTION,
    SEND_INPUT_DESCRIPTION,
    READ_OUTPUT_DESCRIPTION,
    KILL_PROCESS_DESCRIPTION,
)

# ── Create the MCP server ──────────────────────────────────────────────
mcp = FastMCP("Terminal")

# Capture the user's PATH at startup — prevents LLM from overriding it
_ORIGINAL_PATH = os.environ.get("PATH", "")
_ORIGINAL_ENV = dict(os.environ)

# Hard timeout ceiling (seconds)
_MAX_FOREGROUND_TIMEOUT = 120
_MAX_BACKGROUND_TIMEOUT = 1800

# Default working directory
_DEFAULT_CWD = os.getcwd()

# Subprocess flags: prevent child processes from inheriting MCP's stdio
# (MCP uses stdin/stdout for JSON-RPC — any child that reads stdin corrupts
# the protocol stream and causes the client to hang forever)
_SUBPROCESS_SAFE = {
    "stdin": subprocess.DEVNULL,  # never inherit MCP's stdin
}
if platform.system() == "Windows":
    _SUBPROCESS_SAFE["creationflags"] = subprocess.CREATE_NO_WINDOW


# ── Tool version caching ──────────────────────────────────────────────
_TOOL_VERSION_CACHE: dict[str, str] = {}
_TOOL_VERSION_CACHE_TIME: float = 0.0
_TOOL_VERSION_CACHE_TTL: float = 300.0  # 5 minutes
_TOOL_VERSION_CACHE_LOCK = threading.Lock()


def _get_shell() -> str:
    """Get the current shell."""
    if platform.system() == "Windows":
        return os.environ.get("COMSPEC", "cmd.exe")
    return os.environ.get("SHELL", "/bin/bash")


def _check_single_tool_version(name: str, cmd: str) -> tuple[str, str | None]:
    """Check version of a single tool. Returns (name, version) or (name, None)."""
    if not shutil.which(name):
        return name, None
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=3,
            env=_ORIGINAL_ENV,
            **_SUBPROCESS_SAFE,
        )
        version = (result.stdout.strip() or result.stderr.strip()).split("\n")[0]
        if version and result.returncode == 0:
            return name, version
    except (subprocess.TimeoutExpired, Exception):
        pass
    return name, None


def _get_tool_versions() -> dict[str, str]:
    """Detect versions of common tools on PATH with caching and parallel execution.

    Uses threading lock to prevent race conditions during cache refresh.
    """
    global _TOOL_VERSION_CACHE, _TOOL_VERSION_CACHE_TIME

    # Quick check without lock (common path)
    current_time = time.time()
    if _TOOL_VERSION_CACHE and (current_time - _TOOL_VERSION_CACHE_TIME) < _TOOL_VERSION_CACHE_TTL:
        return _TOOL_VERSION_CACHE

    # Acquire lock for cache miss
    with _TOOL_VERSION_CACHE_LOCK:
        # Double-check pattern: re-verify after acquiring lock
        current_time = time.time()
        if _TOOL_VERSION_CACHE and (current_time - _TOOL_VERSION_CACHE_TIME) < _TOOL_VERSION_CACHE_TTL:
            return _TOOL_VERSION_CACHE

        tools = {
            "python": "python --version",
            "node": "node --version",
            "npm": "npm --version",
            "git": "git --version",
            "pip": "pip --version",
            "uv": "uv --version",
            "cargo": "cargo --version",
            "docker": "docker --version",
            "java": "java -version",
        }

        results: dict[str, str] = {}

        # Execute all version checks in parallel using ThreadPoolExecutor
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(tools)) as executor:
            futures = {
                executor.submit(_check_single_tool_version, name, cmd): name
                for name, cmd in tools.items()
            }
            # Wait for all futures with a global timeout
            done, _ = concurrent.futures.wait(futures, timeout=5.0)
            for future in done:
                try:
                    name, version = future.result(timeout=0)
                    if version:
                        results[name] = version
                except Exception:
                    pass

        # Update cache
        _TOOL_VERSION_CACHE = results
        _TOOL_VERSION_CACHE_TIME = current_time
        return results


@mcp.tool(description=GET_ENVIRONMENT_DESCRIPTION)
def get_environment() -> str:
    tool_versions = _get_tool_versions()
    tools_str = "\n".join(f"  {name}: {ver}" for name, ver in sorted(tool_versions.items()))
    if not tools_str:
        tools_str = "  (no common tools detected)"

    available_shells: list[str] = []
    for candidate in ("cmd", "powershell", "bash", "sh"):
        try:
            spec = resolve_shell(candidate)
        except ValueError:
            continue
        available_shells.append(f"  {candidate}: {spec.display_name}")
    shells_str = "\n".join(available_shells) if available_shells else "  (no alternate shells detected)"

    return f"""OS: {platform.system()} {platform.release()} ({platform.machine()})
Python: {sys.version.split()[0]}
Shell: {_get_shell()}
CWD: {os.getcwd()}
Runnable shells:
{shells_str}
Available tools:
{tools_str}"""


@mcp.tool(description=RUN_COMMAND_DESCRIPTION)
def run_command(
    command: str,
    cwd: Optional[str] = None,
    shell: str = "auto",
    timeout: int = 120,
    pty: bool = False,
    background: bool = False,
    yield_ms: int = 10000,
) -> str:
    if cwd and any(char in cwd for char in ("\\", "/")):
        normalized_cwd = cwd.replace("\\", "/")
        if len(normalized_cwd) >= 3 and normalized_cwd[1] == ":" and normalized_cwd[2] == "/":
            if not os.path.isdir(cwd):
                return f"Error: Working directory does not exist: {cwd}"

    # Enforce timeout ceiling
    timeout = min(timeout, _MAX_FOREGROUND_TIMEOUT)

    # Resolve working directory
    work_dir = cwd or _DEFAULT_CWD
    if not os.path.isabs(work_dir):
        work_dir = os.path.abspath(work_dir)
    if not os.path.isdir(work_dir):
        return f"Error: Working directory does not exist: {work_dir}"

    try:
        shell_spec = resolve_shell(shell)
    except ValueError as exc:
        return f"Error: {exc}"

    if background:
        return (
            "Error: background execution is only supported by the main app's "
            "inline terminal runtime."
        )
    if pty:
        return (
            "Error: PTY execution is only supported by the main app's inline "
            "terminal runtime."
        )

    analysis = analyze_command(command, shell_spec.name)
    if analysis.hard_block_reason:
        return f"BLOCKED: {analysis.hard_block_reason}"

    # Security: check blocklist
    blocked, reason = check_blocklist(command)
    if blocked:
        return f"BLOCKED: {reason}"

    # Security: prevent PATH injection in the execution environment
    env = dict(_ORIGINAL_ENV)
    env["PATH"] = _ORIGINAL_PATH

    # Execute command
    try:
        result = subprocess.run(
            build_subprocess_argv(shell_spec, command),
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=work_dir,
            env=env,
            **_SUBPROCESS_SAFE,
        )

        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            if output:
                output += "\n"
            output += result.stderr

        if not output:
            output = "(no output)"

        semantics = interpret_command_result(command, result.returncode, shell_spec.name)
        if semantics.is_error and result.returncode != 0:
            output += f"\n[exit code: {result.returncode}]"
        elif semantics.message:
            if output == "(no output)":
                output = semantics.message
            elif semantics.message not in output:
                output += f"\n[{semantics.message}]"

        return output

    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {timeout} seconds"
    except Exception as e:
        return f"Error executing command: {str(e)}"


@mcp.tool(description=REQUEST_SESSION_MODE_DESCRIPTION)
def request_session_mode(reason: str) -> str:
    # This tool's approval is handled by the terminal service in the main process.
    # The MCP server just returns a placeholder — the actual approval routing
    # happens at the handler layer.
    return "session_mode_requested"


@mcp.tool(description=END_SESSION_MODE_DESCRIPTION)
def end_session_mode() -> str:
    return "session_mode_ended"


@mcp.tool(description=SEND_INPUT_DESCRIPTION)
def send_input(session_id: str, input_text: str, press_enter: bool = True, wait_ms: int = 3000) -> str:
    # Intercepted at the handler layer — this MCP function is never called
    # directly. The handler routes to terminal_service.send_input().
    return "send_input_handled"


@mcp.tool(description=READ_OUTPUT_DESCRIPTION)
def read_output(session_id: str, lines: int = 50) -> str:
    # Intercepted at the handler layer — routes to terminal_service.read_output().
    return "read_output_handled"


@mcp.tool(description=KILL_PROCESS_DESCRIPTION)
def kill_process(session_id: str) -> str:
    # Intercepted at the handler layer — routes to terminal_service.kill_process().
    return "kill_process_handled"


# ── Entry point ────────────────────────────────────────────────────────
if __name__ == "__main__":
    mcp.run()
