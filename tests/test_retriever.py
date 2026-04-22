"""Tests for ToolRetriever hybrid retrieval, caching, and index rebuild behavior."""

import json
import logging
import sys
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest

from source.mcp_integration.core.retriever import RRF_K


def _make_tools(descriptions_by_name):
    """Build a list of tools in Ollama format."""
    return [
        {"function": {"name": name, "description": description}}
        for name, description in descriptions_by_name.items()
    ]


def _tool_names(tools):
    """Return tool names in the current result order."""
    return [tool["function"]["name"] for tool in tools]


def _expected_key(retriever, name, description):
    """Return the current cache key for a tool document."""
    document_text = retriever._tool_document_text(name, description)
    return retriever._cache_key(retriever._ollama_model_name, document_text)


def _embed_tools_with_vectors(retriever, descriptions_by_name, vectors_by_name):
    """Seed the retriever index using deterministic mock embeddings."""
    tools = _make_tools(descriptions_by_name)
    ordered_vectors = [
        np.asarray(vectors_by_name[name], dtype=np.float32)
        for name in descriptions_by_name
    ]
    with patch.object(retriever, "_get_embedding", side_effect=ordered_vectors):
        retriever.embed_tools(tools)
    return tools


@pytest.fixture()
def retriever(tmp_path, monkeypatch):
    """Create a ToolRetriever with a fake local embedding backend."""
    import source.mcp_integration.core.retriever as retriever_module

    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(retriever_module, "_CACHE_DIR", str(cache_dir))
    monkeypatch.setattr(
        retriever_module, "_CACHE_FILE", str(cache_dir / "tool_embeddings.npz")
    )
    monkeypatch.setattr(
        retriever_module,
        "_CACHE_INDEX_FILE",
        str(cache_dir / "tool_embedding_index.json"),
    )

    with patch.object(retriever_module.ToolRetriever, "_check_embedding_backend"):
        tool_retriever = retriever_module.ToolRetriever()
        tool_retriever._embedding_model_type = "ollama"
        tool_retriever._ollama_model_name = "test-embed-model"

    return tool_retriever


