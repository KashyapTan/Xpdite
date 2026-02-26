"""
Conversation management service.

Handles conversation lifecycle, persistence, and query processing.
"""

import os
import copy
import json
import logging
from typing import Callable, List, Dict, Any, Optional, TYPE_CHECKING

logger = logging.getLogger(__name__)

from ..core.state import app_state
from ..core.request_context import RequestContext
from ..core.connection import broadcast_message
from ..core.thread_pool import run_in_thread
from ..llm.router import route_chat
from .screenshots import ScreenshotHandler
from ..database import db

if TYPE_CHECKING:
    from .tab_manager import TabState
    from .query_queue import ConversationQueue


# Conversations service logic


def _extract_skill_slash_commands_sync(message: str) -> tuple[list[dict], str]:
    """Extract slash commands from a user message and match to skills.

    Returns (matched_skills, cleaned_message).
    Removes matched slash commands from the message text.
    If a slash command is recognized but the skill is disabled, strip it
    from the message silently and skip injection.

    This is the synchronous implementation; callers should use
    ``ConversationService.extract_skill_slash_commands`` which wraps it
    in ``run_in_thread`` to avoid blocking the event loop on DB I/O.
    """
    all_skills = db.get_all_skills()
    slash_map = {s["slash_command"]: s for s in all_skills}

    tokens = message.split()
    matched_skills: list[dict] = []
    remaining_tokens: list[str] = []

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


