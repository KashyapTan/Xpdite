"""
SQLite-backed file browser service for the @ attachment picker.

Search is global-from-home and relevance-ranked. The first query can return
fast fallback results while the SQLite index builds in the background.
"""

from __future__ import annotations

import importlib
import logging
import os
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from queue import Empty as QueueEmpty
from queue import Queue
from typing import Any, Callable

from ...infrastructure.config import USER_DATA_DIR

logger = logging.getLogger(__name__)

_WATCHDOG_AVAILABLE = True
try:
    _watchdog_events = importlib.import_module("watchdog.events")
    _watchdog_observers = importlib.import_module("watchdog.observers")
    FileSystemEventHandlerBase = getattr(_watchdog_events, "FileSystemEventHandler")
    ObserverCls = getattr(_watchdog_observers, "Observer")
except Exception:
    _WATCHDOG_AVAILABLE = False
    ObserverCls = None

    class FileSystemEventHandlerBase:
        pass


class _IndexChangeHandler(FileSystemEventHandlerBase):
    """Watchdog handler that queues root index refreshes."""

    def __init__(self, root: str, on_change: Callable[[str], None]) -> None:
        super().__init__()
        self._root = root
        self._on_change = on_change

    def on_any_event(self, event: Any) -> None:
        if getattr(event, "event_type", "") == "opened":
            return
        self._on_change(self._root)


@dataclass
class FileEntry:
    """Represents a file or directory entry in the browser."""

    name: str
    path: str
    relative_path: str
    is_directory: bool
    size: int | None
    extension: str | None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BrowseResult:
    """Result of a search operation."""

    entries: list[FileEntry]
    current_path: str
    parent_path: str | None