class TestConfiguration:
    def test_rrf_k_value(self):
        assert RRF_K == 10

    def test_tokenizer_lowercases_and_splits_on_whitespace(self, retriever):
        assert retriever._tokenize(" Gmail   Search   Inbox ") == [
            "gmail",
            "search",
            "inbox",
        ]

    def test_ensure_sentence_transformers_available_uses_cached_global(self, monkeypatch):
        import source.mcp_integration.core.retriever as retriever_module

        sentinel = object()
        monkeypatch.setattr(retriever_module, "SentenceTransformer", sentinel)
        monkeypatch.setattr(
            retriever_module,
            "_SENTENCE_TRANSFORMERS_IMPORT_ATTEMPTED",
            False,
        )

        assert retriever_module._ensure_sentence_transformers_available() is True
        assert retriever_module.SentenceTransformer is sentinel

    def test_ensure_sentence_transformers_available_does_not_retry_failed_import(
        self, monkeypatch
    ):
        import source.mcp_integration.core.retriever as retriever_module

        monkeypatch.setattr(retriever_module, "SentenceTransformer", None)
        monkeypatch.setattr(
            retriever_module,
            "_SENTENCE_TRANSFORMERS_IMPORT_ATTEMPTED",
            True,
        )

        assert retriever_module._ensure_sentence_transformers_available() is False

    def test_ensure_sentence_transformers_available_imports_module_when_present(
        self, monkeypatch
    ):
        import source.mcp_integration.core.retriever as retriever_module

        fake_module = SimpleNamespace(SentenceTransformer=object())
        monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
        monkeypatch.setattr(retriever_module, "SentenceTransformer", None)
        monkeypatch.setattr(
            retriever_module,
            "_SENTENCE_TRANSFORMERS_IMPORT_ATTEMPTED",
            False,
        )

        assert retriever_module._ensure_sentence_transformers_available() is True
        assert (
            retriever_module.SentenceTransformer
            is fake_module.SentenceTransformer
        )

    def test_sentence_transformers_is_importable_uses_cached_global(self, monkeypatch):
        import source.mcp_integration.core.retriever as retriever_module

        sentinel = object()
        monkeypatch.setattr(retriever_module, "SentenceTransformer", sentinel)

        assert retriever_module._sentence_transformers_is_importable() is True

    def test_resolve_bundled_sentence_transformer_dir_prefers_meipass(
        self, monkeypatch, tmp_path
    ):
        import source.mcp_integration.core.retriever as retriever_module

        bundled_dir = (
            tmp_path
            / "bundle"
            / "embedding-models"
            / retriever_module._SENTENCE_TRANSFORMER_MODEL
        )
        bundled_dir.mkdir(parents=True)

        monkeypatch.setattr(retriever_module.sys, "_MEIPASS", str(tmp_path / "bundle"), raising=False)
        monkeypatch.setattr(retriever_module.sys, "executable", str(tmp_path / "app" / "xpdite-server"))

        assert retriever_module._resolve_bundled_sentence_transformer_dir() == bundled_dir

    def test_resolve_bundled_sentence_transformer_dir_uses_env_override(
        self, monkeypatch, tmp_path
    ):
        import source.mcp_integration.core.retriever as retriever_module

        bundled_dir = tmp_path / "custom-model"
        bundled_dir.mkdir()

        monkeypatch.setenv("XPDITE_SENTENCE_TRANSFORMER_MODEL_DIR", str(bundled_dir))

        assert retriever_module._resolve_bundled_sentence_transformer_dir() == bundled_dir

    def test_resolve_child_python_site_packages_finds_bundled_venv(
        self, monkeypatch, tmp_path
    ):
        import source.mcp_integration.core.retriever as retriever_module

        child_python = tmp_path / ".venv" / "bin" / "python"
        site_packages = tmp_path / ".venv" / "lib" / "python3.13" / "site-packages"
        child_python.parent.mkdir(parents=True)
        child_python.write_text("")
        site_packages.mkdir(parents=True)

        monkeypatch.setattr(
            retriever_module,
            "CHILD_PYTHON_EXECUTABLE",
            str(child_python),
        )

        assert retriever_module._resolve_child_python_site_packages() == site_packages

    def test_resolve_child_python_site_packages_keeps_symlinked_venv_layout(
        self, monkeypatch, tmp_path
    ):
        import source.mcp_integration.core.retriever as retriever_module

        real_python = tmp_path / "uv" / "python"
        child_python = tmp_path / ".venv" / "bin" / "python"
        site_packages = tmp_path / ".venv" / "lib" / "python3.13" / "site-packages"
        real_python.parent.mkdir(parents=True)
        real_python.write_text("")
        child_python.parent.mkdir(parents=True)
        child_python.symlink_to(real_python)
        site_packages.mkdir(parents=True)

        monkeypatch.setattr(
            retriever_module,
            "CHILD_PYTHON_EXECUTABLE",
            str(child_python),
        )

        assert retriever_module._resolve_child_python_site_packages() == site_packages

    def test_ensure_sentence_transformers_available_retries_with_child_runtime(
        self, monkeypatch, tmp_path
    ):
        import source.mcp_integration.core.retriever as retriever_module

        child_python = tmp_path / ".venv" / "bin" / "python"
        site_packages = tmp_path / ".venv" / "lib" / "python3.13" / "site-packages"
        child_python.parent.mkdir(parents=True)
        child_python.write_text("")
        site_packages.mkdir(parents=True)

        sentinel = object()
        import_attempts = {"count": 0}
        original_sys_path = list(sys.path)

        def fake_import():
            import_attempts["count"] += 1
            if import_attempts["count"] == 1:
                raise ImportError("initial failure")
            return sentinel

        monkeypatch.setattr(retriever_module, "SentenceTransformer", None)
        monkeypatch.setattr(
            retriever_module,
            "_SENTENCE_TRANSFORMERS_IMPORT_ATTEMPTED",
            False,
        )
        monkeypatch.setattr(
            retriever_module,
            "CHILD_PYTHON_EXECUTABLE",
            str(child_python),
        )
        monkeypatch.setattr(
            retriever_module,
            "_import_sentence_transformer_class",
            fake_import,
        )

        try:
            assert retriever_module._ensure_sentence_transformers_available() is True
            assert retriever_module.SentenceTransformer is sentinel
            assert sys.path[0] == str(site_packages)
            assert import_attempts["count"] == 2
        finally:
            sys.path[:] = original_sys_path


