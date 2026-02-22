"""
WebSocket message handlers.

Handles all incoming WebSocket message types and routes them to appropriate services.
"""

import json
from typing import Dict, Any
from fastapi import WebSocket

from ..core.state import app_state
from ..services.conversations import ConversationService
from ..services.screenshots import ScreenshotHandler
from ..services.terminal import terminal_service
from ..database import db


def extract_skill_slash_commands(message: str) -> tuple[list[dict], str]:
    """
    Extract slash commands from a user message and match to skills.

    Returns (matched_skills, cleaned_message).
    Removes matched slash commands from the message text.
    If a slash command is recognized but the skill is disabled, strip it
    from the message silently and skip injection.
    """
    all_skills = db.get_all_skills()
    slash_map = {s["slash_command"]: s for s in all_skills}

    tokens = message.split()
    matched_skills = []
    remaining_tokens = []

    for token in tokens:
        if token.startswith("/"):
            cmd = token[1:].lower()
            if cmd in slash_map:
                skill = slash_map[cmd]
                if skill["enabled"]:
                    matched_skills.append(skill)
                # disabled skill: strip from message, skip injection silently
            else:
                remaining_tokens.append(token)  # unknown slash command, leave it
        else:
            remaining_tokens.append(token)

    cleaned_message = " ".join(remaining_tokens)
    return matched_skills, cleaned_message


class MessageHandler:
    """
    Handles incoming WebSocket messages and routes them to appropriate services.

    Each method handles a specific message type from the client.
    """

    def __init__(self, websocket: WebSocket):
        self.websocket = websocket

    async def handle(self, data: Dict[str, Any]):
        """Route a message to the appropriate handler."""
        msg_type = data.get("type")
        handler = getattr(self, f"_handle_{msg_type}", None)

        if handler:
            await handler(data)
        # Silently ignore unknown types

    async def _handle_submit_query(self, data: Dict[str, Any]):
        """Handle query submission."""
        import asyncio

        query_text = data.get("content", "").strip()
        capture_mode = data.get("capture_mode", "none")
        model = data.get("model", "")

        # Update the selected model in global state so the LLM provider uses it
        if model:
            app_state.selected_model = model

        if not query_text:
            await self.websocket.send_text(
                json.dumps({"type": "error", "content": "Empty query"})
            )
            return

        # Parse slash commands from the query text
        forced_skills, cleaned_query = await ConversationService.extract_skill_slash_commands(query_text)

        if forced_skills:
            print(f"[Skills] Slash commands matched: {[s['skill_name'] for s in forced_skills]}")

        # Use cleaned query (slash commands stripped) for the LLM only
        llm_query = cleaned_query.strip() if cleaned_query.strip() else query_text

        # Run as background task — pass original text for display/save, cleaned for LLM
        asyncio.create_task(
            self._safe_submit_query(
                query_text, capture_mode, forced_skills, llm_query=llm_query
            )
        )

    async def _safe_submit_query(self, *args, **kwargs):
        """Wrapper around submit_query that catches and reports errors."""
        try:
            await ConversationService.submit_query(*args, **kwargs)
        except Exception as e:
            import traceback
            traceback.print_exc()
            try:
                await self.websocket.send_text(json.dumps({
                    "type": "error",
                    "content": f"Query failed: {str(e)[:200]}"
                }))
            except Exception:
                pass

    async def _handle_clear_context(self, data: Dict[str, Any]):
        """Handle context clearing."""
        await ConversationService.clear_context()

    async def _handle_remove_screenshot(self, data: Dict[str, Any]):
        """Handle screenshot removal."""
        screenshot_id = data.get("id")
        if screenshot_id:
            await ScreenshotHandler.remove_screenshot(screenshot_id)

    async def _handle_set_capture_mode(self, data: Dict[str, Any]):
        """Handle capture mode change."""
        mode = data.get("mode", "fullscreen")
        if mode in ("fullscreen", "precision", "none"):
            app_state.capture_mode = mode
            print(f"Capture mode set to: {mode}")

    async def _handle_stop_streaming(self, data: Dict[str, Any]):
        """Handle stop streaming request — cancels all in-flight work."""
        # Cancel via RequestContext (new path)
        ctx = app_state.current_request
        if ctx is not None:
            ctx.cancel()

        # Legacy flag for subsystems not yet migrated
        app_state.stop_streaming = True

        # Cancel any pending terminal approvals/sessions so tool loop unblocks
        terminal_service.cancel_all_pending()

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

    async def _handle_resume_conversation(self, data: Dict[str, Any]):
        """Handle conversation resumption."""
        conv_id = data.get("conversation_id")
        if conv_id:
            await ConversationService.resume_conversation(conv_id)

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
    # Terminal Handlers
    # ---------------------------------------------------------

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
