"""Focused tests for MeetingRecorderService and related pipeline flows."""

import json
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import source.services.media.meeting_recorder as mr


class _FakeThread(threading.Thread):
    def __init__(self, target=None, daemon=None, name=None):
        super().__init__(target=target, daemon=daemon, name=name)
        self.started = False
        self.joined = False
        self._alive = True

    def start(self):
        self.started = True

    def is_alive(self):
        return self._alive

    def join(self, timeout=None):
        self.joined = True
        self._alive = False


class TestMeetingRecorderService:
    @pytest.mark.asyncio
    async def test_start_recording_initializes_db_wave_and_thread(self, tmp_path):
        service = mr.MeetingRecorderService()
        fake_loop = MagicMock()
        fake_writer = MagicMock()
        created_threads = []

        def _make_thread(*_args, **kwargs):
            t = _FakeThread(**kwargs)
            created_threads.append(t)
            return t

        with (
            patch.object(mr, "MEETING_AUDIO_DIR", str(tmp_path)),
            patch.object(mr.asyncio, "get_running_loop", return_value=fake_loop),
            patch.object(mr.time, "time", return_value=1700000000.0),
            patch.object(mr.time, "strftime", return_value="Meeting 2026-01-01 10:00"),
            patch.object(mr.db, "create_meeting_recording", return_value="rec-1"),
            patch.object(mr.db, "update_meeting_recording") as mock_db_update,
            patch.object(mr.wave, "open", return_value=fake_writer),
            patch.object(mr.threading, "Thread", side_effect=_make_thread),
        ):
            result = await service.start_recording()

        assert result["recording_id"] == "rec-1"
        assert result["title"] == "Meeting 2026-01-01 10:00"
        assert service.is_recording is True
        fake_writer.setnchannels.assert_called_once_with(mr.CHANNELS)
        fake_writer.setsampwidth.assert_called_once_with(mr.SAMPLE_WIDTH)
        fake_writer.setframerate.assert_called_once_with(mr.SAMPLE_RATE)
        mock_db_update.assert_called_once_with(
            "rec-1", audio_file_path=str(tmp_path / "rec-1.wav")
        )
        assert len(created_threads) == 1
        assert created_threads[0].name == "meeting-transcription"
        assert created_threads[0].started is True

    @pytest.mark.asyncio
    async def test_stop_recording_finalizes_and_enqueues_processing(self):
        service = mr.MeetingRecorderService()
        service._is_recording = True
        service._recording_id = "rec-2"
        service._audio_file_path = "audio.wav"
        service._started_at = 100.0
        service._wav_writer = MagicMock()
        service._processing_pipeline = MagicMock()

        worker = _FakeThread()
        service._transcription_thread = worker

        with (
            patch.object(mr.time, "time", return_value=112.0),
            patch.object(service, "_process_remaining_buffer") as mock_remaining,
            patch.object(mr.db, "update_meeting_recording") as mock_db_update,
        ):
            result = await service.stop_recording()

        assert result == {
            "recording_id": "rec-2",
            "duration_seconds": 12,
            "status": "processing",
        }
        mock_remaining.assert_called_once_with()
        mock_db_update.assert_called_once_with(
            "rec-2", ended_at=112.0, duration_seconds=12, status="processing"
        )
        service._processing_pipeline.enqueue.assert_called_once_with(
            "rec-2", "audio.wav", 12
        )
        assert worker.joined is True
        assert service.recording_id is None
        assert service._audio_file_path is None
        assert service._wav_writer is None

    @pytest.mark.asyncio
    async def test_stop_recording_raises_when_not_recording(self):
        service = mr.MeetingRecorderService()
        with pytest.raises(RuntimeError, match="No recording is in progress"):
            await service.stop_recording()

    def test_handle_audio_chunk_writes_and_buffers_while_recording(self):
        service = mr.MeetingRecorderService()
        service._is_recording = True
        service._wav_writer = MagicMock()

        service.handle_audio_chunk(b"\x01\x02\x03\x04")

        service._wav_writer.writeframes.assert_called_once_with(b"\x01\x02\x03\x04")
        assert bytes(service._audio_buffer) == b"\x01\x02\x03\x04"

    def test_handle_audio_chunk_noop_when_not_recording(self):
        service = mr.MeetingRecorderService()
        service._wav_writer = MagicMock()

        service.handle_audio_chunk(b"\x01\x02")

        service._wav_writer.writeframes.assert_not_called()
        assert bytes(service._audio_buffer) == b""

    def test_process_remaining_buffer_skips_tiny_audio(self):
        service = mr.MeetingRecorderService()
        service._audio_buffer = bytearray(b"\x00" * 10)

        with patch.object(service, "_transcribe_chunk") as mock_transcribe:
            service._process_remaining_buffer()

        mock_transcribe.assert_not_called()

    def test_process_remaining_buffer_appends_transcript(self):
        service = mr.MeetingRecorderService()
        service._recording_id = "rec-3"
        service._audio_buffer = bytearray(b"\x00" * (mr.SAMPLE_RATE * mr.SAMPLE_WIDTH))

        with (
            patch.object(service, "_transcribe_chunk", return_value="hello world"),
            patch.object(mr.db, "append_tier1_transcript") as mock_append,
        ):
            service._process_remaining_buffer()

        mock_append.assert_called_once_with("rec-3", "hello world\n")

    def test_transcribe_chunk_returns_empty_without_model(self):
        service = mr.MeetingRecorderService()
        service._whisper_model = None
        assert service._transcribe_chunk(b"\x00\x00") == ""

    def test_is_silence_and_format_time_helpers(self):
        assert mr.MeetingRecorderService._is_silence(b"") is True
        quiet = (1).to_bytes(2, byteorder="little", signed=True) * 50
        assert mr.MeetingRecorderService._is_silence(quiet) is True
        loud = (2000).to_bytes(2, byteorder="little", signed=True) * 50
        assert mr.MeetingRecorderService._is_silence(loud) is False
        assert mr.MeetingRecorderService._format_time(125.9) == "02:05"

    def test_recover_interrupted_recordings_requeues_and_marks_partial(self):
        service = mr.MeetingRecorderService()
        service._processing_pipeline = MagicMock()

        rows = [
            {
                "id": "r1",
                "status": "processing",
                "audio_file_path": "exists.wav",
                "duration_seconds": 42,
            },
            {
                "id": "r2",
                "status": "processing",
                "audio_file_path": "missing.wav",
                "duration_seconds": 10,
            },
            {"id": "r3", "status": "recording", "audio_file_path": None},
        ]

        with (
            patch.object(mr.db, "get_meeting_recordings", return_value=rows),
            patch.object(mr.os.path, "exists", side_effect=lambda p: p == "exists.wav"),
            patch.object(mr.db, "update_meeting_recording") as mock_update,
        ):
            service.recover_interrupted_recordings()

        service._processing_pipeline.enqueue.assert_called_once_with(
            "r1", "exists.wav", 42
        )
        assert mock_update.call_count == 2

    def test_transcription_worker_broadcasts_error_when_model_load_fails(self):
        service = mr.MeetingRecorderService()
        service._recording_id = "rec-load-fail"

        with (
            patch.object(
                service, "_load_whisper_model", side_effect=RuntimeError("boom")
            ),
            patch.object(service, "_broadcast_from_thread") as mock_broadcast,
        ):
            service._transcription_worker()

        mock_broadcast.assert_called_once()
        call = mock_broadcast.call_args
        assert call.args[0] == "meeting_recording_error"
        assert call.args[1]["recording_id"] == "rec-load-fail"
        assert "failed to load" in call.args[1]["error"]

    def test_transcription_worker_skips_silent_chunk(self):
        service = mr.MeetingRecorderService()
        service._recording_id = "rec-silent"
        chunk_bytes = mr.CHUNK_SAMPLES * mr.SAMPLE_WIDTH
        service._audio_buffer = bytearray(b"\x00" * chunk_bytes)

        with (
            patch.object(
                service._transcription_stop_event, "is_set", side_effect=[False, True]
            ),
            patch.object(service._transcription_stop_event, "wait", return_value=False),
            patch.object(service, "_load_whisper_model"),
            patch.object(service, "_is_silence", return_value=True),
            patch.object(service, "_transcribe_chunk") as mock_transcribe,
            patch.object(mr.db, "append_tier1_transcript") as mock_append,
            patch.object(service, "_broadcast_from_thread") as mock_broadcast,
        ):
            service._transcription_worker()

        mock_transcribe.assert_not_called()
        mock_append.assert_not_called()
        mock_broadcast.assert_not_called()

    def test_transcription_worker_appends_and_broadcasts_transcript_chunk(self):
        service = mr.MeetingRecorderService()
        service._recording_id = "rec-live"
        chunk_bytes = mr.CHUNK_SAMPLES * mr.SAMPLE_WIDTH
        service._audio_buffer = bytearray(b"\x01" * chunk_bytes)

        with (
            patch.object(
                service._transcription_stop_event, "is_set", side_effect=[False, True]
            ),
            patch.object(service._transcription_stop_event, "wait", return_value=False),
            patch.object(service, "_load_whisper_model"),
            patch.object(service, "_is_silence", return_value=False),
            patch.object(service, "_transcribe_chunk", return_value="hello world"),
            patch.object(mr.db, "append_tier1_transcript") as mock_append,
            patch.object(service, "_broadcast_from_thread") as mock_broadcast,
        ):
            service._transcription_worker()

        mock_append.assert_called_once()
        assert mock_append.call_args.args[0] == "rec-live"
        assert "hello world" in mock_append.call_args.args[1]
        mock_broadcast.assert_called_once()
        assert mock_broadcast.call_args.args[0] == "meeting_transcript_chunk"
        assert mock_broadcast.call_args.args[1]["recording_id"] == "rec-live"
        assert mock_broadcast.call_args.args[1]["text"] == "hello world"

    def test_transcription_worker_ignores_short_or_failed_transcription(self):
        service = mr.MeetingRecorderService()
        service._recording_id = "rec-short"
        chunk_bytes = mr.CHUNK_SAMPLES * mr.SAMPLE_WIDTH
        service._audio_buffer = bytearray(b"\x02" * chunk_bytes)

        with (
            patch.object(
                service._transcription_stop_event, "is_set", side_effect=[False, True]
            ),
            patch.object(service._transcription_stop_event, "wait", return_value=False),
            patch.object(service, "_load_whisper_model"),
            patch.object(service, "_is_silence", return_value=False),
            patch.object(service, "_transcribe_chunk", return_value="singleword"),
            patch.object(mr.db, "append_tier1_transcript") as mock_append,
            patch.object(service, "_broadcast_from_thread") as mock_broadcast,
        ):
            service._transcription_worker()

        mock_append.assert_not_called()
        mock_broadcast.assert_not_called()

    def test_transcription_worker_swallow_chunk_transcription_exception(self):
        service = mr.MeetingRecorderService()
        service._recording_id = "rec-transcribe-error"
        chunk_bytes = mr.CHUNK_SAMPLES * mr.SAMPLE_WIDTH
        service._audio_buffer = bytearray(b"\x03" * chunk_bytes)

        with (
            patch.object(
                service._transcription_stop_event, "is_set", side_effect=[False, True]
            ),
            patch.object(service._transcription_stop_event, "wait", return_value=False),
            patch.object(service, "_load_whisper_model"),
            patch.object(service, "_is_silence", return_value=False),
            patch.object(
                service, "_transcribe_chunk", side_effect=RuntimeError("bad chunk")
            ),
            patch.object(mr.db, "append_tier1_transcript") as mock_append,
            patch.object(service, "_broadcast_from_thread") as mock_broadcast,
        ):
            service._transcription_worker()

        mock_append.assert_not_called()
        mock_broadcast.assert_not_called()

    def test_transcribe_chunk_cleans_up_temp_file_on_success_and_remove_error(self):
        service = mr.MeetingRecorderService()
        service._whisper_model = MagicMock(
            transcribe=MagicMock(
                return_value=(
                    [SimpleNamespace(text="hello"), SimpleNamespace(text="there")],
                    None,
                )
            )
        )

        with patch.object(
            mr.os, "remove", side_effect=OSError("locked")
        ) as mock_remove:
            text = service._transcribe_chunk(b"\x00\x00" * 100)

        assert text == "hello there"
        mock_remove.assert_called_once()

    def test_transcribe_chunk_cleans_up_temp_file_when_transcribe_raises(self):
        service = mr.MeetingRecorderService()
        service._whisper_model = MagicMock(
            transcribe=MagicMock(side_effect=RuntimeError("fail"))
        )

        with patch.object(mr.os, "remove") as mock_remove:
            text = service._transcribe_chunk(b"\x00\x00" * 100)

        assert text == ""
        mock_remove.assert_called_once()