class TestBackendSelection:
    def test_check_embedding_backend_prefers_matching_ollama_model_dict_payload(self):
        import source.mcp_integration.core.retriever as retriever_module

        with (
            patch.object(
                retriever_module.ToolRetriever,
                "_load_cache",
            ),
            patch.object(
                retriever_module.ToolRetriever,
                "_load_cache_index",
            ),
            patch.object(
                retriever_module.ollama,
                "list",
                return_value={"models": [{"name": "all-minilm:latest"}]},
            ),
        ):
            tool_retriever = retriever_module.ToolRetriever()

        assert tool_retriever._embedding_model_type == "ollama"
        assert tool_retriever._ollama_model_name == "all-minilm:latest"

    def test_check_embedding_backend_falls_back_to_sentence_transformers(self):
        import source.mcp_integration.core.retriever as retriever_module

        with (
            patch.object(
                retriever_module.ToolRetriever,
                "_load_cache",
            ),
            patch.object(
                retriever_module.ToolRetriever,
                "_load_cache_index",
            ),
            patch.object(
                retriever_module.ollama,
                "list",
                side_effect=RuntimeError("offline"),
            ),
            patch.object(
                retriever_module,
                "_sentence_transformers_is_importable",
                return_value=True,
            ),
        ):
            tool_retriever = retriever_module.ToolRetriever()

        assert tool_retriever._embedding_model_type == "sentence-transformers"

    def test_check_embedding_backend_marks_none_when_no_backend_is_available(self):
        import source.mcp_integration.core.retriever as retriever_module

        with (
            patch.object(
                retriever_module.ToolRetriever,
                "_load_cache",
            ),
            patch.object(
                retriever_module.ToolRetriever,
                "_load_cache_index",
            ),
            patch.object(
                retriever_module.ollama,
                "list",
                return_value=[{"model": "llama3"}],
            ),
            patch.object(
                retriever_module,
                "_sentence_transformers_is_importable",
                return_value=False,
            ),
        ):
            tool_retriever = retriever_module.ToolRetriever()

        assert tool_retriever._embedding_model_type == "none"


class TestIndexBuild:
    def test_embed_tools_builds_normalized_matrix_and_bm25_index(self, retriever):
        descriptions = {
            "search_gmail": "Search Gmail messages",
            "list_calendar": "List calendar events",
        }
        tools = _make_tools(descriptions)

        with patch.object(
            retriever,
            "_get_embedding",
            side_effect=[np.array([3.0, 4.0]), np.array([0.0, 2.0])],
        ):
            retriever.embed_tools(tools)

        assert retriever._tool_name_index == ["search_gmail", "list_calendar"]
        assert retriever._embedding_matrix.shape == (2, 2)
        assert np.allclose(
            np.linalg.norm(retriever._embedding_matrix, axis=1),
            np.ones(2),
        )
        assert retriever._bm25_index is not None

    def test_embed_tools_skips_mismatched_dimensions_at_rebuild(
        self, retriever, caplog
    ):
        tools = _make_tools(
            {
                "first": "First tool",
                "second": "Second tool",
                "third": "Third tool",
            }
        )

        with patch.object(
            retriever,
            "_get_embedding",
            side_effect=[
                np.array([1.0, 0.0]),
                np.array([0.0, 1.0]),
                np.array([1.0, 0.0, 0.0]),
            ],
        ):
            with caplog.at_level(logging.WARNING):
                retriever.embed_tools(tools)

        assert retriever._tool_name_index == ["first", "second"]
        assert retriever._embedding_matrix.shape == (2, 2)
        assert "mismatched dimensions" in caplog.text

    def test_embed_tools_skips_zero_norm_vectors(self, retriever, caplog):
        tools = _make_tools(
            {
                "zero_vector_tool": "Tool with a zero vector",
                "valid_tool": "Tool with a valid vector",
            }
        )

        with patch.object(
            retriever,
            "_get_embedding",
            side_effect=[np.array([0.0, 0.0]), np.array([1.0, 0.0])],
        ):
            with caplog.at_level(logging.WARNING):
                retriever.embed_tools(tools)

        assert retriever._tool_name_index == ["valid_tool"]
        assert retriever._embedding_matrix.shape == (1, 2)
        assert "zero norm" in caplog.text


