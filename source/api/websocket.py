"""
WebSocket endpoint for real-time communication.

Handles bidirectional WebSocket connections with the frontend.
"""
import json
import traceback
import logging
from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

from ..core.connection import manager
from ..core.state import app_state
from .handlers import MessageHandler


async def websocket_endpoint(websocket: WebSocket):
    """
    Bidirectional WebSocket endpoint.

    All messages now carry a ``tab_id`` field (default ``"default"``).
    Server → client messages are stamped with ``tab_id`` automatically
    via the contextvar in ``connection.py``.

    Client -> Server messages (JSON):
      - submit_query: Submit a query with optional capture mode
      - clear_context: Clear screenshots and chat history
      - remove_screenshot: Remove specific screenshot from context
      - set_capture_mode: Set capture mode (fullscreen/precision/none)
      - stop_streaming: Stop the current streaming response
      - cancel_queued_item: Cancel a specific queued (not yet running) item
      - get_conversations: Fetch conversation list
      - load_conversation: Load a specific conversation's messages
      - delete_conversation: Delete a conversation
      - search_conversations: Search conversations by text
      - resume_conversation: Resume a previous conversation
      - start_recording: Start audio recording for transcription
      - stop_recording: Stop audio recording and transcribe
      - tab_created: Notify backend of a new tab
      - tab_closed: Notify backend a tab was closed
      - tab_activated: Notify backend the user switched to a tab
      - terminal_approval_response: User response to terminal approval
      - terminal_session_response: User response to session mode request
      - terminal_stop_session: Stop active terminal session
      - terminal_kill_command: Kill running terminal command
      - terminal_set_ask_level: Set terminal approval level
      - terminal_resize: Resize terminal dimensions
      - meeting_start_recording: Start a meeting recording session
      - meeting_stop_recording: Stop the active meeting recording
      - meeting_audio_chunk: Send base64-encoded PCM audio data
      - get_meeting_recordings: Fetch meeting recording list
      - load_meeting_recording: Load a specific meeting recording detail
      - delete_meeting_recording: Delete a meeting recording
      - search_meeting_recordings: Search meeting recordings by title
      - meeting_get_status: Get current meeting recording status
      - meeting_get_compute_info: Get GPU compute backend info
      - meeting_get_settings: Get meeting recorder settings
      - meeting_update_settings: Update meeting recorder settings
      - meeting_generate_analysis: Generate AI summary and action suggestions
      - meeting_execute_action: Execute a suggested action via MCP tools

    Server -> Client broadcast messages (JSON):
      - ready: Server is ready to receive queries
      - screenshot_start: Screenshot capture starting
      - screenshot_added: Screenshot added to context
      - screenshot_removed: Screenshot removed from context
      - screenshots_cleared: All screenshots cleared
      - screenshot_ready: Legacy message for backwards compatibility
      - query: Echo of submitted query
      - thinking_chunk: Streaming thinking/reasoning
      - thinking_complete: Thinking finished
      - response_chunk: Streaming response token
      - response_complete: Response finished
      - tool_call: MCP tool call event
      - tool_calls_summary: Summary of all tool calls
      - token_usage: Token usage statistics
      - context_cleared: Context was cleared
      - conversation_saved: Conversation was saved
      - conversations_list: List of conversations
      - conversation_loaded: Conversation content loaded
      - conversation_deleted: Conversation was deleted
      - conversation_resumed: Conversation was resumed
      - error: Error message
      - queue_full: Tab queue is at capacity
      - query_queued: A query was added to the queue
      - queue_updated: Queue state snapshot changed
      - ollama_queue_status: Ollama global serialization status
      - terminal_approval_request: Request user approval for command
      - terminal_session_request: Request user approval for session mode
      - terminal_session_started: Terminal session started
      - terminal_session_ended: Terminal session ended
      - terminal_running_notice: Long-running command notice
      - terminal_output: Terminal output chunk
      - terminal_command_complete: Terminal command finished
      - transcription_result: Audio transcription result
      - meeting_recording_started: Meeting recording began
      - meeting_recording_stopped: Meeting recording ended
      - meeting_transcript_chunk: Live transcript segment
      - meeting_recordings_list: List of meeting recordings
      - meeting_recording_loaded: Meeting recording detail loaded
      - meeting_recording_deleted: Meeting recording was deleted
      - meeting_recording_status: Current meeting recording status
      - meeting_recording_error: Error during meeting recording
      - meeting_processing_progress: Tier 2 processing progress update
      - meeting_compute_info: GPU compute backend information
      - meeting_settings: Meeting recorder settings values
      - meeting_analysis_started: AI analysis generation started
      - meeting_analysis_complete: AI summary and actions ready
      - meeting_analysis_error: AI analysis generation failed
      - meeting_action_result: MCP action execution result
    """
    await manager.connect(websocket)
    
    # Notify client that server is ready
    await websocket.send_text(json.dumps({
        "type": "ready", 
        "content": "Server ready. You can start chatting or take a screenshot (Alt+.)"
    }))
    
    # Send any existing screenshots to newly connected client.
    # Screenshots now live per-tab; send each tab's screenshots tagged
    # with the tab_id so the frontend can route them correctly.
    try:
        from ..services.tab_manager_instance import tab_manager
        if tab_manager is not None:
            for tid in tab_manager.get_all_tab_ids():
                ts = tab_manager.get_state(tid)
                if ts is not None:
                    for ss in ts.screenshot_list:
                        await websocket.send_text(json.dumps({
                            "type": "screenshot_added",
                            "tab_id": tid,
                            "content": {
                                "id": ss["id"],
                                "name": ss["name"],
                                "thumbnail": ss["thumbnail"]
                            }
                        }))
    except Exception:
        pass  # tab_manager may not be initialized yet on first connect

    # Fallback: also send any global screenshots (startup edge case)
    for ss in app_state.screenshot_list:
        await websocket.send_text(json.dumps({
            "type": "screenshot_added",
            "content": {
                "id": ss["id"],
                "name": ss["name"],
                "thumbnail": ss["thumbnail"]
            }
        }))
    
    handler = MessageHandler(websocket)
    
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except Exception:
                logger.warning("Ignoring malformed message: %s", raw[:200])
                continue
            
            try:
                await handler.handle(data)
            except Exception as e:
                logger.error("Error handling message type '%s': %s", data.get('type'), e, exc_info=True)
                try:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "content": f"Internal error: {str(e)[:200]}"
                    }))
                except Exception:
                    pass
            
    except WebSocketDisconnect:
        manager.disconnect(websocket)
