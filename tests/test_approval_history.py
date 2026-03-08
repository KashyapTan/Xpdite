"""Tests for approval_history — normalize, remember, check, clear."""

import os
import json
import pytest

from source.services.approval_history import (
    _normalize_command,
    _compute_hash,
    is_command_approved,
    remember_approval,
    get_approval_count,
    clear_approvals,
)
import source.services.approval_history as ah_mod


class TestNormalizeCommand:
    # ---- Two-word prefixed commands ----

    def test_npm_install(self):
        assert _normalize_command("npm install foo bar") == "npm install"

    def test_npx_command(self):
        assert _normalize_command("npx create-react-app my-app") == "npx create-react-app"

    def test_pip_install(self):
        assert _normalize_command("pip install requests") == "pip install"

    def test_git_status(self):
        assert _normalize_command("git status") == "git status"

    def test_git_commit_with_flags(self):
        assert _normalize_command("git commit -m 'msg'") == "git commit"

    def test_docker_build(self):
        assert _normalize_command("docker build -t img .") == "docker build"

    def test_cargo_build(self):
        assert _normalize_command("cargo build --release") == "cargo build"

    def test_uv_add(self):
        assert _normalize_command("uv add pytest") == "uv add"

    # ---- Single-token (non-prefixed) commands ----

    def test_python_returns_first_token(self):
        assert _normalize_command("python script.py arg1") == "python"

    def test_ls_returns_first_token(self):
        assert _normalize_command("ls -la") == "ls"

    def test_single_word_command(self):
        assert _normalize_command("whoami") == "whoami"

    # ---- Edge cases ----

    def test_leading_trailing_whitespace(self):
        assert _normalize_command("  git push  ") == "git push"

    def test_empty_string(self):
        result = _normalize_command("")
        assert result == ""

    def test_whitespace_only(self):
        result = _normalize_command("   ")
        # Empty parts → returns the original (stripped) command
        assert result == "   "

    def test_prefixed_command_with_only_prefix(self):
        """e.g. just 'git' with no subcommand — len(parts) == 1."""
        assert _normalize_command("git") == "git"


# ------------------------------------------------------------------
# _compute_hash
# ------------------------------------------------------------------


class TestComputeHash:
    def test_returns_hex_string(self):
        h = _compute_hash("git push")
        assert isinstance(h, str)
        assert len(h) == 16  # truncated SHA256

    def test_deterministic(self):
        assert _compute_hash("npm install") == _compute_hash("npm install")

    def test_different_inputs(self):
        assert _compute_hash("git push") != _compute_hash("git pull")


# ------------------------------------------------------------------
# Integration: remember / check / clear (with temp file)
# ------------------------------------------------------------------


@pytest.fixture(autouse=False)
def approval_file(tmp_path, monkeypatch):
    """Redirect approval persistence to a temp file and reset cache."""
    path = str(tmp_path / "test-approvals.json")
    monkeypatch.setattr(ah_mod, "_APPROVALS_FILE", path)
    monkeypatch.setattr(ah_mod, "_approvals_cache", None)
    return path


class TestApprovalIntegration:
    def test_remember_and_check(self, approval_file):
        assert is_command_approved("git push origin main") is False
        remember_approval("git push origin main")
        assert is_command_approved("git push origin main") is True
        # Same normalized signature, different args
        assert is_command_approved("git push other-branch") is True

    def test_remember_idempotent(self, approval_file):
        remember_approval("npm install react")
        remember_approval("npm install react")
        assert get_approval_count() == 1

    def test_clear_approvals(self, approval_file):
        remember_approval("git commit -m fix")
        remember_approval("npm install")
        assert get_approval_count() == 2
        clear_approvals()
        assert get_approval_count() == 0
        assert is_command_approved("git commit") is False

    def test_count_increments(self, approval_file):
        assert get_approval_count() == 0
        remember_approval("python main.py")
        assert get_approval_count() == 1
        remember_approval("node server.js")
        assert get_approval_count() == 2

    def test_file_created_on_remember(self, approval_file):
        assert not os.path.exists(approval_file)
        remember_approval("whoami")
        assert os.path.exists(approval_file)

    def test_persists_to_file(self, approval_file):
        remember_approval("cargo build")
        with open(approval_file, "r") as f:
            data = json.load(f)
        assert len(data["approvals"]) == 1
        assert data["approvals"][0]["command_signature"] == "cargo build"

    def test_no_sensitive_data_in_hash(self, approval_file):
        """Hash should not contain the raw command."""
        remember_approval("secret-tool --password=hunter2")
        with open(approval_file, "r") as f:
            data = json.load(f)
        entry = data["approvals"][0]
        assert "hunter2" not in entry["hash"]
