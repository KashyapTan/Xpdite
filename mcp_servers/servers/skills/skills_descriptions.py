from mcp_servers.servers.description_format import build_tool_description


LIST_SKILLS_DESCRIPTION = build_tool_description(
    purpose=(
        "List the available skills and short summaries so you can discover "
        "specialized guidance before solving a task."
    ),
    use_when=(
        "You need to decide which capability-specific instructions to load, "
        "especially before multi-step work that may involve terminal, filesystem, "
        "web search, email, or calendar workflows."
    ),
    inputs="None.",
    returns=(
        "A collection of available skill names with concise descriptions that "
        "helps you choose the most relevant next skill to load."
    ),
    notes=(
        "Call this before use_skill when you are unsure which skill applies. "
        "If a matching skill exists, load it instead of guessing a workflow."
    ),
)

USE_SKILL_DESCRIPTION = build_tool_description(
    purpose=(
        "Load the full instruction content for one named skill so you can follow "
        "its recommended workflow and constraints."
    ),
    use_when=(
        "You already know the skill name, typically after list_skills, and need "
        "the detailed guidance for that capability."
    ),
    inputs="skill_name (string, required).",
    returns=(
        "The complete skill content for the requested skill, including structured "
        "best practices and tool-usage patterns."
    ),
    notes=(
        "Pass an exact skill name from list_skills for the most reliable result. "
        "If the name is unknown, call list_skills again and pick from that output."
    ),
)
