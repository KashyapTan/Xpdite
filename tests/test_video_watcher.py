import asyncio
import sys
import types

import pytest

from source.services import video_watcher as vw


def _direct_run_in_thread(func, *args, **kwargs):
    return func(*args, **kwargs)


async def _direct_run_in_thread_async(func, *args, **kwargs):
    return _direct_run_in_thread(func, *args, **kwargs)


class TestUrlDetection:
    def test_is_youtube_url_accepts_supported_hosts(self):
        assert vw.is_youtube_url("https://www.youtube.com/watch?v=abc123")
        assert vw.is_youtube_url("https://youtu.be/abc123")
        assert vw.is_youtube_url("youtube.com/shorts/abc123")

    def test_is_youtube_url_rejects_non_youtube_hosts(self):
        assert not vw.is_youtube_url("https://vimeo.com/123")
        assert not vw.is_youtube_url("https://example.com/watch?v=abc")


class TestOutputFormatting:
    def test_build_tool_output_truncates_at_limit_with_note(self):
        metadata = vw.VideoMetadata(
            url="https://www.youtube.com/watch?v=abc123",
            video_id="abc123",
            title="Long Video",
            channel="Channel",
            duration_seconds=3600,
            description="desc",
            audio_size_bytes=500_000_000,
        )
        segments = [
            vw.TranscriptSegment(
                text=("word " * 120).strip(),
                start=float(i * 8),
                end=float((i + 1) * 8),
            )
            for i in range(220)
        ]

        output = vw._build_tool_output(
            metadata=metadata,
            segments=segments,
            include_timestamps=True,
            transcript_language="en",
            transcript_source="YouTube captions",
        )

        assert len(output) <= vw.MAX_TOOL_RESULT_LENGTH
        assert "Transcript truncated" in output


class TestCaptionFetch:
    def test_fetch_caption_segments_uses_instance_list_api(self, monkeypatch):
        class FakeTranscript:
            language_code = "en"

            def fetch(self):
                return [{"text": "hello world", "start": 0.0, "duration": 1.5}]

        class FakeTranscriptList:
            def find_transcript(self, languages):
                assert languages == ["en", "en-US", "en-GB"]
                return FakeTranscript()

        class FakeYouTubeTranscriptApi:
            def list(self, video_id: str):
                assert video_id == "abc123"
                return FakeTranscriptList()

        monkeypatch.setitem(
            sys.modules,
            "youtube_transcript_api",
            types.SimpleNamespace(YouTubeTranscriptApi=FakeYouTubeTranscriptApi),
        )

        segments, language_code = vw._fetch_caption_segments("abc123")

        assert language_code == "en"
        assert len(segments) == 1
        assert segments[0].text == "hello world"
        assert segments[0].start == 0.0
        assert segments[0].end == 1.5

    def test_fetch_caption_segments_maps_missing_captions_error(self, monkeypatch):
        class NoTranscriptFound(Exception):
            pass

        class FakeTranscriptList:
            def find_transcript(self, _languages):
                raise NoTranscriptFound("no transcript")

            def __iter__(self):
                return iter(())

        class FakeYouTubeTranscriptApi:
            def list(self, _video_id: str):
                return FakeTranscriptList()

        monkeypatch.setitem(
            sys.modules,
            "youtube_transcript_api",
            types.SimpleNamespace(YouTubeTranscriptApi=FakeYouTubeTranscriptApi),
        )

        with pytest.raises(vw.CaptionUnavailableError, match="No captions were found"):
            vw._fetch_caption_segments("abc123")

    def test_fetch_caption_segments_maps_video_unavailable_error(self, monkeypatch):
        class FakeYouTubeTranscriptApi:
            def list(self, _video_id: str):
                raise RuntimeError("Video unavailable")

        monkeypatch.setitem(
            sys.modules,
            "youtube_transcript_api",
            types.SimpleNamespace(YouTubeTranscriptApi=FakeYouTubeTranscriptApi),
        )

        with pytest.raises(vw.VideoWatcherError, match="unavailable"):
            vw._fetch_caption_segments("abc123")

    def test_fetch_caption_segments_wraps_unexpected_errors(self, monkeypatch):
        class FakeYouTubeTranscriptApi:
            def list(self, _video_id: str):
                raise RuntimeError("backend temporarily down")

        monkeypatch.setitem(
            sys.modules,
            "youtube_transcript_api",
            types.SimpleNamespace(YouTubeTranscriptApi=FakeYouTubeTranscriptApi),
        )

        with pytest.raises(
            vw.VideoWatcherError, match="Failed to fetch YouTube captions"
        ):
            vw._fetch_caption_segments("abc123")


