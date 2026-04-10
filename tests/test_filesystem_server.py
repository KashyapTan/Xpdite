"""Tests for mcp_servers/servers/filesystem/server.py."""
from pathlib import Path

import pytest

from mcp_servers.servers.filesystem import server as filesystem_server


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture()
def filesystem_sandbox(monkeypatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(filesystem_server, "BASE_PATH", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestFilesystemSandbox:
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
