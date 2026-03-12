"""Tests for ToolRetriever similarity scoring and threshold behaviour."""

import json
from unittest.mock import patch

import numpy as np
import pytest

from source.mcp_integration.retriever import MIN_SIMILARITY_THRESHOLD


def _make_tools(descriptions_by_name):
    """Build a list of tools in Ollama format."""
    return [
        {"function": {"name": name, "description": description}}
        for name, description in descriptions_by_name.items()
    ]


# ------------------------------------------------------------------
# Threshold constant
# ------------------------------------------------------------------


def test_min_similarity_threshold_value():
    assert MIN_SIMILARITY_THRESHOLD == 0.3


# ------------------------------------------------------------------
# Similarity scoring with mock embeddings
# ------------------------------------------------------------------


@pytest.fixture()
def retriever(tmp_path, monkeypatch):
    """Create a ToolRetriever with embedding backend disabled."""
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
        ToolRetriever = retriever_module.ToolRetriever
        r = ToolRetriever()
        # Use a fake Ollama backend name so cache keys are stable and local.
        r._embedding_model_type = "ollama"
        r._ollama_model_name = "test-embed-model"
    return r


class TestRetrieveTools:
    def test_returns_empty_when_no_embeddings(self, retriever):
        """With no embeddings available, retrieve_tools should return the
        always-on tools plus nothing else."""
        tools = _make_tools(
            {
                "read_file": "Description of read_file",
                "write_file": "Description of write_file",
                "search": "Description of search",
            }
        )
        result = retriever.retrieve_tools("open a file", tools, always_on=["read_file"])
        # At minimum, always-on should be included
        names = [t["function"]["name"] for t in result]
        assert "read_file" in names

    def test_always_on_tools_included_regardless_of_score(self, retriever):
        """Always-on tools should be returned even with zero similarity."""
        tools = _make_tools(
            {
                "always_tool": "Description of always_tool",
                "other_tool": "Description of other_tool",
            }
        )
        # Pre-populate embeddings so the scoring path runs
        vec_a = np.array([1.0, 0.0, 0.0])
        vec_b = np.array([0.0, 1.0, 0.0])
        retriever._tool_embeddings = {
            "always_tool": vec_a,
            "other_tool": vec_b,
        }
        # Query embedding orthogonal to always_tool but parallel to other_tool
        with patch.object(retriever, "_get_embedding", return_value=vec_b):
            result = retriever.retrieve_tools(
                "query", tools, always_on=["always_tool"], top_k=5
            )
        names = [t["function"]["name"] for t in result]
        assert "always_tool" in names
        assert "other_tool" in names

    def test_threshold_filters_low_similarity(self, retriever):
        """Tools below MIN_SIMILARITY_THRESHOLD should be excluded."""
        tools = _make_tools({"high": "Description of high", "low": "Description of low"})
        # high has cosine sim 1.0, low has cosine sim ~0 with query
        query_vec = np.array([1.0, 0.0])
        retriever._tool_embeddings = {
            "high": np.array([1.0, 0.0]),
            "low": np.array([0.0, 1.0]),
        }
        with patch.object(retriever, "_get_embedding", return_value=query_vec):
            result = retriever.retrieve_tools("query", tools, always_on=[], top_k=5)
        names = [t["function"]["name"] for t in result]
        assert "high" in names
        assert "low" not in names  # cos sim = 0.0 < 0.3

    def test_top_k_limits_results(self, retriever):
        """Only top_k tools should be returned (plus always-on)."""
        tool_names = [f"tool_{i}" for i in range(10)]
        tools = _make_tools({name: f"Description of {name}" for name in tool_names})
        # All embeddings aligned with query, so all score 1.0
        vec = np.array([1.0, 0.0])
        retriever._tool_embeddings = {n: vec.copy() for n in tool_names}
        with patch.object(retriever, "_get_embedding", return_value=vec):
            result = retriever.retrieve_tools("query", tools, always_on=[], top_k=3)
        assert len(result) == 3

    def test_cosine_similarity_ordering(self, retriever):
        """Higher-similarity tools should appear before lower ones."""
        tools = _make_tools(
            {
                "best": "Description of best",
                "good": "Description of good",
                "ok": "Description of ok",
            }
        )
        query_vec = np.array([1.0, 0.0, 0.0])
        retriever._tool_embeddings = {
            "best": np.array([1.0, 0.0, 0.0]),   # cos = 1.0
            "good": np.array([0.8, 0.6, 0.0]),   # cos ≈ 0.8
            "ok":   np.array([0.5, 0.5, 0.707]), # cos ≈ 0.5
        }
        with patch.object(retriever, "_get_embedding", return_value=query_vec):
            result = retriever.retrieve_tools("query", tools, always_on=[], top_k=3)
        names = [t["function"]["name"] for t in result]
        assert names[0] == "best"


class TestEmbedToolsCacheCleanup:
    def test_incremental_refresh_keeps_cache_for_temporarily_absent_tools(self, retriever):
        full_tools = _make_tools(
            {
                "read_file": "Read a file from disk",
                "list_calendars": "List the user's calendars",
            }
        )
        always_on_tools = _make_tools({"read_file": "Read a file from disk"})
        read_key = retriever._cache_key(
            retriever._ollama_model_name, "read_file: Read a file from disk"
        )
        calendar_key = retriever._cache_key(
            retriever._ollama_model_name,
            "list_calendars: List the user's calendars",
        )

        with patch.object(
            retriever,
            "_get_embedding",
            side_effect=[np.array([1.0, 0.0]), np.array([0.0, 1.0])],
        ):
            retriever.embed_tools(full_tools)

        with patch.object(retriever, "_get_embedding") as get_embedding:
            retriever.embed_tools(always_on_tools)
            retriever.embed_tools(full_tools)

        get_embedding.assert_not_called()
        assert read_key in retriever._embedding_cache
        assert calendar_key in retriever._embedding_cache
        assert retriever._tool_cache_index == {
            "read_file": read_key,
            "list_calendars": calendar_key,
        }
        assert set(retriever._tool_embeddings) == {"read_file", "list_calendars"}

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
        initial_key = retriever._cache_key(
            retriever._ollama_model_name, "search_docs: Search the docs"
        )
        updated_key = retriever._cache_key(
            retriever._ollama_model_name, "search_docs: Search the updated docs"
        )

        with patch.object(
            retriever,
            "_get_embedding",
            side_effect=[np.array([1.0, 0.0]), None],
        ):
            retriever.embed_tools(initial_tools)
            retriever.embed_tools(updated_tools)

        assert initial_key in retriever._embedding_cache
        assert updated_key not in retriever._embedding_cache
        assert retriever._tool_cache_index == {"search_docs": initial_key}
        assert np.array_equal(
            retriever._tool_embeddings["search_docs"],
            retriever._embedding_cache[initial_key],
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
        initial_key = retriever._cache_key(
            retriever._ollama_model_name, "search_docs: Search the docs"
        )
        updated_key = retriever._cache_key(
            retriever._ollama_model_name, "search_docs: Search the updated docs"
        )

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
        search_key = retriever._cache_key(
            retriever._ollama_model_name, "search_docs: Search the docs"
        )
        ticket_key = retriever._cache_key(
            retriever._ollama_model_name, "open_ticket: Open a support ticket"
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
        read_key = retriever._cache_key(
            retriever._ollama_model_name, "read_file: Read a file from disk"
        )
        calendar_key = retriever._cache_key(
            retriever._ollama_model_name,
            "list_calendars: List the user's calendars",
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
