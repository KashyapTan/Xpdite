from mcp_servers.servers.description_format import build_tool_description


SPAWN_AGENT_DESCRIPTION = build_tool_description(
    purpose=(
        "Launch an independent sub-agent LLM call for a focused, self-contained "
        "task. Calling this function is the only way to create a sub-agent."
    ),
    use_when=(
        "You need to parallelize work, offload context-heavy tasks, or trigger "
        "post-work review without polluting the main context window. If you tell "
        "the user you are launching or spinning up sub-agents, call this tool in "
        "the same assistant turn."
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
        "Emit multiple spawn_agent function calls in a single turn to run tasks "
        "in parallel; do not just describe that you will launch them. "
        "Sub-agents cannot run terminal commands or spawn further sub-agents."
    ),
)