class TestMetadataExtraction:
    def test_extract_video_metadata_playlist_without_entries_raises(self, monkeypatch):
        class DownloadError(Exception):
            pass

        class FakeYoutubeDL:
            def __init__(self, _opts):
                pass

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def extract_info(self, _url: str, download: bool = False):
                assert download is False
                return {"_type": "playlist", "entries": []}

        monkeypatch.setitem(
            sys.modules,
            "yt_dlp",
            types.SimpleNamespace(YoutubeDL=FakeYoutubeDL),
        )
        monkeypatch.setitem(
            sys.modules,
            "yt_dlp.utils",
            types.SimpleNamespace(DownloadError=DownloadError),
        )

        with pytest.raises(vw.VideoWatcherError, match="playlist has no videos"):
            vw._extract_video_metadata("https://www.youtube.com/playlist?list=xyz")

    def test_extract_video_metadata_playlist_uses_first_entry_and_sets_note(
        self, monkeypatch
    ):
        class DownloadError(Exception):
            pass

        responses = [
            {
                "_type": "playlist",
                "entries": [
                    {
                        "id": "vid123",
                    }
                ],
            },
            {
                "id": "vid123",
                "title": "My Title",
                "uploader": "My Channel",
                "duration": 61,
                "description": "Demo description",
                "formats": [
                    {
                        "vcodec": "none",
                        "acodec": "mp4a.40.2",
                        "abr": 128,
                        "filesize_approx": 2048,
                    }
                ],
            },
        ]

        class FakeYoutubeDL:
            def __init__(self, _opts):
                pass

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def extract_info(self, _url: str, download: bool = False):
                assert download is False
                return responses.pop(0)

        monkeypatch.setitem(
            sys.modules,
            "yt_dlp",
            types.SimpleNamespace(YoutubeDL=FakeYoutubeDL),
        )
        monkeypatch.setitem(
            sys.modules,
            "yt_dlp.utils",
            types.SimpleNamespace(DownloadError=DownloadError),
        )

        metadata = vw._extract_video_metadata(
            "https://www.youtube.com/playlist?list=playlist123"
        )

        assert metadata.video_id == "vid123"
        assert metadata.url == "https://www.youtube.com/watch?v=vid123"
        assert metadata.channel == "My Channel"
        assert metadata.audio_size_bytes == 2048
        assert (
            metadata.playlist_note
            == "Playlist URL detected; using only the first video."
        )

    def test_extract_video_metadata_falls_back_to_video_id_from_url(self, monkeypatch):
        class DownloadError(Exception):
            pass

        class FakeYoutubeDL:
            def __init__(self, _opts):
                pass

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def extract_info(self, _url: str, download: bool = False):
                assert download is False
                return {
                    "title": "No embedded id",
                    "channel": "Fallback Channel",
                }

        monkeypatch.setitem(
            sys.modules,
            "yt_dlp",
            types.SimpleNamespace(YoutubeDL=FakeYoutubeDL),
        )
        monkeypatch.setitem(
            sys.modules,
            "yt_dlp.utils",
            types.SimpleNamespace(DownloadError=DownloadError),
        )

        metadata = vw._extract_video_metadata("https://www.youtube.com/watch?v=abc123")

        assert metadata.video_id == "abc123"
        assert metadata.url == "https://www.youtube.com/watch?v=abc123"

    def test_extract_video_metadata_rejects_non_public_availability(self, monkeypatch):
        class DownloadError(Exception):
            pass

        class FakeYoutubeDL:
            def __init__(self, _opts):
                pass

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def extract_info(self, _url: str, download: bool = False):
                assert download is False
                return {
                    "id": "abc123",
                    "availability": "premium_only",
                }

        monkeypatch.setitem(
            sys.modules,
            "yt_dlp",
            types.SimpleNamespace(YoutubeDL=FakeYoutubeDL),
        )
        monkeypatch.setitem(
            sys.modules,
            "yt_dlp.utils",
            types.SimpleNamespace(DownloadError=DownloadError),
        )

        with pytest.raises(vw.VideoWatcherError, match="not publicly accessible"):
            vw._extract_video_metadata("https://www.youtube.com/watch?v=abc123")


