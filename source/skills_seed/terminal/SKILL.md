---
name: terminal
description: Guidance for terminal command execution, PTY sessions, and environment detection.
trigger-servers: terminal
---

# Terminal Skill

## Workflow
- Always call get_environment first on a new task to understand the OS, shell, and available tools.
- Then ALWAYS call request_session_mode.
- Prefer the filesystem server's `glob_files` and `grep_files` for file discovery and file-content search.
- Do not use `run_command` for `find`, `grep`, `rg`, `ag`, or shell globbing unless the task genuinely needs shell-only behavior the filesystem tools cannot provide.
- Set `shell="powershell"` when you need PowerShell syntax and `shell="bash"` / `shell="sh"` when you need POSIX shell syntax. Leave it as auto only for straightforward native-shell commands.
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
- Obfuscated or high-risk execution patterns such as encoded PowerShell payloads, `Invoke-Expression`, `eval`, or download-to-shell pipelines are blocked.
- User approval is handled by the calling layer; do not reference it in tool arguments.