class TestRetrieveTools:
    def test_returns_always_on_when_no_active_index(self, retriever):
        tools = _make_tools(
            {
                "read_file": "Read a file from disk",
                "search_docs": "Search internal docs",
            }
        )

        result = retriever.retrieve_tools(
            "open a file",
            tools,
            always_on=["read_file"],
            top_k=5,
        )

        assert _tool_names(result) == ["read_file"]

    def test_always_on_tools_are_appended_without_consuming_budget(self, retriever):
        descriptions = {
            "always_tool": "Always include this tool",
            "ranked_tool": "Best ranked tool",
            "other_tool": "Other ranked tool",
        }
        vectors = {
            "always_tool": np.array([1.0, 0.0]),
            "ranked_tool": np.array([0.9, 0.1]),
            "other_tool": np.array([0.0, 1.0]),
        }
        tools = _embed_tools_with_vectors(retriever, descriptions, vectors)

        with patch.object(retriever, "_get_embedding", return_value=np.array([1.0, 0.0])):
            result = retriever.retrieve_tools(
                "query",
                tools,
                always_on=["always_tool"],
                top_k=1,
            )

        assert _tool_names(result) == ["ranked_tool", "always_tool"]

    def test_rrf_promotes_keyword_match_over_semantic_neighbor(self, retriever):
        descriptions = {
            "search_gmail_messages": "Search gmail inbox archive mail",
            "list_calendar_events": "List calendar events appointments",
            "search_docs": "Search internal documentation",
        }
        vectors = {
            "search_gmail_messages": np.array([0.8, 0.6]),
            "list_calendar_events": np.array([0.95, 0.3122499]),
            "search_docs": np.array([0.5, 0.8660254]),
        }
        tools = _embed_tools_with_vectors(retriever, descriptions, vectors)

        with patch.object(retriever, "_get_embedding", return_value=np.array([1.0, 0.0])):
            result = retriever.retrieve_tools(
                "search my gmail",
                tools,
                always_on=[],
                top_k=3,
            )

        assert _tool_names(result)[0] == "search_gmail_messages"

    def test_top_k_limits_ranked_results(self, retriever):
        descriptions = {
            f"tool_{index}": f"Generic tool number {index}" for index in range(5)
        }
        vectors = {
            "tool_0": np.array([1.0, 0.0]),
            "tool_1": np.array([0.9, 0.1]),
            "tool_2": np.array([0.8, 0.2]),
            "tool_3": np.array([0.7, 0.3]),
            "tool_4": np.array([0.6, 0.4]),
        }
        tools = _embed_tools_with_vectors(retriever, descriptions, vectors)

        with patch.object(retriever, "_get_embedding", return_value=np.array([1.0, 0.0])):
            result = retriever.retrieve_tools(
                "query",
                tools,
                always_on=[],
                top_k=3,
            )

        assert len(result) == 3
        assert _tool_names(result) == ["tool_0", "tool_1", "tool_2"]

    def test_rrf_tie_breaker_uses_cosine_similarity(self, retriever):
        descriptions = {
            "tool_a": "alpha helper",
            "tool_b": "beta helper",
        }
        vectors = {
            "tool_a": np.array([1.0, 0.0]),
            "tool_b": np.array([0.8, 0.6]),
        }
        tools = _embed_tools_with_vectors(retriever, descriptions, vectors)

        with patch.object(retriever, "_get_embedding", return_value=np.array([1.0, 0.0])):
            result = retriever.retrieve_tools(
                "beta",
                tools,
                always_on=[],
                top_k=2,
            )

        assert _tool_names(result) == ["tool_a", "tool_b"]

    def test_query_embedding_failure_uses_bm25_signal(self, retriever):
        descriptions = {
            "search_gmail_messages": "Search gmail inbox archive mail",
            "list_calendar_events": "List calendar events appointments",
            "search_docs": "Search internal documentation",
        }
        vectors = {
            "search_gmail_messages": np.array([0.8, 0.6]),
            "list_calendar_events": np.array([0.95, 0.3122499]),
            "search_docs": np.array([0.5, 0.8660254]),
        }
        tools = _embed_tools_with_vectors(retriever, descriptions, vectors)

        with patch.object(retriever, "_get_embedding", return_value=None):
            result = retriever.retrieve_tools(
                "gmail",
                tools,
                always_on=[],
                top_k=1,
            )

        assert _tool_names(result) == ["search_gmail_messages"]

    def test_zero_norm_query_embedding_uses_bm25_signal(self, retriever):
        descriptions = {
            "search_gmail_messages": "Search gmail inbox archive mail",
            "list_calendar_events": "List calendar events appointments",
            "search_docs": "Search internal documentation",
        }
        vectors = {
            "search_gmail_messages": np.array([0.8, 0.6]),
            "list_calendar_events": np.array([0.95, 0.3122499]),
            "search_docs": np.array([0.5, 0.8660254]),
        }
        tools = _embed_tools_with_vectors(retriever, descriptions, vectors)

        with patch.object(retriever, "_get_embedding", return_value=np.array([0.0, 0.0])):
            result = retriever.retrieve_tools(
                "gmail",
                tools,
                always_on=[],
                top_k=1,
            )

        assert _tool_names(result) == ["search_gmail_messages"]

    def test_dimension_mismatch_query_embedding_uses_bm25_signal(
        self, retriever, caplog
    ):
        descriptions = {
            "search_gmail_messages": "Search gmail inbox archive mail",
            "list_calendar_events": "List calendar events appointments",
            "search_docs": "Search internal documentation",
        }
        vectors = {
            "search_gmail_messages": np.array([0.8, 0.6]),
            "list_calendar_events": np.array([0.95, 0.3122499]),
            "search_docs": np.array([0.5, 0.8660254]),
        }
        tools = _embed_tools_with_vectors(retriever, descriptions, vectors)

        with patch.object(retriever, "_get_embedding", return_value=np.array([1.0, 0.0, 0.0])):
            with caplog.at_level(logging.WARNING):
                result = retriever.retrieve_tools(
                    "gmail",
                    tools,
                    always_on=[],
                    top_k=1,
                )

        assert _tool_names(result) == ["search_gmail_messages"]
        assert "does not match tool matrix dimension" in caplog.text

    def test_debug_logging_includes_fused_scores(self, retriever, caplog):
        descriptions = {
            "search_gmail_messages": "Search gmail inbox archive mail",
            "list_calendar_events": "List calendar events appointments",
        }
        vectors = {
            "search_gmail_messages": np.array([0.8, 0.6]),
            "list_calendar_events": np.array([0.95, 0.3122499]),
        }
        tools = _embed_tools_with_vectors(retriever, descriptions, vectors)

        with patch.object(retriever, "_get_embedding", return_value=np.array([1.0, 0.0])):
            with caplog.at_level(logging.DEBUG):
                retriever.retrieve_tools(
                    "gmail",
                    tools,
                    always_on=[],
                    top_k=2,
                )

        score_logs = [
            record.message
            for record in caplog.records
            if "cosine_similarity=" in record.message
        ]
        assert score_logs
        assert any("bm25_score=" in message for message in score_logs)
        assert any("rrf_score=" in message for message in score_logs)

    def test_bm25_zero_scores_fall_back_to_always_on_with_warning(
        self, retriever, caplog
    ):
        descriptions = {
            "always_tool": "Always include this tool",
            "search_docs": "Search internal docs",
        }
        vectors = {
            "always_tool": np.array([1.0, 0.0]),
            "search_docs": np.array([0.0, 1.0]),
        }
        tools = _embed_tools_with_vectors(retriever, descriptions, vectors)

        with patch.object(retriever, "_get_embedding", return_value=None):
            with caplog.at_level(logging.WARNING):
                result = retriever.retrieve_tools(
                    "no keyword overlap here",
                    tools,
                    always_on=["always_tool"],
                    top_k=1,
                )

        assert _tool_names(result) == ["always_tool"]
        assert "BM25 produced no keyword matches" in caplog.text


