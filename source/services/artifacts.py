"""Artifact persistence and filesystem storage helpers."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from ..infrastructure.config import ARTIFACTS_DIR
from ..infrastructure.database import db

_CODE_EXTENSION_MAP = {
    "python": ".py",
    "javascript": ".js",
    "typescript": ".ts",
    "tsx": ".tsx",
    "jsx": ".jsx",
    "json": ".json",
    "html": ".html",
    "css": ".css",
    "scss": ".scss",
    "shell": ".sh",
    "bash": ".sh",
    "powershell": ".ps1",
    "markdown": ".md",
    "sql": ".sql",
    "yaml": ".yml",
    "toml": ".toml",
    "go": ".go",
    "rust": ".rs",
    "java": ".java",
    "c": ".c",
    "cpp": ".cpp",
    "csharp": ".cs",
    "ruby": ".rb",
    "php": ".php",
    "swift": ".swift",
    "kotlin": ".kt",
}


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "artifact"


def _file_extension(artifact_type: str, language: Optional[str]) -> str:
    if artifact_type == "markdown":
        return ".md"
    if artifact_type == "html":
        return ".html"
    normalized = (language or "").strip().lower()
    return _CODE_EXTENSION_MAP.get(normalized, ".txt")


def _artifact_path(artifact_id: str, artifact_type: str, title: str, language: Optional[str]) -> Path:
    subdir = ARTIFACTS_DIR / artifact_type
    subdir.mkdir(parents=True, exist_ok=True)
    return subdir / f"{artifact_id}-{_slugify(title)}{_file_extension(artifact_type, language)}"


def _compute_stats(content: str) -> tuple[int, int]:
    size_bytes = len(content.encode("utf-8"))
    line_count = content.count("\n") + 1 if content else 0
    return size_bytes, line_count


def _read_text_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _write_text_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(content)


def _remove_file(path: Optional[str]) -> None:
    if not path:
        return
    try:
        os.remove(path)
    except FileNotFoundError:
        return


class ArtifactService:
    """High-level artifact CRUD and storage orchestration."""

    @staticmethod
    def persist_generated_artifacts(
        content_blocks: list[dict[str, Any]] | None,
        *,
        conversation_id: Optional[str],
        message_id: Optional[str] = None,
    ) -> list[dict[str, Any]] | None:
        if not content_blocks:
            return content_blocks

        persisted_blocks: list[dict[str, Any]] = []
        for block in content_blocks:
            if block.get("type") != "artifact":
                persisted_blocks.append(block)
                continue

            artifact_id = str(block.get("artifact_id") or "").strip()
            artifact_type = str(block.get("artifact_type") or "").strip()
            title = str(block.get("title") or "").strip()
            language = block.get("language")
            content = str(block.get("content") or "")
            if not artifact_id or not artifact_type or not title:
                persisted_blocks.append(block)
                continue

            size_bytes, line_count = _compute_stats(content)
            storage_kind = "inline" if artifact_type == "html" else "file"
            storage_path = None
            inline_content = None

            if storage_kind == "file":
                artifact_path = _artifact_path(artifact_id, artifact_type, title, language if isinstance(language, str) else None)
                _write_text_file(artifact_path, content)
                storage_path = str(artifact_path)
            else:
                inline_content = content

            db.create_artifact(
                artifact_id=artifact_id,
                conversation_id=conversation_id,
                message_id=message_id,
                artifact_type=artifact_type,
                title=title,
                language=language if isinstance(language, str) and language.strip() else None,
                storage_kind=storage_kind,
                storage_path=storage_path,
                inline_content=inline_content,
                searchable_text=content,
                size_bytes=size_bytes,
                line_count=line_count,
            )

            persisted_blocks.append(
                {
                    "type": "artifact",
                    "artifact_id": artifact_id,
                    "artifact_type": artifact_type,
                    "title": title,
                    "language": language if isinstance(language, str) and language.strip() else None,
                    "size_bytes": size_bytes,
                    "line_count": line_count,
                    "status": "ready",
                }
            )

        return persisted_blocks

    @staticmethod
    def link_artifacts_to_message(
        artifact_ids: Iterable[str],
        *,
        message_id: str,
    ) -> None:
        ids = [artifact_id for artifact_id in artifact_ids if artifact_id]
        if not ids:
            return
        db.link_artifacts_to_message(ids, message_id)

    @staticmethod
    def get_artifact(artifact_id: str) -> Optional[Dict[str, Any]]:
        record = db.get_artifact(artifact_id)
        if record is None:
            return None

        content = ""
        if record["storage_kind"] == "file" and record.get("storage_path"):
            content = _read_text_file(record["storage_path"])
        else:
            content = record.get("inline_content") or ""

        return {
            "id": record["id"],
            "type": record["artifact_type"],
            "title": record["title"],
            "language": record.get("language"),
            "content": content,
            "size_bytes": record["size_bytes"],
            "line_count": record["line_count"],
            "status": record.get("status", "ready"),
            "conversation_id": record.get("conversation_id"),
            "message_id": record.get("message_id"),
            "created_at": record["created_at"],
            "updated_at": record["updated_at"],
        }

    @staticmethod
    def list_artifacts(
        *,
        query: str = "",
        artifact_type: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
        conversation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        rows, total = db.list_artifacts(
            query=query,
            artifact_type=artifact_type,
            status=status,
            page=page,
            page_size=page_size,
            conversation_id=conversation_id,
        )
        return {
            "artifacts": rows,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    @staticmethod
    def create_artifact(
        *,
        artifact_type: str,
        title: str,
        content: str,
        language: Optional[str] = None,
        conversation_id: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        artifact_id = db.generate_artifact_id()
        blocks = [
            {
                "type": "artifact",
                "artifact_id": artifact_id,
                "artifact_type": artifact_type,
                "title": title,
                "language": language,
                "content": content,
            }
        ]
        persisted = ArtifactService.persist_generated_artifacts(
            blocks,
            conversation_id=conversation_id,
            message_id=message_id,
        )
        detail = ArtifactService.get_artifact(artifact_id)
        if detail is None:
            raise ValueError("Artifact creation failed.")
        return detail

    @staticmethod
    def update_artifact(
        artifact_id: str,
        *,
        title: Optional[str] = None,
        content: Optional[str] = None,
        language: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        existing = db.get_artifact(artifact_id)
        if existing is None:
            return None

        next_title = title.strip() if isinstance(title, str) and title.strip() else existing["title"]
        next_language = (
            language.strip()
            if existing["artifact_type"] == "code" and isinstance(language, str) and language.strip()
            else existing.get("language")
        )
        next_content = (
            content
            if content is not None
            else (
                _read_text_file(existing["storage_path"])
                if existing["storage_kind"] == "file" and existing.get("storage_path")
                else existing.get("inline_content") or ""
            )
        )

        size_bytes, line_count = _compute_stats(next_content)
        storage_path = existing.get("storage_path")
        inline_content = None

        if existing["storage_kind"] == "file":
            next_path = _artifact_path(
                artifact_id,
                existing["artifact_type"],
                next_title,
                next_language,
            )
            if storage_path and str(next_path) != storage_path:
                _remove_file(storage_path)
            _write_text_file(next_path, next_content)
            storage_path = str(next_path)
        else:
            inline_content = next_content

        db.update_artifact(
            artifact_id=artifact_id,
            title=next_title,
            language=next_language,
            storage_path=storage_path,
            inline_content=inline_content,
            searchable_text=next_content,
            size_bytes=size_bytes,
            line_count=line_count,
        )
        return ArtifactService.get_artifact(artifact_id)

    @staticmethod
    def delete_artifact(artifact_id: str) -> bool:
        deleted = db.delete_artifact(artifact_id)
        if deleted is None:
            return False
        _remove_file(deleted.get("storage_path"))
        return True

    @staticmethod
    def delete_artifacts_for_message(message_id: str) -> list[str]:
        deleted_rows = db.delete_artifacts_for_message(message_id)
        for row in deleted_rows:
            _remove_file(row.get("storage_path"))
        return [str(row.get("id") or "") for row in deleted_rows if row.get("id")]

    @staticmethod
    def delete_artifacts_for_conversation(conversation_id: str) -> list[str]:
        deleted_rows = db.delete_artifacts_for_conversation(conversation_id)
        for row in deleted_rows:
            _remove_file(row.get("storage_path"))
        return [str(row.get("id") or "") for row in deleted_rows if row.get("id")]


artifact_service = ArtifactService()
