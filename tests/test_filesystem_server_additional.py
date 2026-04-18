from pathlib import Path
from types import SimpleNamespace

import pytest

from mcp_servers.servers.filesystem import server as filesystem_server


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture()
def filesystem_root(monkeypatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(filesystem_server, "BASE_PATH", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_read_file_reports_missing_directory_and_legacy_formats(filesystem_root: Path):
    _write_text(filesystem_root / "legacy.doc", "ignored")

    missing = filesystem_server.read_file("missing.txt")
    directory = filesystem_server.read_file(".")
    legacy = filesystem_server.read_file("legacy.doc")

    assert "was not found" in missing
    assert "is a directory, not a file" in directory
    assert "Legacy format '.doc' is not supported" in legacy


def test_read_file_reports_image_extractor_failures(monkeypatch, filesystem_root: Path):
    image_path = filesystem_root / "photo.png"
    image_path.write_bytes(b"fake")

    extractor = SimpleNamespace(
        _load_image_file=lambda _path: SimpleNamespace(data=None),
    )
    monkeypatch.setattr(filesystem_server, "_get_file_extractor", lambda: extractor)

    result = filesystem_server.read_file("photo.png")

    assert result == "Error: Failed to load image 'photo.png'"


def test_write_create_move_and_rename_report_common_errors(filesystem_root: Path):
    (filesystem_root / "folder").mkdir()
    _write_text(filesystem_root / "source.txt", "hello")
    _write_text(filesystem_root / "dest" / "source.txt", "existing")

    assert "already exists" in filesystem_server.create_folder(".", "folder")
    assert "directory path" in filesystem_server.write_file(".", "content")
    assert "does not exist" in filesystem_server.move_file("missing.txt", "dest")
    assert "not a valid directory" in filesystem_server.move_file("source.txt", "source.txt")
    assert "already exists" in filesystem_server.rename_file("source.txt", "source.txt")
