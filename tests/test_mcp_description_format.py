from mcp_servers.servers.description_format import build_tool_description


def test_build_tool_description_omits_notes_when_none():
    result = build_tool_description(
        purpose="Do a task.",
        use_when="The user asks for it.",
        inputs="name, count.",
        returns="A JSON object.",
    )

    assert result == (
        "Purpose: Do a task.\n"
        "Use when: The user asks for it.\n"
        "Inputs: name, count.\n"
        "Returns: A JSON object."
    )


def test_build_tool_description_includes_notes_when_provided():
    result = build_tool_description(
        purpose="Do a task.",
        use_when="The user asks for it.",
        inputs="name, count.",
        returns="A JSON object.",
        notes="Confirm before running.",
    )

    assert result == (
        "Purpose: Do a task.\n"
        "Use when: The user asks for it.\n"
        "Inputs: name, count.\n"
        "Returns: A JSON object.\n"
        "Notes: Confirm before running."
    )


def test_build_tool_description_keeps_explicit_empty_notes():
    result = build_tool_description(
        purpose="Do a task.",
        use_when="The user asks for it.",
        inputs="name, count.",
        returns="A JSON object.",
        notes="",
    )

    assert result.endswith("\nNotes: ")
