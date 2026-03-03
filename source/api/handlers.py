"""
WebSocket message handlers.

Handles all incoming WebSocket message types and routes them to appropriate services.
Every handler extracts ``tab_id`` from the incoming message (defaulting to ``"default"``).
Tab-scoped operations are routed through the ``TabManager`` singleton.
"""

import json
import logging
from typing import Dict, Any
from fastapi import WebSocket

logger = logging.getLogger(__name__)

from ..core.state import app_state
from ..core.connection import set_current_tab_id, broadcast_to_tab, broadcast_message
from ..services.conversations import ConversationService
from ..services.screenshots import ScreenshotHandler
from ..services.terminal import terminal_service
from ..database import db


class MessageHandler:
    """
    Handles incoming WebSocket messages and routes them to appropriate services.

    Each method handles a specific message type from the client.
    All tab-scoped handlers extract ``tab_id`` to route through the TabManager.
    """

    def __init__(self, websocket: WebSocket):
        self.websocket = websocket

    async def handle(self, data: Dict[str, Any]):
        """Route a message to the appropriate handler."""
        # Track the active tab — every WS message comes from the tab the
        # user is currently interacting with.  Used by ScreenshotHandler to
        # route hotkey-captured screenshots to the correct tab.
        tab_id = data.get("tab_id")
        if tab_id:
            app_state.active_tab_id = tab_id

        msg_type = data.get("type")
        handler = getattr(self, f"_handle_{msg_type}", None)

        if handler:
            await handler(data)
        # Silently ignore unknown types

    # ── Helpers ───────────────────────────────────────────────────

    def _get_tab_id(self, data: Dict[str, Any]) -> str:
        return data.get("tab_id", "default")

    def _get_tab_manager(self):
        from ..services.tab_manager_instance import tab_manager
        return tab_manager

    # ── Tab lifecycle ─────────────────────────────────────────────

    async def _handle_tab_created(self, data: Dict[str, Any]):
        """Handle new tab creation from frontend."""
        tab_id = self._get_tab_id(data)
        try:
            self._get_tab_manager().create_tab(tab_id)
        except ValueError as e:
            await self.websocket.send_text(
                json.dumps({"type": "error", "content": str(e), "tab_id": tab_id})
            )

    async def _handle_tab_closed(self, data: Dict[str, Any]):
        """Handle tab close from frontend."""
        tab_id = self._get_tab_id(data)
        await self._get_tab_manager().close_tab(tab_id)

    async def _handle_tab_activated(self, data: Dict[str, Any]):
        """Handle tab switch from frontend — updates active_tab_id."""
        tab_id = self._get_tab_id(data)
        app_state.active_tab_id = tab_id
        logger.debug("Active tab set to: %s", tab_id)

    # ── Query submission (via queue) ──────────────────────────────

    async def _handle_submit_query(self, data: Dict[str, Any]):
        """Handle query submission — routes through the per-tab queue.

        Fullscreen screenshots are captured HERE (before enqueuing) so they
        happen immediately without being blocked by the Ollama global queue
        or another tab's in-flight LLM request.
        """
        from ..services.query_queue import QueuedQuery, QueueFullError
        from ..config import CaptureMode

        tab_id = self._get_tab_id(data)
        query_text = data.get("content", "").strip()
        capture_mode = data.get("capture_mode", "none")
        model = data.get("model", "")

        # Update the selected model in global state
        if model:
            app_state.selected_model = model

        if not query_text:
            await self.websocket.send_text(
                json.dumps({"type": "error", "content": "Empty query", "tab_id": tab_id})
            )
            return

        # Parse slash commands from the query text
        forced_skills, cleaned_query = await ConversationService.extract_skill_slash_commands(query_text)

        if forced_skills:
            logger.debug("Slash commands matched: %s", [s.name for s in forced_skills])

        llm_query = cleaned_query.strip() if cleaned_query.strip() else query_text

        session = self._get_tab_manager().get_or_create(tab_id)

        # ── Capture fullscreen screenshot BEFORE enqueuing ────────
        # This runs immediately on the event loop so it isn't blocked by
        # the Ollama global queue or another tab's in-flight request.
        if (
            capture_mode == CaptureMode.FULLSCREEN
            and len(session.state.screenshot_list) == 0
            and len(session.state.chat_history) == 0
        ):
            token = set_current_tab_id(tab_id)
            try:
                await ScreenshotHandler.capture_fullscreen(tab_state=session.state)
            finally:
                set_current_tab_id(None)

        queued = QueuedQuery(
            tab_id=tab_id,
            content=query_text,
            model=model or app_state.selected_model,
            capture_mode=capture_mode,
            forced_skills=forced_skills,
            llm_query=llm_query,
        )

        try:
            await session.queue.enqueue(queued)
        except QueueFullError:
            await broadcast_to_tab(tab_id, "queue_full", {"tab_id": tab_id})

    # ── Stop / cancel ─────────────────────────────────────────────

    async def _handle_stop_streaming(self, data: Dict[str, Any]):
        """Handle stop streaming request — stops current item, queue continues."""
        tab_id = self._get_tab_id(data)
        session = self._get_tab_manager().get_session(tab_id)
        if session:
            await session.queue.stop_current()

        # Cancel any pending terminal approvals/sessions so tool loop unblocks
        terminal_service.cancel_all_pending()

    async def _handle_cancel_queued_item(self, data: Dict[str, Any]):
        """Handle cancellation of a specific queued (not yet running) item."""
        tab_id = self._get_tab_id(data)
        item_id = data.get("item_id", "")
        session = self._get_tab_manager().get_session(tab_id)
        if session and item_id:
            await session.queue.cancel_item(item_id)

    # ── Context management ────────────────────────────────────────

    async def _handle_clear_context(self, data: Dict[str, Any]):
        """Handle context clearing — per-tab."""
        tab_id = self._get_tab_id(data)
        session = self._get_tab_manager().get_session(tab_id)
        tab_state = session.state if session else None

        token = set_current_tab_id(tab_id)
        try:
            await ConversationService.clear_context(tab_state=tab_state)
        finally:
            set_current_tab_id(None)

        # Reset the queue's resolved conversation_id
        if session:
            session.queue.reset_conversation()

    async def _handle_resume_conversation(self, data: Dict[str, Any]):
        """Handle conversation resumption — per-tab."""
        tab_id = self._get_tab_id(data)
        conv_id = data.get("conversation_id")
        if conv_id:
            session = self._get_tab_manager().get_or_create(tab_id)
            token = set_current_tab_id(tab_id)
            try:
                await ConversationService.resume_conversation(conv_id, tab_state=session.state)
                # Update the queue's resolved conversation_id
                session.queue.resolved_conversation_id = conv_id
            finally:
                set_current_tab_id(None)

    async def _handle_remove_screenshot(self, data: Dict[str, Any]):
        """Handle screenshot removal — routes to the correct tab's screenshot list."""
        screenshot_id = data.get("id")
        if screenshot_id:
            tab_id = self._get_tab_id(data)
            tab_state = self._get_tab_manager().get_state(tab_id)
            await ScreenshotHandler.remove_screenshot(screenshot_id, tab_state=tab_state)

    async def _handle_set_capture_mode(self, data: Dict[str, Any]):
        """Handle capture mode change."""
        mode = data.get("mode", "fullscreen")
        if mode in ("fullscreen", "precision", "none"):
            app_state.capture_mode = mode
            logger.debug("Capture mode set to: %s", mode)

    async def _handle_get_conversations(self, data: Dict[str, Any]):
        """Handle conversation list request."""
        limit = data.get("limit", 50)
        offset = data.get("offset", 0)
        conversations = ConversationService.get_conversations(
            limit=limit, offset=offset
        )
        # TODO(frontend): content is now a native object, not a JSON string.
        # Remove any extra JSON.parse() calls on the frontend for this message type.
        await self.websocket.send_text(
            json.dumps(
                {"type": "conversations_list", "content": conversations}
            )
        )

    async def _handle_load_conversation(self, data: Dict[str, Any]):
        """Handle full conversation load request."""
        conv_id = data.get("conversation_id")
        if conv_id:
            messages = ConversationService.get_full_conversation(conv_id)
            await self.websocket.send_text(
                json.dumps(
                    {
                        "type": "conversation_loaded",
                        "content": {"conversation_id": conv_id, "messages": messages},
                    }
                )
            )

    async def _handle_delete_conversation(self, data: Dict[str, Any]):
        """Handle conversation deletion."""
        conv_id = data.get("conversation_id")
        if conv_id:
            ConversationService.delete_conversation(conv_id)
            await self.websocket.send_text(
                json.dumps(
                    {
                        "type": "conversation_deleted",
                        "content": {"conversation_id": conv_id},
                    }
                )
            )

    async def _handle_search_conversations(self, data: Dict[str, Any]):
        """Handle conversation search."""
        search_term = data.get("query", "")
        if search_term:
            results = ConversationService.search_conversations(search_term)
        else:
            results = ConversationService.get_conversations(limit=50)

        await self.websocket.send_text(
            json.dumps({"type": "conversations_list", "content": results})
        )

    async def _handle_start_recording(self, data: Dict[str, Any]):
        """Handle start recording request."""
        from ..core.thread_pool import run_in_thread

        if app_state.transcription_service:
            await run_in_thread(app_state.transcription_service.start_recording)

    async def _handle_stop_recording(self, data: Dict[str, Any]):
        """Handle stop recording request."""
        from ..core.thread_pool import run_in_thread

        if app_state.transcription_service:
            # Run transcription in a separate thread to avoid blocking the event loop
            text = await run_in_thread(app_state.transcription_service.stop_recording)

            await self.websocket.send_text(
                json.dumps({"type": "transcription_result", "content": text})
            )

    # ---------------------------------------------------------
    # Meeting Recording Handlers
    # ---------------------------------------------------------

    async def _handle_meeting_start_recording(self, data: Dict[str, Any]):
        """Start a new meeting recording session."""
        from ..services.meeting_recorder import meeting_recorder_service

        try:
            result = await meeting_recorder_service.start_recording()
            await self.websocket.send_text(
                json.dumps({"type": "meeting_recording_started", "content": result})
            )
        except RuntimeError as e:
            await self.websocket.send_text(
                json.dumps({"type": "meeting_recording_error", "content": str(e)})
            )

    async def _handle_meeting_stop_recording(self, data: Dict[str, Any]):
        """Stop the active meeting recording."""
        from ..services.meeting_recorder import meeting_recorder_service

        try:
            result = await meeting_recorder_service.stop_recording()
            await self.websocket.send_text(
                json.dumps({"type": "meeting_recording_stopped", "content": result})
            )
        except RuntimeError as e:
            await self.websocket.send_text(
                json.dumps({"type": "meeting_recording_error", "content": str(e)})
            )

    async def _handle_meeting_audio_chunk(self, data: Dict[str, Any]):
        """Receive a base64-encoded PCM audio chunk from the renderer."""
        import base64
        from ..services.meeting_recorder import meeting_recorder_service

        audio_b64 = data.get("audio", "")
        if audio_b64:
            pcm_data = base64.b64decode(audio_b64)
            meeting_recorder_service.handle_audio_chunk(pcm_data)

    async def _handle_get_meeting_recordings(self, data: Dict[str, Any]):
        """List meeting recordings."""
        limit = data.get("limit", 50)
        offset = data.get("offset", 0)
        recordings = db.get_meeting_recordings(limit=limit, offset=offset)
        await self.websocket.send_text(
            json.dumps({"type": "meeting_recordings_list", "content": recordings})
        )

    async def _handle_load_meeting_recording(self, data: Dict[str, Any]):
        """Load full detail for a single meeting recording."""
        recording_id = data.get("recording_id", "")
        if recording_id:
            recording = db.get_meeting_recording(recording_id)
            await self.websocket.send_text(
                json.dumps(
                    {"type": "meeting_recording_loaded", "content": recording}
                )
            )

    async def _handle_delete_meeting_recording(self, data: Dict[str, Any]):
        """Delete a meeting recording."""
        recording_id = data.get("recording_id", "")
        if recording_id:
            # Also delete the audio file if it exists
            recording = db.get_meeting_recording(recording_id)
            if recording and recording.get("audio_file_path"):
                import os
                try:
                    os.remove(recording["audio_file_path"])
                except OSError:
                    pass
            db.delete_meeting_recording(recording_id)
            await self.websocket.send_text(
                json.dumps(
                    {
                        "type": "meeting_recording_deleted",
                        "content": {"recording_id": recording_id},
                    }
                )
            )

    async def _handle_search_meeting_recordings(self, data: Dict[str, Any]):
        """Search meeting recordings by title."""
        search_term = data.get("query", "")
        if search_term:
            results = db.search_meeting_recordings(search_term)
        else:
            results = db.get_meeting_recordings(limit=50)
        await self.websocket.send_text(
            json.dumps({"type": "meeting_recordings_list", "content": results})
        )

    async def _handle_meeting_get_status(self, data: Dict[str, Any]):
        """Get current meeting recording status."""
        from ..services.meeting_recorder import meeting_recorder_service

        status = meeting_recorder_service.get_status()
        await self.websocket.send_text(
            json.dumps({"type": "meeting_recording_status", "content": status})
        )

    async def _handle_meeting_get_compute_info(self, data: Dict[str, Any]):
        """Get GPU compute backend info for settings display."""
        from ..services.gpu_detector import get_compute_info

        info = get_compute_info()
        await self.websocket.send_text(
            json.dumps({"type": "meeting_compute_info", "content": info})
        )

    async def _handle_meeting_get_settings(self, data: Dict[str, Any]):
        """Get current meeting recorder settings."""
        settings = {
            "whisper_model": db.get_setting("meeting_whisper_model") or "base",
            "keep_audio": db.get_setting("meeting_keep_audio") or "false",
            "diarization_enabled": db.get_setting("meeting_diarization_enabled") or "true",
        }
        await self.websocket.send_text(
            json.dumps({"type": "meeting_settings", "content": settings})
        )

    async def _handle_meeting_update_settings(self, data: Dict[str, Any]):
        """Save meeting recorder settings."""
        from ..services.meeting_recorder import meeting_recorder_service

        settings = data.get("settings", {})
        if "whisper_model" in settings:
            model = settings["whisper_model"]
            if model in ("tiny", "base", "small"):
                db.set_setting("meeting_whisper_model", model)
                meeting_recorder_service.set_model_size(model)
        if "keep_audio" in settings:
            db.set_setting("meeting_keep_audio", settings["keep_audio"])
        if "diarization_enabled" in settings:
            db.set_setting("meeting_diarization_enabled", settings["diarization_enabled"])

        # Return updated settings
        updated = {
            "whisper_model": db.get_setting("meeting_whisper_model") or "base",
            "keep_audio": db.get_setting("meeting_keep_audio") or "false",
            "diarization_enabled": db.get_setting("meeting_diarization_enabled") or "true",
        }
        await self.websocket.send_text(
            json.dumps({"type": "meeting_settings", "content": updated})
        )

    async def _handle_meeting_generate_analysis(self, data: Dict[str, Any]):
        """Generate AI summary and action suggestions for a recording."""
        import asyncio
        from ..services.meeting_recorder import meeting_analysis_service

        recording_id = data.get("recording_id")
        model = data.get("model")  # Optional model override from frontend
        if not recording_id:
            await self.websocket.send_text(
                json.dumps({"type": "meeting_analysis_error", "content": {"error": "Missing recording_id"}})
            )
            return

        # Run in background to avoid blocking WS
        async def _run_analysis():
            try:
                result = await meeting_analysis_service.generate_analysis(recording_id, model=model)
                if "error" in result and result.get("summary") is None:
                    await broadcast_message("meeting_analysis_error", {
                        "recording_id": recording_id,
                        "error": result["error"],
                    })
                else:
                    await broadcast_message("meeting_analysis_complete", {
                        "recording_id": recording_id,
                        "summary": result.get("summary"),
                        "actions": result.get("actions", []),
                        "parse_error": result.get("parse_error", False),
                    })
            except Exception as e:
                logger.error("Analysis handler error: %s", e)
                await broadcast_message("meeting_analysis_error", {
                    "recording_id": recording_id,
                    "error": str(e),
                })

        asyncio.create_task(_run_analysis())

        # Acknowledge request was received
        await self.websocket.send_text(
            json.dumps({"type": "meeting_analysis_started", "content": {"recording_id": recording_id}})
        )

    async def _handle_meeting_execute_action(self, data: Dict[str, Any]):
        """Execute an action suggestion via MCP tools."""
        from ..mcp_integration.manager import mcp_manager

        recording_id = data.get("recording_id", "")
        action = data.get("action", {})
        action_type = action.get("type", "")
        action_index = data.get("action_index", 0)

        try:
            result = ""
            success = True

            if action_type == "calendar_event":
                # Map to Google Calendar MCP tool
                # Server signature: create_event(title, start, end, description, location, attendees)
                result = await mcp_manager.call_tool("create_event", {
                    "title": action.get("title", "Meeting Follow-up"),
                    "start": f"{action.get('date', '')}T{action.get('time', '09:00')}:00",
                    "end": self._calc_end_time(
                        action.get("date", ""),
                        action.get("time", "09:00"),
                        action.get("duration_minutes", 30),
                    ),
                    "description": action.get("description", ""),
                })

            elif action_type == "email":
                # Map to Gmail MCP tool
                result = await mcp_manager.call_tool("create_draft", {
                    "to": action.get("to", ""),
                    "subject": action.get("subject", ""),
                    "body": action.get("body", ""),
                })

            else:
                result = f"Action type '{action_type}' is not executable via MCP"
                success = False

            # MCP call_tool returns "Error: ..." on failure
            if result.startswith("Error:"):
                success = False

            await self.websocket.send_text(
                json.dumps({"type": "meeting_action_result", "content": {
                    "recording_id": recording_id,
                    "action_type": action_type,
                    "action_index": action_index,
                    "success": success,
                    "result": result,
                }})
            )

        except Exception as e:
            logger.error("Action execution failed: %s", e)
            await self.websocket.send_text(
                json.dumps({"type": "meeting_action_result", "content": {
                    "recording_id": recording_id,
                    "action_type": action_type,
                    "action_index": action_index,
                    "success": False,
                    "result": str(e),
                }})
            )

    @staticmethod
    def _calc_end_time(date: str, time: str, duration_minutes: int) -> str:
        """Calculate end time from start date/time + duration."""
        try:
            from datetime import datetime, timedelta
            dt = datetime.fromisoformat(f"{date}T{time}:00")
            end = dt + timedelta(minutes=duration_minutes)
            return end.isoformat()
        except Exception:
            return f"{date}T{time}:00"


    async def _handle_terminal_approval_response(self, data: Dict[str, Any]):
        """Handle user's response to a terminal approval request."""
        request_id = data.get("request_id", "")
        approved = data.get("approved", False)
        remember = data.get("remember", False)

        terminal_service.resolve_approval(request_id, approved, remember)

    async def _handle_terminal_session_response(self, data: Dict[str, Any]):
        """Handle user's response to a session mode request."""
        approved = data.get("approved", False)
        terminal_service.resolve_session(approved)

    async def _handle_terminal_stop_session(self, data: Dict[str, Any]):
        """Handle user clicking the Stop button on an active session."""
        await terminal_service.end_session()

    async def _handle_terminal_kill_command(self, data: Dict[str, Any]):
        """Handle user clicking the Kill button to terminate a running command."""
        await terminal_service.kill_running_command()

    async def _handle_terminal_set_ask_level(self, data: Dict[str, Any]):
        """Handle ask level change from frontend."""
        level = data.get("level", "on-miss")
        if level in ("always", "on-miss", "off"):
            terminal_service.ask_level = level

    async def _handle_terminal_resize(self, data: Dict[str, Any]):
        """Handle terminal panel resize — sync PTY dimensions with xterm viewport."""
        cols = data.get("cols", 120)
        rows = data.get("rows", 24)
        if (
            isinstance(cols, int)
            and isinstance(rows, int)
            and 0 < cols <= 500
            and 0 < rows <= 200
        ):
            await terminal_service.resize_all_pty(cols, rows)
