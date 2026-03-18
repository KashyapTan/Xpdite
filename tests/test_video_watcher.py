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
                text=("word " * 200).strip(),
                start=float(i * 10),
                end=float((i + 1) * 10),
            )
            for i in range(5000)
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


class TestApprovalFlow:
    @pytest.mark.asyncio
    async def test_request_transcription_approval_round_trip(self, monkeypatch):
        sent: dict[str, object] = {}
        service = vw.VideoWatcherService()

        async def fake_broadcast(msg_type: str, content):
            sent["msg_type"] = msg_type
            sent["content"] = content

        monkeypatch.setattr(vw, "broadcast_message", fake_broadcast)

        task = asyncio.create_task(
            service.request_transcription_approval({"title": "Some Video"})
        )
        await asyncio.sleep(0)

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


class TestWatchFlow:
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
        monkeypatch.setattr(vw, "is_current_request_cancelled", lambda: cancelled["value"])
        monkeypatch.setattr(vw, "_extract_video_metadata", _extract)
        monkeypatch.setattr(vw, "_fetch_caption_segments", _fetch)

        output = await service.watch_youtube_video(
            "https://www.youtube.com/watch?v=abc123"
        )
        assert output == vw._REQUEST_CANCELLED_MESSAGE
        assert called["captions"] is False

    @pytest.mark.asyncio
    async def test_watch_returns_declined_message_when_fallback_denied(self, monkeypatch):
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
        monkeypatch.setattr(vw, "is_current_request_cancelled", lambda: cancelled["value"])
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