class TestFriendlyErrorMapping:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (
                "Private video",
                "This video appears to be private and cannot be accessed.",
            ),
            (
                "Video unavailable",
                "This video is unavailable or has been removed.",
            ),
            (
                "Sign in to confirm your age",
                "This video is age-restricted and could not be accessed.",
            ),
            (
                "network timeout",
                "Could not access the video: network timeout",
            ),
        ],
    )
    def test_friendly_download_error_mapping(self, raw, expected):
        assert vw._friendly_download_error(raw) == expected


class TestApprovalFlow:
    @pytest.mark.asyncio
    async def test_request_transcription_approval_round_trip(self, monkeypatch):
        sent: dict[str, object] = {}
        sent_event = asyncio.Event()
        service = vw.VideoWatcherService()

        async def fake_broadcast(msg_type: str, content):
            sent["msg_type"] = msg_type
            sent["content"] = content
            sent_event.set()

        monkeypatch.setattr(vw, "broadcast_message", fake_broadcast)

        task = asyncio.create_task(
            service.request_transcription_approval({"title": "Some Video"})
        )
        await asyncio.wait_for(sent_event.wait(), timeout=1)

        assert sent["msg_type"] == "youtube_transcription_approval"
        request_id = sent["content"]["request_id"]  # type: ignore[index]
        service.resolve_transcription_approval(request_id, True)

        approved = await task
        assert approved is True

    @pytest.mark.asyncio
    async def test_request_transcription_approval_cleans_up_on_broadcast_error(
        self, monkeypatch
    ):
        service = vw.VideoWatcherService()

        async def fake_broadcast(_msg_type: str, _content):
            raise RuntimeError("broadcast failed")

        monkeypatch.setattr(vw, "broadcast_message", fake_broadcast)

        with pytest.raises(RuntimeError):
            await service.request_transcription_approval({"title": "Some Video"})

        assert service._approval_events == {}
        assert service._approval_results == {}

    @pytest.mark.asyncio
    async def test_request_transcription_approval_timeout_cleans_up(self, monkeypatch):
        service = vw.VideoWatcherService()

        async def fake_broadcast(_msg_type: str, _content):
            return None

        async def fake_wait_for(awaitable, timeout):
            assert timeout == vw._APPROVAL_TIMEOUT_SECONDS
            if hasattr(awaitable, "close"):
                awaitable.close()
            raise asyncio.TimeoutError

        monkeypatch.setattr(vw, "broadcast_message", fake_broadcast)
        monkeypatch.setattr(vw.asyncio, "wait_for", fake_wait_for)

        approved = await service.request_transcription_approval({"title": "Some Video"})

        assert approved is False
        assert service._approval_events == {}
        assert service._approval_results == {}

    def test_cancel_all_pending_marks_all_false_and_sets_events(self):
        service = vw.VideoWatcherService()
        event_one = asyncio.Event()
        event_two = asyncio.Event()
        service._approval_events = {"a": event_one, "b": event_two}
        service._approval_results = {"a": True, "b": True}

        service.cancel_all_pending()

        assert service._approval_results == {"a": False, "b": False}
        assert event_one.is_set() is True
        assert event_two.is_set() is True


