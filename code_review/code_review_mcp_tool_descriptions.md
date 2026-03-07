# Code Review - MCP Tool Descriptions

Date: 2026-03-07

Scope:
- mcp_servers/CLAUDE_mcp.md
- mcp_servers/servers/description_format.py
- mcp_servers/servers/calendar/calander_descriptions.py
- mcp_servers/servers/filesystem/filesystem_descriptions.py
- mcp_servers/servers/gmail/gmail_descriptions.py
- mcp_servers/servers/terminal/server.py
- mcp_servers/servers/terminal/terminal_descriptions.py
- mcp_servers/servers/websearch/websearch_descriptions.py
- tests/test_mcp_description_format.py
- tests/test_terminal_mcp_server.py

Verdict: READY

## Issues Found

- The first pass removed several important safety notes while making the descriptions more consistent. Those warnings were restored for terminal command approval and blocking, filesystem overwrite behavior, Gmail send irreversibility, Gmail trash recovery, and calendar deletion irreversibility.
- The new terminal `find_files` description said searches were restricted to the current working directory tree, but the server implementation did not enforce that yet. The server now rejects directories outside the default working tree, and a regression test covers that behavior.
- The shared `build_tool_description()` helper improved consistency but initially had no direct test coverage and unclear `notes` handling for `None` vs empty string. A docstring clarification and unit tests were added to lock the format down.

## Fixes Applied

- Added `mcp_servers/servers/description_format.py` and rewrote the active MCP description modules to use one short, consistent structure: `Purpose`, `Use when`, `Inputs`, `Returns`, and optional `Notes`.
- Updated `mcp_servers/CLAUDE_mcp.md` so future MCP tools follow the same literal section prefixes and know when to include `Notes`.
- Restored critical safety and workflow guidance in the affected descriptions without reverting to overly long prose.
- Updated `mcp_servers/servers/terminal/server.py` so `find_files()` matches its LLM-facing contract.
- Added targeted tests for the shared formatter and the new terminal directory restriction.

## Validation

- `uv run python -m py_compile` on the touched Python files passed.
- `uv run python -m pytest tests/ -v` passed.
- `bun run build` passed.
- `bun run lint` still reports pre-existing repository lint issues unrelated to this change.

## Notes

- Industry guidance referenced during the rewrite emphasized clear tool purpose, selection guidance, inputs, returns, and critical caveats for agent use.
- Unrelated documentation changes already present in the working tree were intentionally left untouched and excluded from the task commit.
