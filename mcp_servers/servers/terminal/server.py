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
- find_files: Find files matching a glob pattern
- request_session_mode: Request autonomous operation (routed via main process)
- end_session_mode: End autonomous session (routed via main process)
"""

import os
import sys
import glob
import shutil
import platform
import subprocess
from typing import Optional

from mcp.server.fastmcp import FastMCP

from mcp_servers.servers.terminal.blocklist import check_blocklist
from mcp_servers.servers.terminal.terminal_descriptions import (
    GET_ENVIRONMENT_DESCRIPTION,
    RUN_COMMAND_DESCRIPTION,
    FIND_FILES_DESCRIPTION,
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


def _get_shell() -> str:
    """Get the current shell."""
    if platform.system() == "Windows":
        return os.environ.get("COMSPEC", "cmd.exe")
    return os.environ.get("SHELL", "/bin/bash")


def _get_tool_versions() -> dict[str, str]:
    """Detect versions of common tools on PATH."""
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

    results = {}
    for name, cmd in tools.items():
        # Fast existence check — avoids slow subprocess timeout for missing tools
        if not shutil.which(name):
            continue
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
                results[name] = version
        except (subprocess.TimeoutExpired, Exception):
            pass

    return results


@mcp.tool(description=GET_ENVIRONMENT_DESCRIPTION)
def get_environment() -> str:
    tool_versions = _get_tool_versions()
    tools_str = "\n".join(f"  {name}: {ver}" for name, ver in sorted(tool_versions.items()))
    if not tools_str:
        tools_str = "  (no common tools detected)"

    return f"""OS: {platform.system()} {platform.release()} ({platform.machine()})
Python: {sys.version.split()[0]}
Shell: {_get_shell()}
CWD: {os.getcwd()}
Available tools:
{tools_str}"""


@mcp.tool(description=RUN_COMMAND_DESCRIPTION)
def run_command(
    command: str,
    cwd: Optional[str] = None,
    timeout: int = 120,
    pty: bool = False,
    background: bool = False,
    yield_ms: int = 10000,
) -> str:
    # Enforce timeout ceiling
    timeout = min(timeout, _MAX_FOREGROUND_TIMEOUT)

    # Resolve working directory
    work_dir = cwd or _DEFAULT_CWD
    if not os.path.isabs(work_dir):
        work_dir = os.path.abspath(work_dir)
    if not os.path.isdir(work_dir):
        return f"Error: Working directory does not exist: {work_dir}"

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
            command,
            shell=True,
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

        if result.returncode != 0:
            output += f"\n[exit code: {result.returncode}]"

        return output

    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {timeout} seconds"
    except Exception as e:
        return f"Error executing command: {str(e)}"


@mcp.tool(description=FIND_FILES_DESCRIPTION)
def find_files(pattern: str, directory: Optional[str] = None) -> str:
    search_dir = directory or _DEFAULT_CWD

    if not os.path.isabs(search_dir):
        search_dir = os.path.abspath(search_dir)
    if not os.path.isdir(search_dir):
        return f"Error: Directory does not exist: {search_dir}"

    try:
        if os.path.commonpath([os.path.realpath(_DEFAULT_CWD), os.path.realpath(search_dir)]) != os.path.realpath(_DEFAULT_CWD):
            return "Error: find_files is restricted to the current working directory tree."
    except ValueError:
        return "Error: find_files is restricted to the current working directory tree."

    search_pattern = os.path.join(search_dir, pattern)

    try:
        matches = glob.glob(search_pattern, recursive=True)

        if not matches:
            return f"No files found matching '{pattern}' in {search_dir}"

        # Limit output to prevent overwhelming the LLM
        if len(matches) > 200:
            return (
                f"Found {len(matches)} files. Showing first 200:\n"
                + "\n".join(matches[:200])
            )

        return f"Found {len(matches)} file(s):\n" + "\n".join(matches)

    except Exception as e:
        return f"Error searching for files: {str(e)}"


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
