"""Meeting Recorder Service.

Orchestrates the recording lifecycle: audio chunk reception, WAV file writing,
live transcription (Tier 1 via faster-whisper), and recording state management.
Includes Tier 2 post-processing pipeline for higher-quality transcription with
word-level timestamps, speaker diarization, and AI title generation.

Audio capture happens in the Electron renderer via electron-audio-loopback.
Raw PCM audio chunks are streamed to this service over WebSocket. This service
handles mixing, file writing, and transcription — no audio processing in the
renderer.
"""

import asyncio
import json
import logging
import os
import struct
import threading
import time
import wave
from typing import Any

from ..config import PROJECT_ROOT
from ..core.connection import broadcast_message
from ..database import db

logger = logging.getLogger(__name__)

# Directory for raw audio files during recording
MEETING_AUDIO_DIR = os.path.join("user_data", "meeting_audio")
os.makedirs(MEETING_AUDIO_DIR, exist_ok=True)

# Audio format constants (must match renderer capture settings)
SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2  # 16-bit PCM = 2 bytes per sample
CHANNELS = 1  # Mono (mixed from loopback + mic)

# Transcription chunk settings
CHUNK_DURATION_SECONDS = 5
OVERLAP_SECONDS = 1
CHUNK_SAMPLES = SAMPLE_RATE * CHUNK_DURATION_SECONDS
OVERLAP_SAMPLES = SAMPLE_RATE * OVERLAP_SECONDS

# Max unprocessed transcription chunks before dropping oldest
MAX_TRANSCRIPTION_QUEUE = 3

# Silence detection: if RMS is below this threshold, skip transcription
SILENCE_RMS_THRESHOLD = 50


