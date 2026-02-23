"""Shared pytest fixtures."""

import os
import sys
import tempfile
import pytest

# Ensure `source` package is importable from the repo root
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
