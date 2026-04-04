"""Tests for mcp_servers/servers/filesystem/server.py."""

import json
from pathlib import Path

import pytest

from mcp_servers.servers.filesystem import server as filesystem_server


def _parse_result(result: str) -> dict:
    return json.loads(result)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture()
def filesystem_sandbox(monkeypatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(filesystem_server, "BASE_PATH", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestGlobFiles:
    def test_safe_path_treats_cross_drive_commonpath_as_permission_denial(
        self,
        filesystem_sandbox: Path,
        monkeypatch,
    ):
        monkeypatch.setattr(
            filesystem_server.os.path,
            "commonpath",
            lambda _paths: (_ for _ in ()).throw(
                ValueError("Paths don't have the same drive")
            ),
        )

        with pytest.raises(PermissionError):
            filesystem_server._get_safe_path(str(filesystem_sandbox / "root.py"))

    def test_matches_flat_and_nested_paths(self, filesystem_sandbox: Path):
        _write_text(filesystem_sandbox / "root.py", "print('root')\n")
        _write_text(filesystem_sandbox / "src" / "nested.py", "print('nested')\n")
        _write_text(filesystem_sandbox / "src" / "notes.txt", "notes\n")

        payload = _parse_result(filesystem_server.glob_files("**/*.py"))

        assert payload["matches"] == ["root.py", "src/nested.py"]
        assert payload["total"] == 2
        assert payload["truncated"] is False
        assert "error" not in payload

    def test_hidden_files_are_excluded_by_default_and_optional(
        self, filesystem_sandbox: Path
    ):
        _write_text(filesystem_sandbox / ".hidden" / "secret.py", "print('secret')\n")

        hidden_off = _parse_result(filesystem_server.glob_files("**/*.py"))
        hidden_on = _parse_result(
            filesystem_server.glob_files("**/*.py", include_hidden=True)
        )

        assert hidden_off["matches"] == []
        assert hidden_on["matches"] == [".hidden/secret.py"]

    def test_truncates_at_500_matches(self, filesystem_sandbox: Path):
        for index in range(501):
            _write_text(filesystem_sandbox / "many" / f"file_{index:03}.txt", "x\n")

        payload = _parse_result(filesystem_server.glob_files("**/*.txt"))

        assert payload["total"] == 500
        assert payload["truncated"] is True
        assert payload["truncation_reason"] == "result_limit"

    def test_sandbox_escape_returns_structured_error(self, filesystem_sandbox: Path):
        payload = _parse_result(
            filesystem_server.glob_files(
                "**/*.py", base_path=str(filesystem_sandbox.parent)
            )
        )

        assert payload["matches"] == []
        assert payload["truncated"] is False
        assert payload["error"]["code"] == "sandbox_violation"

    def test_rejects_parent_directory_glob_pattern(self, filesystem_sandbox: Path):
        payload = _parse_result(filesystem_server.glob_files("../*.py"))

        assert payload["matches"] == []
        assert payload["error"]["code"] == "invalid_pattern"

    def test_rejects_drive_qualified_glob_pattern(self, filesystem_sandbox: Path):
        payload = _parse_result(filesystem_server.glob_files("C:*.py"))

        assert payload["matches"] == []
        assert payload["error"]["code"] == "invalid_pattern"


class TestGrepFiles:
    def test_literal_match_returns_context_lines(self, filesystem_sandbox: Path):
        _write_text(
            filesystem_sandbox / "src" / "app.py",
            "line 1\nbefore line\nneedle here\nafter line\nline 5\n",
        )

        payload = _parse_result(
            filesystem_server.grep_files(
                "needle",
                file_glob="**/*.py",
                context_lines=1,
            )
        )

        assert payload["total_matches"] == 1
        assert payload["files_searched"] == 1
        assert payload["matches"][0]["file"] == "src/app.py"
        assert payload["matches"][0]["line"] == 3
        assert payload["matches"][0]["context_before"] == ["before line"]
        assert payload["matches"][0]["context_after"] == ["after line"]
        assert payload["truncated"] is False
        assert "error" not in payload

    def test_regex_match(self, filesystem_sandbox: Path):
        _write_text(filesystem_sandbox / "models.py", "class Example:\n    pass\n")

        payload = _parse_result(
            filesystem_server.grep_files(
                r"class\s+\w+",
                file_glob="**/*.py",
                is_regex=True,
            )
        )

        assert payload["total_matches"] == 1
        assert payload["matches"][0]["match"] == "class Example:"
        assert payload["is_regex"] is True

    def test_case_insensitive_match(self, filesystem_sandbox: Path):
        _write_text(filesystem_sandbox / "README.txt", "Needle value\n")

        payload = _parse_result(
            filesystem_server.grep_files(
                "needle",
                file_glob="**/*.txt",
                case_sensitive=False,
            )
        )

        assert payload["total_matches"] == 1
        assert payload["matches"][0]["file"] == "README.txt"

    def test_file_glob_restricts_files_searched(self, filesystem_sandbox: Path):
        _write_text(filesystem_sandbox / "a.py", "needle\n")
        _write_text(filesystem_sandbox / "b.txt", "needle\n")

        payload = _parse_result(
            filesystem_server.grep_files(
                "needle",
                file_glob="**/*.py",
            )
        )

        assert payload["total_matches"] == 1
        assert payload["files_searched"] == 1
        assert payload["files_traversed"] == 1
        assert payload["matches"][0]["file"] == "a.py"

    def test_binary_file_is_skipped(self, filesystem_sandbox: Path):
        (filesystem_sandbox / "binary.bin").write_bytes(b"\xff\xfe\x00\x00")
        _write_text(filesystem_sandbox / "text.txt", "needle\n")

        payload = _parse_result(filesystem_server.grep_files("needle"))

        assert payload["total_matches"] == 1
        assert payload["skipped_binary_files"] == 1
        assert payload["matches"][0]["file"] == "text.txt"

    def test_large_file_is_skipped(self, filesystem_sandbox: Path):
        large_path = filesystem_sandbox / "large.txt"
        large_path.write_text("a" * 1_000_001, encoding="utf-8")

        payload = _parse_result(filesystem_server.grep_files("a"))

        assert payload["total_matches"] == 0
        assert payload["skipped_large_files"] == 1
        assert payload["files_searched"] == 0

    def test_invalid_regex_returns_structured_error(self, filesystem_sandbox: Path):
        payload = _parse_result(filesystem_server.grep_files("[", is_regex=True))

        assert payload["total_matches"] == 0
        assert payload["error"]["code"] == "invalid_regex"

    def test_rejects_parent_directory_file_glob(self, filesystem_sandbox: Path):
        payload = _parse_result(
            filesystem_server.grep_files("needle", file_glob="../*.txt")
        )

        assert payload["matches"] == []
        assert payload["error"]["code"] == "invalid_file_glob"

    def test_regex_timeout_returns_structured_error(
        self,
        filesystem_sandbox: Path,
        monkeypatch,
    ):
        _write_text(filesystem_sandbox / "timeout.txt", "needle\n")

        class _TimeoutMatcher:
            def search(self, _line: str, timeout: float | None = None):
                raise TimeoutError("timed out")

        monkeypatch.setattr(
            filesystem_server.regexlib,
            "compile",
            lambda _pattern, _flags=0: _TimeoutMatcher(),
        )

        payload = _parse_result(
            filesystem_server.grep_files(
                "needle",
                file_glob="**/*.txt",
                is_regex=True,
            )
        )

        assert payload["truncated"] is True
        assert payload["truncation_reason"] == "regex_timeout"
        assert payload["error"]["code"] == "regex_timeout"

    def test_truncates_at_max_results(self, filesystem_sandbox: Path):
        _write_text(
            filesystem_sandbox / "src" / "multi.py",
            "needle one\nneedle two\nneedle three\n",
        )

        payload = _parse_result(
            filesystem_server.grep_files(
                "needle",
                file_glob="**/*.py",
                max_results=2,
            )
        )

        assert payload["total_matches"] == 2
        assert payload["truncated"] is True
        assert payload["truncation_reason"] == "max_results"

    def test_empty_directory_returns_empty_results(self, filesystem_sandbox: Path):
        payload = _parse_result(filesystem_server.grep_files("needle"))

        assert payload["matches"] == []
        assert payload["total_matches"] == 0
        assert payload["truncated"] is False
        assert "error" not in payload

    def test_zero_match_returns_empty_results(self, filesystem_sandbox: Path):
        _write_text(filesystem_sandbox / "file.txt", "nothing to see here\n")

        payload = _parse_result(filesystem_server.grep_files("needle"))

        assert payload["matches"] == []
        assert payload["total_matches"] == 0
        assert payload["files_searched"] == 1
        assert payload["truncated"] is False


class TestReadFilePagination:
    def test_text_file_returns_paginated_envelope(self, filesystem_sandbox: Path):
        _write_text(filesystem_sandbox / "app.py", "abcdefghi")

        payload = filesystem_server.read_file("app.py")
        assert isinstance(payload, dict)
        assert payload["content"] == "abcdefghi"
        assert payload["total_chars"] == 9
        assert payload["offset"] == 0
        assert payload["chars_returned"] == 9
        assert payload["has_more"] is False
        assert payload["next_offset"] is None
        assert payload["chunk_summary"] == "Showing characters 0-9 of 9 (100%)"
        assert payload["file_info"]["format"] == "py"
        assert payload["file_info"]["file_size_bytes"] > 0
        assert payload["file_info"]["extracted_images"] == []

    def test_text_file_multi_chunk_with_next_offset(self, filesystem_sandbox: Path):
        _write_text(filesystem_sandbox / "long.txt", "abcdefghij")

        first = filesystem_server.read_file("long.txt", max_chars=4)
        assert first["content"] == "abcd"
        assert first["total_chars"] == 10
        assert first["has_more"] is True
        assert first["next_offset"] == 4
        assert "file_info" in first

        second = filesystem_server.read_file(
            "long.txt", offset=first["next_offset"], max_chars=4
        )
        assert second["content"] == "efgh"
        assert second["offset"] == 4
        assert second["has_more"] is True
        assert second["next_offset"] == 8
        assert "file_info" not in second

        third = filesystem_server.read_file(
            "long.txt", offset=second["next_offset"], max_chars=4
        )
        assert third["content"] == "ij"
        assert third["offset"] == 8
        assert third["chars_returned"] == 2
        assert third["has_more"] is False
        assert third["next_offset"] is None
        assert "file_info" not in third

    def test_offset_beyond_eof_returns_empty_chunk(self, filesystem_sandbox: Path):
        _write_text(filesystem_sandbox / "short.txt", "abc")

        payload = filesystem_server.read_file("short.txt", offset=100)
        assert payload["content"] == ""
        assert payload["chars_returned"] == 0
        assert payload["has_more"] is False
        assert payload["next_offset"] is None
        assert "beyond end of file" in payload["chunk_summary"]

    def test_negative_offset_is_treated_as_zero(self, filesystem_sandbox: Path):
        _write_text(filesystem_sandbox / "short.txt", "abcdef")

        payload = filesystem_server.read_file("short.txt", offset=-5, max_chars=3)
        assert payload["offset"] == 0
        assert payload["content"] == "abc"

    def test_non_positive_max_chars_uses_default(self, filesystem_sandbox: Path):
        _write_text(filesystem_sandbox / "short.txt", "abcdef")

        payload = filesystem_server.read_file("short.txt", max_chars=0)
        assert payload["content"] == "abcdef"
        assert payload["chars_returned"] == 6

    def test_empty_file_returns_valid_envelope(self, filesystem_sandbox: Path):
        _write_text(filesystem_sandbox / "empty.txt", "")

        payload = filesystem_server.read_file("empty.txt")
        assert payload["content"] == ""
        assert payload["total_chars"] == 0
        assert payload["chars_returned"] == 0
        assert payload["has_more"] is False
        assert payload["next_offset"] is None
        assert payload["chunk_summary"] == "Showing characters 0-0 of 0 (100%)"
        assert payload["file_info"]["format"] == "txt"

    def test_image_file_with_offset_returns_error(self, filesystem_sandbox: Path):
        from PIL import Image

        image_path = filesystem_sandbox / "photo.png"
        Image.new("RGB", (20, 20), color="red").save(image_path)

        result = filesystem_server.read_file("photo.png", offset=1)
        assert isinstance(result, str)
        assert "cannot be paginated" in result

    def test_image_file_without_offset_returns_image_payload(
        self, filesystem_sandbox: Path
    ):
        from PIL import Image

        image_path = filesystem_sandbox / "photo.png"
        Image.new("RGB", (20, 20), color="red").save(image_path)

        payload = filesystem_server.read_file("photo.png")
        assert isinstance(payload, dict)
        assert payload["type"] == "image"
        assert payload["media_type"] == "image/png"
        assert payload["width"] == 20
        assert payload["height"] == 20
        assert payload["data"]

    def test_unknown_extension_preserves_warning_prefix(self, filesystem_sandbox: Path):
        _write_text(filesystem_sandbox / "mystery.xyz", "alpha\nbeta\n")

        payload = filesystem_server.read_file("mystery.xyz")
        assert isinstance(payload, dict)
        assert payload["content"].startswith(
            "[Warning: Unknown file format, attempting text read]"
        )

    def test_archive_file_returns_paginated_envelope(self, filesystem_sandbox: Path):
        import zipfile

        archive_path = filesystem_sandbox / "archive.zip"
        with zipfile.ZipFile(archive_path, "w") as zf:
            zf.writestr("a.txt", "one")
            zf.writestr("b.txt", "two")

        payload = filesystem_server.read_file("archive.zip", max_chars=64)
        assert isinstance(payload, dict)
        assert "ZIP Archive Contents" in payload["content"]
        assert payload["total_chars"] >= payload["chars_returned"]
        assert payload["offset"] == 0
        assert "file_info" in payload
        assert payload["file_info"]["format"] == "zip"