class TestWatchFlow:
    @pytest.mark.asyncio
    async def test_watch_returns_cancelled_message_if_already_cancelled(
        self, monkeypatch
    ):
        service = vw.VideoWatcherService()
        called = {"metadata": False}

        def _extract(_url: str):
            called["metadata"] = True
            raise AssertionError("metadata should not be called")

        monkeypatch.setattr(vw, "is_current_request_cancelled", lambda: True)
        monkeypatch.setattr(vw, "_extract_video_metadata", _extract)

        output = await service.watch_youtube_video(
            "https://www.youtube.com/watch?v=abc123"
        )
        assert output == vw._REQUEST_CANCELLED_MESSAGE
        assert called["metadata"] is False

    @pytest.mark.asyncio
    async def test_watch_uses_caption_fast_path(self, monkeypatch):
        service = vw.VideoWatcherService()
        metadata = vw.VideoMetadata(
            url="https://www.youtube.com/watch?v=abc123",
            video_id="abc123",
            title="Demo title",
            channel="Demo channel",
            duration_seconds=125,
            description="demo description",
            audio_size_bytes=12_000_000,
        )

        monkeypatch.setattr(vw, "run_in_thread", _direct_run_in_thread_async)
        monkeypatch.setattr(vw, "_extract_video_metadata", lambda _url: metadata)
        monkeypatch.setattr(
            vw,
            "_fetch_caption_segments",
            lambda _video_id: ([vw.TranscriptSegment("hello world", 0, 5)], "en"),
        )

        output = await service.watch_youtube_video(
            "https://www.youtube.com/watch?v=abc123"
        )
        assert "Source:   YouTube captions" in output
        assert "hello world" in output

    @pytest.mark.asyncio
    async def test_watch_stops_when_request_cancelled_after_metadata(self, monkeypatch):
        service = vw.VideoWatcherService()
        metadata = vw.VideoMetadata(
            url="https://www.youtube.com/watch?v=abc123",
            video_id="abc123",
            title="Demo title",
            channel="Demo channel",
            duration_seconds=125,
            description="demo description",
            audio_size_bytes=12_000_000,
        )
        cancelled = {"value": False}
        called = {"captions": False}

        def _extract(_url: str):
            return metadata

        def _fetch(_video_id: str):
            called["captions"] = True
            return [vw.TranscriptSegment("hello world", 0, 5)], "en"

        async def _run(func, *args, **kwargs):
            result = func(*args, **kwargs)
            if func is _extract:
                cancelled["value"] = True
            return result

        monkeypatch.setattr(vw, "run_in_thread", _run)
        monkeypatch.setattr(
            vw, "is_current_request_cancelled", lambda: cancelled["value"]
        )
        monkeypatch.setattr(vw, "_extract_video_metadata", _extract)
        monkeypatch.setattr(vw, "_fetch_caption_segments", _fetch)

        output = await service.watch_youtube_video(
            "https://www.youtube.com/watch?v=abc123"
        )
        assert output == vw._REQUEST_CANCELLED_MESSAGE
        assert called["captions"] is False

    @pytest.mark.asyncio
    async def test_watch_returns_declined_message_when_fallback_denied(
        self, monkeypatch
    ):
        service = vw.VideoWatcherService()
        metadata = vw.VideoMetadata(
            url="https://www.youtube.com/watch?v=abc123",
            video_id="abc123",
            title="Demo title",
            channel="Demo channel",
            duration_seconds=500,
            description="demo description",
            audio_size_bytes=150_000_000,
        )

        def _raise_caption_unavailable(_video_id: str):
            raise vw.CaptionUnavailableError("no captions")

        async def _deny(_payload):
            return False

        monkeypatch.setattr(vw, "run_in_thread", _direct_run_in_thread_async)
        monkeypatch.setattr(vw, "_extract_video_metadata", lambda _url: metadata)
        monkeypatch.setattr(vw, "_fetch_caption_segments", _raise_caption_unavailable)
        monkeypatch.setattr(
            vw,
            "_build_transcription_plan",
            lambda _duration: vw.TranscriptionPlan("cpu", "int8", "base.en", 200),
        )
        monkeypatch.setattr(service, "request_transcription_approval", _deny)

        output = await service.watch_youtube_video(
            "https://www.youtube.com/watch?v=abc123"
        )
        assert "Transcription was declined" in output

    @pytest.mark.asyncio
    async def test_short_cpu_video_skips_approval(self, monkeypatch):
        service = vw.VideoWatcherService()
        metadata = vw.VideoMetadata(
            url="https://www.youtube.com/watch?v=abc123",
            video_id="abc123",
            title="Short demo",
            channel="Demo channel",
            duration_seconds=90,
            description="demo description",
            audio_size_bytes=10_000_000,
        )
        called = {"approval": False}

        def _raise_caption_unavailable(_video_id: str):
            raise vw.CaptionUnavailableError("no captions")

        async def _request(_payload):
            called["approval"] = True
            return True

        monkeypatch.setattr(vw, "run_in_thread", _direct_run_in_thread_async)
        monkeypatch.setattr(vw, "_extract_video_metadata", lambda _url: metadata)
        monkeypatch.setattr(vw, "_fetch_caption_segments", _raise_caption_unavailable)
        monkeypatch.setattr(
            vw,
            "_build_transcription_plan",
            lambda _duration: vw.TranscriptionPlan("cpu", "int8", "base.en", 90),
        )
        monkeypatch.setattr(
            vw,
            "_download_and_transcribe",
            lambda _url, _plan: ([vw.TranscriptSegment("fallback", 0, 5)], "en"),
        )
        monkeypatch.setattr(service, "request_transcription_approval", _request)

        output = await service.watch_youtube_video(
            "https://www.youtube.com/watch?v=abc123"
        )
        assert called["approval"] is False
        assert "Whisper transcription (base.en)" in output

    @pytest.mark.asyncio
    async def test_watch_returns_cancelled_message_if_cancelled_after_approval(
        self, monkeypatch
    ):
        service = vw.VideoWatcherService()
        metadata = vw.VideoMetadata(
            url="https://www.youtube.com/watch?v=abc123",
            video_id="abc123",
            title="Demo title",
            channel="Demo channel",
            duration_seconds=500,
            description="demo description",
            audio_size_bytes=150_000_000,
        )
        cancelled = {"value": False}

        def _raise_caption_unavailable(_video_id: str):
            raise vw.CaptionUnavailableError("no captions")

        async def _request(_payload):
            cancelled["value"] = True
            return False

        monkeypatch.setattr(vw, "run_in_thread", _direct_run_in_thread_async)
        monkeypatch.setattr(
            vw, "is_current_request_cancelled", lambda: cancelled["value"]
        )
        monkeypatch.setattr(vw, "_extract_video_metadata", lambda _url: metadata)
        monkeypatch.setattr(vw, "_fetch_caption_segments", _raise_caption_unavailable)
        monkeypatch.setattr(
            vw,
            "_build_transcription_plan",
            lambda _duration: vw.TranscriptionPlan("cpu", "int8", "base.en", 200),
        )
        monkeypatch.setattr(service, "request_transcription_approval", _request)

        output = await service.watch_youtube_video(
            "https://www.youtube.com/watch?v=abc123"
        )
        assert output == vw._REQUEST_CANCELLED_MESSAGE

    @pytest.mark.asyncio
    async def test_watch_cancelled_before_transcription_download(self, monkeypatch):
        service = vw.VideoWatcherService()
        metadata = vw.VideoMetadata(
            url="https://www.youtube.com/watch?v=abc123",
            video_id="abc123",
            title="Demo title",
            channel="Demo channel",
            duration_seconds=500,
            description="demo description",
            audio_size_bytes=150_000_000,
        )
        cancelled = {"value": False}
        called = {"download": False}

        def _raise_caption_unavailable(_video_id: str):
            raise vw.CaptionUnavailableError("no captions")

        async def _approve(_payload):
            cancelled["value"] = True
            return True

        def _download(_url: str, _plan: vw.TranscriptionPlan):
            called["download"] = True
            return [vw.TranscriptSegment("fallback", 0, 3)], "en"

        monkeypatch.setattr(vw, "run_in_thread", _direct_run_in_thread_async)
        monkeypatch.setattr(
            vw, "is_current_request_cancelled", lambda: cancelled["value"]
        )
        monkeypatch.setattr(vw, "_extract_video_metadata", lambda _url: metadata)
        monkeypatch.setattr(vw, "_fetch_caption_segments", _raise_caption_unavailable)
        monkeypatch.setattr(
            vw,
            "_build_transcription_plan",
            lambda _duration: vw.TranscriptionPlan("cpu", "int8", "base.en", 200),
        )
        monkeypatch.setattr(vw, "_download_and_transcribe", _download)
        monkeypatch.setattr(service, "request_transcription_approval", _approve)

        output = await service.watch_youtube_video(
            "https://www.youtube.com/watch?v=abc123"
        )

        assert output == vw._REQUEST_CANCELLED_MESSAGE
        assert called["download"] is False


