"""YouTube video watcher service.

Provides transcript-first video understanding for YouTube URLs:
1) Fast caption extraction via youtube-transcript-api.
2) User-approved fallback to audio download + faster-whisper transcription.
"""

from __future__ import annotations

import asyncio
import glob
import logging
import math
import os
import tempfile
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

from ...infrastructure.config import MAX_TOOL_RESULT_LENGTH
from ...core.connection import broadcast_message
from ...core.request_context import is_current_request_cancelled
from ...core.thread_pool import run_in_thread
from .gpu_detector import get_compute_info, get_estimated_processing_time

logger = logging.getLogger(__name__)

_GPU_WHISPER_MODEL = "large-v3"
_CPU_WHISPER_MODEL = "base.en"
_APPROVAL_TIMEOUT_SECONDS = 180.0
_SHORT_VIDEO_SECONDS = 120
_SHORT_CPU_SKIP_APPROVAL_SECONDS = 180
_DESCRIPTION_PREVIEW_CHARS = 300
_REQUEST_CANCELLED_MESSAGE = "Request was cancelled before video processing completed."


class VideoWatcherError(RuntimeError):
    """Raised when the video watcher cannot complete its work."""


class CaptionUnavailableError(VideoWatcherError):
    """Raised when YouTube captions are unavailable and fallback is needed."""


@dataclass(slots=True, frozen=True)
class TranscriptSegment:
    text: str
    start: float
    end: float


@dataclass(slots=True, frozen=True)
class VideoMetadata:
    url: str
    video_id: str
    title: str
    channel: str
    duration_seconds: float
    description: str
    audio_size_bytes: int | None
    playlist_note: str | None = None


@dataclass(slots=True, frozen=True)
class TranscriptionPlan:
    backend: str
    compute_type: str
    whisper_model: str
    estimated_seconds: float


def is_youtube_url(url: str) -> bool:
    """Return True when *url* appears to be a YouTube URL."""
    if not url or not url.strip():
        return False
    candidate = url.strip()
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    parsed = urlparse(candidate)
    host = parsed.netloc.lower()
    return (
        host == "youtu.be"
        or host.endswith(".youtu.be")
        or host == "youtube.com"
        or host.endswith(".youtube.com")
    )


def _normalize_youtube_url(url: str) -> str:
    candidate = (url or "").strip()
    if not candidate:
        raise VideoWatcherError("A YouTube URL is required.")

    if "://" not in candidate:
        candidate = f"https://{candidate}"

    if not is_youtube_url(candidate):
        raise VideoWatcherError("The provided URL is not a valid YouTube link.")

    return candidate


def _extract_video_id(url: str) -> str | None:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.strip("/")
    query = parse_qs(parsed.query)

    if host == "youtu.be" or host.endswith(".youtu.be"):
        return path.split("/")[0] if path else None

    if host == "youtube.com" or host.endswith(".youtube.com"):
        if path == "watch":
            return (query.get("v") or [None])[0]
        if path.startswith("shorts/"):
            return path.split("/", 1)[1].split("/")[0]
        if path.startswith("live/"):
            return path.split("/", 1)[1].split("/")[0]
        if path.startswith("embed/"):
            return path.split("/", 1)[1].split("/")[0]

    return None


def _friendly_download_error(error_text: str) -> str:
    lower = error_text.lower()
    if "private" in lower:
        return "This video appears to be private and cannot be accessed."
    if "video unavailable" in lower or "unavailable" in lower:
        return "This video is unavailable or has been removed."
    if "age" in lower and "sign in" in lower:
        return "This video is age-restricted and could not be accessed."
    return f"Could not access the video: {error_text}"


def _select_best_audio_size_bytes(info: dict[str, Any]) -> int | None:
    formats = info.get("formats") or []
    if not isinstance(formats, list) or not formats:
        return None

    audio_only = [
        fmt
        for fmt in formats
        if isinstance(fmt, dict)
        and fmt.get("vcodec") == "none"
        and fmt.get("acodec") not in (None, "none")
    ]
    candidates = audio_only or [fmt for fmt in formats if isinstance(fmt, dict)]
    if not candidates:
        return None

    def _score(fmt: dict[str, Any]) -> tuple[float, int]:
        bitrate = float(fmt.get("abr") or fmt.get("tbr") or 0.0)
        size = int(fmt.get("filesize") or fmt.get("filesize_approx") or 0)
        return bitrate, size

    best = max(candidates, key=_score)
    size = int(best.get("filesize") or best.get("filesize_approx") or 0)
    return size if size > 0 else None


