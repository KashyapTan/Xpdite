"""Tests for source/mcp_integration/tool_args.py."""

from source.mcp_integration.tool_args import (
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
    assert should_fallback_to_empty_args("memread") is False


def test_merge_streamed_tool_call_arguments_empty_incoming_keeps_existing():
    merged = merge_streamed_tool_call_arguments('{"folder":"procedural"}', "")
    assert merged == '{"folder":"procedural"}'


def test_merge_streamed_tool_call_arguments_shorter_reset_snapshot_keeps_existing():
    merged = merge_streamed_tool_call_arguments('{"folder":"procedural"}', '{"folder":')
    assert merged == '{"folder":"procedural"}'
