"""Audio transcription service using faster-whisper.

Provides start/stop recording with background thread audio capture
and Whisper model inference for speech-to-text.
"""

import threading
import time
import queue
import tempfile
import os
import logging
import asyncio
import pyaudio
import wave
from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)


class TranscriptionService:
    def __init__(self, model_size="base.en"):
        self.model_size = model_size
        self.model = None
        self.is_recording = False
        self._recording_error: str | None = None  # set by _record_audio on failure
        self.stop_recording_event = threading.Event()
        self.audio_queue = queue.Queue()
        self.recording_thread = None

        # Audio configuration
        self.CHUNK = 1024
        self.FORMAT = pyaudio.paInt16
        self.CHANNELS = 1
        self.RATE = 16000
        self.SAMPLE_WIDTH = 2  # pyaudio.paInt16 is always 2 bytes

    def _load_model(self):
        """Load the Whisper model if not already loaded."""
        if self.model is None:
            logger.info("Loading Whisper model: %s...", self.model_size)
            # Run on CPU by default for broad compatibility, or CUDA if available
            # We'll use "int8" quantization for speed
            try:
                self.model = WhisperModel(
                    self.model_size, device="auto", compute_type="int8"
                )
                logger.info("Whisper model loaded successfully.")
            except Exception as e:
                logger.error("Error loading Whisper model: %s", e)

    def start_recording(self) -> None:
        """Start recording audio in a background thread."""
        if self.is_recording:
            return

        self.is_recording = True
        self._recording_error = None
        self.stop_recording_event.clear()
        self.audio_queue = queue.Queue()

        self.recording_thread = threading.Thread(target=self._record_audio, daemon=True)
        self.recording_thread.start()
        logger.info("Recording started...")

    def stop_recording(self) -> str | None:
        """Stop recording and return the transcribed text."""
        if not self.is_recording:
            return None

        logger.info("Stopping recording...")
        self.is_recording = False
        self.stop_recording_event.set()

        if self.recording_thread:
            self.recording_thread.join()

        # Check for recording errors
        if self._recording_error:
            return f"Error: {self._recording_error}"

        # Process the recorded audio
        return self._transcribe_audio()

    def _record_audio(self):
        """Internal method to capture audio from the microphone."""
        p = pyaudio.PyAudio()

        try:
            stream = p.open(
                format=self.FORMAT,
                channels=self.CHANNELS,
                rate=self.RATE,
                input=True,
                frames_per_buffer=self.CHUNK,
            )

            while not self.stop_recording_event.is_set():
                data = stream.read(self.CHUNK)
                self.audio_queue.put(data)

            stream.stop_stream()
            stream.close()
        except Exception as e:
            logger.error("Error recording audio: %s", e)
            self._recording_error = str(e)
        finally:
            p.terminate()

    def _transcribe_audio(self):
        """Transcribe the recorded audio using faster-whisper."""
        # Ensure model is loaded (lazy loading)
        if self.model is None:
            self._load_model()

        if self.model is None:
            return "Error: Transcription model failed to load"

        if self.audio_queue.empty():
            return ""

        # Collect all audio chunks
        frames = []
        while not self.audio_queue.empty():
            frames.append(self.audio_queue.get())

        # Save to a temporary WAV file
        # faster-whisper handles file inputs robustly
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_audio:
            temp_filename = temp_audio.name

        try:
            wf = wave.open(temp_filename, "wb")
            wf.setnchannels(self.CHANNELS)
            wf.setsampwidth(self.SAMPLE_WIDTH)
            wf.setframerate(self.RATE)
            wf.writeframes(b"".join(frames))
            wf.close()

            # Transcribe
            logger.info("Transcribing %d chunks...", len(frames))
            segments, info = self.model.transcribe(temp_filename, beam_size=5)

            text = " ".join([segment.text for segment in segments]).strip()
            logger.info("Transcription result: %s", text)
            return text

        except Exception as e:
            logger.error("Transcription error: %s", e)
            return f"Error: {str(e)}"
        finally:
            # Cleanup temp file
            if os.path.exists(temp_filename):
                os.remove(temp_filename)