def _extract_video_metadata(url: str) -> VideoMetadata:
    try:
        import yt_dlp
        from yt_dlp.utils import DownloadError
    except ImportError as exc:
        raise VideoWatcherError(
            "yt-dlp is not installed. Add it to the Python dependencies."
        ) from exc

    ydl_opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": False,
        "playlist_items": "1",
    }
    playlist_note: str | None = None

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

            if isinstance(info, dict) and info.get("_type") == "playlist":
                entries = [entry for entry in (info.get("entries") or []) if entry]
                if not entries:
                    raise VideoWatcherError(
                        "The provided playlist has no videos to transcribe."
                    )
                first = entries[0]
                first_url = (
                    first.get("webpage_url")
                    or first.get("url")
                    or (
                        f"https://www.youtube.com/watch?v={first.get('id')}"
                        if first.get("id")
                        else None
                    )
                )
                if not first_url:
                    raise VideoWatcherError(
                        "Could not resolve the first video from the playlist URL."
                    )
                if not str(first_url).startswith("http"):
                    first_url = f"https://www.youtube.com/watch?v={first_url}"
                info = ydl.extract_info(str(first_url), download=False)
                playlist_note = "Playlist URL detected; using only the first video."

    except DownloadError as exc:
        raise VideoWatcherError(_friendly_download_error(str(exc))) from exc
    except VideoWatcherError:
        raise
    except Exception as exc:
        raise VideoWatcherError(
            f"Failed to fetch YouTube metadata: {type(exc).__name__}: {exc}"
        ) from exc

    if not isinstance(info, dict):
        raise VideoWatcherError("yt-dlp returned an unexpected metadata format.")

    availability = str(info.get("availability") or "").lower()
    if any(marker in availability for marker in ("private", "subscriber", "premium")):
        raise VideoWatcherError("This video is not publicly accessible.")

    video_id = str(info.get("id") or "").strip()
    if not video_id:
        video_id = _extract_video_id(url) or ""
    if not video_id:
        raise VideoWatcherError("Could not determine a YouTube video ID from this URL.")

    canonical_url = str(info.get("webpage_url") or "").strip()
    if not canonical_url:
        canonical_url = f"https://www.youtube.com/watch?v={video_id}"

    title = str(info.get("title") or "Unknown title").strip()
    channel = str(info.get("channel") or info.get("uploader") or "Unknown channel").strip()
    duration_seconds = float(info.get("duration") or 0.0)
    description = str(info.get("description") or "").strip()
    audio_size_bytes = _select_best_audio_size_bytes(info)

    return VideoMetadata(
        url=canonical_url,
        video_id=video_id,
        title=title,
        channel=channel,
        duration_seconds=duration_seconds,
        description=description,
        audio_size_bytes=audio_size_bytes,
        playlist_note=playlist_note,
    )


def _is_caption_missing_error(exc: Exception) -> bool:
    name = exc.__class__.__name__.lower()
    return any(
        marker in name
        for marker in (
            "notranscriptfound",
            "transcriptsdisabled",
            "novideotranscriptfound",
            "couldnotretrievetranscript",
            "nocaptions",
        )
    )


def _coerce_transcript_entry(entry: Any) -> TranscriptSegment | None:
    if isinstance(entry, dict):
        text = str(entry.get("text") or "").strip()
        start = float(entry.get("start") or 0.0)
        duration = float(entry.get("duration") or 0.0)
    else:
        text = str(getattr(entry, "text", "") or "").strip()
        start = float(getattr(entry, "start", 0.0) or 0.0)
        duration = float(getattr(entry, "duration", 0.0) or 0.0)

    if not text:
        return None

    end = max(start, start + duration)
    return TranscriptSegment(text=text, start=max(0.0, start), end=max(0.0, end))


