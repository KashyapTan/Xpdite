---
name: terminal
description: Guidance for terminal command execution, PTY sessions, and environment detection.
trigger-servers: terminal
---

# Terminal Skill

## Workflow
- Always call get_environment first on a new task to understand the OS, shell, and available tools.
- Then ALWAYS call request_session_mode.
- Prefer find_files over run_command for file discovery — it never requires approval.
- After a command fails, read the full output and exit code before retrying.

## Background & PTY sessions
- Use pty=True + background=True for interactive TUI tools (vim, htop, opencode, etc.).
- Always call kill_process when done with a PTY session — do not leave sessions open.
- Use send_input after starting a background session; you do not need a separate read_output call.

## Windows specifics
- Always wrap file paths in double quotes to handle spaces.
- Use forward slashes or escaped backslashes in paths.

## Security
- Do not attempt to override PATH or access OS system directories — these are blocked silently.
- User approval is handled by the calling layer; do not reference it in tool arguments.
