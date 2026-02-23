"""Tests for _normalize_command in approval_history."""

from source.services.approval_history import _normalize_command


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