class MeetingRecorderService:
    """Singleton service managing active meeting recordings.

    Only one recording can be active at a time. Audio chunks from the
    renderer are written to a WAV file and fed into the live transcription
    pipeline (faster-whisper in a background thread).
    """

    def __init__(self):
        self._recording_id: str | None = None
        self._started_at: float | None = None
        self._audio_file_path: str | None = None
        self._wav_writer: wave.Wave_write | None = None
        self._is_recording = False

        # Transcription state
        self._transcription_thread: threading.Thread | None = None
        self._transcription_stop_event = threading.Event()
        self._audio_buffer = bytearray()  # Accumulates PCM for chunking
        self._buffer_lock = threading.Lock()
        self._whisper_model = None
        self._model_size = "base"

        # Event loop reference for broadcasting from threads
        self._loop: asyncio.AbstractEventLoop | None = None

        # Post-processing pipeline
        self._processing_pipeline = PostProcessingPipeline(self)

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    @property
    def recording_id(self) -> str | None:
        return self._recording_id

    def get_status(self) -> dict[str, Any]:
        """Return current recording status for frontend sync."""
        if not self._is_recording:
            return {"is_recording": False, "recording_id": None}
        elapsed = time.time() - (self._started_at or time.time())
        return {
            "is_recording": True,
            "recording_id": self._recording_id,
            "duration_seconds": int(elapsed),
            "started_at": self._started_at,
        }

    def set_model_size(self, size: str) -> None:
        """Change the Whisper model size for live transcription.

        Takes effect on the next recording start (model is lazily loaded).
        """
        if size in ("tiny", "base", "small"):
            self._model_size = size
            # Force reload on next recording
            self._whisper_model = None

    async def start_recording(self) -> dict[str, Any]:
        """Begin a new recording session.

        Creates a DB record, opens a WAV file writer, and starts the
        live transcription thread.

        Returns dict with recording_id and status info.
        """
        if self._is_recording:
            raise RuntimeError("A recording is already in progress")

        self._loop = asyncio.get_running_loop()
        self._started_at = time.time()

        # Generate title from timestamp
        title = time.strftime("Meeting %Y-%m-%d %H:%M", time.localtime(self._started_at))

        # Create DB record
        self._recording_id = db.create_meeting_recording(title, self._started_at)

        # Open WAV file
        self._audio_file_path = os.path.join(
            MEETING_AUDIO_DIR, f"{self._recording_id}.wav"
        )
        self._wav_writer = wave.open(self._audio_file_path, "wb")
        self._wav_writer.setnchannels(CHANNELS)
        self._wav_writer.setsampwidth(SAMPLE_WIDTH)
        self._wav_writer.setframerate(SAMPLE_RATE)

        # Update DB with audio path
        db.update_meeting_recording(
            self._recording_id, audio_file_path=self._audio_file_path
        )

        # Reset transcription state
        self._audio_buffer = bytearray()
        self._transcription_stop_event.clear()

        # Start transcription thread
        self._is_recording = True
        self._transcription_thread = threading.Thread(
            target=self._transcription_worker,
            daemon=True,
            name="meeting-transcription",
        )
        self._transcription_thread.start()

        logger.info(
            "Meeting recording started: %s (%s)", self._recording_id, title
        )

        return {
            "recording_id": self._recording_id,
            "title": title,
            "started_at": self._started_at,
        }

    async def stop_recording(self) -> dict[str, Any]:
        """Stop the active recording.

        Finalizes the audio file, updates DB, stops the transcription
        thread, and triggers the Tier 2 post-processing pipeline.
        """
        if not self._is_recording:
            raise RuntimeError("No recording is in progress")

        recording_id = self._recording_id
        audio_file_path = self._audio_file_path
        self._is_recording = False
        ended_at = time.time()
        duration = int(ended_at - (self._started_at or ended_at))

        # Stop transcription thread
        self._transcription_stop_event.set()
        if self._transcription_thread and self._transcription_thread.is_alive():
            self._transcription_thread.join(timeout=5)

        # Process any remaining audio in the buffer
        self._process_remaining_buffer()

        # Close WAV file
        if self._wav_writer:
            try:
                self._wav_writer.close()
            except Exception as e:
                logger.error("Error closing WAV file: %s", e)
            self._wav_writer = None

        # Update DB — set to 'processing' since Tier 2 will run
        db.update_meeting_recording(
            recording_id,
            ended_at=ended_at,
            duration_seconds=duration,
            status="processing",
        )

        logger.info(
            "Meeting recording stopped: %s (duration: %ds)", recording_id, duration
        )

        result = {
            "recording_id": recording_id,
            "duration_seconds": duration,
            "status": "processing",
        }

        # Clean up state
        self._recording_id = None
        self._started_at = None
        self._audio_file_path = None

        # Queue Tier 2 post-processing
        self._processing_pipeline.enqueue(recording_id, audio_file_path, duration)

        return result

    def handle_audio_chunk(self, pcm_data: bytes) -> None:
        """Receive a PCM audio chunk from the WebSocket.

        Writes to WAV file and adds to the transcription buffer.
        Called from the WS handler (event loop thread).
        """
        if not self._is_recording:
            return

        # Write to WAV file
        if self._wav_writer:
            try:
                self._wav_writer.writeframes(pcm_data)
            except Exception as e:
                logger.error("Error writing audio to WAV: %s", e)

        # Add to transcription buffer
        with self._buffer_lock:
            self._audio_buffer.extend(pcm_data)

    def _transcription_worker(self) -> None:
        """Background thread for live transcription.

        Pulls 5-second chunks from the audio buffer with 1-second overlap,
        transcribes via faster-whisper, and broadcasts results to the frontend.
        """
        try:
            self._load_whisper_model()
        except Exception as e:
            logger.error("Failed to load Whisper model: %s", e)
            self._broadcast_from_thread(
                "meeting_recording_error",
                {
                    "recording_id": self._recording_id,
                    "error": f"Transcription model failed to load: {e}",
                },
            )
            return

        chunk_bytes = CHUNK_SAMPLES * SAMPLE_WIDTH
        overlap_bytes = OVERLAP_SAMPLES * SAMPLE_WIDTH
        samples_processed = 0

        while not self._transcription_stop_event.is_set():
            # Wait for enough audio to accumulate
            self._transcription_stop_event.wait(timeout=0.5)

            with self._buffer_lock:
                if len(self._audio_buffer) < chunk_bytes:
                    continue
                # Extract chunk
                chunk = bytes(self._audio_buffer[:chunk_bytes])
                # Keep overlap for next chunk
                self._audio_buffer = self._audio_buffer[chunk_bytes - overlap_bytes:]

            # Check for silence (skip transcription for silent chunks)
            if self._is_silence(chunk):
                samples_processed += CHUNK_SAMPLES - OVERLAP_SAMPLES
                continue

            # Transcribe
            try:
                text = self._transcribe_chunk(chunk)
                if text and len(text.split()) >= 2:  # Filter very short segments
                    start_time = samples_processed / SAMPLE_RATE
                    end_time = start_time + CHUNK_DURATION_SECONDS

                    # Append to DB
                    if self._recording_id:
                        timestamp_prefix = f"[{self._format_time(start_time)}] "
                        db.append_tier1_transcript(
                            self._recording_id,
                            timestamp_prefix + text + "\n",
                        )

                    # Broadcast to frontend
                    self._broadcast_from_thread(
                        "meeting_transcript_chunk",
                        {
                            "recording_id": self._recording_id,
                            "text": text,
                            "start_time": start_time,
                            "end_time": end_time,
                        },
                    )
            except Exception as e:
                logger.error("Transcription error for chunk: %s", e)

            samples_processed += CHUNK_SAMPLES - OVERLAP_SAMPLES

    def _process_remaining_buffer(self) -> None:
        """Transcribe any remaining audio in the buffer after recording stops."""
        with self._buffer_lock:
            remaining = bytes(self._audio_buffer)
            self._audio_buffer = bytearray()

        if not remaining or len(remaining) < SAMPLE_RATE * SAMPLE_WIDTH:
            return  # Less than 1 second, skip

        try:
            text = self._transcribe_chunk(remaining)
            if text and self._recording_id:
                db.append_tier1_transcript(self._recording_id, text + "\n")
        except Exception as e:
            logger.error("Error transcribing remaining buffer: %s", e)

    def _load_whisper_model(self) -> None:
        """Load faster-whisper model (lazy, once per app session)."""
        if self._whisper_model is not None:
            return

        logger.info("Loading Whisper model: %s...", self._model_size)
        from faster_whisper import WhisperModel

        self._whisper_model = WhisperModel(
            self._model_size, device="auto", compute_type="int8"
        )
        logger.info("Whisper model loaded.")

    def _transcribe_chunk(self, pcm_data: bytes) -> str:
        """Transcribe a PCM audio chunk using faster-whisper.

        Writes to a temp WAV file since faster-whisper expects file input.
        Returns transcribed text or empty string.
        """
        if not self._whisper_model:
            return ""

        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            wf = wave.open(tmp_path, "wb")
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(SAMPLE_WIDTH)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(pcm_data)
            wf.close()

            segments, _ = self._whisper_model.transcribe(tmp_path, beam_size=5)
            text = " ".join(seg.text for seg in segments).strip()
            return text
        except Exception as e:
            logger.error("Whisper transcription error: %s", e)
            return ""
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    @staticmethod
    def _is_silence(pcm_data: bytes) -> bool:
        """Check if a PCM chunk is effectively silence via RMS."""
        if len(pcm_data) < 2:
            return True

        n_samples = len(pcm_data) // SAMPLE_WIDTH
        if n_samples == 0:
            return True

        # Compute RMS of 16-bit PCM samples
        total = 0
        for i in range(0, len(pcm_data) - 1, SAMPLE_WIDTH):
            sample = struct.unpack_from("<h", pcm_data, i)[0]
            total += sample * sample

        rms = (total / n_samples) ** 0.5
        return rms < SILENCE_RMS_THRESHOLD

    @staticmethod
    def _format_time(seconds: float) -> str:
        """Format seconds as MM:SS."""
        m, s = divmod(int(seconds), 60)
        return f"{m:02d}:{s:02d}"

    def _broadcast_from_thread(self, msg_type: str, content: Any) -> None:
        """Schedule a WebSocket broadcast from a background thread."""
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(
                broadcast_message(msg_type, content), self._loop
            )

    def recover_interrupted_recordings(self) -> None:
        """Re-queue any recordings that were interrupted mid-processing.

        Called at startup to handle crash recovery.
        """
        try:
            recordings = db.get_meeting_recordings(limit=100, offset=0)
            for rec in recordings:
                if rec.get("status") == "processing":
                    rid = rec["id"]
                    audio_path = rec.get("audio_file_path")
                    duration = rec.get("duration_seconds", 0)
                    if audio_path and os.path.exists(audio_path):
                        logger.info("Re-queuing interrupted recording: %s", rid)
                        self._processing_pipeline.enqueue(rid, audio_path, duration)
                    else:
                        logger.warning(
                            "No audio file for interrupted recording %s, marking partial", rid
                        )
                        db.update_meeting_recording(rid, status="partial")
                elif rec.get("status") == "recording":
                    # Recording was interrupted (app crash) — mark partial
                    rid = rec["id"]
                    logger.warning("Recording %s was interrupted, marking partial", rid)
                    db.update_meeting_recording(rid, status="partial")
        except Exception as e:
            logger.error("Error recovering interrupted recordings: %s", e)