class TestTranscriptionOutputVariants:
    def test_build_tool_output_non_english_and_playlist_note(self):
        metadata = vw.VideoMetadata(
            url="https://www.youtube.com/watch?v=abc123",
            video_id="abc123",
            title="Long Video",
            channel="Channel",
            duration_seconds=3600,
            description="Some description",
            audio_size_bytes=500_000_000,
            playlist_note="Playlist URL detected; using only the first video.",
        )
        segments = [vw.TranscriptSegment(text="  hello   world  ", start=0.0, end=4.0)]

        output = vw._build_tool_output(
            metadata=metadata,
            segments=segments,
            include_timestamps=False,
            transcript_language="es",
            transcript_source="Whisper transcription (base.en)",
        )

        assert "Note:     Playlist URL detected; using only the first video." in output
        assert "Language: es (non-English)" in output
        assert "hello world" in output
        assert "[00:00]" not in output

    def test_build_tool_output_with_no_segments_uses_placeholder(self):
        metadata = vw.VideoMetadata(
            url="https://www.youtube.com/watch?v=abc123",
            video_id="abc123",
            title="No Captions",
            channel="Channel",
            duration_seconds=20,
            description="",
            audio_size_bytes=None,
        )

        output = vw._build_tool_output(
            metadata=metadata,
            segments=[],
            include_timestamps=True,
            transcript_language=None,
            transcript_source="YouTube captions",
        )

        assert "(no description)" in output
        assert "(no transcript text)" in output
