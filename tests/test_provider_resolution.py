"""Tests for source/llm/provider_resolution.py.

Covers provider parsing, model normalization, cloud tagging detection,
and the unified model target resolution.
"""

import os
from unittest.mock import patch


class TestParseProvider:
    """Tests for parse_provider()."""

    def test_ollama_prefix_lowercase(self):
        """Models with 'ollama/' prefix are parsed correctly."""
        from source.llm.provider_resolution import parse_provider

        provider, model = parse_provider("ollama/llama3.2")
        assert provider == "ollama"
        assert model == "llama3.2"

    def test_ollama_prefix_uppercase(self):
        """Models with 'Ollama/' mixed case prefix are normalized."""
        from source.llm.provider_resolution import parse_provider

        provider, model = parse_provider("Ollama/llama3.2")
        assert provider == "ollama"
        assert model == "llama3.2"

    def test_bare_model_defaults_to_ollama(self):
        """Models without a prefix default to Ollama provider."""
        from source.llm.provider_resolution import parse_provider

        provider, model = parse_provider("llama3.2")
        assert provider == "ollama"
        assert model == "llama3.2"

    def test_anthropic_provider(self):
        """Anthropic models are parsed correctly."""
        from source.llm.provider_resolution import parse_provider

        provider, model = parse_provider("anthropic/claude-sonnet-4-20250514")
        assert provider == "anthropic"
        assert model == "claude-sonnet-4-20250514"

    def test_anthropic_provider_case_insensitive(self):
        """Provider matching should be case-insensitive."""
        from source.llm.provider_resolution import parse_provider

        provider, model = parse_provider("Anthropic/claude-3")
        assert provider == "anthropic"
        assert model == "claude-3"

        provider, model = parse_provider("OPENAI/gpt-4o")
        assert provider == "openai"
        assert model == "gpt-4o"

    def test_openai_provider(self):
        """OpenAI models are parsed correctly."""
        from source.llm.provider_resolution import parse_provider

        provider, model = parse_provider("openai/gpt-4o")
        assert provider == "openai"
        assert model == "gpt-4o"

    def test_gemini_provider(self):
        """Gemini models are parsed correctly."""
        from source.llm.provider_resolution import parse_provider

        provider, model = parse_provider("gemini/gemini-1.5-pro")
        assert provider == "gemini"
        assert model == "gemini-1.5-pro"

    def test_openrouter_provider(self):
        """OpenRouter models are parsed correctly."""
        from source.llm.provider_resolution import parse_provider

        provider, model = parse_provider("openrouter/meta-llama/llama-3-70b")
        assert provider == "openrouter"
        assert model == "meta-llama/llama-3-70b"

    def test_unknown_provider_with_slash_defaults_to_ollama(self):
        """Unknown providers with slashes default to Ollama."""
        from source.llm.provider_resolution import parse_provider

        provider, model = parse_provider("unknown/some-model")
        assert provider == "ollama"
        assert model == "unknown/some-model"

    def test_empty_string(self):
        """Empty string returns ollama with empty model."""
        from source.llm.provider_resolution import parse_provider

        provider, model = parse_provider("")
        assert provider == "ollama"
        assert model == ""

    def test_none_input(self):
        """None input is handled gracefully."""
        from source.llm.provider_resolution import parse_provider

        provider, model = parse_provider(None)  # type: ignore
        assert provider == "ollama"
        assert model == ""

    def test_whitespace_only(self):
        """Whitespace-only input is trimmed to empty."""
        from source.llm.provider_resolution import parse_provider

        provider, model = parse_provider("   ")
        assert provider == "ollama"
        assert model == ""


