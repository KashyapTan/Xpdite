"""Tests for source/llm/types.py."""

from typing import get_args, get_origin

from source.llm.types import ChatResult


class TestLlmTypes:
    def test_chat_result_type_alias_shape(self):
        origin = get_origin(ChatResult)
        args = get_args(ChatResult)

        assert origin is tuple
        assert len(args) == 4

    def test_chat_result_allows_expected_payload(self):
        payload: ChatResult = (
            "assistant response",
            {"prompt_eval_count": 12, "eval_count": 34},
            [{"name": "tool.run", "args": {"x": 1}}],
            [{"type": "text", "content": "hello"}],
        )

        assert payload[0] == "assistant response"
        assert payload[1]["eval_count"] == 34
        assert payload[2][0]["name"] == "tool.run"

