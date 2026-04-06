"""Tests for source/services/media/transcription.py."""

import importlib
import os
import queue
import sys
import types
from typing import Any

import pytest


@pytest.fixture()
def ts_module(monkeypatch):
    monkeypatch.setitem(
        sys.modules, "pyaudio", types.SimpleNamespace(paInt16=16, PyAudio=object)
    )
    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        types.SimpleNamespace(WhisperModel=object),
    )
    module = importlib.import_module("source.services.media.transcription")
    return importlib.reload(module)


ts: Any


@pytest.fixture(autouse=True)
def _bind_ts(ts_module):
    global ts
    ts = ts_module
    yield


class _FakeThread:
    def __init__(self, target=None, daemon=None):
        self.target = target
        self.daemon = daemon
        self.started = False
        self.joined = False

    def start(self):
        self.started = True

    def join(self):
        self.joined = True


class _Segment:
    def __init__(self, text):
        self.text = text


class TestTranscriptionService:
    def test_start_recording_starts_background_thread(self, monkeypatch):
        service = ts.TranscriptionService()
        created_threads = []

        def _make_thread(*_args, **kwargs):
            thread = _FakeThread(**kwargs)
            created_threads.append(thread)
            return thread

        monkeypatch.setattr(ts.threading, "Thread", _make_thread)

        service.start_recording()

        assert service.is_recording is True
        assert service._recording_error is None
        assert len(created_threads) == 1
        assert created_threads[0].started is True
        assert created_threads[0].daemon is True

    def test_start_recording_noop_when_already_recording(self, monkeypatch):
        service = ts.TranscriptionService()
        service.is_recording = True
        called = {"thread": False}

        def _make_thread(*_args, **_kwargs):
            called["thread"] = True
            return _FakeThread()

        monkeypatch.setattr(ts.threading, "Thread", _make_thread)

        service.start_recording()

        assert called["thread"] is False

    def test_stop_recording_returns_none_when_not_recording(self):
        service = ts.TranscriptionService()
        assert service.stop_recording() is None

    def test_stop_recording_returns_recording_error(self):
        service = ts.TranscriptionService()
        service.is_recording = True
        service._recording_error = "microphone failed"
        worker = _FakeThread()
        service.recording_thread = worker

        result = service.stop_recording()

        assert result == "Error: microphone failed"
        assert worker.joined is True
        assert service.is_recording is False

    def test_stop_recording_transcribes_on_success(self, monkeypatch):
        service = ts.TranscriptionService()
        service.is_recording = True
        service.recording_thread = _FakeThread()
        monkeypatch.setattr(service, "_transcribe_audio", lambda: "hello transcript")

        assert service.stop_recording() == "hello transcript"

    def test_record_audio_reads_stream_and_terminates(self, monkeypatch):
        service = ts.TranscriptionService()

        class _Stream:
            def __init__(self):
                self.closed = False
                self.stopped = False

            def read(self, _chunk):
                service.stop_recording_event.set()
                return b"audio-bytes"

            def stop_stream(self):
                self.stopped = True

            def close(self):
                self.closed = True

        class _PyAudio:
            def __init__(self):
                self.stream = _Stream()
                self.terminated = False

            def open(self, **_kwargs):
                return self.stream

            def terminate(self):
                self.terminated = True

        fake_audio = _PyAudio()
        monkeypatch.setattr(ts.pyaudio, "PyAudio", lambda: fake_audio)

        service._record_audio()

        assert fake_audio.stream.stopped is True
        assert fake_audio.stream.closed is True
        assert fake_audio.terminated is True
        assert service.audio_queue.get_nowait() == b"audio-bytes"

    def test_record_audio_sets_error_on_open_failure(self, monkeypatch):
        service = ts.TranscriptionService()

        class _PyAudio:
            def __init__(self):
                self.terminated = False

            def open(self, **_kwargs):
                raise RuntimeError("mic unavailable")

            def terminate(self):
                self.terminated = True

        fake_audio = _PyAudio()
        monkeypatch.setattr(ts.pyaudio, "PyAudio", lambda: fake_audio)

        service._record_audio()

        assert service._recording_error == "mic unavailable"
        assert fake_audio.terminated is True

    def test_transcribe_audio_returns_model_load_error(self, monkeypatch):
        service = ts.TranscriptionService()
        monkeypatch.setattr(
            ts,
            "WhisperModel",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("load fail")),
        )

        assert (
            service._transcribe_audio() == "Error: Transcription model failed to load"
        )

    def test_transcribe_audio_returns_empty_when_no_audio(self):
        service = ts.TranscriptionService()
        service.model = object()

        assert service._transcribe_audio() == ""

    def test_transcribe_audio_success_and_temp_file_cleanup(
        self, tmp_path, monkeypatch
    ):
        service = ts.TranscriptionService()
        service.audio_queue = queue.Queue()
        service.audio_queue.put(b"a")
        service.audio_queue.put(b"b")

        class _Model:
            def transcribe(self, _filename, beam_size):
                assert beam_size == 5
                return [_Segment("hello"), _Segment("world")], object()

        service.model = _Model()

        temp_path = tmp_path / "audio-temp.wav"

        class _TempFile:
            def __enter__(self):
                temp_path.write_bytes(b"")
                return types.SimpleNamespace(name=str(temp_path))

            def __exit__(self, _exc_type, _exc, _tb):
                return False

        removed = []
        real_remove = os.remove

        def _remove(path):
            removed.append(path)
            real_remove(path)

        class _WaveWriter:
            def setnchannels(self, _v):
                pass

            def setsampwidth(self, _v):
                pass

            def setframerate(self, _v):
                pass

            def writeframes(self, _frames):
                pass

            def close(self):
                pass

        monkeypatch.setattr(
            ts.tempfile, "NamedTemporaryFile", lambda **_kwargs: _TempFile()
        )
        monkeypatch.setattr(ts.wave, "open", lambda *_args, **_kwargs: _WaveWriter())
        monkeypatch.setattr(ts.os, "remove", _remove)

        result = service._transcribe_audio()

        assert result == "hello world"
        assert removed == [str(temp_path)]

    def test_transcribe_audio_handles_model_failure_and_cleans_temp_file(
        self, tmp_path, monkeypatch
    ):
        service = ts.TranscriptionService()
        service.audio_queue = queue.Queue()
        service.audio_queue.put(b"a")

        class _BrokenModel:
            def transcribe(self, _filename, beam_size):
                raise RuntimeError("decode failed")

        service.model = _BrokenModel()

        temp_path = tmp_path / "audio-temp.wav"

        class _TempFile:
            def __enter__(self):
                temp_path.write_bytes(b"")
                return types.SimpleNamespace(name=str(temp_path))

            def __exit__(self, _exc_type, _exc, _tb):
                return False

        removed = []
        real_remove = os.remove

        def _remove(path):
            removed.append(path)
            real_remove(path)

        class _WaveWriter:
            def setnchannels(self, _v):
                pass

            def setsampwidth(self, _v):
                pass

            def setframerate(self, _v):
                pass

            def writeframes(self, _frames):
                pass

            def close(self):
                pass

        monkeypatch.setattr(
            ts.tempfile, "NamedTemporaryFile", lambda **_kwargs: _TempFile()
        )
        monkeypatch.setattr(ts.wave, "open", lambda *_args, **_kwargs: _WaveWriter())
        monkeypatch.setattr(ts.os, "remove", _remove)

        result = service._transcribe_audio()

        assert result == "Error: decode failed"
        assert removed == [str(temp_path)]
