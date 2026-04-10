"""Tests for mcp_servers/servers/grep/server.py."""

import json
import os
from pathlib import Path

import pytest

from mcp_servers.servers.grep import server as grep_server


def _parse_result(result: str) -> dict:
    return json.loads(result)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture()
def grep_sandbox(monkeypatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(grep_server, "BASE_PATH", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestGrepFiles:
    def test_content_mode_returns_context_lines(self, grep_sandbox: Path):
        _write_text(
            grep_sandbox / "src" / "app.py",
            "line 1\nbefore line\nneedle here\nafter line\nline 5\n",
        )

        payload = _parse_result(
            grep_server.grep_files(
                "needle",
                file_glob="**/*.py",
                context_lines=1,
                output_mode="content",
            )
        )

        assert payload["total_matches"] == 1
        assert payload["files_searched"] == 1
        assert payload["matches"][0]["file"] == "src/app.py"
        assert payload["matches"][0]["line"] == 3
        assert payload["matches"][0]["context_before"] == ["before line"]
        assert payload["matches"][0]["context_after"] == ["after line"]
        assert payload["truncated"] is False

    def test_default_mode_returns_matching_files(self, grep_sandbox: Path):
        older = grep_sandbox / "older.py"
        newer = grep_sandbox / "newer.py"
        _write_text(older, "needle\n")
        _write_text(newer, "needle\n")
        older_time = 1_700_000_000
        newer_time = older_time + 60
        os.utime(older, (older_time, older_time))
        os.utime(newer, (newer_time, newer_time))

        payload = _parse_result(grep_server.grep_files("needle", file_glob="**/*.py"))

        assert payload["mode"] == "files_with_matches"
        assert payload["files"] == ["newer.py", "older.py"]
        assert payload["total_files"] == 2

    def test_regex_match(self, grep_sandbox: Path):
        _write_text(grep_sandbox / "models.py", "class Example:\n    pass\n")

        payload = _parse_result(
            grep_server.grep_files(
                r"class\s+\w+",
                file_glob="**/*.py",
                is_regex=True,
                output_mode="content",
            )
        )

        assert payload["total_matches"] == 1
        assert payload["matches"][0]["match"] == "class Example:"
        assert payload["is_regex"] is True

    def test_case_insensitive_match(self, grep_sandbox: Path):
        _write_text(grep_sandbox / "README.txt", "Needle value\n")

        payload = _parse_result(
            grep_server.grep_files(
                "needle",
                file_glob="**/*.txt",
                case_sensitive=False,
                output_mode="content",
            )
        )

        assert payload["total_matches"] == 1
        assert payload["matches"][0]["file"] == "README.txt"

    def test_type_filter_restricts_files(self, grep_sandbox: Path):
        _write_text(grep_sandbox / "a.py", "needle\n")
        _write_text(grep_sandbox / "b.ts", "needle\n")

        payload = _parse_result(grep_server.grep_files("needle", type="py"))

        assert payload["files"] == ["a.py"]
        assert payload["files_searched"] == 1

    def test_path_can_be_single_file(self, grep_sandbox: Path):
        target = grep_sandbox / "src" / "only.py"
        _write_text(target, "needle\n")

        payload = _parse_result(
            grep_server.grep_files("needle", path=str(target), output_mode="content")
        )

        assert payload["matches"][0]["file"] == "only.py"
        assert payload["total_matches"] == 1

    def test_glob_alias_conflict_returns_structured_error(self, grep_sandbox: Path):
        payload = _parse_result(
            grep_server.grep_files(
                "needle",
                file_glob="**/*.py",
                glob="**/*.ts",
            )
        )

        assert payload["matches"] == []
        assert payload["error"]["code"] == "invalid_file_glob"

    def test_binary_file_is_skipped(self, grep_sandbox: Path):
        (grep_sandbox / "binary.bin").write_bytes(b"\xff\xfe\x00\x00")
        _write_text(grep_sandbox / "text.txt", "needle\n")

        payload = _parse_result(grep_server.grep_files("needle", output_mode="content"))

        assert payload["total_matches"] == 1
        assert payload["skipped_binary_files"] == 1
        assert payload["matches"][0]["file"] == "text.txt"

    def test_large_file_is_skipped(self, grep_sandbox: Path):
        large_path = grep_sandbox / "large.txt"
        large_path.write_text("a" * 1_000_001, encoding="utf-8")

        payload = _parse_result(grep_server.grep_files("a", output_mode="content"))

        assert payload["total_matches"] == 0
        assert payload["skipped_large_files"] == 1
        assert payload["files_searched"] == 0

    def test_invalid_regex_returns_structured_error(self, grep_sandbox: Path):
        payload = _parse_result(grep_server.grep_files("[", is_regex=True))

        assert payload["total_matches"] == 0
        assert payload["error"]["code"] == "invalid_regex"

    def test_rejects_parent_directory_file_glob(self, grep_sandbox: Path):
        payload = _parse_result(
            grep_server.grep_files("needle", file_glob="../*.txt")
        )

        assert payload["matches"] == []
        assert payload["error"]["code"] == "invalid_file_glob"

    def test_regex_timeout_returns_structured_error(
        self,
        grep_sandbox: Path,
        monkeypatch,
    ):
        _write_text(grep_sandbox / "timeout.txt", "needle\n")

        class _TimeoutMatcher:
            def search(self, _line: str, timeout: float | None = None):
                raise TimeoutError("timed out")

        monkeypatch.setattr(
            grep_server.regexlib,
            "compile",
            lambda _pattern, _flags=0: _TimeoutMatcher(),
        )

        payload = _parse_result(
            grep_server.grep_files(
                "needle",
                file_glob="**/*.txt",
                is_regex=True,
                output_mode="content",
            )
        )

        assert payload["truncated"] is True
        assert payload["truncation_reason"] == "regex_timeout"
        assert payload["error"]["code"] == "regex_timeout"

    def test_count_mode_supports_offset_and_head_limit(self, grep_sandbox: Path):
        a_file = grep_sandbox / "a.py"
        b_file = grep_sandbox / "b.py"
        c_file = grep_sandbox / "c.py"
        _write_text(a_file, "needle\nneedle\n")
        _write_text(b_file, "needle\n")
        _write_text(c_file, "needle\nneedle\nneedle\n")
        base_time = 1_700_000_000
        os.utime(a_file, (base_time + 60, base_time + 60))
        os.utime(b_file, (base_time + 30, base_time + 30))
        os.utime(c_file, (base_time + 90, base_time + 90))

        payload = _parse_result(
            grep_server.grep_files(
                "needle",
                file_glob="**/*.py",
                output_mode="count",
                head_limit=1,
                offset=1,
            )
        )

        assert payload["mode"] == "count"
        assert payload["counts"] == [{"file": "b.py", "count": 1}]
        assert payload["applied_limit"] == 1
        assert payload["applied_offset"] == 1
        assert payload["truncated"] is True

    def test_skips_vcs_directories_even_when_hidden_files_allowed(
        self,
        grep_sandbox: Path,
    ):
        _write_text(grep_sandbox / ".git" / "hooks" / "pre-commit", "needle\n")
        _write_text(grep_sandbox / ".github" / "workflow.py", "needle\n")

        payload = _parse_result(
            grep_server.grep_files(
                "needle",
                file_glob="**/*",
                include_hidden=True,
            )
        )

        assert payload["files"] == [".github/workflow.py"]

    def test_multiline_regex_search(self, grep_sandbox: Path):
        _write_text(
            grep_sandbox / "sample.txt",
            "alpha\nbeta\ngamma\n",
        )

        payload = _parse_result(
            grep_server.grep_files(
                r"alpha\s+beta",
                path="sample.txt",
                is_regex=True,
                multiline=True,
                output_mode="content",
            )
        )

        assert payload["total_matches"] == 1
        assert payload["matches"][0]["line"] == 1
        assert payload["matches"][0]["end_line"] == 2

    def test_long_lines_are_truncated_in_output(self, grep_sandbox: Path):
        _write_text(grep_sandbox / "minified.js", f"{'a' * 700}needle\n")

        payload = _parse_result(
            grep_server.grep_files("needle", path="minified.js", output_mode="content")
        )

        assert payload["total_matches"] == 1
        assert payload["matches"][0]["match"].endswith("...")