class TestEmbedToolsCacheCleanup:
    def test_incremental_refresh_keeps_cache_for_temporarily_absent_tools(
        self, retriever
    ):
        full_tools = _make_tools(
            {
                "read_file": "Read a file from disk",
                "list_calendars": "List the user's calendars",
            }
        )
        partial_tools = _make_tools({"read_file": "Read a file from disk"})
        read_key = _expected_key(retriever, "read_file", "Read a file from disk")
        calendar_key = _expected_key(
            retriever,
            "list_calendars",
            "List the user's calendars",
        )

        with patch.object(
            retriever,
            "_get_embedding",
            side_effect=[np.array([1.0, 0.0]), np.array([0.0, 1.0])],
        ):
            retriever.embed_tools(full_tools)

        with patch.object(retriever, "_get_embedding") as get_embedding:
            retriever.embed_tools(partial_tools)
            retriever.embed_tools(full_tools)

        get_embedding.assert_not_called()
        assert read_key in retriever._embedding_cache
        assert calendar_key in retriever._embedding_cache
        assert retriever._tool_cache_index == {
            "read_file": read_key,
            "list_calendars": calendar_key,
        }
        assert retriever._tool_name_index == ["read_file", "list_calendars"]

        import source.mcp_integration.core.retriever as retriever_module

        with np.load(retriever_module._CACHE_FILE, allow_pickle=False) as data:
            assert read_key in data.files
            assert calendar_key in data.files
        with open(retriever_module._CACHE_INDEX_FILE, encoding="utf-8") as fh:
            assert json.load(fh) == {
                "read_file": read_key,
                "list_calendars": calendar_key,
            }