class PostProcessingPipeline:
    """Tier 2 post-processing pipeline for meeting recordings.

    Runs sequentially in a background thread. Steps:
    1. Transcription — faster-whisper large-v3 on full audio
    2. Alignment — WhisperX forced alignment (word-level timestamps)
    3. Diarization — SpeechBrain speaker diarization
    4. Merge — Combine alignment + diarization into JSON
    5. AI title — LLM-generated title from first ~500 words
    6. Save + cleanup
    """

    STEPS = [
        "transcribing",
        "aligning",
        "diarizing",
        "merging",
        "generating_title",
        "saving",
    ]

    def __init__(self, recorder_service: MeetingRecorderService):
        self._service = recorder_service
        self._queue: list[dict] = []
        self._queue_lock = threading.Lock()
        self._worker_thread: threading.Thread | None = None
        self._is_running = False

    def enqueue(
        self,
        recording_id: str,
        audio_file_path: str | None,
        duration_seconds: int,
    ) -> None:
        """Add a recording to the processing queue."""
        with self._queue_lock:
            self._queue.append({
                "recording_id": recording_id,
                "audio_file_path": audio_file_path,
                "duration_seconds": duration_seconds,
            })

        # Start worker if not running
        if not self._is_running:
            self._is_running = True
            self._worker_thread = threading.Thread(
                target=self._worker,
                daemon=True,
                name="meeting-postprocess",
            )
            self._worker_thread.start()

    def _worker(self) -> None:
        """Process queued recordings sequentially."""
        while True:
            with self._queue_lock:
                if not self._queue:
                    self._is_running = False
                    return
                job = self._queue.pop(0)

            try:
                self._process_recording(job)
            except Exception as e:
                logger.error(
                    "Post-processing failed for %s: %s",
                    job["recording_id"],
                    e,
                )
                db.update_meeting_recording(
                    job["recording_id"], status="partial"
                )
                self._broadcast_progress(
                    job["recording_id"], "error", 0, 0
                )

    def _process_recording(self, job: dict) -> None:
        """Run the full Tier 2 pipeline on a single recording."""
        recording_id = job["recording_id"]
        audio_path = job["audio_file_path"]
        duration = job["duration_seconds"] or 0

        logger.info("Starting Tier 2 processing for %s", recording_id)

        if not audio_path or not os.path.exists(audio_path):
            logger.error("Audio file not found: %s", audio_path)
            db.update_meeting_recording(recording_id, status="partial")
            return

        from .gpu_detector import get_compute_info, get_estimated_processing_time

        compute_info = get_compute_info()
        backend = compute_info["backend"]
        compute_type = compute_info["compute_type"]
        estimated_total = get_estimated_processing_time(duration)

        # ── Step 1: Full transcription with large-v3 ──
        self._broadcast_progress(
            recording_id, "transcribing", 10, estimated_total * 0.9
        )

        tier2_segments = None
        try:
            tier2_segments = self._transcribe_full(audio_path, backend, compute_type)
        except Exception as e:
            logger.error("Tier 2 transcription failed: %s", e)
            if backend == "cuda":
                logger.info("Retrying Tier 2 on CPU after CUDA failure")
                try:
                    tier2_segments = self._transcribe_full(audio_path, "cpu", "int8")
                except Exception as e2:
                    logger.error("CPU retry also failed: %s", e2)

        if not tier2_segments:
            logger.warning("Tier 2 produced no segments, marking as partial")
            db.update_meeting_recording(recording_id, status="partial")
            self._broadcast_progress(recording_id, "error", 0, 0)
            return

        # ── Step 2: WhisperX alignment ──
        self._broadcast_progress(
            recording_id, "aligning", 40, estimated_total * 0.5
        )

        aligned_segments = None
        try:
            aligned_segments = self._align_transcript(tier2_segments, audio_path, backend)
        except Exception as e:
            logger.warning("WhisperX alignment failed (continuing without): %s", e)

        # ── Step 3: SpeechBrain diarization ──
        self._broadcast_progress(
            recording_id, "diarizing", 60, estimated_total * 0.3
        )

        diarization_enabled = self._get_setting("meeting_diarization_enabled", "true") == "true"
        diarization_result = None
        if diarization_enabled:
            try:
                diarization_result = self._diarize(audio_path, backend)
            except Exception as e:
                logger.warning("Diarization failed (continuing without): %s", e)

        # ── Step 4: Merge into unified JSON ──
        self._broadcast_progress(
            recording_id, "merging", 75, estimated_total * 0.15
        )

        unified_transcript = self._merge_results(
            tier2_segments, aligned_segments, diarization_result
        )

        # ── Step 5: AI title generation ──
        self._broadcast_progress(
            recording_id, "generating_title", 85, estimated_total * 0.1
        )

        ai_title = None
        try:
            ai_title = self._generate_title(unified_transcript)
        except Exception as e:
            logger.warning("AI title generation failed: %s", e)

        # ── Step 6: Save to DB + cleanup ──
        self._broadcast_progress(
            recording_id, "saving", 95, estimated_total * 0.02
        )

        update_fields: dict[str, Any] = {
            "tier2_transcript_json": json.dumps(unified_transcript),
            "status": "ready",
        }
        if ai_title:
            update_fields["title"] = ai_title
            update_fields["ai_title_generated"] = 1

        db.update_meeting_recording(recording_id, **update_fields)

        # Delete audio file if "keep audio" is disabled
        keep_audio = self._get_setting("meeting_keep_audio", "false") == "true"
        if not keep_audio:
            try:
                os.remove(audio_path)
                db.update_meeting_recording(recording_id, audio_file_path=None)
                logger.info("Deleted audio file: %s", audio_path)
            except OSError as e:
                logger.warning("Failed to delete audio: %s", e)

        logger.info("Tier 2 processing complete for %s", recording_id)
        self._broadcast_progress(recording_id, "complete", 100, 0)

    # ----------------------------------------------------------------
    # Pipeline step implementations
    # ----------------------------------------------------------------

    def _transcribe_full(
        self, audio_path: str, backend: str, compute_type: str
    ) -> list[dict]:
        """Full transcription with faster-whisper large-v3."""
        from faster_whisper import WhisperModel

        device = "cuda" if backend == "cuda" else "cpu"
        logger.info(
            "Loading large-v3 model (device=%s, compute=%s)...", device, compute_type
        )
        model = WhisperModel("large-v3", device=device, compute_type=compute_type)

        segments, info = model.transcribe(
            audio_path, beam_size=5, word_timestamps=True
        )

        result = []
        for seg in segments:
            segment_data: dict[str, Any] = {
                "text": seg.text.strip(),
                "start": seg.start,
                "end": seg.end,
            }
            if seg.words:
                segment_data["words"] = [
                    {
                        "word": w.word,
                        "start": w.start,
                        "end": w.end,
                        "probability": w.probability,
                    }
                    for w in seg.words
                ]
            result.append(segment_data)

        logger.info(
            "Tier 2 transcription: %d segments, language=%s",
            len(result),
            getattr(info, "language", "unknown"),
        )
        return result

    def _align_transcript(
        self,
        segments: list[dict],
        audio_path: str,
        backend: str,
    ) -> list[dict] | None:
        """WhisperX forced alignment for word-level timestamps."""
        try:
            import whisperx
            import torch
        except ImportError:
            logger.warning("whisperx not installed — skipping alignment")
            return None

        device = "cuda" if backend == "cuda" and torch.cuda.is_available() else "cpu"

        audio = whisperx.load_audio(audio_path)
        wx_segments = [
            {"text": s["text"], "start": s["start"], "end": s["end"]}
            for s in segments
        ]

        model_a, metadata = whisperx.load_align_model(
            language_code="en", device=device
        )
        result = whisperx.align(wx_segments, model_a, metadata, audio, device)

        return result.get("segments", result.get("word_segments", []))

    def _diarize(self, audio_path: str, backend: str) -> dict | None:
        """SpeechBrain speaker diarization via WhisperX wrapper."""
        try:
            import whisperx
            import torch
        except ImportError:
            logger.warning("whisperx not installed — skipping diarization")
            return None

        device = "cuda" if backend == "cuda" and torch.cuda.is_available() else "cpu"

        diarize_model = whisperx.DiarizationPipeline(device=device)
        audio = whisperx.load_audio(audio_path)
        diarize_segments = diarize_model(audio)

        return diarize_segments

    def _merge_results(
        self,
        transcript_segments: list[dict],
        aligned_segments: list[dict] | None,
        diarization_result: dict | None,
    ) -> list[dict]:
        """Merge transcription, alignment, and diarization into unified JSON."""
        base_segments = aligned_segments if aligned_segments else transcript_segments

        if diarization_result is not None:
            try:
                import whisperx

                result = whisperx.assign_word_speakers(
                    diarization_result, {"segments": base_segments}
                )
                return result.get("segments", base_segments)
            except Exception as e:
                logger.warning("Speaker assignment failed: %s", e)

        return base_segments

    def _generate_title(self, transcript: list[dict]) -> str | None:
        """Generate a short meeting title using the configured LLM.

        Sends the first ~500 words to the LLM and asks for a 3-8 word title.
        """
        words_collected: list[str] = []
        for seg in transcript:
            words_collected.extend(seg.get("text", "").split())
            if len(words_collected) >= 500:
                break
        text_excerpt = " ".join(words_collected[:500])

        if len(text_excerpt.strip()) < 20:
            return None  # Too short for meaningful title

        prompt = (
            "Based on the following meeting transcript excerpt, generate a short, "
            "descriptive meeting title (3-8 words). Return ONLY the title text, "
            "nothing else.\n\n"
            f"Transcript:\n{text_excerpt}"
        )

        try:
            import ollama

            response = ollama.chat(
                model="llama3.2",
                messages=[{"role": "user", "content": prompt}],
            )
            title = response["message"]["content"].strip().strip('"').strip("'")
            if 1 <= len(title.split()) <= 10:
                return title
            logger.warning("AI title too long/short: '%s'", title)
            return title.split(":")[0].strip()[:60]
        except Exception as e:
            logger.warning("AI title generation failed: %s", e)
            return None

    def _broadcast_progress(
        self,
        recording_id: str,
        step: str,
        percentage: int,
        estimated_remaining: float,
    ) -> None:
        """Broadcast processing progress to the frontend."""
        self._service._broadcast_from_thread(
            "meeting_processing_progress",
            {
                "recording_id": recording_id,
                "step": step,
                "percentage": percentage,
                "estimated_remaining_seconds": int(estimated_remaining),
            },
        )

    @staticmethod
    def _get_setting(key: str, default: str = "") -> str:
        """Read a meeting setting from the database."""
        try:
            val = db.get_setting(key)
            return val if val is not None else default
        except Exception:
            return default


