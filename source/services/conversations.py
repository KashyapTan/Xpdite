"""
Conversation management service.

Handles conversation lifecycle, persistence, and query processing.
"""

import os
import json
from typing import List, Dict, Any, Optional

from ..core.state import app_state
from ..core.request_context import RequestContext
from ..core.connection import broadcast_message
from ..llm.router import route_chat
from ..config import SCREENSHOT_FOLDER, CaptureMode
from .screenshots import ScreenshotHandler
from ..database import db


# Conversations service logic


class ConversationService:
    """Manages conversation lifecycle and query processing."""

    @staticmethod
    async def clear_context():
        """Clear screenshots and chat history for a fresh start."""
        from .terminal import terminal_service

        await ScreenshotHandler.clear_screenshots()
        app_state.chat_history = []
        app_state.conversation_id = None

        # Reset terminal service state (ends session mode, clears tracking)
        terminal_service.reset()

        print("Context cleared: screenshots and chat history reset")
        await broadcast_message(
            "context_cleared", "Context cleared. Ready for new conversation."
        )

    @staticmethod
    async def resume_conversation(conversation_id: str):
        """Resume a previously saved conversation."""
        from .terminal import terminal_service
        from ..database import db
        from ..ss import create_thumbnail

        # Clear current state
        app_state.chat_history = []
        await ScreenshotHandler.clear_screenshots()

        # Load conversation from database
        messages = db.get_full_conversation(conversation_id)
        app_state.conversation_id = conversation_id

        # Rebuild in-memory chat history
        for msg in messages:
            entry = {"role": msg["role"], "content": msg["content"]}
            if msg.get("model"):
                entry["model"] = msg["model"]
            if msg.get("images"):
                entry["images"] = msg["images"]
                # Generate thumbnails for frontend
                thumbnails = []
                for img_path in msg["images"]:
                    if os.path.exists(img_path):
                        thumb = create_thumbnail(img_path)
                        thumbnails.append(
                            {"name": os.path.basename(img_path), "thumbnail": thumb}
                        )
                    else:
                        thumbnails.append(
                            {"name": os.path.basename(img_path), "thumbnail": None}
                        )
                msg["images"] = thumbnails
            app_state.chat_history.append(entry)

        print(
            f"Resumed conversation {conversation_id} with {len(app_state.chat_history)} messages"
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
    ):
        """
        Handle query submission from a client.

        Args:
            user_query: The user's original question (with slash commands, for display/save)
            capture_mode: 'fullscreen', 'precision', or 'none'
            forced_skills: Skills forced via slash commands (e.g. /terminal)
            llm_query: Cleaned query without slash commands (for the LLM). Uses user_query if None.
        """
        from ..ss import take_fullscreen_screenshot, create_thumbnail

        current_model = app_state.selected_model
        print(
            f"[DEBUG] submit_query: model={current_model}, capture_mode={capture_mode}, screenshots={len(app_state.screenshot_list)}"
        )

        # ── Request lifecycle: create context ─────────────────────────
        async with app_state._request_lock:
            if (
                app_state.current_request is not None
                and not app_state.current_request.is_done
            ):
                await broadcast_message("error", "Already streaming. Please wait.")
                return
            ctx = RequestContext()
            ctx.forced_skills = forced_skills or []
            app_state.current_request = ctx
            # Legacy sync
            app_state.is_streaming = True
            app_state.stop_streaming = False

        try:
            # Auto-capture fullscreen on first message of new conversation
            if (
                capture_mode == CaptureMode.FULLSCREEN
                and len(app_state.screenshot_list) == 0
                and len(app_state.chat_history) == 0
            ):
                await ScreenshotHandler.capture_fullscreen()

            # Get image paths
            image_paths = app_state.get_image_paths()

            # Echo query to clients
            await broadcast_message("query", user_query)

            # Reset stop flag (use the context now)
            app_state.stop_streaming = False

            # Stream the response — use cleaned query (without slash commands) for the LLM
            query_for_llm = llm_query if llm_query else user_query
            response_text, token_stats, tool_calls, interleaved_blocks_from_llm = await route_chat(
                current_model,
                query_for_llm,
                image_paths,
                app_state.chat_history.copy(),
                forced_skills=ctx.forced_skills,
            )

            # 1. Create conversation entry if it doesn't exist
            from ..database import db
            if app_state.conversation_id is None:
                title = user_query[:50] + ("..." if len(user_query) > 50 else "")
                app_state.conversation_id = db.start_new_conversation(title)
                print(f"Created conversation: {app_state.conversation_id}")

                # Flush any terminal events that were queued before conversation existed
                from .terminal import terminal_service
                from ..database import db
                terminal_service.flush_pending_events(app_state.conversation_id)

            # Persist token usage
            input_tokens = token_stats.get("prompt_eval_count", 0)
            output_tokens = token_stats.get("eval_count", 0)
            if input_tokens or output_tokens:
                try:
                    db.add_token_usage(
                        app_state.conversation_id, input_tokens, output_tokens
                    )
                except Exception as e:
                    print(f"Error saving token usage: {e}")

            # Broadcast tool calls summary
            if tool_calls:
                await broadcast_message("tool_calls_summary", json.dumps(tool_calls))

            # Add to chat history
            user_msg: Dict[str, Any] = {"role": "user", "content": user_query}
            if image_paths:
                user_msg["images"] = image_paths
            app_state.chat_history.append(user_msg)

            if response_text.strip():
                assistant_msg: Dict[str, Any] = {
                    "role": "assistant",
                    "content": response_text,
                    "model": current_model,
                }
                if tool_calls:
                    assistant_msg["tool_calls"] = tool_calls
                app_state.chat_history.append(assistant_msg)
            elif tool_calls:
                # Safety net: tool calls were made but response was empty.
                # Save a fallback message so conversation history isn't broken.
                fallback_text = (
                    "[Tool calls completed but model returned empty response]"
                )
                assistant_msg = {
                    "role": "assistant",
                    "content": fallback_text,
                    "model": current_model,
                    "tool_calls": tool_calls,
                }
                app_state.chat_history.append(assistant_msg)
                response_text = fallback_text
                print(
                    f"[WARN] Empty response after tool calls — saved fallback message"
                )

            # Persist to database
            from ..database import db
            db.add_message(
                app_state.conversation_id,
                "user",
                user_query,
                image_paths if image_paths else None,
            )
            if response_text.strip() or tool_calls:
                # Use interleaved blocks from LLM if available (preserves actual text↔tool order).
                # Fall back to flat construction (all tools then text) for legacy/edge cases.
                content_blocks_data: List[Dict] | None = None
                if interleaved_blocks_from_llm:
                    # Drop results from tool_call blocks — they are not stored to save space
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
                    app_state.conversation_id,
                    "assistant",
                    save_text,
                    model=current_model,
                    content_blocks=content_blocks_data,
                )

            # Notify frontend
            await broadcast_message(
                "conversation_saved",
                json.dumps({"conversation_id": app_state.conversation_id}),
            )

            print(f"Chat history: {len(app_state.chat_history)} messages")

            # Clear screenshots after embedding in history
            if image_paths and len(app_state.screenshot_list) > 0:
                app_state.screenshot_list.clear()
                await broadcast_message("screenshots_cleared", "")

        except Exception as e:
            await broadcast_message("error", f"Error processing: {e}")
        finally:
            # ── Request lifecycle: mark done ──────────────────────────
            ctx.mark_done()
            async with app_state._request_lock:
                app_state.current_request = None
                # Legacy sync
                app_state.is_streaming = False

            # Auto-expire session mode after each turn so the LLM
            # doesn't need to remember to call end_session_mode.
            from .terminal import terminal_service

            if terminal_service.session_mode:
                await terminal_service.end_session()
                print("[Terminal] Session mode auto-expired after turn")

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