def _fetch_caption_segments(video_id: str) -> tuple[list[TranscriptSegment], str | None]:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError as exc:
        raise VideoWatcherError(
            "youtube-transcript-api is not installed. Add it to the Python dependencies."
        ) from exc

    preferred_languages = ["en", "en-US", "en-GB"]
    transcript_api = YouTubeTranscriptApi()

    transcript_obj: Any = None
    language_code: str | None = None

    try:
        transcript_list = transcript_api.list(video_id)
        for finder_name in (
            "find_transcript",
            "find_manually_created_transcript",
            "find_generated_transcript",
        ):
            finder = getattr(transcript_list, finder_name, None)
            if finder is None:
                continue
            try:
                transcript_obj = finder(preferred_languages)
                break
            except Exception:
                continue

        if transcript_obj is None:
            transcript_obj = next(iter(transcript_list))

        language_code = (
            getattr(transcript_obj, "language_code", None)
            or getattr(transcript_obj, "language", None)
        )
        raw_segments = transcript_obj.fetch()

    except StopIteration as exc:
        raise CaptionUnavailableError("No captions were found for this video.") from exc
    except Exception as exc:
        if _is_caption_missing_error(exc):
            raise CaptionUnavailableError("No captions were found for this video.") from exc
        if "video unavailable" in str(exc).lower():
            raise VideoWatcherError("This video is unavailable or has been removed.") from exc
        raise VideoWatcherError(
            f"Failed to fetch YouTube captions: {type(exc).__name__}: {exc}"
        ) from exc

    segments: list[TranscriptSegment] = []
    for entry in raw_segments:
        coerced = _coerce_transcript_entry(entry)
        if coerced is not None:
            segments.append(coerced)

    if not segments:
        raise CaptionUnavailableError("Captions were present but contained no text.")

    return segments, str(language_code).strip() if language_code else None


def _build_transcription_plan(duration_seconds: float) -> TranscriptionPlan:
    compute_info = get_compute_info()
    backend = str(compute_info.get("backend", "cpu"))
    compute_type = str(compute_info.get("compute_type", "int8"))
    whisper_model = _GPU_WHISPER_MODEL if backend == "cuda" else _CPU_WHISPER_MODEL
    estimated_seconds = float(get_estimated_processing_time(max(duration_seconds, 0.0)))

    return TranscriptionPlan(
        backend=backend,
        compute_type=compute_type,
        whisper_model=whisper_model,
        estimated_seconds=estimated_seconds,
    )


def _resolve_audio_path(temp_dir: str, ydl: Any, info: dict[str, Any]) -> str | None:
    prepared = ydl.prepare_filename(info)
    if os.path.exists(prepared):
        return prepared

    stem, _ = os.path.splitext(prepared)
    alt_matches = glob.glob(f"{stem}.*")
    for match in alt_matches:
        if os.path.isfile(match):
            return match

    files = [
        os.path.join(temp_dir, name)
        for name in os.listdir(temp_dir)
        if os.path.isfile(os.path.join(temp_dir, name))
    ]
    return files[0] if files else None


def _download_and_transcribe(
    url: str, plan: TranscriptionPlan
) -> tuple[list[TranscriptSegment], str | None]:
    try:
        import yt_dlp
        from yt_dlp.utils import DownloadError
    except ImportError as exc:
        raise VideoWatcherError(
            "yt-dlp is not installed. Add it to the Python dependencies."
        ) from exc

    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise VideoWatcherError("faster-whisper is not available for transcription.") from exc

    with tempfile.TemporaryDirectory(prefix="xpdite-youtube-") as temp_dir:
        ydl_opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "format": "bestaudio/best",
            "outtmpl": os.path.join(temp_dir, "%(id)s.%(ext)s"),
        }

        audio_path: str | None = None
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if not isinstance(info, dict):
                    raise VideoWatcherError("yt-dlp returned an unexpected download payload.")
                audio_path = _resolve_audio_path(temp_dir, ydl, info)

            if not audio_path or not os.path.exists(audio_path):
                raise VideoWatcherError(
                    "Audio download completed but no audio file could be found."
                )

            device = "cuda" if plan.backend == "cuda" else "cpu"
            model = WhisperModel(
                plan.whisper_model,
                device=device,
                compute_type=plan.compute_type,
            )

            result_segments, info = model.transcribe(audio_path, beam_size=5)
            transcript_segments: list[TranscriptSegment] = []
            for segment in result_segments:
                text = str(getattr(segment, "text", "") or "").strip()
                if not text:
                    continue
                start = float(getattr(segment, "start", 0.0) or 0.0)
                end = float(getattr(segment, "end", start) or start)
                transcript_segments.append(
                    TranscriptSegment(text=text, start=max(0.0, start), end=max(0.0, end))
                )

            if not transcript_segments:
                raise VideoWatcherError("Transcription completed but returned no text.")

            language = getattr(info, "language", None)
            return transcript_segments, str(language).strip() if language else None

        except DownloadError as exc:
            raise VideoWatcherError(_friendly_download_error(str(exc))) from exc
        except VideoWatcherError:
            raise
        except Exception as exc:
            raise VideoWatcherError(
                f"Transcription failed: {type(exc).__name__}: {exc}"
            ) from exc
        finally:
            if audio_path and os.path.exists(audio_path):
                try:
                    os.remove(audio_path)
                except OSError:
                    logger.warning("Failed to remove temporary audio file: %s", audio_path)


