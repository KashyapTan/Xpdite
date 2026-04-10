"""
Approval History Manager.

Manages the exec-approvals.json file for the "on-miss" ask level.
When a user clicks "Allow & Remember", the command signature is saved
so it auto-approves next time.

File location: user_data/exec-approvals.json
"""

import json
import hashlib
import os
import time
import threading
from pathlib import Path

from .command_analysis import _extract_shell_signature


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_APPROVALS_FILE = str(_PROJECT_ROOT / "user_data" / "exec-approvals.json")

# In-memory cache + lock to avoid repeated file I/O and race conditions (M24, M25)
_approvals_cache: dict | None = None
_approvals_lock = threading.Lock()


def _load_approvals() -> dict:
    """Load the approvals file, using an in-memory cache when available."""
    global _approvals_cache
    if _approvals_cache is not None:
        return _approvals_cache

    if not os.path.exists(_APPROVALS_FILE):
        _approvals_cache = {"approvals": []}
        return _approvals_cache

    try:
        with open(_APPROVALS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "approvals" not in data:
                data["approvals"] = []
            _approvals_cache = data
            return _approvals_cache
    except (json.JSONDecodeError, IOError):
        _approvals_cache = {"approvals": []}
        return _approvals_cache


def _save_approvals(data: dict):
    """Save the approvals file."""
    os.makedirs(os.path.dirname(_APPROVALS_FILE), exist_ok=True)
    with open(_APPROVALS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _compute_hash(command_signature: str) -> str:
    """Compute a stable hash for a command signature."""
    return hashlib.sha256(command_signature.encode("utf-8")).hexdigest()[:16]


def _normalize_command(command: str, shell: str | None = None) -> str:
    """
    Normalize a command to a signature for approval matching.

    Extracts a stable command prefix so remembered approvals survive
    differences in file paths, URLs, and other volatile arguments.
    """
    if not command.strip():
        return command
    shell_name = "powershell" if (shell or "").strip().lower() == "powershell" else "bash"
    return _extract_shell_signature(command, shell_name)


def is_command_approved(command: str, shell: str | None = None) -> bool:
    """
    Check if a command (or its normalized signature) has been
    previously approved and remembered.
    """
    with _approvals_lock:
        data = _load_approvals()
        signature = _normalize_command(command, shell=shell)
        sig_hash = _compute_hash(signature)

        return any(a["hash"] == sig_hash for a in data["approvals"])


def remember_approval(command: str, shell: str | None = None):
    """
    Save a command's approval so future identical commands auto-approve.
    Called when user clicks "Allow & Remember".
    """
    global _approvals_cache
    with _approvals_lock:
        data = _load_approvals()
        signature = _normalize_command(command, shell=shell)
        sig_hash = _compute_hash(signature)

        # Don't duplicate
        if any(a["hash"] == sig_hash for a in data["approvals"]):
            return

        data["approvals"].append({
            "hash": sig_hash,
            "command_signature": signature,
            "approved_at": time.time(),
        })

        _save_approvals(data)
        _approvals_cache = data


def get_approval_count() -> int:
    """Return the number of remembered approvals."""
    with _approvals_lock:
        data = _load_approvals()
        return len(data["approvals"])


def clear_approvals():
    """Clear all remembered approvals."""
    global _approvals_cache
    with _approvals_lock:
        _save_approvals({"approvals": []})
        _approvals_cache = None