class MeetingAnalysisService:
    """On-demand AI analysis for completed meeting recordings.

    Generates summary + structured action suggestions via Ollama,
    saves to DB, and broadcasts results.
    """

    def __init__(self, recorder_service: MeetingRecorderService) -> None:
        self._service = recorder_service

    async def generate_analysis(self, recording_id: str) -> dict[str, Any]:
        """Generate AI summary and action suggestions for a recording.

        Returns dict with {summary, actions[], error?}.
        """
        import asyncio

        recording = db.get_meeting_recording(recording_id)
        if not recording:
            return {"error": "Recording not found"}

        # Get best available transcript text
        transcript_text = self._extract_transcript_text(recording)
        if not transcript_text or len(transcript_text.strip()) < 20:
            return {"error": "Transcript too short for analysis"}

        # Truncate to ~4000 words to avoid overloading context
        words = transcript_text.split()
        if len(words) > 4000:
            transcript_text = " ".join(words[:4000]) + "\n\n[... transcript truncated ...]"

        # Build prompt
        prompt = self._build_analysis_prompt(transcript_text)

        try:
            # Run blocking LLM call in a thread to avoid event loop stall
            loop = asyncio.get_running_loop()
            raw_response = await loop.run_in_executor(
                None, self._call_ollama, prompt
            )

            # Parse structured response
            result = self._parse_analysis_response(raw_response)

            # Save to database
            db.update_meeting_recording(
                recording_id,
                ai_summary=result["summary"],
                ai_actions_json=json.dumps(result["actions"]),
            )

            return result

        except Exception as e:
            logger.error("AI analysis failed for %s: %s", recording_id, e)
            return {"error": str(e), "summary": None, "actions": []}

    @staticmethod
    def _call_ollama(prompt: str) -> str:
        """Blocking Ollama call — run in a thread executor."""
        import ollama
        from ..core.state import app_state

        response = ollama.chat(
            model=app_state.selected_model,
            messages=[{"role": "user", "content": prompt}],
        )
        return response["message"]["content"].strip()

    def _extract_transcript_text(self, recording: dict) -> str:
        """Extract plain text from the best available transcript."""
        # Prefer Tier 2 if available
        tier2 = recording.get("tier2_transcript_json")
        if tier2:
            try:
                segments = json.loads(tier2) if isinstance(tier2, str) else tier2
                if isinstance(segments, list) and segments:
                    parts = []
                    for seg in segments:
                        speaker = seg.get("speaker", "")
                        text = seg.get("text", "")
                        if speaker:
                            parts.append(f"{speaker}: {text}")
                        else:
                            parts.append(text)
                    return "\n".join(parts)
            except (json.JSONDecodeError, TypeError):
                pass

        # Fall back to Tier 1
        return recording.get("tier1_transcript", "")

    def _build_analysis_prompt(self, transcript: str) -> str:
        """Build the analysis prompt for the LLM."""
        return (
            "You are analyzing a meeting transcript. Provide:\n"
            "1. A concise summary (3-5 sentences)\n"
            "2. Action suggestions extracted from the meeting\n\n"
            "Respond in this exact JSON format (no extra text):\n"
            "```json\n"
            "{\n"
            '  "summary": "...",\n'
            '  "actions": [\n'
            "    {\n"
            '      "type": "calendar_event",\n'
            '      "title": "...",\n'
            '      "date": "YYYY-MM-DD",\n'
            '      "time": "HH:MM",\n'
            '      "duration_minutes": 30,\n'
            '      "description": "..."\n'
            "    },\n"
            "    {\n"
            '      "type": "email",\n'
            '      "to": "...",\n'
            '      "subject": "...",\n'
            '      "body": "..."\n'
            "    },\n"
            "    {\n"
            '      "type": "task",\n'
            '      "description": "...",\n'
            '      "assignee": "...",\n'
            '      "due_date": "YYYY-MM-DD"\n'
            "    }\n"
            "  ]\n"
            "}\n"
            "```\n\n"
            "Only include actions that are clearly mentioned or implied in the "
            "transcript. If no actions are apparent, return an empty actions array.\n"
            "Extract real names, dates, and details from the transcript — do not "
            "use placeholders.\n\n"
            f"Transcript:\n{transcript}"
        )

    @staticmethod
    def _parse_analysis_response(raw: str) -> dict[str, Any]:
        """Parse the LLM response into summary + actions."""
        json_str = raw

        # Strip markdown code fences if present
        for fence in ("```json", "```"):
            idx = raw.find(fence)
            if idx != -1:
                content_start = idx + len(fence)
                closing = raw.find("```", content_start)
                json_str = raw[content_start:closing] if closing != -1 else raw[content_start:]
                break

        try:
            parsed = json.loads(json_str.strip())
            summary = parsed.get("summary", "")
            actions = parsed.get("actions", [])

            # Validate action types
            valid_types = ("calendar_event", "email", "task")
            valid_actions = [
                a for a in actions
                if isinstance(a, dict) and a.get("type") in valid_types
            ]

            return {"summary": summary, "actions": valid_actions}

        except (json.JSONDecodeError, ValueError):
            logger.warning("Failed to parse AI analysis JSON, using raw text as summary")
            return {"summary": raw[:1000], "actions": [], "parse_error": True}


# Module-level singletons
meeting_recorder_service = MeetingRecorderService()
meeting_analysis_service = MeetingAnalysisService(meeting_recorder_service)
meeting_recorder_service.recover_interrupted_recordings()

