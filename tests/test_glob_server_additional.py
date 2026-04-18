import json
from pathlib import Path

import pytest

from mcp_servers.servers.glob import server as glob_server


def _parse_result(payload: str) -> dict:
    return json.loads(payload)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture()
def glob_root(monkeypatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(glob_server, "BASE_PATH", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_apply_offset_limit_treats_zero_as_unlimited():
    items, truncated, applied_limit = glob_server._apply_offset_limit(
        ["a", "b", "c"],
        offset=1,
        limit=0,
    )

    assert items == ["b", "c"]
    assert truncated is False
    assert applied_limit is None


def test_resolve_search_path_supports_legacy_base_path_alias():
    assert glob_server._resolve_search_path(".", "src") == ("src", None)
    assert glob_server._resolve_search_path("src", "tests")[1] is not None


def test_glob_files_reports_missing_and_non_directory_paths(glob_root: Path):
    missing = _parse_result(glob_server.glob_files("**/*.py", path="missing"))
    _write_text(glob_root / "file.txt", "hello")
    not_dir = _parse_result(glob_server.glob_files("**/*.txt", path="file.txt"))

    assert missing["error"]["code"] == "path_not_found"
    assert not_dir["error"]["code"] == "not_a_directory"


def test_glob_files_rejects_invalid_exclude_pattern(glob_root: Path):
    payload = _parse_result(
        glob_server.glob_files("**/*.py", exclude="../private/**/*.py")
    )

    assert payload["error"]["code"] == "invalid_exclude"


def test_glob_files_marks_result_cap_truncation(monkeypatch, glob_root: Path):
    monkeypatch.setattr(glob_server, "_GLOB_SCAN_CAP", 2)
    for index in range(3):
        _write_text(glob_root / f"file_{index}.txt", "x")

    payload = _parse_result(glob_server.glob_files("**/*.txt", head_limit=0))

    assert set(payload["matches"]) == {"file_0.txt", "file_1.txt"}
    assert payload["available_matches"] == 2
    assert payload["truncated"] is True
    assert payload["truncation_reason"] == "result_cap"


def test_glob_files_reports_filesystem_errors(monkeypatch, glob_root: Path):
    _write_text(glob_root / "file.txt", "x")
    monkeypatch.setattr(
        glob_server.globlib,
        "iglob",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk error")),
    )

    payload = _parse_result(glob_server.glob_files("**/*.txt"))

    assert payload["error"]["code"] == "filesystem_error"
