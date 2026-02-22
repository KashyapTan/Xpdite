"""
WebSocket endpoint for real-time communication.

Handles bidirectional WebSocket connections with the frontend.
"""
import json
import traceback
from fastapi import WebSocket, WebSocketDisconnect

from ..core.connection import manager
from ..core.state import app_state
from .handlers import MessageHandler


async def websocket_endpoint(websocket: WebSocket):
    """
    Bidirectional WebSocket endpoint.

    Client -> Server messages (JSON):
      - submit_query: Submit a query with optional capture mode
      - clear_context: Clear screenshots and chat history
      - remove_screenshot: Remove specific screenshot from context
      - set_capture_mode: Set capture mode (fullscreen/precision/none)
      - stop_streaming: Stop the current streaming response
      - get_conversations: Fetch conversation list
      - load_conversation: Load a specific conversation's messages
      - delete_conversation: Delete a conversation
      - search_conversations: Search conversations by text
      - resume_conversation: Resume a previous conversation
      - start_recording: Start audio recording for transcription
      - stop_recording: Stop audio recording and transcribe
      - terminal_approval_response: User response to terminal approval
      - terminal_session_response: User response to session mode request
      - terminal_stop_session: Stop active terminal session
      - terminal_kill_command: Kill running terminal command
      - terminal_set_ask_level: Set terminal approval level
      - terminal_resize: Resize terminal dimensions

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
      - terminal_approval_request: Request user approval for command
      - terminal_session_request: Request user approval for session mode
      - terminal_session_started: Terminal session started
      - terminal_session_ended: Terminal session ended
      - terminal_running_notice: Long-running command notice
      - terminal_output: Terminal output chunk
      - terminal_command_complete: Terminal command finished
      - transcription_result: Audio transcription result
    """
    await manager.connect(websocket)
    
    # Notify client that server is ready
    await websocket.send_text(json.dumps({
        "type": "ready", 
        "content": "Server ready. You can start chatting or take a screenshot (Alt+.)"
    }))
    
    # Send any existing screenshots to newly connected client
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
                print(f"[WS] Ignoring malformed message: {raw[:200]}")
                continue
            
            try:
                await handler.handle(data)
            except Exception as e:
                print(f"[WS] Error handling message type '{data.get('type')}': {e}")
                traceback.print_exc()
                try:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "content": f"Internal error: {str(e)[:200]}"
                    }))
                except Exception:
                    pass
            
    except WebSocketDisconnect:
        manager.disconnect(websocket)