class TestPostProcessingPipeline:
    def test_enqueue_starts_worker_thread_once(self):
        pipeline = mr.PostProcessingPipeline(MagicMock())
        created_threads = []

        def _make_thread(*_args, **kwargs):
            t = _FakeThread(**kwargs)
            created_threads.append(t)
            return t

        with patch.object(mr.threading, "Thread", side_effect=_make_thread):
            pipeline.enqueue("rec-1", "a.wav", 10)

        assert pipeline._is_running is True
        assert len(created_threads) == 1
        assert created_threads[0].name == "meeting-postprocess"
        assert created_threads[0].started is True

    def test_worker_handles_processing_exception(self):
        pipeline = mr.PostProcessingPipeline(MagicMock())
        pipeline._queue = [
            {"recording_id": "rec-9", "audio_file_path": "a.wav", "duration_seconds": 1}
        ]

        with (
            patch.object(
                pipeline, "_process_recording", side_effect=RuntimeError("boom")
            ),
            patch.object(mr.db, "update_meeting_recording") as mock_update,
            patch.object(pipeline, "_broadcast_progress") as mock_progress,
        ):
            pipeline._worker()

        mock_update.assert_called_once_with("rec-9", status="partial")
        mock_progress.assert_called_once_with("rec-9", "error", 0, 0)
        assert pipeline._is_running is False

    def test_process_recording_missing_audio_marks_partial(self):
        pipeline = mr.PostProcessingPipeline(MagicMock())
        job = {
            "recording_id": "rec-miss",
            "audio_file_path": "missing.wav",
            "duration_seconds": 5,
        }

        with (
            patch.object(mr.os.path, "exists", return_value=False),
            patch.object(mr.db, "update_meeting_recording") as mock_update,
        ):
            pipeline._process_recording(job)

        mock_update.assert_called_once_with("rec-miss", status="partial")

    def test_process_recording_happy_path_saves_ready_and_cleans_audio(self, tmp_path):
        pipeline = mr.PostProcessingPipeline(MagicMock())
        audio_path = tmp_path / "rec.wav"
        audio_path.write_bytes(b"x")

        job = {
            "recording_id": "rec-ok",
            "audio_file_path": str(audio_path),
            "duration_seconds": 120,
        }

        with (
            patch(
                "source.services.media.gpu_detector.get_compute_info",
                return_value={"backend": "cpu", "compute_type": "int8"},
            ),
            patch(
                "source.services.media.gpu_detector.get_estimated_processing_time",
                return_value=100.0,
            ),
            patch.object(
                pipeline,
                "_transcribe_full",
                return_value=[{"text": "hello", "start": 0, "end": 1}],
            ),
            patch.object(pipeline, "_align_transcript", return_value=None),
            patch.object(pipeline, "_merge_results", return_value=[{"text": "hello"}]),
            patch.object(pipeline, "_generate_title", return_value="Sprint Planning"),
            patch.object(
                pipeline,
                "_get_setting",
                side_effect=lambda key, default="": {
                    "meeting_diarization_enabled": "false",
                    "meeting_keep_audio": "false",
                }.get(key, default),
            ),
            patch.object(pipeline, "_broadcast_progress"),
            patch.object(mr.db, "update_meeting_recording") as mock_update,
            patch.object(mr.os, "remove") as mock_remove,
        ):
            pipeline._process_recording(job)

        first_update_kwargs = mock_update.call_args_list[0].kwargs
        assert first_update_kwargs["status"] == "ready"
        assert first_update_kwargs["title"] == "Sprint Planning"
        assert first_update_kwargs["ai_title_generated"] == 1
        assert json.loads(first_update_kwargs["tier2_transcript_json"]) == [
            {"text": "hello"}
        ]
        mock_remove.assert_called_once_with(str(audio_path))

    def test_process_recording_cuda_transcribe_fallbacks_to_cpu(self, tmp_path):
        pipeline = mr.PostProcessingPipeline(MagicMock())
        audio_path = tmp_path / "fallback.wav"
        audio_path.write_bytes(b"x")
        job = {
            "recording_id": "rec-fallback",
            "audio_file_path": str(audio_path),
            "duration_seconds": 30,
        }

        with (
            patch(
                "source.services.media.gpu_detector.get_compute_info",
                return_value={"backend": "cuda", "compute_type": "float16"},
            ),
            patch(
                "source.services.media.gpu_detector.get_estimated_processing_time",
                return_value=40.0,
            ),
            patch.object(
                pipeline,
                "_transcribe_full",
                side_effect=[
                    RuntimeError("cuda oom"),
                    [{"text": "ok", "start": 0, "end": 1}],
                ],
            ) as mock_transcribe,
            patch.object(pipeline, "_align_transcript", return_value=None),
            patch.object(pipeline, "_merge_results", return_value=[{"text": "ok"}]),
            patch.object(pipeline, "_generate_title", return_value=None),
            patch.object(
                pipeline,
                "_get_setting",
                side_effect=lambda key, default="": {
                    "meeting_diarization_enabled": "false",
                    "meeting_keep_audio": "true",
                }.get(key, default),
            ),
            patch.object(pipeline, "_broadcast_progress"),
            patch.object(mr.db, "update_meeting_recording") as mock_update,
            patch.object(mr.os, "remove") as mock_remove,
        ):
            pipeline._process_recording(job)

        assert mock_transcribe.call_count == 2
        assert mock_transcribe.call_args_list[0].args == (
            str(audio_path),
            "cuda",
            "float16",
        )
        assert mock_transcribe.call_args_list[1].args == (
            str(audio_path),
            "cpu",
            "int8",
        )
        assert mock_update.call_args_list[0].kwargs["status"] == "ready"
        assert "title" not in mock_update.call_args_list[0].kwargs
        mock_remove.assert_not_called()

    def test_process_recording_marks_partial_when_tier2_transcription_fails_after_retry(
        self, tmp_path
    ):
        pipeline = mr.PostProcessingPipeline(MagicMock())
        audio_path = tmp_path / "retry_fail.wav"
        audio_path.write_bytes(b"x")
        job = {
            "recording_id": "rec-retry-fail",
            "audio_file_path": str(audio_path),
            "duration_seconds": 20,
        }

        with (
            patch(
                "source.services.media.gpu_detector.get_compute_info",
                return_value={"backend": "cuda", "compute_type": "float16"},
            ),
            patch(
                "source.services.media.gpu_detector.get_estimated_processing_time",
                return_value=20.0,
            ),
            patch.object(
                pipeline, "_transcribe_full", side_effect=RuntimeError("always fails")
            ),
            patch.object(pipeline, "_align_transcript") as mock_align,
            patch.object(mr.db, "update_meeting_recording") as mock_update,
            patch.object(pipeline, "_broadcast_progress") as mock_progress,
        ):
            pipeline._process_recording(job)

        mock_update.assert_called_once_with("rec-retry-fail", status="partial")
        mock_align.assert_not_called()
        assert any(
            call.args == ("rec-retry-fail", "error", 0, 0)
            for call in mock_progress.call_args_list
        )

    def test_process_recording_continues_when_alignment_and_diarization_fail(
        self, tmp_path
    ):
        pipeline = mr.PostProcessingPipeline(MagicMock())
        audio_path = tmp_path / "recover.wav"
        audio_path.write_bytes(b"x")
        job = {
            "recording_id": "rec-continue",
            "audio_file_path": str(audio_path),
            "duration_seconds": 15,
        }

        with (
            patch(
                "source.services.media.gpu_detector.get_compute_info",
                return_value={"backend": "cpu", "compute_type": "int8"},
            ),
            patch(
                "source.services.media.gpu_detector.get_estimated_processing_time",
                return_value=10.0,
            ),
            patch.object(
                pipeline,
                "_transcribe_full",
                return_value=[{"text": "segment", "start": 0, "end": 1}],
            ),
            patch.object(
                pipeline, "_align_transcript", side_effect=RuntimeError("align failed")
            ),
            patch.object(
                pipeline, "_diarize", side_effect=RuntimeError("diarize failed")
            ),
            patch.object(pipeline, "_merge_results", return_value=[{"text": "final"}]),
            patch.object(pipeline, "_generate_title", return_value=None),
            patch.object(
                pipeline,
                "_get_setting",
                side_effect=lambda key, default="": {
                    "meeting_diarization_enabled": "true",
                    "meeting_keep_audio": "true",
                }.get(key, default),
            ),
            patch.object(pipeline, "_broadcast_progress"),
            patch.object(mr.db, "update_meeting_recording") as mock_update,
            patch.object(mr.os, "remove") as mock_remove,
        ):
            pipeline._process_recording(job)

        saved_kwargs = mock_update.call_args_list[0].kwargs
        assert saved_kwargs["status"] == "ready"
        assert json.loads(saved_kwargs["tier2_transcript_json"]) == [{"text": "final"}]
        assert "title" not in saved_kwargs
        mock_remove.assert_not_called()

    def test_generate_title_uses_meeting_analysis_model_setting(self):
        pipeline = mr.PostProcessingPipeline(MagicMock())
        transcript = [
            {
                "text": "Project kickoff discussed timeline deliverables risks owners "
                "and next steps for the quarter planning meeting"
            }
        ]

        with (
            patch.object(
                pipeline,
                "_get_setting",
                side_effect=lambda key, default="": (
                    "openrouter/z-ai/glm-4.5-air:free"
                    if key == "meeting_analysis_model"
                    else default
                ),
            ),
            patch.object(
                mr.MeetingAnalysisService,
                "_call_llm",
                return_value="Quarterly Planning Alignment",
            ) as mock_call_llm,
        ):
            title = pipeline._generate_title(transcript)

        assert title == "Quarterly Planning Alignment"
        call_kwargs = mock_call_llm.call_args.kwargs
        assert call_kwargs["model"] == "openrouter/z-ai/glm-4.5-air:free"


