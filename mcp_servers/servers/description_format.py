def build_tool_description(
    *,
    purpose: str,
    use_when: str,
    inputs: str,
    returns: str,
    notes: str | None = None,
) -> str:
    """Build a consistent MCP tool description string.

    Pass notes=None to omit the Notes section.
    """
    sections = [
        f"Purpose: {purpose}",
        f"Use when: {use_when}",
        f"Inputs: {inputs}",
        f"Returns: {returns}",
    ]
    if notes is not None:
        sections.append(f"Notes: {notes}")
    return "\n".join(sections)
