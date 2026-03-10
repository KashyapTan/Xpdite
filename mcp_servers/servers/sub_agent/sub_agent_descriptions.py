from mcp_servers.servers.description_format import build_tool_description


SPAWN_AGENT_DESCRIPTION = build_tool_description(
    purpose="Delegate a focused, self-contained task to an independent sub-agent LLM call.",
    use_when=(
        "You need to parallelize work, offload context-heavy tasks, or trigger "
        "post-work review without polluting the main context window."
    ),
    inputs=(
        "instruction (required string — fully self-contained task description with all context), "
        "model_tier (optional: 'fast'|'smart'|'self', default 'fast'), "
        "agent_name (optional string for display)"
    ),
    returns="The sub-agent's complete response as a string.",
    notes=(
        "Sub-agents have no access to conversation history — include all relevant "
        "context in the instruction. Default to 'fast' for informational tasks. "
        "Use 'smart' for analysis/review. Use 'self' sparingly (most expensive). "
        "Emit multiple spawn_agent calls in a single turn to run tasks in parallel. "
        "Sub-agents cannot run terminal commands or spawn further sub-agents."
    ),
)