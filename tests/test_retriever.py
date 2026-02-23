"""Tests for ToolRetriever similarity scoring and threshold behaviour."""

from unittest.mock import patch, MagicMock

import numpy as np
import pytest

from source.mcp_integration.retriever import MIN_SIMILARITY_THRESHOLD


# ------------------------------------------------------------------
# Threshold constant
# ------------------------------------------------------------------


def test_min_similarity_threshold_value():
    assert MIN_SIMILARITY_THRESHOLD == 0.3


# ------------------------------------------------------------------
# Similarity scoring with mock embeddings
# ------------------------------------------------------------------


@pytest.fixture()
def retriever():
    """Create a ToolRetriever with embedding backend disabled."""
    with patch(
        "source.mcp_integration.retriever.ToolRetriever._check_embedding_backend"
    ):
        from source.mcp_integration.retriever import ToolRetriever

        r = ToolRetriever()
        # Use a fake backend type so embed/retrieve paths aren't short-circuited
        r._embedding_model_type = "test"
    return r


class TestRetrieveTools:
    def _make_tools(self, names):
        """Helper — build a list of tools in Ollama format."""
        return [
            {"function": {"name": n, "description": f"Description of {n}"}}
            for n in names
        ]

    def test_returns_empty_when_no_embeddings(self, retriever):
        """With no embeddings available, retrieve_tools should return the
        always-on tools plus nothing else."""
        tools = self._make_tools(["read_file", "write_file", "search"])
        result = retriever.retrieve_tools("open a file", tools, always_on=["read_file"])
        # At minimum, always-on should be included
        names = [t["function"]["name"] for t in result]
        assert "read_file" in names

    def test_always_on_tools_included_regardless_of_score(self, retriever):
        """Always-on tools should be returned even with zero similarity."""
        tools = self._make_tools(["always_tool", "other_tool"])
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
        tools = self._make_tools(["high", "low"])
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
        tools = self._make_tools(tool_names)
        # All embeddings aligned with query, so all score 1.0
        vec = np.array([1.0, 0.0])
        retriever._tool_embeddings = {n: vec.copy() for n in tool_names}
        with patch.object(retriever, "_get_embedding", return_value=vec):
            result = retriever.retrieve_tools("query", tools, always_on=[], top_k=3)
        assert len(result) == 3

    def test_cosine_similarity_ordering(self, retriever):
        """Higher-similarity tools should appear before lower ones."""
        tools = self._make_tools(["best", "good", "ok"])
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