class FileBrowserService:
    """Service for globally searching filesystem attachments."""

    EXCLUDED_DIRS: set[str] = {
        "node_modules",
        ".git",
        "__pycache__",
        ".venv",
        "venv",
        "dist",
        "build",
        ".next",
        "target",
        "out",
        ".cache",
        "coverage",
        ".tox",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "egg-info",
        ".eggs",
        "__pypackages__",
        ".hg",
        ".svn",
        ".bzr",
    }

    MAX_DEPTH: int = 6
    MAX_RESULTS: int = 50
    MAX_INDEX_ENTRIES: int = 120000
    FALLBACK_SCAN_ENTRIES: int = 20000
    CANDIDATE_LIMIT: int = 1200

    WATCHER_BATCH_WINDOW_SECONDS: float = 0.6
    INDEX_REFRESH_SECONDS: float = 35.0
    EVENT_REINDEX_MIN_INTERVAL_SECONDS: float = 2.0

    def __init__(
        self,
        *,
        index_db_path: str | None = None,
        enable_watcher: bool = True,
    ) -> None:
        db_path = (
            Path(index_db_path)
            if index_db_path
            else Path(USER_DATA_DIR) / "file_browser_index.db"
        )
        db_path.parent.mkdir(parents=True, exist_ok=True)

        self._index_db_path = str(db_path)
        self._enable_watcher = enable_watcher

        self._state_lock = threading.Lock()
        self._watcher_thread: threading.Thread | None = None
        self._watcher_stop = threading.Event()
        self._index_queue: Queue[str] = Queue()
        self._queued_or_running_roots: set[str] = set()
        self._root_last_indexed: dict[str, float] = {}
        self._root_last_event_queued: dict[str, float] = {}

        self._watchdog_available = _WATCHDOG_AVAILABLE
        self._watch_observer: Any | None = None
        self._watch_handlers: dict[str, _IndexChangeHandler] = {}
        self._watch_scheduled_roots: set[str] = set()

        self._init_index_db()
        self._load_index_state()

    def get_home_directory(self) -> str:
        return str(Path.home())

    def _connect_index(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._index_db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    @contextmanager
    def _index_connection(self) -> sqlite3.Connection:
        conn = self._connect_index()
        try:
            yield conn
        finally:
            conn.close()

    def _init_index_db(self) -> None:
        with self._index_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS file_entries (
                    root_path TEXT NOT NULL,
                    path TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    lower_relative_path TEXT NOT NULL,
                    name TEXT NOT NULL,
                    lower_name TEXT NOT NULL,
                    is_directory INTEGER NOT NULL,
                    size INTEGER,
                    extension TEXT,
                    indexed_at REAL NOT NULL,
                    PRIMARY KEY (root_path, path)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_file_entries_root_name
                ON file_entries(root_path, lower_name)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_file_entries_root_rel
                ON file_entries(root_path, lower_relative_path)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_file_entries_root_type_name
                ON file_entries(root_path, is_directory, lower_name)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS indexed_roots (
                    root_path TEXT PRIMARY KEY,
                    last_indexed REAL NOT NULL,
                    entry_count INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.commit()

    def _load_index_state(self) -> None:
        with self._index_connection() as conn:
            rows = conn.execute(
                "SELECT root_path, last_indexed FROM indexed_roots"
            ).fetchall()

        with self._state_lock:
            self._root_last_indexed = {
                str(row["root_path"]): float(row["last_indexed"]) for row in rows
            }

    def start(self) -> None:
        """Start background index consumer + file observer."""
        if not self._enable_watcher:
            return

        should_start = False
        with self._state_lock:
            if self._watcher_thread is None or not self._watcher_thread.is_alive():
                self._watcher_stop.clear()
                self._watcher_thread = threading.Thread(
                    target=self._watch_loop,
                    name="file-browser-indexer",
                    daemon=True,
                )
                should_start = True

        if should_start:
            self._watcher_thread.start()
            self._ensure_observer_started()

    def shutdown(self) -> None:
        """Stop background workers."""
        self._watcher_stop.set()
        self._stop_observer()

        thread: threading.Thread | None
        with self._state_lock:
            thread = self._watcher_thread
            self._watcher_thread = None

        if thread and thread.is_alive():
            thread.join(timeout=2.0)

    def request_index_refresh(self, root_path: str | None = None) -> None:
        """Queue a rebuild for a root (defaults to home)."""
        home = self.get_home_directory()
        root = os.path.realpath(root_path if root_path else home)
        if not self._is_safe_path(root, home):
            raise ValueError("Search root is outside allowed directory")
        if not os.path.exists(root):
            raise FileNotFoundError(f"Path not found: {root}")
        if not os.path.isdir(root):
            raise ValueError(f"Path is not a directory: {root}")

        self.start()
        self._ensure_root_observed(root)
        self._queue_index_job(root, force=True)

    def build_index_now(self, root_path: str | None = None) -> None:
        """Synchronously build or rebuild an index for a root."""
        home = self.get_home_directory()
        root = os.path.realpath(root_path if root_path else home)
        if not self._is_safe_path(root, home):
            raise ValueError("Search root is outside allowed directory")
        if not os.path.exists(root):
            raise FileNotFoundError(f"Path not found: {root}")
        if not os.path.isdir(root):
            raise ValueError(f"Path is not a directory: {root}")

        self._run_index_job(root)

    def _watch_loop(self) -> None:
        while not self._watcher_stop.is_set():
            try:
                queued_root = self._index_queue.get(
                    timeout=self.WATCHER_BATCH_WINDOW_SECONDS
                )
            except QueueEmpty:
                continue
            self._run_index_job(queued_root)

    def _on_watch_event(self, root: str) -> None:
        now = time.time()
        with self._state_lock:
            last_event = self._root_last_event_queued.get(root)
            if (
                last_event is not None
                and now - last_event < self.EVENT_REINDEX_MIN_INTERVAL_SECONDS
            ):
                return
            self._root_last_event_queued[root] = now

        self._queue_index_job(root, force=True)

    def _ensure_observer_started(self) -> None:
        if not self._watchdog_available or ObserverCls is None:
            return

        with self._state_lock:
            observer = self._watch_observer
            if observer is not None:
                return

            observer = ObserverCls(timeout=self.WATCHER_BATCH_WINDOW_SECONDS)
            observer.daemon = True
            observer.start()
            self._watch_observer = observer

    def _stop_observer(self) -> None:
        observer: Any | None
        with self._state_lock:
            observer = self._watch_observer
            self._watch_observer = None
            self._watch_handlers.clear()
            self._watch_scheduled_roots.clear()

        if observer is None:
            return

        try:
            observer.stop()
            observer.join(timeout=2.0)
        except Exception:
            logger.debug("Error while stopping file watcher observer", exc_info=True)

    def _ensure_root_observed(self, root: str) -> None:
        if not self._watchdog_available:
            return

        observer: Any | None
        with self._state_lock:
            observer = self._watch_observer
            if observer is None:
                return
            if root in self._watch_scheduled_roots:
                return

            handler = _IndexChangeHandler(root, self._on_watch_event)
            self._watch_handlers[root] = handler
            self._watch_scheduled_roots.add(root)

        try:
            observer.schedule(handler, root, recursive=True)
        except Exception:
            with self._state_lock:
                self._watch_handlers.pop(root, None)
                self._watch_scheduled_roots.discard(root)
            logger.warning("Failed to watch file root '%s'", root, exc_info=True)

    def _queue_index_job(
        self,
        root: str,
        *,
        force: bool = False,
    ) -> None:
        with self._state_lock:
            if not force:
                last_indexed = self._root_last_indexed.get(root)
                min_age = self.INDEX_REFRESH_SECONDS
                if last_indexed is not None and time.time() - last_indexed < min_age:
                    return
            if root in self._queued_or_running_roots:
                return
            self._queued_or_running_roots.add(root)
        self._index_queue.put(root)

    def _run_index_job(self, root: str) -> None:
        try:
            started_at = time.time()
            entries = self._build_index(root)
            self._replace_root_index(root, entries)
            elapsed_ms = int((time.time() - started_at) * 1000)
            logger.info(
                "Indexed file root '%s' (%d entries) in %dms",
                root,
                len(entries),
                elapsed_ms,
            )
        except Exception as exc:
            logger.warning("File index refresh failed for '%s': %s", root, exc)
        finally:
            with self._state_lock:
                self._queued_or_running_roots.discard(root)

    def _replace_root_index(self, root: str, entries: list[FileEntry]) -> None:
        indexed_at = time.time()
        rows = [
            (
                root,
                entry.path,
                entry.relative_path,
                entry.relative_path.lower(),
                entry.name,
                entry.name.lower(),
                1 if entry.is_directory else 0,
                entry.size,
                entry.extension,
                indexed_at,
            )
            for entry in entries
        ]

        with self._index_connection() as conn:
            conn.execute("BEGIN")
            conn.execute("DELETE FROM file_entries WHERE root_path = ?", (root,))
            if rows:
                conn.executemany(
                    """
                    INSERT INTO file_entries (
                        root_path,
                        path,
                        relative_path,
                        lower_relative_path,
                        name,
                        lower_name,
                        is_directory,
                        size,
                        extension,
                        indexed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
            conn.execute(
                """
                INSERT INTO indexed_roots (root_path, last_indexed, entry_count)
                VALUES (?, ?, ?)
                ON CONFLICT(root_path)
                DO UPDATE SET
                    last_indexed = excluded.last_indexed,
                    entry_count = excluded.entry_count
                """,
                (root, indexed_at, len(entries)),
            )
            conn.commit()

        with self._state_lock:
            self._root_last_indexed[root] = indexed_at

    def _has_index(self, root: str) -> bool:
        with self._state_lock:
            return root in self._root_last_indexed

    @staticmethod
    def _is_within_scope(path: str, scope_root: str) -> bool:
        try:
            resolved = os.path.realpath(path)
            scope_resolved = os.path.realpath(scope_root)
            resolved_norm = os.path.normcase(resolved)
            scope_norm = os.path.normcase(scope_resolved)
            return resolved_norm == scope_norm or resolved_norm.startswith(
                scope_norm + os.sep
            )
        except (OSError, ValueError):
            return False

    def _is_safe_path(self, path: str, home: str) -> bool:
        return self._is_within_scope(path, home)

    def _should_exclude_dir(self, name: str) -> bool:
        if name in self.EXCLUDED_DIRS:
            return True
        return name.endswith(".egg-info")

    def _get_extension(self, name: str) -> str | None:
        if "." not in name:
            return None
        ext = name.rsplit(".", 1)[-1].lower()
        return ext if ext else None

    def _build_index(self, root: str) -> list[FileEntry]:
        entries: list[FileEntry] = []
        visited_dirs: set[str] = set()
        seen_entry_realpaths: set[str] = set()
        root_resolved = os.path.realpath(root)
        stack: list[tuple[str, int]] = [(root, 0)]

        while stack and len(entries) < self.MAX_INDEX_ENTRIES:
            current_path, depth = stack.pop()
            if depth > self.MAX_DEPTH:
                continue

            try:
                resolved_dir = os.path.realpath(current_path)
                if resolved_dir in visited_dirs:
                    continue
                if not self._is_within_scope(resolved_dir, root_resolved):
                    continue
                visited_dirs.add(resolved_dir)
            except (OSError, ValueError):
                continue

            try:
                with os.scandir(current_path) as iterator:
                    for entry in iterator:
                        if len(entries) >= self.MAX_INDEX_ENTRIES:
                            break

                        try:
                            is_dir = entry.is_dir(follow_symlinks=True)
                            name = entry.name
                            if is_dir and self._should_exclude_dir(name):
                                continue

                            abs_path = os.path.abspath(entry.path)
                            real_entry_path = os.path.realpath(abs_path)
                            if not self._is_within_scope(
                                real_entry_path, root_resolved
                            ):
                                continue
                            if real_entry_path in seen_entry_realpaths:
                                if is_dir:
                                    stack.append((entry.path, depth + 1))
                                continue

                            try:
                                rel_path = os.path.relpath(abs_path, root_resolved)
                            except ValueError:
                                continue

                            size: int | None = None
                            if not is_dir:
                                try:
                                    size = entry.stat(follow_symlinks=True).st_size
                                except OSError:
                                    size = None

                            if is_dir:
                                stack.append((entry.path, depth + 1))
                                seen_entry_realpaths.add(real_entry_path)
                                continue

                            entries.append(
                                FileEntry(
                                    name=name,
                                    path=abs_path,
                                    relative_path=rel_path,
                                    is_directory=False,
                                    size=size,
                                    extension=self._get_extension(name),
                                )
                            )
                            seen_entry_realpaths.add(real_entry_path)
                        except (OSError, PermissionError):
                            continue
            except (OSError, PermissionError):
                continue

        return entries

    @staticmethod
    def _subsequence_distance(needle: str, haystack: str) -> int | None:
        if not needle:
            return 0

        i = 0
        first = -1
        last = -1
        for index, char in enumerate(haystack):
            if i < len(needle) and char == needle[i]:
                if first == -1:
                    first = index
                last = index
                i += 1
                if i == len(needle):
                    break

        if i != len(needle):
            return None

        return max(0, (last - first + 1) - len(needle))

    @staticmethod
    def _is_boundary(text: str, index: int) -> bool:
        if index <= 0:
            return True
        return text[index - 1] in "/\\._- "

    def _match_score(self, query_lower: str, entry: FileEntry) -> float:
        if not query_lower:
            return 1.0

        name = entry.name.lower()
        rel = entry.relative_path.lower()
        stem = name.rsplit(".", 1)[0]

        score = 0.0

        if name == query_lower:
            score += 2400.0
        if stem == query_lower:
            score += 2100.0
        if rel == query_lower:
            score += 2200.0

        if name.startswith(query_lower):
            score += 1500.0
        if stem.startswith(query_lower):
            score += 1300.0
        if rel.startswith(query_lower):
            score += 1250.0

        name_index = name.find(query_lower)
        if name_index >= 0:
            score += 950.0 - min(name_index, 80) * 7.0
            if self._is_boundary(name, name_index):
                score += 140.0

        rel_index = rel.find(query_lower)
        if rel_index >= 0:
            score += 620.0 - min(rel_index, 180) * 2.4
            if self._is_boundary(rel, rel_index):
                score += 95.0

        query_tokens = [
            token for token in re.split(r"[\\/._\-\s]+", query_lower) if token
        ]
        missing_tokens = 0
        for token in query_tokens:
            token_name_index = name.find(token)
            if token_name_index >= 0:
                score += 110.0 - min(token_name_index, 36) * 2.0
                continue
            token_rel_index = rel.find(token)
            if token_rel_index >= 0:
                score += 70.0 - min(token_rel_index, 90) * 0.8
                continue
            missing_tokens += 1

        if missing_tokens:
            score -= missing_tokens * 120.0

        if name_index < 0 and rel_index < 0:
            query_alnum = "".join(ch for ch in query_lower if ch.isalnum())
            if query_alnum:
                name_alnum = "".join(ch for ch in name if ch.isalnum())
                rel_alnum = "".join(ch for ch in rel if ch.isalnum())
                name_gap = self._subsequence_distance(query_alnum, name_alnum)
                rel_gap = self._subsequence_distance(query_alnum, rel_alnum)
                if name_gap is not None:
                    score += 290.0 - min(name_gap, 34) * 5.0
                elif rel_gap is not None:
                    score += 170.0 - min(rel_gap, 34) * 3.0

        if entry.extension:
            ext_query = query_lower.rsplit(".", 1)[-1]
            if query_lower.endswith(f".{entry.extension}"):
                score += 140.0
            elif ext_query == entry.extension:
                score += 75.0

        score += max(0.0, 28.0 - min(len(entry.name), 60) * 0.5)

        if entry.is_directory:
            score -= 18.0

        return max(0.0, score)

    def _search_walk(self, root: str, query_lower: str) -> list[FileEntry]:
        candidates: list[tuple[float, FileEntry]] = []
        visited_paths: set[str] = set()
        seen_entry_realpaths: set[str] = set()
        root_resolved = os.path.realpath(root)
        stack: list[tuple[str, int]] = [(root, 0)]
        scanned_entries = 0

        while stack and scanned_entries < self.FALLBACK_SCAN_ENTRIES:
            current_path, depth = stack.pop()
            if depth > self.MAX_DEPTH:
                continue

            try:
                resolved = os.path.realpath(current_path)
                if resolved in visited_paths:
                    continue
                if not self._is_within_scope(resolved, root_resolved):
                    continue
                visited_paths.add(resolved)

                with os.scandir(current_path) as iterator:
                    for entry in iterator:
                        scanned_entries += 1
                        if scanned_entries > self.FALLBACK_SCAN_ENTRIES:
                            break

                        try:
                            name = entry.name
                            is_dir = entry.is_dir(follow_symlinks=True)
                            if is_dir and self._should_exclude_dir(name):
                                continue

                            abs_path = os.path.abspath(entry.path)
                            real_entry_path = os.path.realpath(abs_path)
                            if not self._is_within_scope(
                                real_entry_path, root_resolved
                            ):
                                continue
                            if real_entry_path in seen_entry_realpaths:
                                if is_dir:
                                    stack.append((entry.path, depth + 1))
                                continue

                            try:
                                rel_path = os.path.relpath(abs_path, root_resolved)
                            except ValueError:
                                continue
                            if is_dir:
                                stack.append((entry.path, depth + 1))
                                seen_entry_realpaths.add(real_entry_path)
                                continue

                            candidate = FileEntry(
                                name=name,
                                path=abs_path,
                                relative_path=rel_path,
                                is_directory=False,
                                size=None,
                                extension=self._get_extension(name),
                            )
                            score = self._match_score(query_lower, candidate)
                            if score > 0:
                                try:
                                    candidate.size = entry.stat(
                                        follow_symlinks=True
                                    ).st_size
                                except OSError:
                                    candidate.size = None
                                candidates.append((score, candidate))
                                seen_entry_realpaths.add(real_entry_path)
                        except (OSError, PermissionError):
                            continue
            except (OSError, PermissionError):
                continue

        candidates.sort(
            key=lambda item: (
                -item[0],
                len(item[1].name),
                item[1].name.lower(),
                item[1].relative_path.lower(),
            )
        )
        return [entry for _, entry in candidates[: self.MAX_RESULTS]]

    def _fetch_candidates_from_index(
        self, root: str, query_lower: str
    ) -> list[FileEntry]:
        candidates: dict[str, FileEntry] = {}
        prefix = f"{query_lower}%"
        contains = f"%{query_lower}%"
        first_char = f"{query_lower[:1]}%"

        select_sql = """
            SELECT name, path, relative_path, is_directory, size, extension
            FROM file_entries
            WHERE root_path = ? AND is_directory = 0
        """

        def to_entry(row: sqlite3.Row) -> FileEntry:
            return FileEntry(
                name=str(row["name"]),
                path=str(row["path"]),
                relative_path=str(row["relative_path"]),
                is_directory=bool(row["is_directory"]),
                size=int(row["size"]) if row["size"] is not None else None,
                extension=str(row["extension"]) if row["extension"] else None,
            )

        def run_query(conn: sqlite3.Connection, where_clause: str, value: str) -> None:
            if len(candidates) >= self.CANDIDATE_LIMIT:
                return
            remaining = self.CANDIDATE_LIMIT - len(candidates)
            rows = conn.execute(
                select_sql + where_clause + " LIMIT ?",
                (root, value, remaining),
            ).fetchall()
            for row in rows:
                path = str(row["path"])
                if path in candidates:
                    continue
                candidates[path] = to_entry(row)
                if len(candidates) >= self.CANDIDATE_LIMIT:
                    return

        with self._index_connection() as conn:
            run_query(conn, " AND lower_name = ?", query_lower)
            run_query(conn, " AND lower_relative_path = ?", query_lower)
            run_query(conn, " AND lower_name LIKE ?", prefix)
            run_query(conn, " AND lower_relative_path LIKE ?", prefix)

            if len(query_lower) >= 3 and len(candidates) < self.MAX_RESULTS:
                run_query(conn, " AND lower_name LIKE ?", contains)

            if len(query_lower) >= 4 and len(candidates) < self.MAX_RESULTS:
                run_query(conn, " AND lower_relative_path LIKE ?", contains)

            if query_lower and len(candidates) < self.CANDIDATE_LIMIT:
                run_query(conn, " AND lower_name LIKE ?", first_char)

        return list(candidates.values())

    def _search_index(self, root: str, query_lower: str) -> list[FileEntry]:
        candidates = self._fetch_candidates_from_index(root, query_lower)
        if not candidates:
            return []

        scored: list[tuple[float, FileEntry]] = []
        for candidate in candidates:
            score = self._match_score(query_lower, candidate)
            if score > 0:
                scored.append((score, candidate))

        scored.sort(
            key=lambda item: (
                -item[0],
                len(item[1].name),
                item[1].name.lower(),
                item[1].relative_path.lower(),
            )
        )
        return [entry for _, entry in scored[: self.MAX_RESULTS]]

    def search(self, query: str, root_path: str | None = None) -> BrowseResult:
        query_lower = query.strip().lower()
        home = self.get_home_directory()
        search_root = root_path if root_path else home

        if not self._is_safe_path(search_root, home):
            raise ValueError("Search root is outside allowed directory")
        if not os.path.exists(search_root):
            raise FileNotFoundError(f"Path not found: {search_root}")
        if not os.path.isdir(search_root):
            raise ValueError(f"Path is not a directory: {search_root}")

        resolved_root = os.path.realpath(search_root)

        self.start()
        self._ensure_root_observed(resolved_root)

        if not query_lower:
            self._queue_index_job(resolved_root)
            return BrowseResult(
                entries=[], current_path=resolved_root, parent_path=None
            )

        if self._has_index(resolved_root):
            matching = self._search_index(resolved_root, query_lower)
            self._queue_index_job(resolved_root)
        else:
            self._queue_index_job(resolved_root, force=True)
            matching = self._search_walk(resolved_root, query_lower)

        return BrowseResult(
            entries=matching[: self.MAX_RESULTS],
            current_path=resolved_root,
            parent_path=None,
        )

    def list_directory(self, path: str | None = None) -> BrowseResult:
        """Legacy compatibility path. Uses global search-only mode."""
        home = self.get_home_directory()
        target_path = path if path else home
        if not self._is_safe_path(target_path, home):
            raise ValueError("Path is outside allowed directory")
        if not os.path.exists(target_path):
            raise FileNotFoundError(f"Path not found: {target_path}")
        if not os.path.isdir(target_path):
            raise ValueError(f"Path is not a directory: {target_path}")

        resolved_target = os.path.realpath(target_path)
        self.start()
        self._ensure_root_observed(resolved_target)
        self._queue_index_job(resolved_target)
        return BrowseResult(entries=[], current_path=resolved_target, parent_path=None)

    def clear_cache(self) -> None:
        """Clear persisted indexes and in-memory state."""
        with self._index_connection() as conn:
            conn.execute("DELETE FROM file_entries")
            conn.execute("DELETE FROM indexed_roots")
            conn.commit()

        with self._state_lock:
            self._root_last_indexed.clear()
            self._root_last_event_queued.clear()
            self._queued_or_running_roots.clear()

        while True:
            try:
                self._index_queue.get_nowait()
            except QueueEmpty:
                break


file_browser_service = FileBrowserService()