class TestNormalizeOllamaModelName:
    """Tests for normalize_ollama_model_name()."""

    def test_strips_ollama_prefix(self):
        """Removes 'ollama/' prefix."""
        from source.llm.provider_resolution import normalize_ollama_model_name

        assert normalize_ollama_model_name("ollama/llama3.2") == "llama3.2"

    def test_strips_ollama_prefix_case_insensitive(self):
        """Removes 'Ollama/' prefix regardless of case."""
        from source.llm.provider_resolution import normalize_ollama_model_name

        assert normalize_ollama_model_name("Ollama/llama3.2") == "llama3.2"
        assert normalize_ollama_model_name("OLLAMA/llama3.2") == "llama3.2"

    def test_no_prefix_unchanged(self):
        """Models without prefix are returned unchanged."""
        from source.llm.provider_resolution import normalize_ollama_model_name

        assert normalize_ollama_model_name("llama3.2") == "llama3.2"

    def test_strips_whitespace(self):
        """Leading/trailing whitespace is stripped."""
        from source.llm.provider_resolution import normalize_ollama_model_name

        assert normalize_ollama_model_name("  llama3.2  ") == "llama3.2"
        assert normalize_ollama_model_name("  ollama/llama3.2  ") == "llama3.2"

    def test_empty_string(self):
        """Empty string returns empty string."""
        from source.llm.provider_resolution import normalize_ollama_model_name

        assert normalize_ollama_model_name("") == ""

    def test_none_input(self):
        """None input returns empty string."""
        from source.llm.provider_resolution import normalize_ollama_model_name

        assert normalize_ollama_model_name(None) == ""  # type: ignore

    def test_nested_ollama_prefix(self):
        """Double 'ollama/' prefix strips only the first layer."""
        from source.llm.provider_resolution import normalize_ollama_model_name

        result = normalize_ollama_model_name("ollama/ollama/model")
        # Current behavior: strips first ollama/, returns "ollama/model"
        assert result == "ollama/model"


class TestIsCloudTaggedOllamaModel:
    """Tests for is_cloud_tagged_ollama_model()."""

    def test_cloud_suffix_lowercase(self):
        """Detects ':cloud' suffix."""
        from source.llm.provider_resolution import is_cloud_tagged_ollama_model

        assert is_cloud_tagged_ollama_model("llama3.2:cloud") is True

    def test_cloud_suffix_mixed_case(self):
        """Detects ':Cloud' and ':CLOUD' suffixes."""
        from source.llm.provider_resolution import is_cloud_tagged_ollama_model

        # The check uses .lower() so this should work
        assert is_cloud_tagged_ollama_model("llama3.2:CLOUD") is True
        assert is_cloud_tagged_ollama_model("llama3.2:Cloud") is True

    def test_cloud_dash_suffix(self):
        """Detects '-cloud' suffix."""
        from source.llm.provider_resolution import is_cloud_tagged_ollama_model

        assert is_cloud_tagged_ollama_model("llama3.2-cloud") is True

    def test_no_cloud_tag(self):
        """Returns False for non-cloud models."""
        from source.llm.provider_resolution import is_cloud_tagged_ollama_model

        assert is_cloud_tagged_ollama_model("llama3.2") is False
        assert is_cloud_tagged_ollama_model("llama3.2:latest") is False

    def test_cloud_in_middle_not_detected(self):
        """'cloud' in the middle of the name is not detected."""
        from source.llm.provider_resolution import is_cloud_tagged_ollama_model

        assert is_cloud_tagged_ollama_model("cloudmodel:latest") is False

    def test_with_ollama_prefix(self):
        """Works with 'ollama/' prefix."""
        from source.llm.provider_resolution import is_cloud_tagged_ollama_model

        assert is_cloud_tagged_ollama_model("ollama/llama3.2:cloud") is True


class TestIsLocalOllamaApiBase:
    """Tests for is_local_ollama_api_base()."""

    def test_localhost(self):
        """Localhost URLs are detected as local."""
        from source.llm.provider_resolution import is_local_ollama_api_base

        assert is_local_ollama_api_base("http://localhost:11434") is True
        assert is_local_ollama_api_base("http://localhost") is True

    def test_127_0_0_1(self):
        """127.0.0.1 URLs are detected as local."""
        from source.llm.provider_resolution import is_local_ollama_api_base

        assert is_local_ollama_api_base("http://127.0.0.1:11434") is True
        assert is_local_ollama_api_base("http://127.0.0.1") is True

    def test_ipv6_localhost(self):
        """IPv6 localhost (::1) is detected as local."""
        from source.llm.provider_resolution import is_local_ollama_api_base

        assert is_local_ollama_api_base("http://[::1]:11434") is True

    def test_remote_url(self):
        """Remote URLs are not detected as local."""
        from source.llm.provider_resolution import is_local_ollama_api_base

        assert is_local_ollama_api_base("https://ollama.example.com") is False
        assert is_local_ollama_api_base("http://192.168.1.100:11434") is False

    def test_none_defaults_to_local(self):
        """None input defaults to local (uses DEFAULT_OLLAMA_API_BASE)."""
        from source.llm.provider_resolution import is_local_ollama_api_base

        assert is_local_ollama_api_base(None) is True

    def test_empty_string_defaults_to_local(self):
        """Empty string defaults to local."""
        from source.llm.provider_resolution import is_local_ollama_api_base

        assert is_local_ollama_api_base("") is True