class TestMeetingAnalysisServiceGenerateAnalysis:
    @pytest.mark.asyncio
    async def test_generate_analysis_missing_recording(self):
        service = mr.MeetingAnalysisService(MagicMock())
        with patch.object(mr.db, "get_meeting_recording", return_value=None):
            result = await service.generate_analysis("missing")
        assert result == {"error": "Recording not found"}

    @pytest.mark.asyncio
    async def test_generate_analysis_short_transcript(self):
        service = mr.MeetingAnalysisService(MagicMock())
        recording = {"tier1_transcript": "too short", "tier2_transcript_json": None}

        with patch.object(mr.db, "get_meeting_recording", return_value=recording):
            result = await service.generate_analysis("rec-short")

        assert result == {"error": "Transcript too short for analysis"}

    @pytest.mark.asyncio
    async def test_generate_analysis_success_updates_db(self):
        service = mr.MeetingAnalysisService(MagicMock())
        recording = {
            "tier1_transcript": "This is a long enough transcript with many words. "
            * 4,
            "tier2_transcript_json": None,
        }
        fake_loop = SimpleNamespace(
            run_in_executor=AsyncMock(return_value='{"summary":"S","actions":[]}')
        )

        with (
            patch.object(mr.db, "get_meeting_recording", return_value=recording),
            patch.object(mr.asyncio, "get_running_loop", return_value=fake_loop),
            patch.object(
                service,
                "_parse_analysis_response",
                return_value={"summary": "S", "actions": []},
            ),
            patch.object(mr.db, "update_meeting_recording") as mock_update,
        ):
            result = await service.generate_analysis("rec-good")

        assert result == {"summary": "S", "actions": []}
        mock_update.assert_called_once_with(
            "rec-good", ai_summary="S", ai_actions_json="[]"
        )

    @pytest.mark.asyncio
    async def test_generate_analysis_llm_exception_returns_error_payload(self):
        service = mr.MeetingAnalysisService(MagicMock())
        recording = {
            "tier1_transcript": "This is a long enough transcript with many words. "
            * 4,
            "tier2_transcript_json": None,
        }
        fake_loop = SimpleNamespace(
            run_in_executor=AsyncMock(side_effect=RuntimeError("llm down"))
        )

        with (
            patch.object(mr.db, "get_meeting_recording", return_value=recording),
            patch.object(mr.asyncio, "get_running_loop", return_value=fake_loop),
        ):
            result = await service.generate_analysis("rec-err")

        assert result["error"] == "llm down"
        assert result["summary"] is None
        assert result["actions"] == []
