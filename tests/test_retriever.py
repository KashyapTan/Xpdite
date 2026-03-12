"""Tests for ToolRetriever hybrid retrieval, caching, and index rebuild behavior."""

import json
import logging
from unittest.mock import patch

import numpy as np
import pytest

from source.mcp_integration.retriever import RRF_K


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
    import source.mcp_integration.retriever as retriever_module

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

        import source.mcp_integration.retriever as retriever_module

        with np.load(retriever_module._CACHE_FILE, allow_pickle=False) as data:
            assert read_key in data.files
            assert calendar_key in data.files
        with open(retriever_module._CACHE_INDEX_FILE, encoding="utf-8") as fh:
            assert json.load(fh) == {
                "read_file": read_key,
                "list_calendars": calendar_key,
            }

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

        import source.mcp_integration.retriever as retriever_module

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

        import source.mcp_integration.retriever as retriever_module

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

        import source.mcp_integration.retriever as retriever_module

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

        import source.mcp_integration.retriever as retriever_module

        with np.load(retriever_module._CACHE_FILE, allow_pickle=False) as data:
            assert read_key in data.files
            assert calendar_key in data.files
        with open(retriever_module._CACHE_INDEX_FILE, encoding="utf-8") as fh:
            assert json.load(fh) == {
                "read_file": read_key,
                "list_calendars": calendar_key,
            }
