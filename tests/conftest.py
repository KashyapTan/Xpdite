"""Shared pytest fixtures."""
# uv run python -m pytest tests/ -v
import os
import sys

# Ensure `source` package is importable from the repo root
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
