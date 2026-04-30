from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


def test_extract_ollama_native_context_uses_context_length_keys():
    from source.llm.core.model_context import _extract_ollama_native_context

    assert (
        _extract_ollama_native_context(
            {
                "general.architecture": "qwen2",
                "qwen2.context_length": 32768,
                "qwen2.embedding_length": 4096,
            }
        )
        == 32768
    )


def test_effective_ollama_context_uses_configured_num_ctx_cap():
    from source.llm.core.model_context import _effective_ollama_context_window

    context_window, source = _effective_ollama_context_window(
        native_context=131072,
        model_num_ctx=8192,
        configured_num_ctx=32768,
    )

    assert context_window == 32768
    assert source == "ollama_show+configured_num_ctx"


@pytest.mark.asyncio
async def test_resolve_ollama_context_window_reads_show_metadata():
    response = SimpleNamespace(
        modelinfo={"gemma3.context_length": 131072},
        parameters="temperature 0.7\nnum_ctx 2048",
    )
    client = SimpleNamespace(show=AsyncMock(return_value=response))

    with patch(
        "source.llm.core.model_context.OllamaAsyncClient",
        return_value=client,
    ):
        from source.llm.core.model_context import resolve_model_context_window

        context = await resolve_model_context_window("gemma3:4b")

    assert context.model == "gemma3:4b"
    assert context.context_window == 32768
    assert context.source == "ollama_show+configured_num_ctx"


@pytest.mark.asyncio
async def test_resolve_ollama_cloud_context_window_uses_native_max_without_local_cap():
    response = SimpleNamespace(
        modelinfo={"qwen3.context_length": 262144},
        parameters="temperature 0.7\nnum_ctx 32768",
    )
    client = SimpleNamespace(show=AsyncMock(return_value=response))

    with patch(
        "source.llm.core.model_context.OllamaAsyncClient",
        return_value=client,
    ):
        from source.llm.core.model_context import resolve_model_context_window

        context = await resolve_model_context_window("qwen3-coder-next:cloud")

    assert context.model == "qwen3-coder-next:cloud"
    assert context.context_window == 262144
    assert context.source == "ollama_cloud_show"


@pytest.mark.asyncio
async def test_resolve_cloud_context_window_uses_litellm_model_info():
    with patch(
        "source.llm.core.model_context.litellm.get_model_info",
        return_value={"max_input_tokens": 200000, "max_output_tokens": 32000},
    ):
        from source.llm.core.model_context import resolve_model_context_window

        context = await resolve_model_context_window("openai/gpt-test")

    assert context.model == "openai/gpt-test"
    assert context.context_window == 200000
    assert context.source == "litellm_model_info"
