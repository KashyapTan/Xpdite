"""
Filesystem-backed long-term memory service.

Memory is stored as markdown files with restricted YAML-like front matter under
``user_data/memory``. The parser/writer only supports the app's known metadata
fields so we can stay dependency-free at runtime.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from ..config import MEMORY_DEFAULT_FOLDERS, MEMORY_DIR, MEMORY_PROFILE_FILE

logger = logging.getLogger(__name__)

_FRONT_MATTER_DELIMITER = "---"


def _utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp with millisecond precision."""
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _quote_front_matter_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _humanize_stem(stem: str) -> str:
    return " ".join(part for part in stem.replace("_", " ").replace("-", " ").split()).strip().title()


def _derive_abstract(body: str, fallback: str) -> str:
    collapsed = " ".join(body.replace("\r", "\n").split())
    if not collapsed:
        return fallback
    return collapsed[:157] + "..." if len(collapsed) > 160 else collapsed


def _has_windows_drive_prefix(path: PurePosixPath) -> bool:
    first_part = path.parts[0] if path.parts else ""
    return len(first_part) >= 2 and first_part[1] == ":" and first_part[0].isalpha()


@dataclass
class ParsedMemoryFile:
    path: str
    folder: str
    title: str
    category: str
    importance: float
    tags: list[str]
    abstract: str
    created: str
    updated: str
    last_accessed: str
    body: str
    raw_text: str
    parse_warning: str | None = None

    def to_summary_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "path": self.path,
            "folder": self.folder,
            "title": self.title,
            "category": self.category,
            "importance": self.importance,
            "tags": list(self.tags),
            "abstract": self.abstract,
            "created": self.created,
            "updated": self.updated,
            "last_accessed": self.last_accessed,
        }
        if self.parse_warning:
            data["parse_warning"] = self.parse_warning
        return data

    def to_detail_dict(self) -> dict[str, Any]:
        data = self.to_summary_dict()
        data["body"] = self.body
        data["raw_text"] = self.raw_text
        return data