class TestGetOllamaApiBase:
    """Tests for get_ollama_api_base()."""

    def test_default_value(self):
        """Returns default when env var not set."""
        from source.llm.provider_resolution import (
            get_ollama_api_base,
            DEFAULT_OLLAMA_API_BASE,
        )

        with patch.dict(os.environ, {}, clear=True):
            # Remove OLLAMA_API_BASE if it exists
            os.environ.pop("OLLAMA_API_BASE", None)
            result = get_ollama_api_base()
            assert result == DEFAULT_OLLAMA_API_BASE

    def test_env_var_override(self):
        """Uses OLLAMA_API_BASE env var when set."""
        from source.llm.provider_resolution import get_ollama_api_base

        with patch.dict(os.environ, {"OLLAMA_API_BASE": "http://custom:11434"}):
            result = get_ollama_api_base()
            assert result == "http://custom:11434"

    def test_strips_whitespace(self):
        """Whitespace in env var is stripped."""
        from source.llm.provider_resolution import get_ollama_api_base

        with patch.dict(os.environ, {"OLLAMA_API_BASE": "  http://custom:11434  "}):
            result = get_ollama_api_base()
            assert result == "http://custom:11434"


class TestGetOllamaApiKey:
    """Tests for get_ollama_api_key()."""

    def test_returns_none_when_not_set(self):
        """Returns None when OLLAMA_API_KEY not set."""
        from source.llm.provider_resolution import get_ollama_api_key

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("OLLAMA_API_KEY", None)
            result = get_ollama_api_key()
            assert result is None

    def test_returns_key_when_set(self):
        """Returns the API key when OLLAMA_API_KEY is set."""
        from source.llm.provider_resolution import get_ollama_api_key

        with patch.dict(os.environ, {"OLLAMA_API_KEY": "test-key-123"}):
            result = get_ollama_api_key()
            assert result == "test-key-123"

    def test_empty_string_returns_none(self):
        """Empty string returns None (not empty string)."""
        from source.llm.provider_resolution import get_ollama_api_key

        with patch.dict(os.environ, {"OLLAMA_API_KEY": ""}):
            result = get_ollama_api_key()
            assert result is None

    def test_whitespace_only_returns_none(self):
        """Whitespace-only value returns None."""
        from source.llm.provider_resolution import get_ollama_api_key

        with patch.dict(os.environ, {"OLLAMA_API_KEY": "   "}):
            result = get_ollama_api_key()
            assert result is None


