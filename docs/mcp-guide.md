# MCP Guide

This guide explains how Xpdite integrates with the Model Context Protocol (MCP).

## MCP in Xpdite

Xpdite uses MCP to expose external capabilities (filesystem, web, integrations) to models.

Execution modes:

- **Subprocess MCP servers** over stdio (JSON-RPC)
- **Inline tools** executed directly inside backend tool loops

## Tool Retrieval

Xpdite does not send every tool on every request by default.

- Semantic retrieval ranks candidate tools per query.
- Configurable `top_k` controls retrieval breadth.
- `always_on` tools are forcibly included.

Configuration endpoints:

- `GET /api/settings/tools`
- `PUT /api/settings/tools`

## Current Tool Topology

### Subprocess Servers

Configured in `source/mcp_integration/core/manager.py`.

- `filesystem`
- `glob`
- `grep`
- `websearch`
- `windows_mcp`
- optional auth-driven servers such as `gmail` and `calendar`

### Inline Tool Servers

Registered in-process and intercepted in provider loops.

- `terminal`
- `sub_agent`
- `video_watcher`
- `skills`
- `memory`
- `scheduler`

## Provider Execution Behavior

### Ollama Path

- Performs a detection pass for potential tool calls.
- Runs tool rounds up to `MAX_MCP_TOOL_ROUNDS`.
- Streams follow-up tokens between tool calls.

### API-key Cloud Path

- Streams via LiteLLM provider integration.
- Executes tool calls when emitted.
- Continues iterative text/tool/text rounds until completion.

### ChatGPT Subscription Path

- Streams through the bundled Codex app-server using an isolated ephemeral thread.
- Registers only the semantically retrieved Xpdite tools as per-turn dynamic tools.
- Routes server-initiated tool calls through the same shared `XpditeToolExecutor` used by API-key cloud providers.
- Rejects unregistered names through a private per-turn alias map and fails closed if Codex attempts a shell, file, web, or other built-in tool outside Xpdite's allowlist.
- Does not retry a turn after a tool may have produced an external side effect.

## Add a New Subprocess MCP Server

1. Create `mcp_servers/servers/<name>/server.py` with MCP tool definitions.
2. Register connection in `init_mcp_servers()` (`source/mcp_integration/core/manager.py`).
3. Restart app and verify server appears in `GET /api/mcp/servers`.
4. Add/adjust tests in `tests/test_mcp_manager.py` and related integration tests.

Minimal pattern:

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("my_server")

@mcp.tool()
def my_tool(arg: str) -> str:
    return f"ok: {arg}"

if __name__ == "__main__":
    mcp.run()
```

## Add a New Inline Tool

1. Define tool schemas in `mcp_servers/servers/<server>/inline_tools.py`.
2. Register with `register_inline_tools(...)` in MCP manager init.
3. Add execution interception in:
   - `source/mcp_integration/core/handlers.py` (Ollama path)
   - `source/llm/core/tool_executor.py` (API-key cloud and ChatGPT subscription paths)
4. Implement execution logic in backend services/executors.
5. Add tests for definition and execution flow.

## Reliability and Safety Guidelines

- Time-bound external tool calls where appropriate.
- Sanitize and truncate large tool outputs.
- Emit structured tool call lifecycle events to renderer.
- Keep inline and subprocess behavior consistent across provider paths.

## Troubleshooting

- If tools are missing, verify server connection and `/api/mcp/servers` output.
- If a tool never triggers, inspect retrieval settings (`always_on`, `top_k`).
- If a new inline tool works only for one provider, check both interception paths.

## Related Docs

- `docs/api-reference.md`
- `docs/development.md`
- `mcp_servers/CLAUDE_mcp.md`