class TestRetrieverAdditionalCoverage:
    def test_get_embedding_uses_ollama_backend_and_returns_float32(self, retriever):
        retriever._embedding_model_type = "ollama"
        retriever._ollama_model_name = "demo-embed"

        with patch(
            "source.mcp_integration.core.retriever.ollama.embeddings",
            return_value={"embedding": [1, 2, 3]},
        ):
            embedding = retriever._get_embedding("hello")

        assert embedding.dtype == np.float32
        assert np.allclose(embedding, np.array([1, 2, 3], dtype=np.float32))

    def test_get_embedding_returns_none_when_ollama_embedding_fails(
        self, retriever, caplog
    ):
        retriever._embedding_model_type = "ollama"

        with patch(
            "source.mcp_integration.core.retriever.ollama.embeddings",
            side_effect=RuntimeError("boom"),
        ):
            with caplog.at_level(logging.WARNING):
                embedding = retriever._get_embedding("hello")

        assert embedding is None
        assert "Ollama embedding failed" in caplog.text

    def test_get_embedding_lazy_loads_sentence_transformers_model(
        self, retriever, monkeypatch
    ):
        import source.mcp_integration.core.retriever as retriever_module

        constructed = {}

        class FakeSentenceTransformer:
            def __init__(self, model_name, **kwargs):
                constructed["model_name"] = model_name
                constructed["kwargs"] = kwargs

            def encode(self, text, **kwargs):
                assert text == "hello"
                assert kwargs == {"show_progress_bar": False}
                return [0.25, 0.75]

        retriever._embedding_model_type = "sentence-transformers"
        retriever._st_model = None
        monkeypatch.setattr(
            retriever_module,
            "SentenceTransformer",
            FakeSentenceTransformer,
        )

        with patch.object(
            retriever_module,
            "_ensure_sentence_transformers_available",
            return_value=True,
        ):
            embedding = retriever._get_embedding("hello")

        assert constructed["model_name"] == retriever_module._SENTENCE_TRANSFORMER_MODEL
        assert constructed["kwargs"] == {}
        assert np.allclose(embedding, np.array([0.25, 0.75], dtype=np.float32))

    def test_get_embedding_uses_bundled_sentence_transformer_model(
        self, retriever, monkeypatch, tmp_path
    ):
        import source.mcp_integration.core.retriever as retriever_module

        constructed = {}
        bundled_dir = tmp_path / "embedding-models" / retriever_module._SENTENCE_TRANSFORMER_MODEL
        bundled_dir.mkdir(parents=True)

        class FakeSentenceTransformer:
            def __init__(self, model_name, **kwargs):
                constructed["model_name"] = model_name
                constructed["kwargs"] = kwargs

            def encode(self, text, **kwargs):
                assert text == "hello"
                assert kwargs == {"show_progress_bar": False}
                return [0.4, 0.6]

        retriever._embedding_model_type = "sentence-transformers"
        retriever._st_model = None
        monkeypatch.setattr(retriever_module, "SentenceTransformer", FakeSentenceTransformer)
        monkeypatch.setattr(
            retriever_module,
            "_resolve_bundled_sentence_transformer_dir",
            lambda: bundled_dir,
        )

        with patch.object(
            retriever_module,
            "_ensure_sentence_transformers_available",
            return_value=True,
        ):
            embedding = retriever._get_embedding("hello")

        assert constructed["model_name"] == str(bundled_dir)
        assert constructed["kwargs"] == {"local_files_only": True}
        assert np.allclose(embedding, np.array([0.4, 0.6], dtype=np.float32))

    def test_get_embedding_uses_existing_sentence_transformer_numpy_output(
        self, retriever
    ):
        retriever._embedding_model_type = "sentence-transformers"
        retriever._st_model = SimpleNamespace(
            encode=lambda _text, **_kwargs: np.array([0.1, 0.9], dtype=np.float64)
        )

        embedding = retriever._get_embedding("hello")

        assert embedding.dtype == np.float32
        assert np.allclose(embedding, np.array([0.1, 0.9], dtype=np.float32))

    def test_load_cache_reads_npz_embeddings_from_disk(self, retriever):
        import source.mcp_integration.core.retriever as retriever_module

        retriever_module.os.makedirs(retriever_module._CACHE_DIR, exist_ok=True)
        np.savez(
            retriever_module._CACHE_FILE,
            first=np.array([1.0, 2.0], dtype=np.float32),
        )
        retriever._embedding_cache = {}

        retriever._load_cache()

        assert "first" in retriever._embedding_cache
        assert np.allclose(
            retriever._embedding_cache["first"],
            np.array([1.0, 2.0], dtype=np.float32),
        )

    def test_load_cache_warns_and_clears_state_for_invalid_npz(
        self, retriever, caplog
    ):
        import source.mcp_integration.core.retriever as retriever_module

        retriever_module.os.makedirs(retriever_module._CACHE_DIR, exist_ok=True)
        with open(retriever_module._CACHE_FILE, "wb") as fh:
            fh.write(b"not-a-valid-npz")

        retriever._embedding_cache = {"stale": np.array([1.0], dtype=np.float32)}
        with caplog.at_level(logging.WARNING):
            retriever._load_cache()

        assert retriever._embedding_cache == {}
        assert "Could not load embedding cache" in caplog.text

    def test_save_cache_logs_warning_when_atomic_write_fails(
        self, retriever, caplog
    ):
        retriever._embedding_cache = {"tool": np.array([1.0], dtype=np.float32)}

        with patch.object(
            retriever,
            "_write_file_atomically",
            side_effect=OSError("disk full"),
        ):
            with caplog.at_level(logging.WARNING):
                retriever._save_cache()

        assert "Could not save embedding cache" in caplog.text

    def test_load_cache_index_accepts_valid_string_mapping(self, retriever):
        import source.mcp_integration.core.retriever as retriever_module

        retriever_module.os.makedirs(retriever_module._CACHE_DIR, exist_ok=True)
        with open(retriever_module._CACHE_INDEX_FILE, "w", encoding="utf-8") as fh:
            json.dump({"tool": "cache-key"}, fh)

        retriever._tool_cache_index = {}
        retriever._load_cache_index()

        assert retriever._tool_cache_index == {"tool": "cache-key"}

    def test_load_cache_index_rejects_invalid_mapping_values(
        self, retriever, caplog
    ):
        import source.mcp_integration.core.retriever as retriever_module

        retriever_module.os.makedirs(retriever_module._CACHE_DIR, exist_ok=True)
        with open(retriever_module._CACHE_INDEX_FILE, "w", encoding="utf-8") as fh:
            json.dump({"tool": 123}, fh)

        retriever._tool_cache_index = {"stale": "value"}
        with caplog.at_level(logging.WARNING):
            retriever._load_cache_index()

        assert retriever._tool_cache_index == {}
        assert "Embedding cache index is invalid" in caplog.text

    def test_load_cache_index_warns_on_json_error(self, retriever, caplog):
        import source.mcp_integration.core.retriever as retriever_module

        retriever_module.os.makedirs(retriever_module._CACHE_DIR, exist_ok=True)
        with open(retriever_module._CACHE_INDEX_FILE, "w", encoding="utf-8") as fh:
            fh.write("{invalid-json")

        with caplog.at_level(logging.WARNING):
            retriever._load_cache_index()

        assert retriever._tool_cache_index == {}
        assert "Could not load embedding cache index" in caplog.text

    def test_save_cache_index_logs_warning_when_atomic_write_fails(
        self, retriever, caplog
    ):
        retriever._tool_cache_index = {"tool": "cache-key"}

        with patch.object(
            retriever,
            "_write_file_atomically",
            side_effect=OSError("disk full"),
        ):
            with caplog.at_level(logging.WARNING):
                retriever._save_cache_index()

        assert "Could not save cache index" in caplog.text

    def test_embed_tools_with_no_backend_clears_active_indexes(self, retriever):
        retriever._embedding_model_type = "none"
        retriever._embedding_matrix = np.array([[1.0]], dtype=np.float32)
        retriever._tool_name_index = ["tool"]
        retriever._bm25_index = object()

        retriever.embed_tools(_make_tools({"tool": "desc"}))

        assert retriever._embedding_matrix.shape == (0, 0)
        assert retriever._tool_name_index == []
        assert retriever._bm25_index is None

    def test_rebuild_retrieval_index_disables_bm25_once_when_dependency_missing(
        self, retriever, monkeypatch, caplog
    ):
        import source.mcp_integration.core.retriever as retriever_module

        monkeypatch.setattr(retriever_module, "BM25_AVAILABLE", False)
        monkeypatch.setattr(retriever_module, "BM25Okapi", None)
        retriever._bm25_warning_emitted = False

        with caplog.at_level(logging.WARNING):
            retriever._rebuild_retrieval_index(
                [("tool", "tool desc", np.array([1.0, 0.0], dtype=np.float32))]
            )
            retriever._rebuild_retrieval_index(
                [("tool", "tool desc", np.array([1.0, 0.0], dtype=np.float32))]
            )

        assert retriever._bm25_index is None
        assert caplog.text.count("rank_bm25 is unavailable") == 1

    def test_format_helpers_handle_missing_values(self, retriever):
        assert retriever._format_float(None) == "n/a"
        assert retriever._format_rank(None) == "n/a"

    def test_lazy_retriever_constructs_singleton_once_and_delegates(
        self, monkeypatch
    ):
        import source.mcp_integration.core.retriever as retriever_module

        constructions = []

        class FakeRetriever:
            marker = "ready"

            def __init__(self):
                constructions.append("init")

            def retrieve_tools(self, *args, **kwargs):
                return ("retrieve", args, kwargs)

            def embed_tools(self, *args, **kwargs):
                return ("embed", args, kwargs)

        monkeypatch.setattr(retriever_module, "_retriever_instance", None)
        monkeypatch.setattr(retriever_module, "ToolRetriever", FakeRetriever)
        proxy = retriever_module._LazyRetriever()

        assert proxy.retrieve_tools("query", [], []) == (
            "retrieve",
            ("query", [], []),
            {},
        )
        assert proxy.embed_tools([]) == ("embed", ([],), {})
        assert proxy.marker == "ready"
        assert constructions == ["init"]

    def test_description_change_keeps_old_cache_until_reembed_succeeds(self, retriever):
        initial_tools = _make_tools({"search_docs": "Search the docs"})
        updated_tools = _make_tools({"search_docs": "Search the updated docs"})
        initial_key = _expected_key(retriever, "search_docs", "Search the docs")
        updated_key = _expected_key(retriever, "search_docs", "Search the updated docs")
        initial_embedding = np.array([1.0, 0.0], dtype=np.float32)

        with patch.object(
            retriever,
            "_get_embedding",
            side_effect=[initial_embedding, None],
        ):
            retriever.embed_tools(initial_tools)
            retriever.embed_tools(updated_tools)

        assert initial_key in retriever._embedding_cache
        assert updated_key not in retriever._embedding_cache
        assert retriever._tool_cache_index == {"search_docs": initial_key}
        assert retriever._tool_name_index == ["search_docs"]
        assert np.allclose(
            retriever._embedding_matrix[0],
            initial_embedding / np.linalg.norm(initial_embedding),
        )

        import source.mcp_integration.core.retriever as retriever_module

        with np.load(retriever_module._CACHE_FILE, allow_pickle=False) as data:
            assert initial_key in data.files
            assert updated_key not in data.files
        with open(retriever_module._CACHE_INDEX_FILE, encoding="utf-8") as fh:
            assert json.load(fh) == {"search_docs": initial_key}

    def test_description_change_replaces_stale_cache_entry(self, retriever):
        initial_tools = _make_tools({"search_docs": "Search the docs"})
        updated_tools = _make_tools({"search_docs": "Search the updated docs"})
        initial_key = _expected_key(retriever, "search_docs", "Search the docs")
        updated_key = _expected_key(retriever, "search_docs", "Search the updated docs")

        with patch.object(
            retriever,
            "_get_embedding",
            side_effect=[np.array([1.0, 0.0]), np.array([0.0, 1.0])],
        ):
            retriever.embed_tools(initial_tools)
            retriever.embed_tools(updated_tools)

        assert initial_key not in retriever._embedding_cache
        assert updated_key in retriever._embedding_cache
        assert retriever._tool_cache_index == {"search_docs": updated_key}

        import source.mcp_integration.core.retriever as retriever_module

        with np.load(retriever_module._CACHE_FILE, allow_pickle=False) as data:
            assert initial_key not in data.files
            assert updated_key in data.files
        with open(retriever_module._CACHE_INDEX_FILE, encoding="utf-8") as fh:
            assert json.load(fh) == {"search_docs": updated_key}

    def test_tools_missing_from_current_refresh_stay_cached(self, retriever):
        tools = _make_tools(
            {
                "search_docs": "Search the docs",
                "open_ticket": "Open a support ticket",
            }
        )
        search_key = _expected_key(retriever, "search_docs", "Search the docs")
        ticket_key = _expected_key(
            retriever,
            "open_ticket",
            "Open a support ticket",
        )

        with patch.object(
            retriever,
            "_get_embedding",
            side_effect=[np.array([1.0, 0.0]), np.array([0.0, 1.0])],
        ):
            retriever.embed_tools(tools)

        with patch.object(retriever, "_get_embedding") as get_embedding:
            retriever.embed_tools(_make_tools({"search_docs": "Search the docs"}))

        get_embedding.assert_not_called()
        assert search_key in retriever._embedding_cache
        assert ticket_key in retriever._embedding_cache
        assert retriever._tool_cache_index == {
            "search_docs": search_key,
            "open_ticket": ticket_key,
        }

        import source.mcp_integration.core.retriever as retriever_module

        with np.load(retriever_module._CACHE_FILE, allow_pickle=False) as data:
            assert search_key in data.files
            assert ticket_key in data.files
        with open(retriever_module._CACHE_INDEX_FILE, encoding="utf-8") as fh:
            assert json.load(fh) == {
                "search_docs": search_key,
                "open_ticket": ticket_key,
            }

    def test_optional_tools_reuse_cached_embeddings_after_absence(self, retriever):
        tools = _make_tools(
            {
                "read_file": "Read a file from disk",
                "list_calendars": "List the user's calendars",
            }
        )
        read_key = _expected_key(retriever, "read_file", "Read a file from disk")
        calendar_key = _expected_key(
            retriever,
            "list_calendars",
            "List the user's calendars",
        )

        with patch.object(
            retriever,
            "_get_embedding",
            side_effect=[np.array([1.0, 0.0]), np.array([0.0, 1.0])],
        ):
            retriever.embed_tools(tools)

        with patch.object(retriever, "_get_embedding") as get_embedding:
            retriever.embed_tools(_make_tools({"read_file": "Read a file from disk"}))
            retriever.embed_tools(tools)

        get_embedding.assert_not_called()
        assert read_key in retriever._embedding_cache
        assert calendar_key in retriever._embedding_cache
        assert retriever._tool_cache_index == {
            "read_file": read_key,
            "list_calendars": calendar_key,
        }

        import source.mcp_integration.core.retriever as retriever_module

        with np.load(retriever_module._CACHE_FILE, allow_pickle=False) as data:
            assert read_key in data.files
            assert calendar_key in data.files
        with open(retriever_module._CACHE_INDEX_FILE, encoding="utf-8") as fh:
            assert json.load(fh) == {
                "read_file": read_key,
                "list_calendars": calendar_key,
            }
