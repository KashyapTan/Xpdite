"""Shared pytest fixtures."""
# uv run python -m pytest tests/ -v
import os
import sys
import pytest
from unittest.mock import MagicMock

# Ensure `source` package is importable from the repo root
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# ---------------------------------------------------------------------------
# Break the single circular import that breaks all tests.
#
# The cycle is:
#   mcp_integration.handlers (A, currently loading)
#     → terminal_executor → services.terminal → services.__init__
#     → conversations → llm.__init__ → llm.ollama_provider
#     → mcp_integration.handlers  ← re-imports partially-loaded (A) → ImportError
#
# Stubbing ONLY this one leaf module in sys.modules before pytest collects any
# test file means every `from ..mcp_integration.handlers import ...` resolves
# to a MagicMock rather than the half-initialized real module.
#
# We do NOT stub source.mcp_integration itself so the real package stays
# importable — test_retriever.py and others that import real submodules (e.g.
# source.mcp_integration.retriever) continue to work correctly.
#
# setdefault() ensures we never overwrite a real module if one is already
# loaded (e.g. in future integration tests that bootstrap the full stack).
# ---------------------------------------------------------------------------
_handlers_stub = MagicMock()
_handlers_stub.handle_mcp_tool_calls = MagicMock()
sys.modules.setdefault("source.mcp_integration.handlers", _handlers_stub)
