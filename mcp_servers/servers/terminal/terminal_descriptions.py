from mcp_servers.servers.description_format import build_tool_description


GET_ENVIRONMENT_DESCRIPTION = build_tool_description(
    purpose="Report the current OS, shell, working directory, and versions of common CLI tools.",
    use_when=(
        "You need to understand the runtime before planning terminal work or "
        "checking whether a common tool is installed."
    ),
    inputs="None.",
    returns=(
        "A text summary with OS, Python version, shell, CWD, and detected "
        "versions for common tools on PATH such as python, node, npm, git, "
        "pip, uv, cargo, docker, and java."
    ),
    notes=(
        "Call this first when environment details matter. A tool can still "
        "exist even if it is not listed here."
    ),
)

RUN_COMMAND_DESCRIPTION = build_tool_description(
    purpose="Run a shell command and return combined stdout and stderr.",
    use_when=(
        "You need to execute a CLI command, script, build step, or one-off shell task."
    ),
    inputs=(
        "command, cwd (optional absolute path), timeout seconds (optional), "
        "pty (optional for interactive TUIs), background (optional for PTY "
        "sessions that should keep running), yield_ms (optional wait before "
        "returning from a background PTY session)."
    ),
    returns=(
        "Foreground calls return command output. Background PTY calls return a "
        "session_id plus recent output so you can continue with send_input, "
        "read_output, or kill_process."
    ),
    notes=(
        "Use pty=True for interactive CLIs. background is useful with PTY "
        "sessions. Quote Windows paths that contain spaces. Security: commands "
        "touching OS system paths are always blocked, PATH overrides are "
        "rejected, and user approval is required before execution."
    ),
)

FIND_FILES_DESCRIPTION = build_tool_description(
    purpose="Find files that match a glob pattern under the current working directory tree.",
    use_when=(
        "You need to discover candidate files before opening, editing, or running commands on them."
    ),
    inputs="pattern (for example *.py or **/*.ts) and directory (optional, must stay inside the current working directory tree).",
    returns="A text list of matching file paths, capped at the first 200 matches.",
    notes="Use this for file discovery only. It does not read file contents and does not require user approval.",
)

REQUEST_SESSION_MODE_DESCRIPTION = build_tool_description(
    purpose="Ask the user for temporary autonomous approval for a multi-step terminal task.",
    use_when=(
        "You expect to run several related commands and stopping for approval on each command would be noisy."
    ),
    inputs="reason = a short explanation of the planned batch of work.",
    returns="A status string indicating whether session mode was approved.",
)

END_SESSION_MODE_DESCRIPTION = build_tool_description(
    purpose="End an approved terminal session early.",
    use_when=(
        "You are done with the batch of commands or need to return control before the turn ends."
    ),
    inputs="None.",
    returns="A status string confirming the session ended.",
    notes="Session mode also expires automatically at the end of the turn.",
)

SEND_INPUT_DESCRIPTION = build_tool_description(
    purpose="Send text or control input to a running PTY background session.",
    use_when=(
        "run_command returned a session_id for an interactive CLI that needs more input."
    ),
    inputs=(
        "session_id, input_text, press_enter (default True), wait_ms (default 3000). "
        "Use escapes like \\x03 for Ctrl-C when needed."
    ),
    returns="A status message plus recent session output after the input is processed.",
    notes="After this call you usually do not need read_output immediately because recent output is already included.",
)

READ_OUTPUT_DESCRIPTION = build_tool_description(
    purpose="Read the latest buffered output from a PTY background session.",
    use_when=(
        "You need another snapshot from a running or recently finished interactive session without sending input."
    ),
    inputs="session_id, lines (default 50).",
    returns="A status header plus recent output with ANSI escape codes stripped for readability.",
    notes="If the session has already exited, the response tells you not to call read_output or kill_process again.",
)

KILL_PROCESS_DESCRIPTION = build_tool_description(
    purpose="Terminate a running PTY background session by session_id.",
    use_when=(
        "The interactive command is no longer needed, is hung, or should be stopped."
    ),
    inputs="session_id.",
    returns="A confirmation string or an error string.",
    notes="Use this to clean up background interactive sessions when you are done.",
)
