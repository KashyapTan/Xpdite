"""Tests for source/mcp_integration/tool_args.py."""

from source.mcp_integration.tool_args import normalize_tool_args


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

