# Code Review — MCP Tool Retriever Refactor

## Scope

Reviewed files:

- `source/mcp_integration/retriever.py`
- `tests/test_retriever.py`
- `pyproject.toml`
- `uv.lock`

Reference docs:

- `Implementation_plans/mcp_tool_retriver_refactor.md`
- `CODE_REVIEW_GUIDE.md`

## Review Summary

Three focused review passes were run for correctness, security/resilience, and performance/quality, followed by a judge synthesis pass.

## Problems Found

### Fixed

1. **Redundant embedding flatten in `embed_tools()`**
   - Review finding: the active-entry rebuild path re-flattened embeddings that were already flattened when loaded from cache or freshly embedded.
   - Fix: removed the redundant flattening on append and reused the already-flattened vectors directly during index normalization.

2. **Missing explicit edge-case coverage for fallback paths**
   - Review finding: zero-norm and dimension-mismatch fallback behavior existed, but did not have dedicated tests.
   - Fix: added tests covering:
     - zero-norm tool embeddings being skipped during index rebuild
     - zero-norm query embeddings falling back to BM25-driven ranking
     - query/tool embedding dimension mismatch falling back to BM25-driven ranking

### Reviewed and Not Actioned

1. **BM25 snapshot reference safety**
   - Initial concern: `bm25_index = self._bm25_index` might race with concurrent index rebuilds.
   - Result: judged as a false positive. The retriever snapshots the object reference while holding the lock, and the BM25 object is replaced rather than mutated in place.

2. **Zero-norm tolerance in `_normalize_vector()`**
   - Initial suggestion: replace `norm == 0.0` with a tolerance check.
   - Result: not actioned. This was judged to be speculative hardening rather than a demonstrated defect in the current float32-based implementation.

## Final Verdict

**Ready for merge.**

The refactor matches the requested design: pre-normalized matrix cosine scoring, BM25 indexing with matched tokenization, RRF fusion with `k=10`, cosine tie-breaking, additive always-on tools, richer debug logging, dependency updates, and expanded tests.