def _format_hms(seconds: float) -> str:
    if seconds <= 0:
        return "Unknown"
    total = int(round(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _format_mmss(seconds: float) -> str:
    total = int(max(0, seconds))
    minutes, secs = divmod(total, 60)
    return f"{minutes:02d}:{secs:02d}"


def _format_file_size(size_bytes: int | None) -> str:
    if not size_bytes or size_bytes <= 0:
        return "Unknown"
    size = float(size_bytes)
    units = ["B", "KB", "MB", "GB"]
    unit_index = 0
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    return f"{size:.1f} {units[unit_index]}"


def _estimate_download_time_range(
    size_bytes: int | None,
) -> tuple[str, float | None, float | None]:
    if not size_bytes or size_bytes <= 0:
        return "Unknown", None, None

    fast_seconds = size_bytes / (15 * 1024 * 1024)  # ~15 MB/s
    slow_seconds = size_bytes / (5 * 1024 * 1024)   # ~5 MB/s
    low = max(5.0, min(fast_seconds, slow_seconds))
    high = max(low, max(fast_seconds, slow_seconds))

    if high < 60:
        return "under 1 min", low, high

    low_min = max(1, math.ceil(low / 60))
    high_min = max(low_min, math.ceil(high / 60))
    if low_min == high_min:
        return f"~{low_min} min", low, high
    return f"{low_min}-{high_min} min", low, high


def _format_duration_estimate(seconds: float) -> str:
    if seconds < 60:
        return "under 1 min"
    minutes = math.ceil(seconds / 60)
    if minutes < 60:
        return f"~{minutes} min"
    hours = minutes // 60
    rem_minutes = minutes % 60
    if rem_minutes == 0:
        return f"~{hours}h"
    return f"~{hours}h {rem_minutes}m"


def _format_total_time_estimate(
    download_low: float | None,
    download_high: float | None,
    transcription_seconds: float,
) -> str:
    if download_low is None or download_high is None:
        return f"{_format_duration_estimate(transcription_seconds)} + download"

    low = download_low + transcription_seconds
    high = download_high + transcription_seconds
    if high < 60:
        return "under 1 min"
    low_min = max(1, math.ceil(low / 60))
    high_min = max(low_min, math.ceil(high / 60))
    if low_min == high_min:
        return f"~{low_min} min"
    return f"{low_min}-{high_min} min"


def _truncate_description(description: str) -> str:
    cleaned = description.strip()
    if not cleaned:
        return "(no description)"
    if len(cleaned) <= _DESCRIPTION_PREVIEW_CHARS:
        return cleaned
    return cleaned[: _DESCRIPTION_PREVIEW_CHARS - 3].rstrip() + "..."


def _render_transcript_lines(
    segments: list[TranscriptSegment], include_timestamps: bool
) -> list[tuple[str, float]]:
    rendered: list[tuple[str, float]] = []
    for segment in segments:
        text = " ".join(segment.text.split())
        if not text:
            continue
        prefix = f"[{_format_mmss(segment.start)}] " if include_timestamps else ""
        rendered.append((f"{prefix}{text}", segment.end))
    return rendered


def _truncate_rendered_lines(
    rendered_lines: list[tuple[str, float]], max_chars: int
) -> tuple[str, float]:
    if max_chars <= 0 or not rendered_lines:
        return "", 0.0

    chosen: list[str] = []
    used = 0
    last_end = 0.0

    for line, segment_end in rendered_lines:
        extra = len(line) + (1 if chosen else 0)
        if used + extra > max_chars:
            break
        chosen.append(line)
        used += extra
        last_end = segment_end

    if chosen:
        return "\n".join(chosen), last_end

    first_line, first_end = rendered_lines[0]
    partial = first_line[:max_chars]
    ratio = len(partial) / max(len(first_line), 1)
    return partial, first_end * ratio


def _estimate_capture_percent(
    last_end_seconds: float,
    duration_seconds: float,
    truncated_chars: int,
    full_chars: int,
) -> float:
    if duration_seconds > 0 and last_end_seconds > 0:
        return round(
            max(0.0, min(100.0, (last_end_seconds / duration_seconds) * 100)),
            1,
        )
    if full_chars > 0:
        return round(max(0.0, min(100.0, (truncated_chars / full_chars) * 100)), 1)
    return 0.0


def _build_tool_output(
    metadata: VideoMetadata,
    segments: list[TranscriptSegment],
    include_timestamps: bool,
    transcript_language: str | None,
    transcript_source: str,
) -> str:
    language_line = None
    if transcript_language:
        lang = transcript_language.strip()
        if lang and not lang.lower().startswith("en"):
            language_line = f"{lang} (non-English)"
        elif lang:
            language_line = lang

    header_lines = [
        "[YouTube Video]",
        f"Title:    {metadata.title}",
        f"Channel:  {metadata.channel}",
        f"Duration: {_format_hms(metadata.duration_seconds)}",
        f"URL:      {metadata.url}",
        f"Source:   {transcript_source}",
    ]
    if metadata.playlist_note:
        header_lines.append(f"Note:     {metadata.playlist_note}")
    if language_line:
        header_lines.append(f"Language: {language_line}")
    header_lines.extend(
        [
            "",
            "Description:",
            _truncate_description(metadata.description),
            "",
            "Transcript:",
            "",
        ]
    )
    header = "\n".join(header_lines)

    rendered_lines = _render_transcript_lines(segments, include_timestamps)
    if not rendered_lines:
        rendered_lines = [("(no transcript text)", 0.0)]

    full_transcript_chars = sum(len(line) for line, _ in rendered_lines)
    if len(rendered_lines) > 1:
        full_transcript_chars += len(rendered_lines) - 1

    if len(header) + full_transcript_chars <= MAX_TOOL_RESULT_LENGTH:
        full_transcript = "\n".join(line for line, _ in rendered_lines)
        return header + full_transcript

    truncation_note_template = (
        "\n\n[Transcript truncated: captured approximately {percent:.1f}% of the video "
        "before hitting the 100,000-character tool limit. Ask for a specific time "
        "range if you need the rest.]"
    )
    reserved_note_len = len(truncation_note_template.format(percent=100.0))
    max_transcript_chars = max(
        0,
        MAX_TOOL_RESULT_LENGTH - len(header) - reserved_note_len,
    )
    truncated_body, last_end = _truncate_rendered_lines(
        rendered_lines, max_transcript_chars
    )
    if not truncated_body:
        first_line, _ = rendered_lines[0]
        truncated_body = first_line[:max_transcript_chars]

    percent = _estimate_capture_percent(
        last_end_seconds=last_end,
        duration_seconds=metadata.duration_seconds,
        truncated_chars=len(truncated_body),
        full_chars=full_transcript_chars,
    )
    truncation_note = truncation_note_template.format(percent=percent)

    max_body_with_note = max(
        0,
        MAX_TOOL_RESULT_LENGTH - len(header) - len(truncation_note),
    )
    if len(truncated_body) > max_body_with_note:
        truncated_body = truncated_body[:max_body_with_note]

    return header + truncated_body + truncation_note


class VideoWatcherService:
    """Coordinates YouTube transcript retrieval and fallback transcription."""

    def __init__(self):
        self._approval_events: dict[str, asyncio.Event] = {}
        self._approval_results: dict[str, bool] = {}

    async def request_transcription_approval(self, payload: dict[str, Any]) -> bool:
        request_id = str(uuid.uuid4())
        event = asyncio.Event()
        self._approval_events[request_id] = event
        self._approval_results[request_id] = False

        try:
            await broadcast_message(
                "youtube_transcription_approval",
                {
                    **payload,
                    "request_id": request_id,
                },
            )
            await asyncio.wait_for(event.wait(), timeout=_APPROVAL_TIMEOUT_SECONDS)
            return self._approval_results.get(request_id, False)
        except asyncio.TimeoutError:
            return False
        finally:
            self._cleanup_approval(request_id)

    def resolve_transcription_approval(self, request_id: str, approved: bool) -> None:
        event = self._approval_events.get(request_id)
        if event is None:
            return
        self._approval_results[request_id] = approved
        event.set()

    def cancel_all_pending(self) -> None:
        for request_id, event in list(self._approval_events.items()):
            self._approval_results[request_id] = False
            event.set()

    async def watch_youtube_video(self, url: str, include_timestamps: bool = False) -> str:
        if is_current_request_cancelled():
            return _REQUEST_CANCELLED_MESSAGE

        normalized_url = _normalize_youtube_url(url)
        if is_current_request_cancelled():
            return _REQUEST_CANCELLED_MESSAGE

        metadata = await run_in_thread(_extract_video_metadata, normalized_url)
        if is_current_request_cancelled():
            return _REQUEST_CANCELLED_MESSAGE

        try:
            segments, transcript_language = await run_in_thread(
                _fetch_caption_segments, metadata.video_id
            )
            if is_current_request_cancelled():
                return _REQUEST_CANCELLED_MESSAGE
            transcript_source = "YouTube captions"
        except CaptionUnavailableError:
            if is_current_request_cancelled():
                return _REQUEST_CANCELLED_MESSAGE

            plan = _build_transcription_plan(metadata.duration_seconds)

            should_skip_approval = (
                plan.backend == "cpu"
                and metadata.duration_seconds > 0
                and metadata.duration_seconds < _SHORT_VIDEO_SECONDS
                and plan.estimated_seconds < _SHORT_CPU_SKIP_APPROVAL_SECONDS
            )

            if not should_skip_approval:
                download_estimate, dl_low, dl_high = _estimate_download_time_range(
                    metadata.audio_size_bytes
                )
                payload = {
                    "title": metadata.title,
                    "channel": metadata.channel,
                    "duration": _format_hms(metadata.duration_seconds),
                    "duration_seconds": int(round(metadata.duration_seconds)),
                    "url": metadata.url,
                    "no_captions_reason": "No captions were found for this video.",
                    "audio_size_estimate": _format_file_size(metadata.audio_size_bytes),
                    "audio_size_bytes": metadata.audio_size_bytes,
                    "download_time_estimate": download_estimate,
                    "transcription_time_estimate": _format_duration_estimate(
                        plan.estimated_seconds
                    ),
                    "total_time_estimate": _format_total_time_estimate(
                        dl_low, dl_high, plan.estimated_seconds
                    ),
                    "whisper_model": plan.whisper_model,
                    "compute_backend": plan.backend,
                }
                if metadata.playlist_note:
                    payload["playlist_note"] = metadata.playlist_note

                if is_current_request_cancelled():
                    return _REQUEST_CANCELLED_MESSAGE

                approved = await self.request_transcription_approval(payload)
                if is_current_request_cancelled():
                    return _REQUEST_CANCELLED_MESSAGE
                if not approved:
                    return (
                        "Transcription was declined. I could not watch this video "
                        "without captions. You can try a video with captions or "
                        "approve transcription next time."
                    )

            if is_current_request_cancelled():
                return _REQUEST_CANCELLED_MESSAGE

            segments, transcript_language = await run_in_thread(
                _download_and_transcribe, metadata.url, plan
            )
            if is_current_request_cancelled():
                return _REQUEST_CANCELLED_MESSAGE
            transcript_source = f"Whisper transcription ({plan.whisper_model})"

        if is_current_request_cancelled():
            return _REQUEST_CANCELLED_MESSAGE

        return _build_tool_output(
            metadata=metadata,
            segments=segments,
            include_timestamps=include_timestamps,
            transcript_language=transcript_language,
            transcript_source=transcript_source,
        )

    def _cleanup_approval(self, request_id: str) -> None:
        self._approval_events.pop(request_id, None)
        self._approval_results.pop(request_id, None)


video_watcher_service = VideoWatcherService()

