from mcp_servers.servers.description_format import build_inline_tool_definition
from mcp_servers.servers.memory.inline_tools import MEMORY_INLINE_TOOLS
from mcp_servers.servers.scheduler.inline_tools import SCHEDULER_INLINE_TOOLS
from mcp_servers.servers.skills.inline_tools import SKILLS_INLINE_TOOLS


def test_build_inline_tool_definition_trims_description():
    tool = build_inline_tool_definition(
        "demo",
        "  Example description.  ",
        {"type": "object", "properties": {}},
    )

    assert tool == {
        "name": "demo",
        "description": "Example description.",
        "parameters": {"type": "object", "properties": {}},
    }


def test_memory_inline_tool_schema_matches_expected_shape():
    assert [tool["name"] for tool in MEMORY_INLINE_TOOLS] == [
        "memlist",
        "memread",
        "memcommit",
    ]

    memcommit = next(tool for tool in MEMORY_INLINE_TOOLS if tool["name"] == "memcommit")
    assert memcommit["parameters"]["required"] == [
        "path",
        "title",
        "category",
        "importance",
        "tags",
        "abstract",
        "body",
    ]


def test_scheduler_inline_tools_cover_job_lifecycle():
    assert [tool["name"] for tool in SCHEDULER_INLINE_TOOLS] == [
        "create_job",
        "list_jobs",
        "delete_job",
        "pause_job",
        "resume_job",
        "run_job_now",
    ]

    create_job = SCHEDULER_INLINE_TOOLS[0]
    assert create_job["parameters"]["required"] == [
        "name",
        "cron_expression",
        "instruction",
        "timezone",
    ]
    assert (
        create_job["parameters"]["properties"]["is_one_shot"]["default"] is False
    )


def test_skills_inline_tools_require_skill_name_for_use_skill():
    assert [tool["name"] for tool in SKILLS_INLINE_TOOLS] == [
        "list_skills",
        "use_skill",
    ]

    use_skill = SKILLS_INLINE_TOOLS[1]
    assert use_skill["parameters"]["required"] == ["skill_name"]
