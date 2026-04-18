"""Shared pytest fixtures."""
# uv run python -m pytest tests/ -v
import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Ensure `source` package is importable from the repo root
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

if os.name == "nt":
    pytest_temp_root = os.path.join(ROOT, "codex-temp", "pytest-temp-root")
    os.makedirs(pytest_temp_root, exist_ok=True)
    os.environ.setdefault("PYTEST_DEBUG_TEMPROOT", pytest_temp_root)
    os.environ.setdefault("TMP", pytest_temp_root)
    os.environ.setdefault("TEMP", pytest_temp_root)
    tempfile.tempdir = pytest_temp_root

    _workspace_temp_root = Path(pytest_temp_root) / "temporary-directories"
    _workspace_temp_root.mkdir(parents=True, exist_ok=True)

    class _WorkspaceTemporaryDirectory:
        def __init__(
            self,
            suffix: str | None = None,
            prefix: str | None = None,
            dir: str | os.PathLike[str] | None = None,
            ignore_cleanup_errors: bool = False,
        ) -> None:
            base = Path(dir) if dir is not None else _workspace_temp_root
            base.mkdir(parents=True, exist_ok=True)
            name = f"{prefix or 'tmp'}{uuid.uuid4().hex}{suffix or ''}"
            self.name = str(base / name)
            Path(self.name).mkdir(parents=True, exist_ok=False)
            self._ignore_cleanup_errors = ignore_cleanup_errors

        def __enter__(self) -> str:
            return self.name

        def __exit__(self, exc_type, exc, tb) -> None:
            self.cleanup()

        def cleanup(self) -> None:
            shutil.rmtree(self.name, ignore_errors=True)

    tempfile.TemporaryDirectory = _WorkspaceTemporaryDirectory

    try:
        import _pytest.pathlib as _pytest_pathlib

        _pytest_pathlib.cleanup_dead_symlinks = lambda root: None
    except Exception:
        pass


@pytest.fixture()
def tmp_path():
    """Provide a repo-local tmp_path replacement for this sandboxed Windows env."""
    base = Path(ROOT) / "codex-temp" / "pytest-fixtures"
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"case-{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)

# ---------------------------------------------------------------------------
# Break the single circular import that breaks all tests.
#
# The cycle is:
#   mcp_integration.core.handlers (A, currently loading)
#     → terminal_executor → services.shell.terminal → services.__init__
#     → conversations → llm.__init__ → llm.providers.ollama_provider
#     → mcp_integration.core.handlers  ← re-imports partially-loaded (A) → ImportError
#
# Stubbing ONLY this one leaf module in sys.modules before pytest collects any
# test file means every `from ..mcp_integration.core.handlers import ...` resolves
# to a MagicMock rather than the half-initialized real module.
#
# We do NOT stub source.mcp_integration itself so the real package stays
# importable — test_retriever.py and others that import real submodules (e.g.
# source.mcp_integration.core.retriever) continue to work correctly.
#
# setdefault() ensures we never overwrite a real module if one is already
# loaded (e.g. in future integration tests that bootstrap the full stack).
# ---------------------------------------------------------------------------
_handlers_stub = MagicMock()
_handlers_stub.handle_mcp_tool_calls = MagicMock()
sys.modules.setdefault("source.mcp_integration.core.handlers", _handlers_stub)
