"""Tests for source/mcp_integration/core/tool_output.py."""

from source.mcp_integration.core.tool_output import (
    _fence_language,
    _format_scalar,
    _humanize_key,
    _is_scalar,
    _parse_json_string,
    _render_dict,
    _render_list,
    _render_markdown,
    _render_named_section,
    _scalar_lines,
    format_tool_output,
)


def test_format_tool_output_preserves_images_and_plain_strings():
    image_payload = {"type": "image", "data": "abc"}

    assert format_tool_output(image_payload) is image_payload
    assert format_tool_output("plain text") == "plain text"
    assert format_tool_output(123) == "123"


def test_parse_json_string_rejects_non_json_and_invalid_json():
    assert _parse_json_string("plain text") is None
    assert _parse_json_string("  ") is None
    assert _parse_json_string("{bad json") is None
    assert _parse_json_string('{"ok": true}') == {"ok": True}


def test_render_error_dict_includes_scalar_extras():
    rendered = _render_dict(
        {
            "error": {"code": "bad_request", "message": "Missing argument"},
            "request_id": "req-123",
            "retryable": False,
            "details": {"ignored": True},
        }
    )

    assert rendered == (
        "**Error (`bad_request`):** Missing argument\n\n"
        "- **Request id:** req-123\n"
        "- **Retryable:** No"
    )


def test_render_content_dict_uses_language_fence_and_extra_sections():
    rendered = format_tool_output(
        {
            "chunk_summary": "Showing characters 1-3 of 3",
            "file_format": "py",
            "content": "print('hi')",
            "title": "Example",
            "has_more": False,
            "metadata": {"owner": "alice"},
            "items": ["a", "b"],
        }
    )

    assert "Showing characters 1-3 of 3" in rendered
    assert "- **File format:** py" in rendered
    assert "- **Title:** Example" in rendered
    assert "- **Has more:** No" in rendered
    assert "```py\nprint('hi')\n```" in rendered
    assert "**Metadata:** - **Owner:** alice" in rendered
    assert "**Items:**\n- a\n- b" in rendered


def test_render_markdown_handles_none_bool_and_generic_dict_sections():
    rendered = _render_markdown(
        {
            "job_name": "backup",
            "success": True,
            "details": {"duration_seconds": 5},
            "steps": ["prepare", "run"],
        }
    )

    assert "- **Job name:** backup" in rendered
    assert "- **Success:** Yes" in rendered
    assert "**Details:** - **Duration seconds:** 5" in rendered
    assert "**Steps:**\n- prepare\n- run" in rendered
    assert _render_markdown(None) == "_No data returned._"
    assert _render_markdown(True) == "Yes"
    assert _render_markdown(False) == "No"


def test_render_list_handles_scalar_and_nested_items():
    assert _render_list([]) == "_No items._"
    assert _render_list([1, True, None]) == "- 1\n- Yes\n- _None_"

    rendered = _render_list([{"name": "first"}, {"values": [False, "ok"]}])

    assert rendered == (
        "1. - **Name:** first\n"
        "2. **Values:**\n"
        "   - No\n"
        "   - ok"
    )


def test_named_sections_and_scalar_helpers_cover_edge_cases():
    assert _render_named_section("result_data", "ok") == "**Result data:** ok"
    assert _render_named_section("nested_block", {"answer": 42}) == (
        "**Nested block:** - **Answer:** 42"
    )
    assert _scalar_lines({"job_id": 7, "enabled": True}) == [
        "- **Job id:** 7",
        "- **Enabled:** Yes",
    ]
    assert _format_scalar(None) == "_None_"
    assert _format_scalar(False) == "No"
    assert _is_scalar("text") is True
    assert _is_scalar({"nested": 1}) is False
    assert _humanize_key("next_offset") == "Next offset"
    assert _fence_language(" py ") == "py"
    assert _fence_language("c++") == "c++"
    assert _fence_language("bad language!") == ""
