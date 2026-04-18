import os
from pathlib import Path

import pytest

from source.services.filesystem.file_browser import FileBrowserService, FileEntry


@pytest.fixture
def browser(tmp_path):
    home_path = tmp_path / "home"
    home_path.mkdir()
    index_dir = tmp_path / ".index"
    index_dir.mkdir()

    service = FileBrowserService(
        index_db_path=str(index_dir / "file-index.db"),
        enable_watcher=False,
    )
    service.get_home_directory = lambda: str(home_path)  # type: ignore[method-assign]
    try:
        yield service
    finally:
        service.shutdown()


def test_list_directory_returns_entries_sorted_dirs_first(browser):
    home_path = Path(browser.get_home_directory())
    (home_path / "a_dir").mkdir()
    (home_path / "z.txt").write_text("z", encoding="utf-8")
    (home_path / "a.txt").write_text("a", encoding="utf-8")

    result = browser.list_directory()
    assert result.current_path == os.path.realpath(str(home_path))
    assert result.parent_path is None
    assert result.entries == []


def test_search_respects_depth_and_exclusions(browser):
    home_path = Path(browser.get_home_directory())
    (home_path / "node_modules").mkdir()
    (home_path / "node_modules" / "hidden.js").write_text("x", encoding="utf-8")

    current = home_path
    for i in range(7):
        current = current / f"lvl{i}"
        current.mkdir()
    (current / "too_deep.txt").write_text("deep", encoding="utf-8")

    shallow = home_path / "src"
    shallow.mkdir()
    (shallow / "target-file.txt").write_text("ok", encoding="utf-8")

    browser.build_index_now(str(home_path))
    result = browser.search("target")
    assert any(entry.name == "target-file.txt" for entry in result.entries)
    assert all(entry.name != "hidden.js" for entry in result.entries)
    assert all(entry.name != "too_deep.txt" for entry in result.entries)


def test_search_raises_for_path_outside_home(browser, tmp_path):
    home_path = Path(browser.get_home_directory())
    outside = home_path.parent
    with pytest.raises(ValueError):
        browser.search("x", str(outside))


def test_search_uses_sqlite_index_when_available(browser, monkeypatch):
    home_path = Path(browser.get_home_directory())
    (home_path / "alpha.txt").write_text("a", encoding="utf-8")
    browser.build_index_now(str(home_path))

    search_walk_calls = 0

    def wrapped_search(root: str, query_lower: str):
        nonlocal search_walk_calls
        search_walk_calls += 1
        return []

    monkeypatch.setattr(browser, "_search_walk", wrapped_search)

    result = browser.search("alpha")

    assert any(entry.name == "alpha.txt" for entry in result.entries)
    assert search_walk_calls == 0


def test_search_fallback_when_index_missing(browser, monkeypatch):
    home_path = Path(browser.get_home_directory())
    (home_path / "alpha.txt").write_text("a", encoding="utf-8")

    search_walk_calls = 0

    def wrapped_search(root: str, query_lower: str):
        nonlocal search_walk_calls
        search_walk_calls += 1
        return [
            FileEntry(
                name="alpha.txt",
                path=str(home_path / "alpha.txt"),
                relative_path="alpha.txt",
                is_directory=False,
                size=1,
                extension="txt",
            )
        ]

    monkeypatch.setattr(browser, "_search_walk", wrapped_search)

    result = browser.search("alpha")
    assert search_walk_calls == 1
    assert [entry.name for entry in result.entries] == ["alpha.txt"]


def test_search_ranks_exact_file_match_first(browser):
    home_path = Path(browser.get_home_directory())
    (home_path / "main.ts").write_text("a", encoding="utf-8")
    (home_path / "main-helper.ts").write_text("a", encoding="utf-8")
    (home_path / "domain.ts").write_text("a", encoding="utf-8")
    (home_path / "xmainx.ts").write_text("a", encoding="utf-8")

    browser.build_index_now(str(home_path))

    result = browser.search("main.ts")
    assert result.entries
    assert result.entries[0].name == "main.ts"


def test_list_directory_queues_index_refresh(browser, monkeypatch):
    home_path = Path(browser.get_home_directory())
    (home_path / "alpha.txt").write_text("a", encoding="utf-8")

    queued_roots: list[str] = []

    def fake_queue(root: str) -> None:
        queued_roots.append(root)

    monkeypatch.setattr(browser, "_queue_index_job", fake_queue)

    result = browser.list_directory()

    assert result.current_path == os.path.realpath(str(home_path))
    assert result.entries == []
    assert queued_roots == [os.path.realpath(str(home_path))]


def test_search_empty_query_returns_no_entries(browser):
    home_path = Path(browser.get_home_directory())
    (home_path / "alpha.txt").write_text("a", encoding="utf-8")

    result = browser.search("")
    assert result.entries == []


def test_search_skips_entries_that_resolve_outside_root(browser, tmp_path, monkeypatch):
    home_path = Path(browser.get_home_directory())
    target = home_path / "escape.txt"
    target.write_text("a", encoding="utf-8")

    outside_path = os.path.abspath(str(tmp_path / "outside" / "escape.txt"))
    target_abs = os.path.abspath(str(target))
    original_realpath = os.path.realpath

    def fake_realpath(path: os.PathLike[str] | str) -> str:
        path_str = os.path.abspath(str(path))
        if os.path.normcase(path_str) == os.path.normcase(target_abs):
            return outside_path
        return original_realpath(path)

    monkeypatch.setattr(os.path, "realpath", fake_realpath)

    result = browser.search("escape")
    assert all(entry.name != "escape.txt" for entry in result.entries)


def test_search_handles_relpath_value_error(browser, monkeypatch):
    home_path = Path(browser.get_home_directory())
    (home_path / "alpha.txt").write_text("a", encoding="utf-8")

    browser.build_index_now(str(home_path))
    browser.clear_cache()

    def raising_relpath(path, start):
        raise ValueError("broken relpath")

    monkeypatch.setattr(os.path, "relpath", raising_relpath)

    result = browser.search("alpha")
    assert result.entries == []


def test_watch_event_forces_index_refresh_even_with_fresh_index(browser, monkeypatch):
    home_path = Path(browser.get_home_directory())
    browser.build_index_now(str(home_path))

    queued_calls: list[tuple[str, bool]] = []

    def fake_queue(root: str, *, force: bool = False) -> None:
        queued_calls.append((root, force))

    monkeypatch.setattr(browser, "_queue_index_job", fake_queue)

    browser._on_watch_event(str(home_path))

    assert queued_calls == [(str(home_path), True)]
