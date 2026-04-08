"""Artifact parsing and streaming helpers for model output."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional

from ...core.connection import broadcast_message

ArtifactType = Literal["code", "markdown", "html"]

_OPEN_TAG_PREFIX = "<artifact"
_CLOSE_TAG = "</artifact>"
_ATTR_PATTERN = re.compile(r"""([a-zA-Z_:][\w:.-]*)\s*=\s*(['"])(.*?)\2""", re.DOTALL)
_ALLOWED_ARTIFACT_TYPES = {"code", "markdown", "html"}


def _count_lines(content: str) -> int:
    if not content:
        return 0
    return content.count("\n") + 1


def _artifact_block_payload(
    *,
    artifact_id: str,
    artifact_type: str,
    title: str,
    language: Optional[str],
    size_bytes: int,
    line_count: int,
    status: str,
    content: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "type": "artifact",
        "artifact_id": artifact_id,
        "artifact_type": artifact_type,
        "title": title,
        "language": language,
        "size_bytes": size_bytes,
        "line_count": line_count,
        "status": status,
    }
    if content is not None:
        payload["content"] = content
    return payload


def append_text_block(interleaved_blocks: List[Dict[str, Any]], text: str) -> None:
    """Append text to the ordered content-block stream, merging adjacent text."""
    if not text:
        return

    if interleaved_blocks and interleaved_blocks[-1].get("type") == "text":
        interleaved_blocks[-1]["content"] = (
            str(interleaved_blocks[-1].get("content", "")) + text
        )
        return

    interleaved_blocks.append({"type": "text", "content": text})


@dataclass
class ArtifactChunk:
    artifact_id: str
    artifact_type: ArtifactType
    title: str
    language: Optional[str]
    open_tag: str
    content: str = ""

    def start_payload(self) -> Dict[str, Any]:
        return _artifact_block_payload(
            artifact_id=self.artifact_id,
            artifact_type=self.artifact_type,
            title=self.title,
            language=self.language,
            size_bytes=0,
            line_count=0,
            status="streaming",
        )

    def complete_payload(self) -> Dict[str, Any]:
        return _artifact_block_payload(
            artifact_id=self.artifact_id,
            artifact_type=self.artifact_type,
            title=self.title,
            language=self.language,
            size_bytes=len(self.content.encode("utf-8")),
            line_count=_count_lines(self.content),
            status="ready",
            content=self.content,
        )


def _find_tag_end(text: str) -> Optional[int]:
    quote: Optional[str] = None
    for index, char in enumerate(text):
        if quote is not None:
            if char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
            continue
        if char == ">":
            return index
    return None


def _tail_that_might_start_tag(text: str) -> str:
    max_keep = min(len(text), len(_OPEN_TAG_PREFIX) - 1)
    for keep in range(max_keep, 0, -1):
        if _OPEN_TAG_PREFIX.startswith(text[-keep:]):
            return text[-keep:]
    return ""


def _tail_that_might_start_sequence(text: str, *sequences: str) -> str:
    max_keep = min(len(text), max(len(sequence) for sequence in sequences) - 1)
    for keep in range(max_keep, 0, -1):
        suffix = text[-keep:]
        if any(sequence.startswith(suffix) for sequence in sequences):
            return suffix
    return ""


def _parse_open_tag(open_tag: str) -> Optional[ArtifactChunk]:
    if not open_tag.startswith(_OPEN_TAG_PREFIX) or not open_tag.endswith(">"):
        return None

    attrs = {match.group(1): match.group(3) for match in _ATTR_PATTERN.finditer(open_tag)}
    artifact_type = attrs.get("type")
    title = attrs.get("title", "").strip()
    language = attrs.get("language")

    if artifact_type not in _ALLOWED_ARTIFACT_TYPES:
        return None
    if not title:
        return None
    if artifact_type != "code":
        language = None

    return ArtifactChunk(
        artifact_id=str(uuid.uuid4()),
        artifact_type=artifact_type,  # type: ignore[arg-type]
        title=title,
        language=language.strip() if isinstance(language, str) and language.strip() else None,
        open_tag=open_tag,
    )


class ArtifactStreamParser:
    """Incrementally parse streamed model output into text and artifact events."""

    def __init__(self) -> None:
        self._buffer = ""
        self._active_artifact: Optional[ArtifactChunk] = None
        self._nested_depth = 0

    def feed(self, chunk: str) -> List[Dict[str, Any]]:
        if not chunk:
            return []

        self._buffer += chunk
        events: List[Dict[str, Any]] = []

        while True:
            if self._active_artifact is None:
                start_index = self._buffer.find(_OPEN_TAG_PREFIX)
                if start_index == -1:
                    tail = _tail_that_might_start_tag(self._buffer)
                    flush_until = len(self._buffer) - len(tail)
                    if flush_until > 0:
                        events.append(
                            {"type": "text", "content": self._buffer[:flush_until]}
                        )
                        self._buffer = self._buffer[flush_until:]
                    break

                if start_index > 0:
                    events.append({"type": "text", "content": self._buffer[:start_index]})
                    self._buffer = self._buffer[start_index:]

                tag_end = _find_tag_end(self._buffer)
                if tag_end is None:
                    break

                open_tag = self._buffer[: tag_end + 1]
                parsed = _parse_open_tag(open_tag)
                if parsed is None:
                    events.append({"type": "text", "content": open_tag})
                    self._buffer = self._buffer[tag_end + 1 :]
                    continue

                self._active_artifact = parsed
                self._nested_depth = 0
                self._buffer = self._buffer[tag_end + 1 :]
                events.append({"type": "artifact_start", "artifact": parsed.start_payload()})
                continue

            next_open = self._buffer.find(_OPEN_TAG_PREFIX)
            next_close = self._buffer.find(_CLOSE_TAG)

            candidates = [index for index in (next_open, next_close) if index != -1]
            if not candidates:
                tail = _tail_that_might_start_sequence(
                    self._buffer, _OPEN_TAG_PREFIX, _CLOSE_TAG
                )
                flush_until = len(self._buffer) - len(tail)
                if flush_until > 0:
                    self._active_artifact.content += self._buffer[:flush_until]
                    self._buffer = self._buffer[flush_until:]
                break

            next_index = min(candidates)
            if next_index > 0:
                self._active_artifact.content += self._buffer[:next_index]
                self._buffer = self._buffer[next_index:]
                continue

            if self._buffer.startswith(_OPEN_TAG_PREFIX):
                tag_end = _find_tag_end(self._buffer)
                if tag_end is None:
                    break
                nested_open_tag = self._buffer[: tag_end + 1]
                self._active_artifact.content += nested_open_tag
                self._nested_depth += 1
                self._buffer = self._buffer[tag_end + 1 :]
                continue

            if self._buffer.startswith(_CLOSE_TAG):
                if self._nested_depth > 0:
                    self._active_artifact.content += _CLOSE_TAG
                    self._nested_depth -= 1
                    self._buffer = self._buffer[len(_CLOSE_TAG) :]
                    continue

                events.append(
                    {
                        "type": "artifact_complete",
                        "artifact": self._active_artifact.complete_payload(),
                    }
                )
                self._buffer = self._buffer[len(_CLOSE_TAG) :]
                self._active_artifact = None
                self._nested_depth = 0

        return events

    def finalize(self) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []

        if self._active_artifact is not None:
            fallback_text = (
                f"{self._active_artifact.open_tag}"
                f"{self._active_artifact.content}"
                f"{self._buffer}"
            )
            events.append(
                {
                    "type": "artifact_abandoned",
                    "artifact_id": self._active_artifact.artifact_id,
                }
            )
            if fallback_text:
                events.append({"type": "text", "content": fallback_text})
            self._active_artifact = None
            self._nested_depth = 0
            self._buffer = ""
            return events

        if self._buffer:
            events.append({"type": "text", "content": self._buffer})
            self._buffer = ""

        return events


async def emit_artifact_stream_events(
    events: List[Dict[str, Any]],
    interleaved_blocks: List[Dict[str, Any]],
) -> str:
    """Broadcast parser events and update ordered content blocks.

    Returns the cleaned conversational text emitted by these events.
    """
    text_parts: List[str] = []

    for event in events:
        event_type = event.get("type")
        if event_type == "text":
            text = str(event.get("content", ""))
            if not text:
                continue
            text_parts.append(text)
            append_text_block(interleaved_blocks, text)
            await broadcast_message("response_chunk", text)
            continue

        if event_type == "artifact_start":
            await broadcast_message("artifact_start", event["artifact"])
            continue

        if event_type == "artifact_complete":
            artifact_payload = dict(event["artifact"])
            interleaved_blocks.append(artifact_payload)
            await broadcast_message("artifact_complete", artifact_payload)
            continue

        if event_type == "artifact_abandoned":
            await broadcast_message(
                "artifact_deleted",
                {"artifact_id": event["artifact_id"], "reason": "abandoned"},
            )

    return "".join(text_parts)
