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

## Related Docs

- `docs/api-reference.md`
- `docs/features-overview.md`
