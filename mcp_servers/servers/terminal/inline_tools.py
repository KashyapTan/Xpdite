from typing import Any

from mcp_servers.servers.terminal.terminal_descriptions import (
    END_SESSION_MODE_DESCRIPTION,
    FIND_FILES_DESCRIPTION,
    GET_ENVIRONMENT_DESCRIPTION,
    KILL_PROCESS_DESCRIPTION,
    READ_OUTPUT_DESCRIPTION,
    REQUEST_SESSION_MODE_DESCRIPTION,
    RUN_COMMAND_DESCRIPTION,
    SEND_INPUT_DESCRIPTION,
)


def _build_tool_definition(
    name: str, description: str, parameters: dict[str, Any]
) -> dict[str, Any]:
    return {
        "name": name,
        "description": description.strip(),
        "parameters": parameters,
    }


TERMINAL_INLINE_TOOLS: list[dict[str, Any]] = [
    _build_tool_definition(
        "get_environment",
        GET_ENVIRONMENT_DESCRIPTION,
        {"type": "object", "properties": {}},
    ),
    _build_tool_definition(
        "run_command",
        RUN_COMMAND_DESCRIPTION,
        {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command to execute",
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory (absolute path)",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Seconds before force-killing (max 120 foreground, 1800 background)",
                    "default": 120,
                },
                "pty": {
                    "type": "boolean",
                    "description": "Use PTY for interactive/TUI commands",
                    "default": False,
                },
                "background": {
                    "type": "boolean",
                    "description": "Run in background, return session_id",
                    "default": False,
                },
                "yield_ms": {
                    "type": "integer",
                    "description": "Ms to wait before returning for background processes",
                    "default": 10000,
                },
            },
            "required": ["command"],
        },
    ),
    _build_tool_definition(
        "find_files",
        FIND_FILES_DESCRIPTION,
        {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern (e.g. '*.py', '**/*.ts')",
                },
                "directory": {
                    "type": "string",
                    "description": "Directory to search in",
                },
            },
            "required": ["pattern"],
        },
    ),
    _build_tool_definition(
        "request_session_mode",
        REQUEST_SESSION_MODE_DESCRIPTION,
        {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Why you need autonomous operation",
                }
            },
            "required": ["reason"],
        },
    ),
    _build_tool_definition(
        "end_session_mode",
        END_SESSION_MODE_DESCRIPTION,
        {"type": "object", "properties": {}},
    ),
    _build_tool_definition(
        "send_input",
        SEND_INPUT_DESCRIPTION,
        {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Session ID from run_command",
                },
                "input_text": {
                    "type": "string",
                    "description": "Text to send to the session",
                },
                "press_enter": {
                    "type": "boolean",
                    "description": "Auto-press Enter after input",
                    "default": True,
                },
                "wait_ms": {
                    "type": "integer",
                    "description": "Ms to wait after sending before returning output",
                    "default": 3000,
                },
            },
            "required": ["session_id", "input_text"],
        },
    ),
    _build_tool_definition(
        "read_output",
        READ_OUTPUT_DESCRIPTION,
        {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Session ID from run_command",
                },
                "lines": {
                    "type": "integer",
                    "description": "Number of recent lines to return",
                    "default": 50,
                },
            },
            "required": ["session_id"],
        },
    ),
    _build_tool_definition(
        "kill_process",
        KILL_PROCESS_DESCRIPTION,
        {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Session ID from run_command",
                }
            },
            "required": ["session_id"],
        },
    ),
]