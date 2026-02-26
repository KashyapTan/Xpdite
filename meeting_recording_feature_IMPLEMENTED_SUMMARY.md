# Meeting Recorder Feature Implementation Details

This document details all the changes made across Phases 1, 2, and 3 to implement the end-to-end recording, transcription, and AI analysis features of the Meeting Recorder in Xpdite.

---

## Phase 1: Audio Capture, Live Transcription, and Core Infrastructure

The goal of Phase 1 was to establish the bedrock of the recording feature: capturing system and microphone audio without external drivers, streaming it to the backend, live transcribing it, and saving it to the database.

### 1. Dual-Stream Audio Capture (`electron-audio-loopback`)
- Integrated `electron-audio-loopback` in the Electron renderer to capture both the system output (what the user hears) and the microphone input simultaneously.
- Established a binary WebSocket pipeline to stream 16kHz, 16-bit PCM raw audio chunks from the frontend to the backend every 500ms.
- Built a Python-side audio mixer to combine the mic and loopback tracks to prevent clipping.
- Incremental archiving: Audio is streamed directly into an OPUS (`.opus`) file incrementally, preventing data loss if the app crashes mid-meeting.

### 2. Tier 1 Live Transcription (`faster-whisper`)
- Implemented real-time transcription using `faster-whisper` (`base` or `small` models).
- Built a rolling audio chunk processor that feeds 5-second overlapping audio chunks to the model to produce continuous, timestamped text.
- Sent `meeting_transcript_chunk` WebSocket events back to the frontend to accumulate a live-scrolling meeting transcript view while the meeting is happening.
- Implemented queue dropping (discarding oldest chunks) if transcription falls behind audio capture, ensuring the user interface remains snappy.

### 3. Core UI and Recording Lifecycle
- Created the distinct "Meeting Recorder" mode toggle in the UI, replacing the standard chat input with a centered recording toggle button.
- Built the "Meeting Recordings" history tab to browse past meetings, including a search bar and duration metrics.
- Persisted global recording state so the user can switch away to the chat tab, interact with the LLM, and browse the web without interrupting an active background recording.

### 4. Database Schema
- Expanded the local SQLite database to include a comprehensive `meeting_recordings` table tracking `started_at`, `ended_at`, `duration_seconds`, recording `status` (`recording`, `processing`, `ready`, `partial`), and transcript/blob references.

---

## Phase 2: Tier 2 Audio Post-Processing Pipeline

The goal of Phase 2 was to process finished recordings in the background to achieve high-quality transcription and speaker diarization.

### 1. Dependency Management
- Added several heavy AI/ML packages to the project using `uv add`:
  - `whisperx` (version `3.8.1`+)
  - `speechbrain` (version `1.0.3`+)
  - `torchaudio` and `torch` (version `2.8.0`+)

### 2. Device and Environment Configuration (`gpu_detector.py`)
- Created `source/services/gpu_detector.py` to handle PyTorch device placement:
  - Detects CUDA (NVIDIA) or MPS/CoreML (Apple Silicon) automatically.
  - Exposes `get_device()` to return `"cuda"`, `"mps"`, or `"cpu"`, along with VRAM info.
- Built `_handle_meeting_get_compute_info` WS handler to show compute backend info in the UI.

### 3. Settings Implementation
- Extended `DatabaseManager` to persist user preferences:
  - `meeting_whisper_model`: Sets model size (`tiny`, `base`, `small`).
  - `meeting_keep_audio`: Toggle dictating whether raw PCM/WAV audio is preserved.
  - `meeting_diarization_enabled`: Toggle for running speaker diarization.

### 4. Background Post-Processing Engine (`meeting_recorder.py`)
- Implemented `PostProcessingPipeline` to run sequentially when recording stops:
  1. **Audio Alignment:** Converts chunked Tier 1 audio into a single `.wav` file.
  2. **Tier 2 Transcription:** Re-transcribes the audio using a higher-quality model.
  3. **Diarization:** Runs speaker diarization to separate voices ("Speaker 1", "Speaker 2").
  4. **Cleanup:** Removes the combined `.wav` file based on preferences.
- Built crash recovery/fallback mechanism to downgrade gracefully on GPU OOM errors.

### 5. UI Integration for Processing
- Created `meeting_processing_progress` WS message to output real-time percent-complete updates.
- Rendered status badges (e.g., `Processing — Diarizing audio... 64%`) across the UI.
- Updated the transcript UI to display segmented blocks with distinct colors assigned to different speakers.

---

## Phase 3: AI Analysis & Action Abstraction

The goal of Phase 3 was to harness LLMs to process the finalized text transcript, extract insights, and bridge into automated actions via MCP servers.

### 1. `MeetingAnalysisService` Backend Module
- Built `generate_analysis(recording_id)` to orchestrate intelligence:
  - **Transcript Extraction:** Looks for Tier 2 JSON segments; falls back to Tier 1 text if unavailable.
  - **Context Management:** Truncates extremely long meetings (over 4000 words) to prevent blowing out the context window.
  - **Dynamic Model Injection:** Uses `app_state.selected_model` matching the global user choice.
  - **Thread Pooling:** Uses `loop.run_in_executor()` to run `ollama.chat()` asynchronously, preventing event loop blocking.

### 2. Prompting & LLM JSON Engineering
- Prompt enforces two outputs: a 3-5 sentence `summary`, and an array of `actions` dicts.
- Built robust JSON parser (`_parse_analysis_response()`):
  - Gracefully strips markdown code fences using `find()` loops.
  - Catches LLM `JSONDecodeError`s, falling back to outputting raw text as the summary and setting an error flag, guaranteeing the UI never crashes on bad model output.

### 3. Action Suggestion Mapping (MCP Tools)
- Mapped 3 action types:
  - **`calendar_event`:** Requires `title`, `date`, `time`, and `duration_minutes`.
  - **`email`:** Requires `to`, `subject`, and `body`.
  - **`task`:** Requires `description`, `assignee`, and `due_date`.
- Created WebSocket handler `_handle_meeting_execute_action` to parse frontend calls and route them to `mcp_manager.call_tool()`.
- Explicitly mapped Calendar args (`title`, `start`, `end`) and Gmail args (`to`, `subject`, `body`) to match exact MCP server signatures.

### 4. Meeting Detail UI Overhaul (`MeetingRecordingDetail.tsx`)
- Constructed interactive React UI:
  - **On-Demand Loading:** "✨ Summarize with AI" button.
  - **Loading States:** Spinner overlay and "Based on live transcript" warning banners.
  - **Error Bounds:** Retry button displayed on WebSocket errors.
- **Action Suggestion Forms:**
  - Interactive cards (Calendar, Email, Task) with color-coded borders.
  - Editable `input`/`textarea` fields so users can overwrite AI parameter predictions before executing.
  - Connected "Create Draft" and "Create Event" buttons straight to the MCP Websocket layer.

### 5. Backend Logic Validation (TDD)
- Built `tests/test_meeting_analysis.py` containing 29 robust edge-case unit tests spanning exactly 4 logic clusters to isolate error handling bounds:
  1. `TestParseAnalysisResponse` (11 tests — JSON extraction, error formatting).
  2. `TestExtractTranscriptText` (8 tests — fallback logic).
  3. `TestCalcEndTime` (6 tests — string date math).
  4. `TestBuildAnalysisPrompt` (4 tests).