class MemoryService:
    """Filesystem CRUD and parsing for Xpdite memories."""

    def __init__(
        self,
        root_dir: Path = MEMORY_DIR,
        profile_file: Path = MEMORY_PROFILE_FILE,
        default_folders: tuple[str, ...] = MEMORY_DEFAULT_FOLDERS,
    ) -> None:
        self._root_dir = root_dir
        self._profile_file = profile_file
        self._default_folders = default_folders
        self._path_locks: dict[str, threading.Lock] = {}
        self._path_locks_guard = threading.Lock()
        self.initialize()

    @property
    def root_dir(self) -> Path:
        return self._root_dir

    @property
    def profile_file(self) -> Path:
        return self._profile_file

    def initialize(self) -> None:
        """Ensure the root and suggested default folders exist."""
        self._root_dir.mkdir(parents=True, exist_ok=True)
        for folder in self._default_folders:
            (self._root_dir / folder).mkdir(parents=True, exist_ok=True)

    def _get_path_lock(self, path: str) -> threading.Lock:
        with self._path_locks_guard:
            lock = self._path_locks.get(path)
            if lock is None:
                lock = threading.Lock()
                self._path_locks[path] = lock
            return lock

    def _normalize_memory_path(self, path: str) -> str:
        if not path or not path.strip():
            raise ValueError("Memory path is required.")

        normalized = path.strip().replace("\\", "/")
        pure_path = PurePosixPath(normalized)

        if pure_path.is_absolute() or _has_windows_drive_prefix(pure_path):
            raise ValueError("Memory paths must be relative to the memory root.")

        parts: list[str] = []
        for part in pure_path.parts:
            if part in ("", "."):
                continue
            if part == "..":
                raise ValueError("Path traversal is not allowed.")
            parts.append(part)

        if not parts:
            raise ValueError("Memory path must point to a markdown file.")

        normalized_path = PurePosixPath(*parts)
        if normalized_path.suffix.lower() != ".md":
            raise ValueError("Memory files must use the .md extension.")

        return normalized_path.as_posix()

    def _normalize_folder(self, folder: str) -> str:
        normalized = folder.strip().replace("\\", "/")
        pure_path = PurePosixPath(normalized)

        if pure_path.is_absolute() or _has_windows_drive_prefix(pure_path):
            raise ValueError("Folder filters must be relative to the memory root.")

        parts: list[str] = []
        for part in pure_path.parts:
            if part in ("", "."):
                continue
            if part == "..":
                raise ValueError("Path traversal is not allowed.")
            parts.append(part)

        if not parts:
            return ""

        return PurePosixPath(*parts).as_posix()

    def _resolve_memory_path(self, path: str) -> tuple[str, Path]:
        normalized = self._normalize_memory_path(path)
        resolved = (self._root_dir / normalized).resolve()
        root_resolved = self._root_dir.resolve()

        try:
            resolved.relative_to(root_resolved)
        except ValueError as exc:
            raise ValueError("Resolved memory path escapes the memory root.") from exc

        return normalized, resolved

    def _resolve_folder_path(self, folder: str) -> tuple[str, Path]:
        normalized = self._normalize_folder(folder)
        resolved = (self._root_dir / normalized).resolve()
        root_resolved = self._root_dir.resolve()

        try:
            resolved.relative_to(root_resolved)
        except ValueError as exc:
            raise ValueError("Resolved folder escapes the memory root.") from exc

        return normalized, resolved

    def _parse_scalar(self, raw_value: str) -> str:
        value = raw_value.strip()
        if value.startswith('"') and value.endswith('"'):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return value.strip('"')
            return parsed if isinstance(parsed, str) else str(parsed)
        if value.startswith("'") and value.endswith("'"):
            return value[1:-1]
        return value

    def _parse_tags(self, raw_value: str) -> list[str]:
        value = raw_value.strip()
        if not value:
            return []

        if value.startswith("[") and value.endswith("]"):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return [
                        str(item).strip()
                        for item in parsed
                        if str(item).strip()
                    ]
            except json.JSONDecodeError:
                pass

            inner = value[1:-1].strip()
            if not inner:
                return []
            return [
                part.strip().strip("'").strip('"')
                for part in inner.split(",")
                if part.strip().strip("'").strip('"')
            ]

        return [part.strip() for part in value.split(",") if part.strip()]

    def _parse_front_matter(self, front_matter: str) -> tuple[dict[str, Any], list[str]]:
        metadata: dict[str, Any] = {}
        warnings: list[str] = []

        for raw_line in front_matter.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if ":" not in line:
                warnings.append(f"Could not parse front matter line: {raw_line}")
                continue

            key, raw_value = line.split(":", 1)
            key = key.strip()
            raw_value = raw_value.strip()

            if key == "tags":
                metadata["tags"] = self._parse_tags(raw_value)
            elif key == "importance":
                try:
                    metadata["importance"] = float(raw_value)
                except ValueError:
                    warnings.append(f"Invalid importance value: {raw_value}")
            elif key in {"title", "category", "created", "updated", "last_accessed", "abstract"}:
                metadata[key] = self._parse_scalar(raw_value)

        return metadata, warnings

    def _find_front_matter_boundary(self, text: str) -> tuple[list[str], int] | None:
        lines = text.splitlines()
        if not lines or lines[0].strip() != _FRONT_MATTER_DELIMITER:
            return None

        for index, line in enumerate(lines[1:], start=1):
            if line.strip() == _FRONT_MATTER_DELIMITER:
                return lines, index

        return lines, -1

    def _parse_memory_text(self, text: str, path: str) -> ParsedMemoryFile:
        folder = PurePosixPath(path).parent.as_posix()
        folder = "" if folder == "." else folder

        metadata: dict[str, Any] = {}
        warnings: list[str] = []
        body = text

        front_matter_boundary = self._find_front_matter_boundary(text)
        if front_matter_boundary is not None:
            lines, closing_index = front_matter_boundary
            if closing_index < 0:
                warnings.append("Front matter opening delimiter is missing a closing delimiter.")
            else:
                front_matter = "\n".join(lines[1:closing_index])
                body_lines = lines[closing_index + 1 :]
                if body_lines and body_lines[0] == "":
                    body_lines = body_lines[1:]
                body = "\n".join(body_lines)
                metadata, parse_warnings = self._parse_front_matter(front_matter)
                warnings.extend(parse_warnings)

        title = str(metadata.get("title") or _humanize_stem(PurePosixPath(path).stem))
        category = str(metadata.get("category") or (folder.split("/", 1)[0] if folder else "memory"))
        abstract = str(metadata.get("abstract") or _derive_abstract(body, title))
        importance_raw = metadata.get("importance", 0.5)
        try:
            importance = float(importance_raw)
        except (TypeError, ValueError):
            importance = 0.5
            warnings.append("Importance could not be parsed and was defaulted to 0.5.")
        importance = max(0.0, min(1.0, importance))

        tags = metadata.get("tags") or []
        if not isinstance(tags, list):
            tags = [str(tags)]

        return ParsedMemoryFile(
            path=path,
            folder=folder,
            title=title,
            category=category,
            importance=importance,
            tags=[str(tag) for tag in tags if str(tag).strip()],
            abstract=abstract,
            created=str(metadata.get("created") or ""),
            updated=str(metadata.get("updated") or ""),
            last_accessed=str(metadata.get("last_accessed") or ""),
            body=body,
            raw_text=text,
            parse_warning="; ".join(warnings) if warnings else None,
        )

    def _render_memory_text(
        self,
        *,
        title: str,
        category: str,
        importance: float,
        created: str,
        updated: str,
        last_accessed: str,
        tags: list[str],
        abstract: str,
        body: str,
    ) -> str:
        lines = [
            _FRONT_MATTER_DELIMITER,
            f"title: {_quote_front_matter_string(title)}",
            f"category: {_quote_front_matter_string(category)}",
            f"importance: {importance:.3f}".rstrip("0").rstrip("."),
            f"created: {_quote_front_matter_string(created)}",
            f"updated: {_quote_front_matter_string(updated)}",
            f"last_accessed: {_quote_front_matter_string(last_accessed)}",
            f"tags: {json.dumps(tags, ensure_ascii=False)}",
            f"abstract: {_quote_front_matter_string(abstract)}",
            _FRONT_MATTER_DELIMITER,
            "",
            body,
        ]
        text = "\n".join(lines)
        return text if text.endswith("\n") else f"{text}\n"

    def _write_text_atomically(self, path: Path, text: str) -> None:
        temp_path = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    logger.debug("Failed to clean up temporary memory file %s", temp_path)

    def _update_front_matter_field(self, text: str, key: str, value: str) -> str:
        """Update one front matter field while preserving unknown lines."""
        front_matter_boundary = self._find_front_matter_boundary(text)
        if front_matter_boundary is None:
            return text

        lines, closing_index = front_matter_boundary
        if closing_index < 0:
            return text

        rendered_field = f"{key}: {_quote_front_matter_string(value)}"
        front_matter_lines = lines[1:closing_index]
        updated_front_matter: list[str] = []
        replaced = False

        for raw_line in front_matter_lines:
            stripped = raw_line.strip()
            if stripped.startswith(f"{key}:"):
                updated_front_matter.append(rendered_field)
                replaced = True
            else:
                updated_front_matter.append(raw_line)

        if not replaced:
            updated_front_matter.append(rendered_field)

        updated_lines = [
            _FRONT_MATTER_DELIMITER,
            *updated_front_matter,
            _FRONT_MATTER_DELIMITER,
            *lines[closing_index + 1 :],
        ]
        updated_text = "\n".join(updated_lines)
        return f"{updated_text}\n" if text.endswith("\n") else updated_text.rstrip("\n")

    def _touch_last_accessed(self, normalized: str, resolved: Path) -> dict[str, Any] | None:
        with self._get_path_lock(normalized):
            try:
                latest_text = resolved.read_text(encoding="utf-8")
            except OSError as exc:
                logger.warning(
                    "Could not refresh last_accessed for %s during read: %s",
                    normalized,
                    exc,
                )
                return None

            updated_text = self._update_front_matter_field(
                latest_text,
                "last_accessed",
                _utc_timestamp(),
            )
            if updated_text == latest_text:
                return None

            try:
                self._write_text_atomically(resolved, updated_text)
            except OSError as exc:
                logger.warning(
                    "Could not persist last_accessed for %s during read: %s",
                    normalized,
                    exc,
                )
                return None

        return self._parse_memory_text(updated_text, normalized).to_detail_dict()

    def list_memories(self, folder: str | None = None) -> list[dict[str, Any]]:
        """Return memory summaries under the full tree or a filtered subtree."""
        self.initialize()

        search_root = self._root_dir
        root_resolved = self._root_dir.resolve()
        if folder:
            normalized_folder, resolved_search_root = self._resolve_folder_path(folder)
            if not resolved_search_root.exists():
                return []
            search_root = self._root_dir / normalized_folder

        memories: list[dict[str, Any]] = []
        for memory_path in sorted(search_root.rglob("*.md")):
            if not memory_path.is_file():
                continue
            try:
                relative_path = memory_path.relative_to(self._root_dir).as_posix()
                resolved_path = memory_path.resolve()
                resolved_path.relative_to(root_resolved)
                text = memory_path.read_text(encoding="utf-8")
                parsed = self._parse_memory_text(text, relative_path)
                memories.append(parsed.to_summary_dict())
            except ValueError:
                logger.warning("Skipping memory file outside root during listing: %s", memory_path)
            except Exception as exc:
                relative_path = memory_path.relative_to(self._root_dir).as_posix()
                logger.warning("Failed to parse memory file %s: %s", relative_path, exc)
                fallback_title = _humanize_stem(memory_path.stem)
                folder = PurePosixPath(relative_path).parent.as_posix()
                folder = "" if folder == "." else folder
                memories.append(
                    {
                        "path": relative_path,
                        "folder": folder,
                        "title": fallback_title,
                        "category": "memory",
                        "importance": 0.5,
                        "tags": [],
                        "abstract": fallback_title,
                        "created": "",
                        "updated": "",
                        "last_accessed": "",
                        "parse_warning": "File could not be parsed.",
                    }
                )

        return memories

    def read_memory(self, path: str, *, touch_access: bool = True) -> dict[str, Any]:
        """Read a single memory file."""
        self.initialize()
        normalized, resolved = self._resolve_memory_path(path)

        if not resolved.exists() or not resolved.is_file():
            raise FileNotFoundError(f"Memory file not found: {normalized}")

        text = resolved.read_text(encoding="utf-8")
        parsed = self._parse_memory_text(text, normalized)

        if touch_access:
            touched_detail = self._touch_last_accessed(normalized, resolved)
            if touched_detail is not None:
                return touched_detail

        return parsed.to_detail_dict()

    def upsert_memory(
        self,
        *,
        path: str,
        title: str,
        category: str,
        importance: float,
        tags: list[str] | None,
        abstract: str,
        body: str,
        preserve_created: str | None = None,
        preserve_updated: str | None = None,
    ) -> dict[str, Any]:
        """Create or overwrite a memory file."""
        self.initialize()

        normalized, resolved = self._resolve_memory_path(path)
        if not title or not title.strip():
            raise ValueError("Memory title is required.")
        if not category or not category.strip():
            raise ValueError("Memory category is required.")
        if not abstract or not abstract.strip():
            raise ValueError("Memory abstract is required.")

        try:
            numeric_importance = float(importance)
        except (TypeError, ValueError) as exc:
            raise ValueError("Memory importance must be a number between 0.0 and 1.0.") from exc

        if numeric_importance < 0.0 or numeric_importance > 1.0:
            raise ValueError("Memory importance must be between 0.0 and 1.0.")

        with self._get_path_lock(normalized):
            existing_created = preserve_created
            if resolved.exists() and existing_created is None:
                try:
                    existing_text = resolved.read_text(encoding="utf-8")
                    existing_parsed = self._parse_memory_text(existing_text, normalized)
                    existing_created = existing_parsed.created or None
                except Exception as exc:
                    logger.warning("Could not read existing memory metadata for %s: %s", normalized, exc)

            timestamp = _utc_timestamp()
            created = existing_created or timestamp
            updated = preserve_updated or timestamp
            last_accessed = timestamp
            tag_list = [str(tag).strip() for tag in (tags or []) if str(tag).strip()]

            resolved.parent.mkdir(parents=True, exist_ok=True)
            rendered = self._render_memory_text(
                title=title.strip(),
                category=category.strip(),
                importance=numeric_importance,
                created=created,
                updated=updated,
                last_accessed=last_accessed,
                tags=tag_list,
                abstract=abstract.strip(),
                body=body,
            )
            self._write_text_atomically(resolved, rendered)

        return self._parse_memory_text(rendered, normalized).to_detail_dict()

    def delete_memory(self, path: str) -> bool:
        """Delete a single memory file if it exists."""
        normalized, resolved = self._resolve_memory_path(path)
        with self._get_path_lock(normalized):
            if not resolved.exists():
                return False
            resolved.unlink()
        logger.info("Deleted memory file %s", normalized)
        return True

    def clear_all_memories(self) -> int:
        """Delete all memory files and recreate the suggested directory layout."""
        self.initialize()
        deleted_count = sum(1 for _ in self._root_dir.rglob("*.md"))
        if self._root_dir.exists():
            shutil.rmtree(self._root_dir)
        self.initialize()
        logger.info("Cleared all memories (%d file(s))", deleted_count)
        return deleted_count


memory_service = MemoryService()
