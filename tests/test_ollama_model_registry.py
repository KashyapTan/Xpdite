"""Tests for source/llm/ollama_model_registry.py."""

from unittest.mock import patch


class TestShouldHintNativeFunctionCalling:
    def test_requires_explicit_metadata_support(self):
        from source.llm.ollama_model_registry import should_hint_native_function_calling

        with patch(
            "source.llm.ollama_model_registry._fetch_launch_metadata",
            return_value=None,
        ):
            assert (
                should_hint_native_function_calling(
                    "ollama_chat/qwen3:8b",
                    {"supports_function_calling": True},
                )
                is True
            )

    def test_launch_metadata_supports_tools_returns_true(self):
        from source.llm.ollama_model_registry import should_hint_native_function_calling

        with patch(
            "source.llm.ollama_model_registry._fetch_launch_metadata",
            return_value={"supports_tools": True},
        ):
            assert (
                should_hint_native_function_calling("ollama_chat/qwen3:8b", {}) is True
            )

    def test_launch_metadata_capabilities_tools_returns_true(self):
        from source.llm.ollama_model_registry import should_hint_native_function_calling

        with patch(
            "source.llm.ollama_model_registry._fetch_launch_metadata",
            return_value={"capabilities": ["tools"]},
        ):
            assert (
                should_hint_native_function_calling("ollama_chat/qwen3:8b", {}) is True
            )

    def test_no_metadata_support_returns_false(self):
        from source.llm.ollama_model_registry import should_hint_native_function_calling

        with patch(
            "source.llm.ollama_model_registry._fetch_launch_metadata",
            return_value=None,
        ):
            assert (
                should_hint_native_function_calling("ollama_chat/qwen3:8b", {}) is False
            )

    def test_missing_or_false_metadata_returns_false(self):
        from source.llm.ollama_model_registry import should_hint_native_function_calling

        with patch(
            "source.llm.ollama_model_registry._fetch_launch_metadata",
            return_value=None,
        ):
            assert should_hint_native_function_calling("ollama_chat/mistral") is False
            assert (
                should_hint_native_function_calling(
                    "ollama_chat/qwen3:8b",
                    {},
                )
                is False
            )
            assert (
                should_hint_native_function_calling(
                    "ollama_chat/qwen3:8b",
                    {"supports_function_calling": False},
                )
                is False
            )

    def test_non_ollama_model_returns_false(self):
        from source.llm.ollama_model_registry import should_hint_native_function_calling

        with patch(
            "source.llm.ollama_model_registry._fetch_launch_metadata",
            return_value={"supports_tools": True},
        ):
            assert (
                should_hint_native_function_calling(
                    "openai/gpt-4o",
                    {"supports_function_calling": True},
                )
                is False
            )


class TestRegisterOllamaNativeFunctionCallingHint:
    def test_registers_once_for_supported_model(self):
        from source.llm import ollama_model_registry as registry

        registry._REGISTERED_MODELS.clear()
        with (
            patch.object(registry.litellm, "register_model") as register_model,
            patch(
                "source.llm.ollama_model_registry._fetch_launch_metadata",
                return_value=None,
            ),
        ):
            first = registry.register_ollama_native_function_calling_hint(
                "ollama_chat/qwen3:8b",
                {"supports_function_calling": True},
            )
            second = registry.register_ollama_native_function_calling_hint(
                "ollama_chat/qwen3:8b",
                {"supports_function_calling": True},
            )

        assert first is True
        assert second is False
        register_model.assert_called_once()

    def test_does_not_register_for_unsupported_model(self):
        from source.llm import ollama_model_registry as registry

        registry._REGISTERED_MODELS.clear()
        with (
            patch.object(registry.litellm, "register_model") as register_model,
            patch(
                "source.llm.ollama_model_registry._fetch_launch_metadata",
                return_value=None,
            ),
        ):
            result = registry.register_ollama_native_function_calling_hint(
                "ollama_chat/mistral",
                {},
            )

        assert result is False
        register_model.assert_not_called()

    def test_returns_false_when_register_model_missing(self):
        from source.llm import ollama_model_registry as registry

        registry._REGISTERED_MODELS.clear()
        with (
            patch.object(registry.litellm, "register_model", None),
            patch(
                "source.llm.ollama_model_registry._fetch_launch_metadata",
                return_value=None,
            ),
        ):
            result = registry.register_ollama_native_function_calling_hint(
                "ollama_chat/qwen3:8b",
                {"supports_function_calling": True},
            )

        assert result is False
        assert "ollama_chat/qwen3:8b" not in registry._REGISTERED_MODELS

    def test_returns_false_when_registration_raises(self):
        from source.llm import ollama_model_registry as registry

        registry._REGISTERED_MODELS.clear()
        with (
            patch.object(
                registry.litellm,
                "register_model",
                side_effect=RuntimeError("fail"),
            ),
            patch(
                "source.llm.ollama_model_registry._fetch_launch_metadata",
                return_value=None,
            ),
        ):
            result = registry.register_ollama_native_function_calling_hint(
                "ollama_chat/qwen3:8b",
                {"supports_function_calling": True},
            )

        assert result is False
        assert "ollama_chat/qwen3:8b" not in registry._REGISTERED_MODELS
