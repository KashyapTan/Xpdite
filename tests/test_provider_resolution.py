"""Tests for source/llm/provider_resolution.py.

Covers provider parsing, model normalization, cloud tagging detection,
and the unified model target resolution.
"""

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
        """Always returns the local default."""
        from source.llm.provider_resolution import (
            get_ollama_api_base,
            DEFAULT_OLLAMA_API_BASE,
        )

        result = get_ollama_api_base()
        assert result == DEFAULT_OLLAMA_API_BASE


class TestGetOllamaApiKey:
    """Tests for get_ollama_api_key()."""

    def test_returns_none(self):
        """Always returns None for local Ollama."""
        from source.llm.provider_resolution import get_ollama_api_key

        result = get_ollama_api_key()
        assert result is None


class TestResolveModelTarget:
    """Tests for resolve_model_target()."""

    def test_ollama_local_model(self):
        """Local Ollama model is resolved correctly."""
        from source.llm.provider_resolution import resolve_model_target

        target = resolve_model_target("llama3.2")

        assert target.provider == "ollama"
        assert target.model == "llama3.2"
        assert target.litellm_model == "ollama_chat/llama3.2"
        assert target.api_base == "http://localhost:11434"
        assert target.api_key is None
        assert target.is_local_runtime is True
        assert "num_ctx" in target.provider_kwargs

    def test_ollama_explicit_prefix(self):
        """Ollama with explicit 'ollama/' prefix works."""
        from source.llm.provider_resolution import resolve_model_target

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

        assert is_local_ollama_model("llama3.2") is True

    def test_cloud_provider(self):
        """Cloud provider returns False."""
        from source.llm.provider_resolution import is_local_ollama_model

        with patch(
            "source.llm.key_manager.key_manager.get_api_key", return_value="sk-test"
        ):
            assert is_local_ollama_model("anthropic/claude-3") is False

    def test_cloud_tag_names_are_not_local_ollama(self):
        """Cloud-tagged Ollama models (:cloud, -cloud) are not local.

        Cloud-hosted Ollama models can run in parallel (they don't share a
        local GPU), so they should return False to bypass serialization.
        """
        from source.llm.provider_resolution import is_local_ollama_model

        assert is_local_ollama_model("llama3.2:cloud") is False
        assert is_local_ollama_model("llama3.2-cloud") is False
