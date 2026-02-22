GET_ENVIRONMENT_DESCRIPTION = """
Returns the current working directory, OS, Python version, shell,
and versions of common tools found on PATH (node, npm, git, python, etc.).
Always call this first before running any commands to understand the environment.
NOTE: This tool only returns some basic os and computer info and the python, node, npm, git, pip, uv, cargo, and docker versions.
NOTE: Just because a tool that the user says to use is not listed here does not necessarily mean it is unavailable.
"""

RUN_COMMAND_DESCRIPTION = """
    Run a shell command and return stdout + stderr.
    Note: You are on windows

    Parameters:
    - command: the shell command to run
    - cwd: working directory (absolute path). Defaults to project root.
    - timeout: seconds before force-killing (max 120 for foreground, 1800 for background).
    **IMPORTANT**:
    - pty: set to True for interactive/TUI commands (claudecode, opencode, OpenAI Codex, vim, htop, etc.)
           that need a real terminal. When pty=True the command runs in a
           pseudoterminal and its full TUI renders in the user's terminal panel.
    - background: set to True for long-running commands. Instead of blocking
                  until completion, the command runs in the background and you
                  receive a session_id. Use send_input / read_output / kill_process
                  to interact with it later.
    - yield_ms: when background=True, how long (ms) to wait before returning
                control to you. You'll get whatever output appeared so far plus
                the session_id. Default: 10000 (10 seconds).
    - When running code using file paths: Always wrap file paths in double quotes (e.g., "C:/Users/Name With Space/script.py"). 
      Windows shells split commands at spaces; failing to quote paths containing spaces 
      will cause 'File Not Found' errors.

    Security:
    - Commands touching OS system paths are always blocked regardless of other settings
    - env.PATH overrides are always rejected
    - User approval is handled by the calling layer before this tool is invoked

    Returns the command output (stdout + stderr combined).
    For background commands that are still running, returns a session_id
    and recent output. Use send_input / read_output / kill_process with that session_id.

    Examples:
    - Simple: run_command(command="dir")
    - Interactive TUI: run_command(command="opencode", pty=True, background=True)
    - Long build: run_command(command="npm run build", background=True, yield_ms=30000)
"""

FIND_FILES_DESCRIPTION = """
    Find files matching a glob pattern in a directory.
    Never requires user approval.

    Parameters:
    - pattern: glob pattern (e.g., '*.py', '**/*.ts')
    - directory: directory to search in (defaults to project root)

    Returns a newline-separated list of matching file paths.
"""

REQUEST_SESSION_MODE_DESCRIPTION = """
    Request autonomous operation for a multi-step task.
    Call this when you need to run a sequence of commands without
    per-command interruptions. Describe what you plan to do and
    approximately how many steps are involved.

    Note: This request is routed to the user for approval. The user
    can deny the request, in which case each command will still
    require individual approval.

    Returns: 'approved' or 'denied'
"""

END_SESSION_MODE_DESCRIPTION = """
    Signal that your autonomous task is complete early.
    Session mode auto-expires at the end of each turn, so calling this
    is optional. Use it only if you want to relinquish autonomous
    access before your response is finished (e.g. after encountering
    an error that requires user input).
    Returns: 'session ended'
"""

SEND_INPUT_DESCRIPTION = """
    Send input text to a running background/interactive session.

    Use this to type into interactive CLIs that were started with
    run_command(pty=True, background=True).

    Parameters:
    - session_id: the session ID returned by run_command when background=True
    - input_text: the text to send. Just type naturally — Enter is pressed
                  automatically unless press_enter=False.
                  For control characters: use \\x03 for Ctrl-C, \\x1b for Escape.
    - press_enter: (default True) automatically press Enter after the input.
                   Set to False for partial input, arrow keys, or control chars.
    - wait_ms: (default 3000) milliseconds to wait after sending before
               returning. The response includes recent output so you can
               see the effect of your input. Increase for slow operations.

    IMPORTANT: After sending input, this tool waits and then returns the
    latest output. You do NOT need to call read_output separately — just
    check the response from send_input to see what happened.

    Returns confirmation and recent output from the session.
"""

READ_OUTPUT_DESCRIPTION = """
    Read recent output from a running background session.

    Returns the latest output (ANSI escape codes stripped for readability).
    The raw output with ANSI codes is simultaneously rendered in the user's
    terminal panel for full TUI display.

    Parameters:
    - session_id: the session ID returned by run_command when background=True
    - lines: number of recent lines to return (default 50)

    Returns the recent output text and session status (running/exited).
"""

KILL_PROCESS_DESCRIPTION = """
    Kill a running background session.

    Terminates the process and cleans up the session.
    Always call this when you're done with an interactive CLI session.

    Parameters:
    - session_id: the session ID returned by run_command when background=True

    Returns confirmation or error message.
"""
