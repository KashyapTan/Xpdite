"""Tests for mcp_servers/servers/glob/server.py."""

import json
import os
from pathlib import Path

import pytest

from mcp_servers.servers.glob import server as glob_server


def _parse_result(result: str) -> dict:
    return json.loads(result)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture()
def glob_sandbox(monkeypatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(glob_server, "BASE_PATH", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestGlobFiles:
    def test_matches_flat_and_nested_paths(self, glob_sandbox: Path):
        root = glob_sandbox / "root.py"
        nested = glob_sandbox / "src" / "nested.py"
        _write_text(root, "print('root')\n")
        _write_text(nested, "print('nested')\n")
        _write_text(glob_sandbox / "src" / "notes.txt", "notes\n")
        root_time = 1_700_000_000
        nested_time = root_time + 60
        root.touch()
        nested.touch()
        os.utime(root, (root_time, root_time))
        os.utime(nested, (nested_time, nested_time))

        payload = _parse_result(glob_server.glob_files("**/*.py", path="."))

        assert payload["matches"] == ["src/nested.py", "root.py"]
        assert payload["available_matches"] == 2
        assert payload["truncated"] is False
        assert "error" not in payload

    def test_hidden_files_are_excluded_by_default_and_optional(
        self,
        glob_sandbox: Path,
    ):
        _write_text(glob_sandbox / ".hidden" / "secret.py", "print('secret')\n")

        hidden_off = _parse_result(glob_server.glob_files("**/*.py"))
        hidden_on = _parse_result(
            glob_server.glob_files("**/*.py", include_hidden=True)
        )

        assert hidden_off["matches"] == []
        assert hidden_on["matches"] == [".hidden/secret.py"]

    def test_exclude_filter_removes_matching_paths(self, glob_sandbox: Path):
        _write_text(glob_sandbox / "src" / "keep.py", "print('keep')\n")
        _write_text(glob_sandbox / "src" / "__pycache__" / "drop.py", "compiled\n")

        payload = _parse_result(
            glob_server.glob_files(
                "**/*.py",
                path="src",
                exclude="**/__pycache__/**",
            )
        )

        assert payload["matches"] == ["keep.py"]

    def test_supports_pagination(self, glob_sandbox: Path):
        for index in range(5):
            _write_text(glob_sandbox / "many" / f"file_{index}.txt", "x\n")

        payload = _parse_result(
            glob_server.glob_files("**/*.txt", head_limit=2, offset=1)
        )

        assert payload["total"] == 2
        assert payload["available_matches"] == 5
        assert payload["applied_limit"] == 2
        assert payload["applied_offset"] == 1
        assert payload["truncated"] is True

    def test_base_path_alias_conflict_returns_error(self, glob_sandbox: Path):
        payload = _parse_result(
            glob_server.glob_files("**/*.py", path="src", base_path="tests")
        )

        assert payload["matches"] == []
        assert payload["error"]["code"] == "invalid_path"

    def test_sandbox_escape_returns_structured_error(self, glob_sandbox: Path):
        payload = _parse_result(
            glob_server.glob_files("**/*.py", path=str(glob_sandbox.parent))
        )

        assert payload["matches"] == []
        assert payload["truncated"] is False
        assert payload["error"]["code"] == "sandbox_violation"

    def test_rejects_parent_directory_glob_pattern(self, glob_sandbox: Path):
        payload = _parse_result(glob_server.glob_files("../*.py"))

        assert payload["matches"] == []
        assert payload["error"]["code"] == "invalid_pattern"

    def test_rejects_drive_qualified_glob_pattern(self, glob_sandbox: Path):
        payload = _parse_result(glob_server.glob_files("C:*.py"))

        assert payload["matches"] == []
        assert payload["error"]["code"] == "invalid_pattern"
