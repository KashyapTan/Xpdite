"""Tests for source/llm/ollama_model_registry.py."""

from unittest.mock import patch


class TestShouldHintNativeFunctionCalling:
    def test_known_prefix_returns_true(self):
        from source.llm.ollama_model_registry import should_hint_native_function_calling

        assert should_hint_native_function_calling("ollama_chat/qwen3:8b") is True
        assert should_hint_native_function_calling("ollama_chat/llama3.2") is True

    def test_unknown_prefix_returns_false(self):
        from source.llm.ollama_model_registry import should_hint_native_function_calling

        assert should_hint_native_function_calling("ollama_chat/mistral") is False

    def test_non_ollama_model_returns_false(self):
        from source.llm.ollama_model_registry import should_hint_native_function_calling

        assert should_hint_native_function_calling("openai/gpt-4o") is False

    def test_env_override_prefixes(self):
        from source.llm.ollama_model_registry import should_hint_native_function_calling

        with patch.dict("os.environ", {"XPDITE_OLLAMA_NATIVE_FC_PREFIXES": "phi4"}):
            assert should_hint_native_function_calling("ollama_chat/phi4") is True
            assert should_hint_native_function_calling("ollama_chat/qwen3:8b") is False


class TestRegisterOllamaNativeFunctionCallingHint:
    def test_registers_once_for_supported_model(self):
        from source.llm import ollama_model_registry as registry

        registry._REGISTERED_MODELS.clear()
        with patch.object(registry.litellm, "register_model") as register_model:
            first = registry.register_ollama_native_function_calling_hint(
                "ollama_chat/qwen3:8b"
            )
            second = registry.register_ollama_native_function_calling_hint(
                "ollama_chat/qwen3:8b"
            )

        assert first is True
        assert second is False
        register_model.assert_called_once()

    def test_does_not_register_for_unsupported_model(self):
        from source.llm import ollama_model_registry as registry

        registry._REGISTERED_MODELS.clear()
        with patch.object(registry.litellm, "register_model") as register_model:
            result = registry.register_ollama_native_function_calling_hint(
                "ollama_chat/mistral"
            )

        assert result is False
        register_model.assert_not_called()

    def test_returns_false_when_register_model_missing(self):
        from source.llm import ollama_model_registry as registry

        registry._REGISTERED_MODELS.clear()
        with patch.object(registry.litellm, "register_model", None):
            result = registry.register_ollama_native_function_calling_hint(
                "ollama_chat/qwen3:8b"
            )

        assert result is False
        assert "ollama_chat/qwen3:8b" not in registry._REGISTERED_MODELS

    def test_returns_false_when_registration_raises(self):
        from source.llm import ollama_model_registry as registry

        registry._REGISTERED_MODELS.clear()
        with patch.object(
            registry.litellm,
            "register_model",
            side_effect=RuntimeError("fail"),
        ):
            result = registry.register_ollama_native_function_calling_hint(
                "ollama_chat/qwen3:8b"
            )

        assert result is False
        assert "ollama_chat/qwen3:8b" not in registry._REGISTERED_MODELS
