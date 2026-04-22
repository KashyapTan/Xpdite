# Meeting Recorder

This document covers meeting recording, transcript handling, and analysis flows.

## Capabilities

- Start/stop meeting recording sessions.
- Stream transcript chunks to UI.
- Persist recordings and metadata.
- Generate AI analysis and execute suggested actions.

## WebSocket Request Types

- `meeting_start_recording`
- `meeting_stop_recording`
- `meeting_audio_chunk`
- `get_meeting_recordings`
- `load_meeting_recording`
- `delete_meeting_recording`
- `search_meeting_recordings`
- `meeting_get_status`
- `meeting_get_compute_info`
- `meeting_get_settings`
- `meeting_update_settings`
- `meeting_generate_analysis`
- `meeting_execute_action`

## WebSocket Events

- `meeting_recording_started`
- `meeting_recording_stopped`
- `meeting_transcript_chunk`
- `meeting_recordings_list`
- `meeting_recording_loaded`
- `meeting_recording_deleted`
- `meeting_recording_status`
- `meeting_recording_error`
- `meeting_processing_progress`
- `meeting_compute_info`
- `meeting_settings`
- `meeting_analysis_started`
- `meeting_analysis_complete`
- `meeting_analysis_error`
- `meeting_action_result`

## Data and Lifecycle Notes

- Recordings and transcript metadata are persisted in backend storage.
- Analysis model preference can be stored and reused.

## Hugging Face Token Setup

Speaker diarization now requires each user to add their own Hugging Face token in Settings > Meeting.

Setup flow:

1. Create a token at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens).
2. Accept the model licenses for:
   - [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1)
   - [pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0)
3. Paste the token into the Hugging Face field in Settings > Meeting and save it.

The token is encrypted through the existing key-manager flow before it is stored. The meeting recorder no longer reads `HF_TOKEN` from `.env` or process environment variables.

## Related Docs

- `docs/api-reference.md`
- `docs/features-overview.md`
