"""Tests for source/mcp_integration/tool_args.py."""

from source.mcp_integration.tool_args import (
    format_tool_arg_error,
    merge_streamed_tool_call_arguments,
    normalize_tool_args,
    should_fallback_to_empty_args,
)


def test_normalize_tool_args_dict():
    args, error = normalize_tool_args({"a": 1})
    assert args == {"a": 1}
    assert error is None


def test_normalize_tool_args_none():
    args, error = normalize_tool_args(None)
    assert args == {}
    assert error is None


def test_normalize_tool_args_valid_json_string():
    args, error = normalize_tool_args('{"x": "y"}')
    assert args == {"x": "y"}
    assert error is None


def test_normalize_tool_args_empty_string():
    args, error = normalize_tool_args("   ")
    assert args == {}
    assert error is None


def test_normalize_tool_args_invalid_json_string():
    args, error = normalize_tool_args("{bad json")
    assert args == {}
    assert error is not None
    assert "invalid JSON arguments" in error


def test_normalize_tool_args_json_array_rejected():
    args, error = normalize_tool_args("[1,2,3]")
    assert args == {}
    assert error is not None
    assert "JSON object" in error


def test_normalize_tool_args_unsupported_type():
    args, error = normalize_tool_args(123)
    assert args == {}
    assert error is not None
    assert "unsupported argument type" in error


# ============================================================================
# JSON Repair Tests - Trailing garbage after valid JSON
# ============================================================================


def test_normalize_tool_args_repairs_trailing_text():
    """Ollama models often emit extra text after the JSON object."""
    args, error = normalize_tool_args(
        '{"url": "https://example.com"}\n\nHere is the result...'
    )
    assert args == {"url": "https://example.com"}
    assert error is None


def test_normalize_tool_args_repairs_trailing_garbage():
    """Models may emit garbage characters after the JSON."""
    args, error = normalize_tool_args('{"query": "search term"} some random text')
    assert args == {"query": "search term"}
    assert error is None


def test_normalize_tool_args_repairs_trailing_newlines():
    """Trailing newlines should be handled."""
    args, error = normalize_tool_args('{"path": "/file.txt"}\n\n\n')
    assert args == {"path": "/file.txt"}
    assert error is None


def test_normalize_tool_args_repairs_nested_json_trailing():
    """Nested JSON with trailing text."""
    args, error = normalize_tool_args('{"config": {"key": "value"}}extra')
    assert args == {"config": {"key": "value"}}
    assert error is None


# ============================================================================
# JSON Repair Tests - Truncated JSON
# ============================================================================


def test_normalize_tool_args_repairs_truncated_simple():
    """Truncated JSON with missing closing brace."""
    args, error = normalize_tool_args('{"instruction": "do something"')
    assert args == {"instruction": "do something"}
    assert error is None


def test_normalize_tool_args_repairs_truncated_nested():
    """Truncated nested JSON."""
    args, error = normalize_tool_args('{"outer": {"inner": "value"}')
    assert args == {"outer": {"inner": "value"}}
    assert error is None


def test_normalize_tool_args_repairs_truncated_array():
    """Truncated JSON with array inside."""
    args, error = normalize_tool_args('{"items": [1, 2, 3]')
    assert args == {"items": [1, 2, 3]}
    assert error is None


def test_normalize_tool_args_repairs_truncated_string():
    """Truncated JSON with unclosed string."""
    args, error = normalize_tool_args('{"text": "hello world')
    assert args == {"text": "hello world"}
    assert error is None


# ============================================================================
# JSON Repair Tests - Leading garbage
# ============================================================================


def test_normalize_tool_args_repairs_leading_text():
    """Some models emit text before the JSON object."""
    args, error = normalize_tool_args('Here are the arguments: {"param": "value"}')
    assert args == {"param": "value"}
    assert error is None


def test_normalize_tool_args_repairs_leading_and_trailing():
    """Both leading and trailing garbage."""
    args, error = normalize_tool_args('Arguments: {"x": 1} Done!')
    assert args == {"x": 1}
    assert error is None


# ============================================================================
# JSON Repair Tests - Control characters
# ============================================================================


def test_normalize_tool_args_repairs_control_chars():
    """Control characters in JSON should be removed."""
    # Contains ASCII control characters that break JSON parsing
    raw = '{"path": "test.txt\x00\x01"}'
    args, error = normalize_tool_args(raw)
    # Should either parse successfully or repair
    # The control chars are removed, so this should parse
    assert error is None or "path" in args


# ============================================================================
# Merge Streaming Arguments Tests
# ============================================================================


def test_merge_streamed_tool_call_arguments_incremental_append():
    merged = merge_streamed_tool_call_arguments('{"path":', ' "x.md"}')
    assert merged == '{"path": "x.md"}'


def test_merge_streamed_tool_call_arguments_cumulative_replace():
    merged = merge_streamed_tool_call_arguments('{"folder":', '{"folder":"projects"}')
    assert merged == '{"folder":"projects"}'


def test_merge_streamed_tool_call_arguments_duplicate_chunk_not_duplicated():
    merged = merge_streamed_tool_call_arguments('{"folder":"projects"}', '"}')
    assert merged == '{"folder":"projects"}'


def test_should_fallback_to_empty_args_for_safe_tools():
    assert should_fallback_to_empty_args("memlist") is True
    assert should_fallback_to_empty_args("list_skills") is True
    assert should_fallback_to_empty_args("get_environment") is True
    assert should_fallback_to_empty_args("end_session_mode") is True
    assert should_fallback_to_empty_args("memread") is False


def test_merge_streamed_tool_call_arguments_empty_incoming_keeps_existing():
    merged = merge_streamed_tool_call_arguments('{"folder":"procedural"}', "")
    assert merged == '{"folder":"procedural"}'


def test_merge_streamed_tool_call_arguments_shorter_reset_snapshot_keeps_existing():
    merged = merge_streamed_tool_call_arguments('{"folder":"procedural"}', '{"folder":')
    assert merged == '{"folder":"procedural"}'


# ============================================================================
# Error Message Formatting Tests
# ============================================================================


def test_format_tool_arg_error_without_schema():
    """Error message without schema just includes the error."""
    result = format_tool_arg_error("read_file", "invalid JSON", None)
    assert "read_file" in result
    assert "invalid JSON" in result


def test_format_tool_arg_error_with_schema():
    """Error message with schema includes parameter hints."""
    schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path to read"},
            "encoding": {"type": "string", "description": "File encoding"},
        },
        "required": ["path"],
    }
    result = format_tool_arg_error("read_file", "missing required parameter", schema)
    assert "read_file" in result
    assert "path" in result
    assert "required" in result.lower()
    assert "encoding" in result
    assert "optional" in result.lower()


def test_format_tool_arg_error_empty_schema():
    """Error message with empty schema properties."""
    schema = {"type": "object", "properties": {}}
    result = format_tool_arg_error("list_all", "parse error", schema)
    assert "list_all" in result
    assert "parse error" in result
    # Should not include "Expected parameters" section
    assert "Expected parameters" not in result
