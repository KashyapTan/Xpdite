"""Tests for _build_gemini_contents in source/llm/cloud_provider.py.

Validates that chat history → Gemini Content conversion handles:
- Plain user/assistant messages
- Assistant messages with tool_calls → FunctionCall + FunctionResponse parts
- User messages with images
- Tool role messages (transient) are skipped
"""

import pytest
from google.genai import types


class TestBuildGeminiContents:
    """Unit tests for the Gemini content builder."""

    @staticmethod
    def _build(chat_history, user_query="hello", image_paths=None):
        from source.llm.cloud_provider import _build_gemini_contents
        return _build_gemini_contents(chat_history, user_query, image_paths or [])

    def test_plain_user_assistant_roundtrip(self):
        history = [
            {"role": "user", "content": "What is 2+2?"},
            {"role": "assistant", "content": "4"},
        ]
        contents = self._build(history, "next question")

        assert len(contents) == 3  # 2 history + 1 current query
        assert contents[0].role == "user"
        assert contents[0].parts[0].text == "What is 2+2?"
        assert contents[1].role == "model"
        assert contents[1].parts[0].text == "4"
        assert contents[2].role == "user"
        assert contents[2].parts[0].text == "next question"

    def test_assistant_with_tool_calls_produces_function_call_and_response(self):
        """Tool amnesia fix: assistant tool_calls must become FunctionCall +
        FunctionResponse parts so Gemini retains memory of past tool use."""
        history = [
            {"role": "user", "content": "Search for cats"},
            {
                "role": "assistant",
                "content": "Let me search.",
                "tool_calls": [
                    {
                        "name": "web_search",
                        "args": {"query": "cats"},
                        "result": "Cats are great.",
                        "server": "websearch",
                    }
                ],
            },
        ]
        contents = self._build(history, "thanks")

        # history[0] → user, history[1] → model (FunctionCall) + user (FunctionResponse), current → user
        assert len(contents) == 4

        # Model turn should have text + function_call
        model_content = contents[1]
        assert model_content.role == "model"
        assert len(model_content.parts) == 2
        assert model_content.parts[0].text == "Let me search."
        fc = model_content.parts[1].function_call
        assert fc.name == "web_search"
        assert dict(fc.args) == {"query": "cats"}

        # Function response turn
        fr_content = contents[2]
        assert fr_content.role == "user"
        assert len(fr_content.parts) == 1
        fr = fr_content.parts[0].function_response
        assert fr.name == "web_search"
        assert fr.response == {"result": "Cats are great."}

    def test_assistant_with_multiple_tool_calls(self):
        history = [
            {"role": "user", "content": "Do two things"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"name": "tool_a", "args": {"x": 1}, "result": "res_a", "server": "s"},
                    {"name": "tool_b", "args": {"y": 2}, "result": "res_b", "server": "s"},
                ],
            },
        ]
        contents = self._build(history, "ok")

        model_content = contents[1]
        assert model_content.role == "model"
        # Empty content → no text part, only 2 FunctionCall parts
        assert len(model_content.parts) == 2
        assert model_content.parts[0].function_call.name == "tool_a"
        assert model_content.parts[1].function_call.name == "tool_b"

        fr_content = contents[2]
        assert fr_content.role == "user"
        assert len(fr_content.parts) == 2
        assert fr_content.parts[0].function_response.name == "tool_a"
        assert fr_content.parts[1].function_response.name == "tool_b"

    def test_tool_role_messages_are_skipped(self):
        """Transient tool messages should be ignored."""
        history = [
            {"role": "user", "content": "hi"},
            {"role": "tool", "content": "some result", "name": "fn"},
            {"role": "assistant", "content": "done"},
        ]
        contents = self._build(history, "bye")

        assert len(contents) == 3  # user, model, current user
        roles = [c.role for c in contents]
        assert roles == ["user", "model", "user"]

    def test_assistant_with_empty_tool_calls_list(self):
        """Empty tool_calls list should be treated as plain assistant text."""
        history = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "just text", "tool_calls": []},
        ]
        contents = self._build(history, "ok")

        assert len(contents) == 3
        # Should be a plain model text (no FunctionCall/FunctionResponse)
        model_content = contents[1]
        assert model_content.role == "model"
        assert len(model_content.parts) == 1
        assert model_content.parts[0].text == "just text"

    def test_missing_args_and_result_default_safely(self):
        """tool_calls entries with missing args/result should use defaults."""
        history = [
            {"role": "user", "content": "go"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"name": "simple_tool", "server": "s"}],
            },
        ]
        contents = self._build(history, "done")

        model_content = contents[1]
        fc = model_content.parts[0].function_call
        assert fc.name == "simple_tool"
        assert dict(fc.args) == {}

        fr_content = contents[2]
        fr = fr_content.parts[0].function_response
        assert fr.response == {"result": ""}
