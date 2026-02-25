"""
Default skill definitions for the Skills system.

Each skill maps to an MCP server category and provides behavioral guidance
that gets injected into the system prompt when that category is active.

Seeded into the database on first boot via INSERT OR IGNORE so that
user edits are never overwritten on app update.
"""

DEFAULT_SKILLS = [
    {
        "skill_name": "terminal",
        "display_name": "Terminal",
        "slash_command": "terminal",
        "content": """## Terminal Skill

**Workflow:**
- Always call get_environment first on a new task to understand the OS, shell, and available tools.
- Then ALWAYS call request_session_mode.
- Prefer find_files over run_command for file discovery — it never requires approval.
- After a command fails, read the full output and exit code before retrying.

**Background & PTY sessions:**
- Use pty=True + background=True for interactive TUI tools (vim, htop, opencode, etc.).
- Always call kill_process when done with a PTY session — do not leave sessions open.
- Use send_input after starting a background session; you do not need a separate read_output call.

**Windows specifics:**
- Always wrap file paths in double quotes to handle spaces.
- Use forward slashes or escaped backslashes in paths.

**Security:**
- Do not attempt to override PATH or access OS system directories — these are blocked silently.
- User approval is handled by the calling layer; do not reference it in tool arguments.""",
    },
    {
        "skill_name": "filesystem",
        "display_name": "File System",
        "slash_command": "filesystem",
        "content": """## File System Skill

**Workflow:**
- List directory contents before reading or writing to understand the existing structure.
- Always read a file fully before making edits — partial context leads to errors.
- NEVER write to a file without reading it.
- When writing, preserve the original file encoding and line endings.
- Use move/rename rather than write+delete for file restructuring.

**Safety:**
- Never overwrite files without confirming intent if the content looks user-generated.
- Avoid writing to system directories or paths outside the project root unless explicitly instructed.""",
    },
    {
        "skill_name": "websearch",
        "display_name": "Web Search",
        "slash_command": "websearch",
        "content": """## Web Search Skill

**Workflow:**
- Start with a broad search, then narrow with follow-up queries if results are insufficient.
- Read the full page content for detailed questions — search snippets are often too brief.
- Prefer primary sources (official docs, repos, gov sites) over aggregators.
- If the user provides a URL, fetch it directly rather than searching for it.

**Quality:**
- Summarize findings in your own words — do not reproduce large blocks of source text.
- Note if information may be outdated and suggest the user verify time-sensitive details.""",
    },
    {
        "skill_name": "gmail",
        "display_name": "Gmail",
        "slash_command": "gmail",
        "content": """## Gmail Skill

**Workflow:**
- Search before reading — use search to locate relevant threads, then read specific messages.
- When replying, read the full thread first to maintain context and avoid duplication.
- Confirm recipient, subject, and body with the user before sending any email.
- Use labels to organize rather than deleting unless the user explicitly asks to delete.

**Tone:**
- Match the formality of the existing thread when drafting replies.
- Flag if an email contains sensitive content before summarizing it.""",
    },
    {
        "skill_name": "calendar",
        "display_name": "Calendar",
        "slash_command": "calendar",
        "content": """## Calendar Skill

**Workflow:**
- Check free/busy before proposing or creating events to avoid conflicts.
- Always confirm timezone with the user for events involving other people.
- When listing events, show the most relevant time window — default to the next 7 days unless asked otherwise.
- Confirm all event details (title, time, attendees, location) before creating or modifying.""",
    },
]
