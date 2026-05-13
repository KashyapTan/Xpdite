from types import SimpleNamespace

from source.llm.core.token_usage import (
    build_prompt_cache_key,
    merge_token_stats,
    usage_from_litellm_chat_usage,
    usage_from_litellm_responses_usage,
    usage_from_ollama_response,
)


def test_openai_cached_tokens_are_metadata_not_added_to_prompt_total():
    usage = SimpleNamespace(
        prompt_tokens=1200,
        completion_tokens=80,
        prompt_tokens_details=SimpleNamespace(cached_tokens=768),
    )

    stats = usage_from_litellm_chat_usage(usage)

    assert stats == {
        "prompt_eval_count": 1200,
        "eval_count": 80,
        "cached_tokens": 768,
    }


def test_anthropic_cache_read_and_write_tokens_are_metadata_not_added_to_prompt_total():
    usage = {
        "prompt_tokens": 300,
        "completion_tokens": 60,
        "cache_read_input_tokens": 700,
        "cache_creation_input_tokens": 200,
    }

    stats = usage_from_litellm_chat_usage(usage)

    assert stats == {
        "prompt_eval_count": 300,
        "eval_count": 60,
        "cached_tokens": 700,
        "cache_write_tokens": 200,
    }


def test_responses_usage_reads_cached_input_details():
    usage = {
        "input_tokens": 900,
        "output_tokens": 45,
        "input_tokens_details": {"cached_tokens": 512},
    }

    stats = usage_from_litellm_responses_usage(usage)

    assert stats == {
        "prompt_eval_count": 900,
        "eval_count": 45,
        "cached_tokens": 512,
    }


def test_gemini_cached_content_token_count_is_reported_when_available():
    usage = {
        "prompt_tokens": 1000,
        "completion_tokens": 75,
        "cached_content_token_count": 256,
    }

    stats = usage_from_litellm_chat_usage(usage)

    assert stats == {
        "prompt_eval_count": 1000,
        "eval_count": 75,
        "cached_tokens": 256,
    }


def test_ollama_usage_does_not_invent_cache_metrics():
    stats = usage_from_ollama_response(
        {"prompt_eval_count": 50, "eval_count": 20}
    )

    assert stats == {"prompt_eval_count": 50, "eval_count": 20}


def test_merge_token_stats_preserves_reported_zero_cache_fields():
    merged = merge_token_stats(
        {"prompt_eval_count": 10, "eval_count": 5, "cached_tokens": 0},
        {"prompt_eval_count": 3, "eval_count": 2, "cached_tokens": 4},
    )

    assert merged == {
        "prompt_eval_count": 13,
        "eval_count": 7,
        "cached_tokens": 4,
    }


def test_prompt_cache_key_hashes_prompt_and_tools_without_raw_content():
    key = build_prompt_cache_key(
        "openai",
        "gpt-4.1",
        system_prompt="secret stable prompt",
        tools=[{"function": {"name": "read_file"}}],
    )

    assert key.startswith("xpdite-openai-gpt-4.1-")
    assert "secret" not in key
    assert "read_file" not in key
