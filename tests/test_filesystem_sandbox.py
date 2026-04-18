import json
import os
from pathlib import Path

import pytest

from mcp_servers.servers.filesystem import sandbox as filesystem_sandbox
from mcp_servers.servers.filesystem import server as filesystem_server


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture()
def fs_root(monkeypatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(filesystem_server, "BASE_PATH", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_get_safe_path_rejects_escaping_base(fs_root: Path):
    inside = filesystem_sandbox.get_safe_path(str(fs_root / "file.txt"), str(fs_root))
    assert inside == os.path.realpath(fs_root / "file.txt")

    with pytest.raises(PermissionError):
        filesystem_sandbox.get_safe_path(str(fs_root.parent), str(fs_root))


def test_sandbox_helper_functions_cover_hidden_vcs_and_glob_behavior():
    assert json.loads(filesystem_sandbox.json_response({"ok": True})) == {"ok": True}
    assert filesystem_sandbox.build_error("bad", "nope") == {
        "code": "bad",
        "message": "nope",
    }
    assert filesystem_sandbox.to_display_path(Path("src") / "app.py") == "src/app.py"
    assert filesystem_sandbox.to_display_path(".") == "."
    assert filesystem_sandbox.has_hidden_part(Path(".secret") / "env") is True
    assert filesystem_sandbox.has_vcs_part(Path(".git") / "hooks") is True
    assert (
        filesystem_sandbox.should_skip_relative_path(".hidden/file.txt", include_hidden=False)
        is True
    )
    assert (
        filesystem_sandbox.should_skip_relative_path(".hidden/file.txt", include_hidden=True)
        is False
    )
    assert filesystem_sandbox.validate_relative_glob_pattern(
        str(Path.cwd() / "*.py"), "pattern"
    )
    assert filesystem_sandbox.validate_relative_glob_pattern("../*.py", "pattern")
    assert filesystem_sandbox.validate_relative_glob_pattern("C:*.py", "pattern")
    assert filesystem_sandbox.safe_mtime("missing-file.txt") == 0.0
    assert filesystem_sandbox.split_glob_patterns("*.py, *.ts {a,b}.txt") == [
        "*.py",
        "*.ts",
        "{a,b}.txt",
    ]
    assert filesystem_sandbox.path_matches_glob("root.py", "**/*.py") is True


def test_is_within_search_root_checks_real_paths(fs_root: Path):
    inside = fs_root / "src" / "app.py"
    outside = fs_root.parent / "outside.txt"
    inside.parent.mkdir(parents=True, exist_ok=True)
    inside.write_text("ok", encoding="utf-8")
    outside.write_text("nope", encoding="utf-8")

    assert filesystem_sandbox.is_within_search_root(str(inside), str(fs_root)) is True
    assert filesystem_sandbox.is_within_search_root(str(outside), str(fs_root)) is False


def test_list_directory_orders_entries_by_mtime(fs_root: Path):
    older = fs_root / "older.txt"
    newer = fs_root / "newer.txt"
    _write_text(older, "old")
    _write_text(newer, "new")
    base_time = 1_700_000_000
    os.utime(older, (base_time, base_time))
    os.utime(newer, (base_time + 60, base_time + 60))

    assert filesystem_server.list_directory(".") == ["newer.txt", "older.txt"]


def test_list_directory_reports_file_path_error(fs_root: Path):
    _write_text(fs_root / "note.txt", "hello")

    result = filesystem_server.list_directory("note.txt")

    assert result == [
        "Error: 'note.txt' is a file, not a directory. Use read_file to view it."
    ]


def test_write_file_create_folder_move_file_and_rename_file(fs_root: Path):
    assert (
        filesystem_server.create_folder(".", "docs")
        == "Success: Folder 'docs' created successfully at '.'."
    )
    assert filesystem_server.write_file("docs/readme.txt", "hello") == (
        "Success: Successfully wrote 5 characters to 'docs/readme.txt'."
    )

    moved = filesystem_server.move_file("docs/readme.txt", ".")
    renamed = filesystem_server.rename_file("readme.txt", "README.md")

    assert moved == "Success: Moved 'readme.txt' to '.'."
    assert renamed == "Success: Renamed 'readme.txt' to 'README.md'."
    assert (fs_root / "README.md").read_text(encoding="utf-8") == "hello"


def test_write_file_and_rename_file_reject_invalid_targets(fs_root: Path):
    result = filesystem_server.write_file("missing/file.txt", "hello")
    assert "Please use create_folder first." in result

    _write_text(fs_root / "source.txt", "hello")
    rename_result = filesystem_server.rename_file("source.txt", "nested/file.txt")
    assert "'new_name' must be a filename only" in rename_result


def test_move_file_refuses_to_overwrite_existing_destination(fs_root: Path):
    source_dir = fs_root / "src"
    dest_dir = fs_root / "dest"
    _write_text(source_dir / "data.txt", "source")
    _write_text(dest_dir / "data.txt", "existing")

    result = filesystem_server.move_file("src/data.txt", "dest")

    assert "Move aborted" in result
