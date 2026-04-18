import json
from pathlib import Path

import pytest

from mcp_servers.servers.grep import server as grep_server


def _parse_result(payload: str) -> dict:
    return json.loads(payload)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture()
def grep_root(monkeypatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(grep_server, "BASE_PATH", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_normalize_glob_filter_rejects_absolute_patterns():
    patterns, error = grep_server._normalize_glob_filter(
        "**/*",
        str(Path.cwd() / "*.py"),
    )

    assert patterns is None
    assert error["code"] == "invalid_file_glob"


def test_normalize_type_filter_rejects_unknown_type():
    extensions, error = grep_server._normalize_type_filter("protobuf")

    assert extensions is None
    assert error["code"] == "invalid_type"


def test_truncate_output_line_and_multiline_match_records():
    long_line = "x" * 600
    assert grep_server._truncate_output_line(long_line).endswith("...")

    matcher = grep_server.regexlib.compile(r"alpha\s+beta", grep_server.regexlib.DOTALL)
    records, count = grep_server._build_multiline_match_records(
        "zero\nalpha\nbeta\ngamma\n",
        matcher,
        display_path="sample.txt",
        context_lines=1,
    )

    assert count == 1
    assert records[0]["line"] == 2
    assert records[0]["end_line"] == 3
    assert records[0]["context_before"] == ["zero"]
    assert records[0]["context_after"] == ["gamma"]


def test_grep_files_validates_modes_and_offsets(grep_root: Path):
    invalid_mode = _parse_result(grep_server.grep_files("needle", output_mode="summary"))
    invalid_multiline = _parse_result(
        grep_server.grep_files("needle", multiline=True, is_regex=False)
    )
    invalid_offset = _parse_result(grep_server.grep_files("needle", offset=-1))

    assert invalid_mode["error"]["code"] == "invalid_output_mode"
    assert invalid_multiline["error"]["code"] == "invalid_multiline_mode"
    assert invalid_offset["error"]["code"] == "invalid_offset"


def test_grep_files_reports_missing_path_and_sandbox_violations(grep_root: Path):
    missing = _parse_result(grep_server.grep_files("needle", path="missing.txt"))
    outside = _parse_result(
        grep_server.grep_files("needle", path=str(grep_root.parent / "escape.txt"))
    )

    assert missing["error"]["code"] == "path_not_found"
    assert outside["error"]["code"] == "sandbox_violation"


def test_grep_files_marks_file_scan_cap(monkeypatch, grep_root: Path):
    monkeypatch.setattr(grep_server, "_GREP_MAX_FILES", 2)
    for index in range(3):
        _write_text(grep_root / f"file_{index}.txt", "needle\n")

    payload = _parse_result(grep_server.grep_files("needle", file_glob="**/*.txt"))

    assert payload["truncated"] is True
    assert payload["truncation_reason"] == "file_scan_cap"


def test_grep_files_reports_filesystem_errors(monkeypatch, grep_root: Path):
    _write_text(grep_root / "sample.txt", "needle\n")
    monkeypatch.setattr(
        grep_server,
        "get_safe_path",
        lambda _path, _base: (_ for _ in ()).throw(OSError("broken fs")),
    )

    payload = _parse_result(grep_server.grep_files("needle"))

    assert payload["error"]["code"] == "filesystem_error"