class TestResolveModelTarget:
    """Tests for resolve_model_target()."""

    def test_ollama_local_model(self):
        """Local Ollama model is resolved correctly."""
        from source.llm.provider_resolution import resolve_model_target

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("OLLAMA_API_BASE", None)
            os.environ.pop("OLLAMA_API_KEY", None)

            target = resolve_model_target("llama3.2")

            assert target.provider == "ollama"
            assert target.model == "llama3.2"
            assert target.litellm_model == "ollama_chat/llama3.2"
            assert target.api_base == "http://localhost:11434"
            assert target.api_key is None
            assert target.is_local_runtime is True
            assert "num_ctx" in target.provider_kwargs

    def test_ollama_cloud_tagged_model(self):
        """Cloud-tagged Ollama model is not marked as local."""
        from source.llm.provider_resolution import resolve_model_target

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("OLLAMA_API_BASE", None)
            os.environ.pop("OLLAMA_API_KEY", None)

            target = resolve_model_target("llama3.2:cloud")

            assert target.provider == "ollama"
            assert target.model == "llama3.2:cloud"
            assert target.is_local_runtime is False

    def test_ollama_remote_api_base(self):
        """Ollama with remote API base is not marked as local."""
        from source.llm.provider_resolution import resolve_model_target

        with patch.dict(os.environ, {"OLLAMA_API_BASE": "https://remote.example.com"}):
            target = resolve_model_target("llama3.2")

            assert target.provider == "ollama"
            assert target.is_local_runtime is False
            assert target.api_base == "https://remote.example.com"

    def test_ollama_with_api_key(self):
        """Ollama with API key is included in target."""
        from source.llm.provider_resolution import resolve_model_target

        with patch.dict(os.environ, {"OLLAMA_API_KEY": "secret-key"}):
            target = resolve_model_target("llama3.2")

            assert target.api_key == "secret-key"

    def test_ollama_explicit_prefix(self):
        """Ollama with explicit 'ollama/' prefix works."""
        from source.llm.provider_resolution import resolve_model_target

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("OLLAMA_API_BASE", None)
            os.environ.pop("OLLAMA_API_KEY", None)

            target = resolve_model_target("ollama/llama3.2")

            assert target.provider == "ollama"
            assert target.model == "llama3.2"
            assert target.litellm_model == "ollama_chat/llama3.2"

    def test_anthropic_model(self):
        """Anthropic model is resolved correctly."""
        from source.llm.provider_resolution import resolve_model_target

        with patch(
            "source.llm.key_manager.key_manager.get_api_key", return_value="sk-test"
        ):
            target = resolve_model_target("anthropic/claude-sonnet-4-20250514")

            assert target.provider == "anthropic"
            assert target.model == "claude-sonnet-4-20250514"
            assert target.litellm_model == "anthropic/claude-sonnet-4-20250514"
            assert target.api_key == "sk-test"
            assert target.api_base is None
            assert target.is_local_runtime is False

    def test_openai_model(self):
        """OpenAI model is resolved correctly."""
        from source.llm.provider_resolution import resolve_model_target

        with patch(
            "source.llm.key_manager.key_manager.get_api_key", return_value="sk-openai"
        ):
            target = resolve_model_target("openai/gpt-4o")

            assert target.provider == "openai"
            assert target.model == "gpt-4o"
            assert target.litellm_model == "openai/gpt-4o"

    def test_empty_model_name(self):
        """Empty model name creates target with empty model."""
        from source.llm.provider_resolution import resolve_model_target

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("OLLAMA_API_BASE", None)
            os.environ.pop("OLLAMA_API_KEY", None)

            target = resolve_model_target("")

            assert target.provider == "ollama"
            assert target.model == ""
            assert target.litellm_model == "ollama_chat/"
            # is_local_runtime should be False because bare_model is empty
            assert target.is_local_runtime is False


class TestIsLocalOllamaModel:
    """Tests for is_local_ollama_model()."""

    def test_local_ollama(self):
        """Local Ollama model returns True."""
        from source.llm.provider_resolution import is_local_ollama_model

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("OLLAMA_API_BASE", None)
            os.environ.pop("OLLAMA_API_KEY", None)

            assert is_local_ollama_model("llama3.2") is True

    def test_cloud_provider(self):
        """Cloud provider returns False."""
        from source.llm.provider_resolution import is_local_ollama_model

        with patch(
            "source.llm.key_manager.key_manager.get_api_key", return_value="sk-test"
        ):
            assert is_local_ollama_model("anthropic/claude-3") is False

    def test_ollama_cloud_tagged(self):
        """Cloud-tagged Ollama returns False."""
        from source.llm.provider_resolution import is_local_ollama_model

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("OLLAMA_API_BASE", None)

            assert is_local_ollama_model("llama3.2:cloud") is False
            assert is_local_ollama_model("llama3.2-cloud") is False

    def test_ollama_remote_base(self):
        """Ollama with remote API base returns False."""
        from source.llm.provider_resolution import is_local_ollama_model

        with patch.dict(os.environ, {"OLLAMA_API_BASE": "https://remote.example.com"}):
            assert is_local_ollama_model("llama3.2") is False