class ConversationService:
    """Manages conversation lifecycle and query processing."""

    @staticmethod
    async def extract_skill_slash_commands(message: str) -> tuple[list[dict], str]:
        """Extract slash commands from a user message (async wrapper).

        Delegates to ``_extract_skill_slash_commands_sync`` via
        ``run_in_thread`` so the synchronous DB call does not block the
        event loop.
        """
        return await run_in_thread(_extract_skill_slash_commands_sync, message)

    @staticmethod
    async def clear_context(tab_state: Optional["TabState"] = None):
        """Clear screenshots and chat history for a fresh start.

        If *tab_state* is provided, clears per-tab state instead of global.
        """
        from .terminal import terminal_service

        if tab_state is not None:
            await ScreenshotHandler.clear_screenshots(tab_state=tab_state)
            tab_state.chat_history = []
            tab_state.conversation_id = None
        else:
            await ScreenshotHandler.clear_screenshots()
            app_state.chat_history = []
            app_state.conversation_id = None

        # Reset terminal service state (ends session mode, clears tracking)
        terminal_service.reset()

        logger.info("Context cleared: screenshots and chat history reset")
        await broadcast_message(
            "context_cleared", "Context cleared. Ready for new conversation."
        )

    @staticmethod
    async def resume_conversation(conversation_id: str, tab_state: Optional["TabState"] = None):
        """Resume a previously saved conversation.

        If *tab_state* is provided, loads into per-tab state.
        """
        from .terminal import terminal_service
        from ..ss import create_thumbnail

        # Resolve state target
        chat_history_target = tab_state.chat_history if tab_state else app_state.chat_history

        # Clear current state
        chat_history_target.clear()
        if tab_state is not None:
            await ScreenshotHandler.clear_screenshots(tab_state=tab_state)
        else:
            await ScreenshotHandler.clear_screenshots()

        # Load conversation from database
        messages = db.get_full_conversation(conversation_id)
        if tab_state is not None:
            tab_state.conversation_id = conversation_id
        else:
            app_state.conversation_id = conversation_id

        # Rebuild in-memory chat history
        for msg in messages:
            entry = {"role": msg["role"], "content": msg["content"]}
            if msg.get("model"):
                entry["model"] = msg["model"]
            if msg.get("images"):
                entry["images"] = msg["images"]
                # Generate thumbnails for frontend (blocking I/O via run_in_thread)
                thumbnails = []
                for img_path in msg["images"]:
                    if os.path.exists(img_path):
                        thumb = await run_in_thread(create_thumbnail, img_path)
                        thumbnails.append(
                            {"name": os.path.basename(img_path), "thumbnail": thumb}
                        )
                    else:
                        thumbnails.append(
                            {"name": os.path.basename(img_path), "thumbnail": None}
                        )
                msg["images"] = thumbnails
            chat_history_target.append(entry)

        chat_history_len = len(tab_state.chat_history) if tab_state else len(app_state.chat_history)
        logger.info(
            "Resumed conversation %s with %d messages",
            conversation_id, chat_history_len
        )

        # Notify client
        token_usage = db.get_token_usage(conversation_id)
        await broadcast_message(
            "conversation_resumed",
            json.dumps(
                {
                    "conversation_id": conversation_id,
                    "messages": messages,
                    "token_usage": token_usage,
                }
            ),
        )

    @staticmethod
    async def submit_query(
        user_query: str,
        capture_mode: str = "none",
        forced_skills: list[dict] | None = None,
        llm_query: str | None = None,
        tab_state: Optional["TabState"] = None,
        queue: Optional["ConversationQueue"] = None,
        model: Optional[str] = None,
    ) -> Optional[str]:
        """
        Handle query submission from a client.

        Args:
            user_query: The user's original question (with slash commands, for display/save)
            capture_mode: 'fullscreen', 'precision', or 'none'
            forced_skills: Skills forced via slash commands (e.g. /terminal)
            llm_query: Cleaned query without slash commands (for the LLM). Uses user_query if None.
            tab_state: Per-tab state container. Falls back to app_state if None.
            queue: The ConversationQueue managing this request (for registering ctx).
            model: Explicit model override (e.g. from queued query).

        Returns:
            The conversation_id (str) or None on failure.
        """

        # ── Resolve state targets ─────────────────────────────────────
        _chat_history = tab_state.chat_history if tab_state else app_state.chat_history
        _get_conv_id: Callable[[], Optional[str]] = lambda: tab_state.conversation_id if tab_state else app_state.conversation_id
        _set_conv_id = lambda v: (setattr(tab_state, "conversation_id", v) if tab_state else setattr(app_state, "conversation_id", v))

        def _require_conv_id() -> str:
            """Return conversation_id or raise — used after we know it's been set."""
            cid = _get_conv_id()
            assert cid is not None, "conversation_id should be set by this point"
            return cid

        _screenshot_list = tab_state.screenshot_list if tab_state else app_state.screenshot_list
        _request_lock = tab_state._request_lock if tab_state else app_state._request_lock

        current_model = model or app_state.selected_model

        logger.debug(
            "submit_query: model=%s, capture_mode=%s, screenshots=%d",
            current_model, capture_mode, len(_screenshot_list)
        )

        # ── Request lifecycle: create context ─────────────────────────
        async with _request_lock:
            current_req = tab_state.current_request if tab_state else app_state.current_request
            if current_req is not None and not current_req.is_done:
                await broadcast_message("error", "Already streaming. Please wait.")
                return None
            ctx = RequestContext()
            ctx.forced_skills = forced_skills or []
            if tab_state:
                tab_state.current_request = ctx
                tab_state.is_streaming = True
                tab_state.stop_streaming = False
            else:
                app_state.current_request = ctx
                app_state.is_streaming = True
                app_state.stop_streaming = False

        # Set contextvars so LLM layer gets per-task request + model
        from ..core.request_context import set_current_request, set_current_model
        _ctx_token = set_current_request(ctx)
        _model_token = set_current_model(current_model)

        # Register ctx on the queue so stop_current works
        if queue is not None:
            queue.set_active_ctx(ctx)

        try:
            # NOTE: Fullscreen auto-capture is now done in the handler
            # (_handle_submit_query) BEFORE enqueuing, so screenshots are
            # taken immediately without being blocked by the Ollama queue.

            # Get image paths
            if tab_state:
                image_paths = tab_state.get_image_paths()
            else:
                image_paths = app_state.get_image_paths()

            # Echo query to clients
            await broadcast_message("query", user_query)

            # Stream the response — use cleaned query (without slash commands) for the LLM
            query_for_llm = llm_query if llm_query else user_query
            response_text, token_stats, tool_calls, interleaved_blocks_from_llm = await route_chat(
                current_model,
                query_for_llm,
                image_paths,
                copy.deepcopy(_chat_history),
                forced_skills=ctx.forced_skills,
            )

            # Check if request was cancelled during route_chat
            if ctx.cancelled:
                # ── Save interrupted conversation ────────────────────
                if _get_conv_id() is None:
                    title = user_query[:50] + ("..." if len(user_query) > 50 else "")
                    _set_conv_id(db.start_new_conversation(title))
                    logger.info("Created conversation (interrupted): %s", _require_conv_id())

                    from .terminal import terminal_service
                    terminal_service.flush_pending_events(_require_conv_id())

                # Persist any token usage that was collected
                input_tokens = token_stats.get("prompt_eval_count", 0)
                output_tokens = token_stats.get("eval_count", 0)
                if input_tokens or output_tokens:
                    try:
                        db.add_token_usage(_require_conv_id(), input_tokens, output_tokens)
                    except Exception as e:
                        logger.error("Error saving token usage (interrupted): %s", e)

                # Broadcast tool calls summary if any ran before interruption
                if tool_calls:
                    await broadcast_message("tool_calls_summary", json.dumps(tool_calls))

                # Build interrupted assistant text
                if response_text.strip():
                    interrupted_text = response_text + "\n\n[Response interrupted]"
                else:
                    interrupted_text = "[Response interrupted]"

                # Build content_blocks (mirrors the normal path)
                content_blocks_data: List[Dict] | None = None
                if interleaved_blocks_from_llm:
                    content_blocks_data = [
                        {k: v for k, v in block.items() if k != "result"}
                        for block in interleaved_blocks_from_llm
                    ]
                elif tool_calls:
                    content_blocks_data = [
                        {
                            "type": "tool_call",
                            "name": tc["name"],
                            "args": tc.get("args", {}),
                            "server": tc.get("server", ""),
                        }
                        for tc in tool_calls
                    ]
                    if response_text.strip():
                        content_blocks_data.append(
                            {"type": "text", "content": response_text}
                        )

                # Add to in-memory chat history
                user_msg: Dict[str, Any] = {"role": "user", "content": user_query}
                if image_paths:
                    user_msg["images"] = image_paths
                _chat_history.append(user_msg)

                assistant_msg: Dict[str, Any] = {
                    "role": "assistant",
                    "content": interrupted_text,
                    "model": current_model,
                }
                if tool_calls:
                    assistant_msg["tool_calls"] = tool_calls
                _chat_history.append(assistant_msg)

                # Persist to database
                db.add_message(
                    _require_conv_id(),
                    "user",
                    user_query,
                    image_paths if image_paths else None,
                )
                db.add_message(
                    _require_conv_id(),
                    "assistant",
                    interrupted_text,
                    model=current_model,
                    content_blocks=content_blocks_data,
                )

                await broadcast_message(
                    "conversation_saved",
                    json.dumps({"conversation_id": _require_conv_id()}),
                )

                logger.info("Saved interrupted conversation: %s", _require_conv_id())

                return _require_conv_id()

            # 1. Create conversation entry if it doesn't exist
            if _get_conv_id() is None:
                title = user_query[:50] + ("..." if len(user_query) > 50 else "")
                _set_conv_id(db.start_new_conversation(title))
                logger.info("Created conversation: %s", _require_conv_id())

                # Flush any terminal events that were queued before conversation existed
                from .terminal import terminal_service
                terminal_service.flush_pending_events(_require_conv_id())

            # Persist token usage
            input_tokens = token_stats.get("prompt_eval_count", 0)
            output_tokens = token_stats.get("eval_count", 0)
            if input_tokens or output_tokens:
                try:
                    db.add_token_usage(_require_conv_id(), input_tokens, output_tokens)
                except Exception as e:
                    logger.error("Error saving token usage: %s", e)

            # Broadcast tool calls summary
            if tool_calls:
                await broadcast_message("tool_calls_summary", json.dumps(tool_calls))

            # Add to chat history
            user_msg: Dict[str, Any] = {"role": "user", "content": user_query}
            if image_paths:
                user_msg["images"] = image_paths
            _chat_history.append(user_msg)

            if response_text.strip():
                assistant_msg: Dict[str, Any] = {
                    "role": "assistant",
                    "content": response_text,
                    "model": current_model,
                }
                if tool_calls:
                    assistant_msg["tool_calls"] = tool_calls
                _chat_history.append(assistant_msg)
            elif tool_calls:
                fallback_text = (
                    "[Tool calls completed but model returned empty response]"
                )
                assistant_msg = {
                    "role": "assistant",
                    "content": fallback_text,
                    "model": current_model,
                    "tool_calls": tool_calls,
                }
                _chat_history.append(assistant_msg)
                response_text = fallback_text
                logger.warning(
                    "Empty response after tool calls — saved fallback message"
                )

            # Persist to database
            db.add_message(
                _require_conv_id(),
                "user",
                user_query,
                image_paths if image_paths else None,
            )
            if response_text.strip() or tool_calls:
                content_blocks_data: List[Dict] | None = None
                if interleaved_blocks_from_llm:
                    content_blocks_data = [
                        {k: v for k, v in block.items() if k != "result"}
                        for block in interleaved_blocks_from_llm
                    ]
                elif tool_calls:
                    content_blocks_data = [
                        {
                            "type": "tool_call",
                            "name": tc["name"],
                            "args": tc.get("args", {}),
                            "server": tc.get("server", ""),
                        }
                        for tc in tool_calls
                    ]
                    if response_text.strip():
                        content_blocks_data.append(
                            {"type": "text", "content": response_text}
                        )

                save_text = response_text if response_text.strip() else "[Tool calls completed]"
                db.add_message(
                    _require_conv_id(),
                    "assistant",
                    save_text,
                    model=current_model,
                    content_blocks=content_blocks_data,
                )

            # Notify frontend
            await broadcast_message(
                "conversation_saved",
                json.dumps({"conversation_id": _require_conv_id()}),
            )

            logger.debug("Chat history: %d messages", len(_chat_history))

            return _require_conv_id()

        except Exception as e:
            await broadcast_message("error", f"Error processing: {e}")
            return None
        finally:
            # ── Always clear screenshots that were consumed ───────────
            # Covers normal, cancelled, AND exception paths so the
            # frontend chip container is never left stale.
            if _screenshot_list:
                _screenshot_list.clear()
                await broadcast_message("screenshots_cleared", "")

            # ── Request lifecycle: mark done ──────────────────────────
            ctx.mark_done()
            set_current_request(None)  # Clear contextvars
            set_current_model(None)

            async with _request_lock:
                if tab_state:
                    tab_state.current_request = None
                    tab_state.is_streaming = False
                else:
                    app_state.current_request = None
                    app_state.is_streaming = False

            # Unregister from queue
            if queue is not None:
                queue.clear_active_ctx()

            # Auto-expire session mode after each turn
            from .terminal import terminal_service

            if terminal_service.session_mode:
                await terminal_service.end_session()
                logger.info("Session mode auto-expired after turn")

    @staticmethod
    def get_conversations(limit: int = 50, offset: int = 0) -> List[Dict]:
        """Get recent conversations."""
        return db.get_recent_conversations(limit=limit, offset=offset)

    @staticmethod
    def search_conversations(query: str) -> List[Dict]:
        """Search conversations by text."""
        return db.search_conversations(query)

    @staticmethod
    def delete_conversation(conversation_id: str):
        """Delete a conversation."""
        db.delete_conversation(conversation_id)

    @staticmethod
    def get_full_conversation(conversation_id: str) -> List[Dict]:
        """Get all messages from a conversation."""
        return db.get_full_conversation(conversation_id)
