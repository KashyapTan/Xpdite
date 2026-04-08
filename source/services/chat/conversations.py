"""
Conversation management service.

Handles conversation lifecycle, persistence, and query processing.
"""

import os
import copy
import json
import logging
import re
import uuid
import asyncio
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from ...infrastructure.config import MAX_TOOL_RESULT_LENGTH
from ...core.connection import broadcast_message
from ...core.request_context import RequestContext
from ...core.state import app_state
from ...core.thread_pool import run_in_thread
from ...infrastructure.database import db
from ...llm.core.router import route_chat
from ..artifacts import artifact_service
from ..media.screenshots import ScreenshotHandler

logger = logging.getLogger(__name__)

_SLASH_COMMAND_PATTERN = re.compile(r"(?<!\S)/([a-zA-Z0-9_-]+)(?=\s|$)")
_ATTACHMENT_READ_FILE_MAX_CHARS = 8000
if TYPE_CHECKING:
    from .tab_manager import TabState
    from .query_queue import ConversationQueue


# Conversations service logic


def _extract_skill_slash_commands_sync(message: str) -> tuple[list, str]:
    """Extract slash commands from a user message and match to skills.

    Returns (matched_skills, cleaned_message) where matched_skills is a
    list of ``Skill`` objects from the SkillManager.
    Removes matched slash commands from the message text.
    If a slash command is recognized but the skill is disabled, strip it
    from the message silently and skip injection.

    This is the synchronous implementation; callers should use
    ``ConversationService.extract_skill_slash_commands`` which wraps it
    in ``run_in_thread``.
    """
    from ..skills_runtime.skills import get_skill_manager

    manager = get_skill_manager()
    all_skills = manager.get_all_skills()
    slash_map = {s.slash_command.lower(): s for s in all_skills if s.slash_command}

    matched_skills: list = []
    seen_commands: set[str] = set()
    cleaned_parts: list[str] = []
    last_index = 0

    for match in _SLASH_COMMAND_PATTERN.finditer(message):
        cmd = match.group(1).lower()
        skill = slash_map.get(cmd)
        if skill is None:
            continue

        start, end = match.span()
        cleaned_parts.append(message[last_index:start])

        if skill.enabled and cmd not in seen_commands:
            matched_skills.append(skill)
            seen_commands.add(cmd)

        last_index = end

    cleaned_parts.append(message[last_index:])
    cleaned_message = " ".join("".join(cleaned_parts).split())
    return matched_skills, cleaned_message


def _truncate_attachment_tool_result(result: str) -> str:
    """Mirror tool-loop truncation behavior for large textual payloads."""
    if len(result) > MAX_TOOL_RESULT_LENGTH:
        return result[:MAX_TOOL_RESULT_LENGTH] + "... [Output truncated due to length]"
    return result


async def _run_read_file_for_attachment(path: str) -> str | dict[str, Any]:
    """Execute filesystem read_file with the same defaults as tool calls."""
    from mcp_servers.servers.filesystem.server import read_file

    return await run_in_thread(read_file, path, 0, _ATTACHMENT_READ_FILE_MAX_CHARS)


@lru_cache(maxsize=1)
def _get_thumbnail_creator():
    try:
        from ...infrastructure.screenshot_runtime import create_thumbnail
    except Exception as exc:
        logger.warning("Screenshot thumbnail support unavailable: %s", exc)
        return None
    return create_thumbnail


class ConversationService:
    """Manages conversation lifecycle and query processing."""

    @staticmethod
    async def extract_skill_slash_commands(message: str) -> tuple[list, str]:
        """Extract slash commands from a user message (async wrapper).

        Delegates to ``_extract_skill_slash_commands_sync`` via
        ``run_in_thread`` so the synchronous filesystem reads do not block
        the event loop.
        """
        return await run_in_thread(_extract_skill_slash_commands_sync, message)

    @staticmethod
    def _conversation_title(text: str) -> str:
        return text[:50] + ("..." if len(text) > 50 else "")

    @staticmethod
    async def _hydrate_message_images(message: Dict[str, Any]) -> Dict[str, Any]:
        hydrated_message = copy.deepcopy(message)
        images = hydrated_message.get("images")
        if not images or not all(isinstance(image, str) for image in images):
            return hydrated_message

        create_thumbnail = _get_thumbnail_creator()

        thumbnails = []
        for image_path in images:
            thumbnail = None
            if create_thumbnail is not None and os.path.exists(image_path):
                thumbnail = await run_in_thread(create_thumbnail, image_path)

            thumbnails.append(
                {
                    "name": os.path.basename(image_path),
                    "thumbnail": thumbnail,
                }
            )

        hydrated_message["images"] = thumbnails
        return hydrated_message

    @staticmethod
    async def _hydrate_messages_for_frontend(
        messages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        return [
            await ConversationService._hydrate_message_images(message)
            for message in messages
        ]

    @staticmethod
    async def _hydrate_turn_payload(
        turn: Dict[str, Any] | None,
    ) -> Dict[str, Any] | None:
        if turn is None:
            return None

        hydrated_turn = {
            "turn_id": turn["turn_id"],
            "user": await ConversationService._hydrate_message_images(turn["user"]),
        }
        if turn.get("assistant") is not None:
            hydrated_turn[
                "assistant"
            ] = await ConversationService._hydrate_message_images(turn["assistant"])
        return hydrated_turn

    @staticmethod
    def _set_chat_history(
        conversation_id: str, tab_state: Optional["TabState"] = None
    ) -> None:
        history = db.get_active_chat_history(conversation_id)
        if tab_state is not None:
            tab_state.chat_history = history
        else:
            app_state.chat_history = history

    @staticmethod
    def _build_content_blocks_data(
        response_text: str,
        tool_calls: List[Dict[str, Any]],
        interleaved_blocks_from_llm: Optional[List[Dict[str, Any]]],
        *,
        interrupted: bool = False,
    ) -> List[Dict[str, Any]] | None:
        if interleaved_blocks_from_llm:
            blocks = [
                {k: v for k, v in block.items() if k != "result"}
                for block in interleaved_blocks_from_llm
            ]
            if interrupted:
                blocks.append({"type": "text", "content": "\n\n[Response interrupted]"})
            return blocks

        if not tool_calls:
            return None

        blocks = [
            {
                "type": "tool_call",
                "name": tc["name"],
                "args": tc.get("args", {}),
                "server": tc.get("server", ""),
            }
            for tc in tool_calls
        ]
        if response_text.strip():
            blocks.append({"type": "text", "content": response_text})
        return blocks

    @staticmethod
    def _extract_artifact_ids(
        content_blocks: Optional[List[Dict[str, Any]]],
    ) -> List[str]:
        if not content_blocks:
            return []
        return [
            artifact_id
            for artifact_id in (
                str(block.get("artifact_id") or "").strip()
                for block in content_blocks
                if block.get("type") == "artifact"
            )
            if artifact_id
        ]

    @staticmethod
    def _artifact_deleted_payload(
        artifact: Dict[str, Any] | str,
    ) -> Dict[str, Any] | None:
        if isinstance(artifact, str):
            artifact_id = artifact.strip()
            return {"artifact_id": artifact_id} if artifact_id else None

        artifact_id = str(
            artifact.get("id") or artifact.get("artifact_id") or ""
        ).strip()
        if not artifact_id:
            return None

        payload: Dict[str, Any] = {"artifact_id": artifact_id}
        if artifact.get("conversation_id") is not None:
            payload["conversation_id"] = artifact.get("conversation_id")
        if artifact.get("message_id") is not None:
            payload["message_id"] = artifact.get("message_id")
        if artifact.get("reason") is not None:
            payload["reason"] = artifact.get("reason")
        return payload

    @staticmethod
    async def _broadcast_deleted_artifacts(
        artifacts: List[Dict[str, Any] | str],
    ) -> None:
        for artifact in artifacts:
            payload = ConversationService._artifact_deleted_payload(artifact)
            if payload is None:
                continue
            await broadcast_message("artifact_deleted", payload)

    @staticmethod
    def _resolve_turn_context(target_message_id: str) -> Dict[str, Any]:
        target_message = db.get_message_by_id(target_message_id)
        if target_message is None:
            raise ValueError("Selected message could not be found.")

        conversation_id = target_message["conversation_id"]
        turn_id = target_message["turn_id"]
        turn_messages = db.get_turn_messages(conversation_id, turn_id)
        user_message = next(
            (msg for msg in turn_messages if msg["role"] == "user"), None
        )
        assistant_message = next(
            (msg for msg in turn_messages if msg["role"] == "assistant"), None
        )
        if user_message is None:
            raise ValueError("Selected turn does not have a user message.")
        if assistant_message is None:
            raise ValueError("Selected turn does not have an assistant response yet.")

        return {
            "conversation_id": conversation_id,
            "turn_id": turn_id,
            "user_message": user_message,
            "assistant_message": assistant_message,
            "history_before_turn": db.get_active_chat_history(
                conversation_id,
                stop_before_turn_id=turn_id,
            ),
            "image_paths": user_message.get("images", []),
        }

    @staticmethod
    async def clear_context(tab_state: Optional["TabState"] = None):
        """Clear screenshots and chat history for a fresh start.

        If *tab_state* is provided, clears per-tab state instead of global.
        """
        from ..shell.terminal import terminal_service

        if tab_state is not None:
            await ScreenshotHandler.clear_screenshots(tab_state=tab_state)
            tab_state.chat_history = []
            tab_state.conversation_id = None
        else:
            await ScreenshotHandler.clear_screenshots()
            app_state.chat_history = []
            app_state.conversation_id = None

        terminal_service.reset()

        logger.info("Context cleared: screenshots and chat history reset")
        await broadcast_message(
            "context_cleared", "Context cleared. Ready for new conversation."
        )

    @staticmethod
    async def resume_conversation(
        conversation_id: str, tab_state: Optional["TabState"] = None
    ):
        """Resume a previously saved conversation.

        If *tab_state* is provided, loads into per-tab state.
        """

        # Resolve state target
        chat_history_target = (
            tab_state.chat_history if tab_state else app_state.chat_history
        )

        # Clear current state
        chat_history_target.clear()
        if tab_state is not None:
            await ScreenshotHandler.clear_screenshots(tab_state=tab_state)
        else:
            await ScreenshotHandler.clear_screenshots()

        # Load conversation from database
        raw_messages = db.get_full_conversation(conversation_id)
        messages = await ConversationService._hydrate_messages_for_frontend(
            copy.deepcopy(raw_messages)
        )
        if tab_state is not None:
            tab_state.conversation_id = conversation_id
        else:
            app_state.conversation_id = conversation_id

        ConversationService._set_chat_history(conversation_id, tab_state=tab_state)

        chat_history_len = (
            len(tab_state.chat_history) if tab_state else len(app_state.chat_history)
        )
        logger.info(
            "Resumed conversation %s with %d messages",
            conversation_id,
            chat_history_len,
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
        attached_files: list[dict[str, str]] | None = None,
        forced_skills: list | None = None,
        llm_query: str | None = None,
        tab_state: Optional["TabState"] = None,
        queue: Optional["ConversationQueue"] = None,
        model: Optional[str] = None,
        action: str = "submit",
        target_message_id: Optional[str] = None,
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
            action: 'submit' for new turns, 'retry' to regenerate, 'edit' to edit an earlier turn.
            target_message_id: Stable message identifier for retry/edit actions.

        Returns:
            The conversation_id (str) or None on failure.
        """

        if action not in {"submit", "retry", "edit"}:
            await broadcast_message(
                "error", f"Unsupported conversation action: {action}"
            )
            return None

        def _get_conv_id() -> Optional[str]:
            return tab_state.conversation_id if tab_state else app_state.conversation_id

        def _set_conv_id(value: Optional[str]) -> None:
            if tab_state:
                setattr(tab_state, "conversation_id", value)
            else:
                setattr(app_state, "conversation_id", value)

        def _require_conv_id() -> str:
            """Return conversation_id or raise — used after we know it's been set."""
            cid = _get_conv_id()
            assert cid is not None, "conversation_id should be set by this point"
            return cid

        if tab_state is None:
            raise RuntimeError(
                "submit_query requires tab_state; global screenshot state is no longer supported"
            )

        _screenshot_list = tab_state.screenshot_list
        _request_lock = (
            tab_state._request_lock if tab_state else app_state._request_lock
        )

        current_model = model or app_state.selected_model

        logger.debug(
            "submit_query: action=%s, model=%s, capture_mode=%s, screenshots=%d",
            action,
            current_model,
            capture_mode,
            len(_screenshot_list),
        )

        # ── Request lifecycle: create context ─────────────────────────
        async with _request_lock:
            current_req = (
                tab_state.current_request if tab_state else app_state.current_request
            )
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
        from ...core.request_context import set_current_request, set_current_model

        _ctx_token = set_current_request(ctx)
        _model_token = set_current_model(current_model)

        # Register ctx on the queue so stop_current works
        if queue is not None:
            queue.set_active_ctx(ctx)

        turn_context: Dict[str, Any] | None = None
        should_clear_screenshots = action == "submit"

        try:
            # NOTE: Fullscreen auto-capture is now done in the handler
            # (_handle_submit_query) BEFORE enqueuing, so screenshots are
            # taken immediately without being blocked by the Ollama queue.
            if action == "submit":
                image_paths = tab_state.get_image_paths()
                history_for_llm = copy.deepcopy(tab_state.chat_history)
                display_query = user_query
            else:
                if not target_message_id:
                    await broadcast_message(
                        "error", "Retry/edit actions require a target message."
                    )
                    return None
                try:
                    turn_context = ConversationService._resolve_turn_context(
                        target_message_id
                    )
                except ValueError as exc:
                    await broadcast_message("error", str(exc))
                    return None

                _set_conv_id(turn_context["conversation_id"])
                history_for_llm = copy.deepcopy(turn_context["history_before_turn"])
                image_paths = turn_context["image_paths"]
                display_query = (
                    turn_context["user_message"]["content"]
                    if action == "retry"
                    else user_query
                )

            query_for_llm = llm_query if llm_query else display_query
            tool_retrieval_query = query_for_llm

            if action == "submit" and attached_files:
                attachment_blocks: list[str] = []
                attachment_warnings: list[str] = []

                async def _extract_one(
                    attached: dict[str, str],
                ) -> tuple[str | None, str | None, str | None]:
                    file_path = str(attached.get("path", "")).strip()
                    file_name = str(
                        attached.get("name", "")
                    ).strip() or os.path.basename(file_path)
                    if not file_path:
                        return None, None, "Skipped empty attachment path."
                    if not os.path.exists(file_path):
                        return None, None, f"Attachment missing: {file_name}"

                    relative_path = file_path
                    try:
                        relative_path = os.path.relpath(
                            file_path, os.path.expanduser("~")
                        )
                    except Exception:
                        pass

                    try:
                        result = await _run_read_file_for_attachment(file_path)

                        if isinstance(result, str):
                            if result.startswith("Error:"):
                                return (
                                    None,
                                    None,
                                    f"Attachment skipped ({file_name}): {result}",
                                )
                            block_text = _truncate_attachment_tool_result(result)
                            block = (
                                f"--- Attached via read_file: {file_name} ({relative_path}) ---\n"
                                f"{block_text}\n"
                                f"--- End: {file_name} ---"
                            )
                            return block, None, None

                        if not isinstance(result, dict):
                            return (
                                None,
                                None,
                                f"Attachment skipped ({file_name}): unexpected read_file result type.",
                            )

                        if result.get("type") == "image":
                            width = result.get("width", "?")
                            height = result.get("height", "?")
                            file_size = int(result.get("file_size_bytes", 0) or 0)
                            block = (
                                f"--- Attached via read_file: {file_name} ({relative_path}) ---\n"
                                f"Image: {width}x{height}, {file_size:,} bytes\n"
                                "[This image was auto-attached as multimodal context from the @ attachment.]\n"
                                f"--- End: {file_name} ---"
                            )
                            return block, file_path, None

                        serialized_result = json.dumps(
                            result,
                            ensure_ascii=False,
                            default=str,
                            indent=2,
                        )
                        block_text = _truncate_attachment_tool_result(serialized_result)

                        block = (
                            f"--- Attached via read_file: {file_name} ({relative_path}) ---\n"
                            f"{block_text}\n"
                            f"--- End: {file_name} ---"
                        )
                        return block, None, None
                    except Exception as exc:
                        return (
                            None,
                            None,
                            f"Attachment read_file failed for {file_name}: {exc}",
                        )

                extraction_results = await asyncio.gather(
                    *[_extract_one(attached) for attached in attached_files[:10]],
                    return_exceptions=False,
                )

                for block, image_path, warning in extraction_results:
                    if block:
                        attachment_blocks.append(block)
                    if image_path:
                        image_paths.append(image_path)
                    if warning:
                        attachment_warnings.append(warning)

                if attachment_blocks:
                    query_for_llm = "\n\n".join([*attachment_blocks, query_for_llm])
                if attachment_warnings:
                    warning_block = "\n".join(
                        f"[Attachment warning] {warning}"
                        for warning in attachment_warnings
                    )
                    query_for_llm = f"{warning_block}\n\n{query_for_llm}"

            await broadcast_message("query", display_query)

            (
                response_text,
                token_stats,
                tool_calls,
                interleaved_blocks_from_llm,
            ) = await route_chat(
                current_model,
                query_for_llm,
                image_paths,
                history_for_llm,
                forced_skills=ctx.forced_skills,
                tool_retrieval_query=tool_retrieval_query,
            )

            interrupted = ctx.cancelled
            if interrupted:
                if response_text.strip():
                    response_text = response_text + "\n\n[Response interrupted]"
                else:
                    response_text = "[Response interrupted]"

            if _get_conv_id() is None:
                _set_conv_id(
                    db.start_new_conversation(
                        ConversationService._conversation_title(display_query)
                    )
                )
                logger.info("Created conversation: %s", _require_conv_id())

                from ..shell.terminal import terminal_service

                terminal_service.flush_pending_events(_require_conv_id())

            input_tokens = token_stats.get("prompt_eval_count", 0)
            output_tokens = token_stats.get("eval_count", 0)
            if input_tokens or output_tokens:
                try:
                    db.add_token_usage(_require_conv_id(), input_tokens, output_tokens)
                except Exception as exc:
                    logger.error("Error saving token usage: %s", exc)

            if tool_calls:
                await broadcast_message("tool_calls_summary", json.dumps(tool_calls))

            if not response_text.strip() and tool_calls:
                response_text = (
                    "[Tool calls completed but model returned empty response]"
                )
                logger.warning(
                    "Empty response after tool calls — saved fallback message"
                )

            content_blocks_data = ConversationService._build_content_blocks_data(
                response_text,
                tool_calls,
                interleaved_blocks_from_llm,
                interrupted=interrupted,
            )
            should_save_assistant = bool(
                (response_text and response_text.strip())
                or tool_calls
                or content_blocks_data
            )

            if turn_context is not None:
                later_assistant_ids = db.get_assistant_message_ids_after_turn(
                    turn_context["conversation_id"], turn_context["turn_id"]
                )
                if later_assistant_ids:
                    deleted_batches = await asyncio.gather(
                        *[
                            run_in_thread(
                                artifact_service.delete_artifacts_for_message,
                                assistant_message_id,
                            )
                            for assistant_message_id in later_assistant_ids
                        ]
                    )
                    for deleted_artifacts in deleted_batches:
                        await ConversationService._broadcast_deleted_artifacts(
                            deleted_artifacts
                        )

                if action == "edit":
                    deleted_artifacts = await run_in_thread(
                        artifact_service.delete_artifacts_for_message,
                        turn_context["assistant_message"]["message_id"],
                    )
                    await ConversationService._broadcast_deleted_artifacts(
                        deleted_artifacts
                    )

            if content_blocks_data:
                persist_message_id = (
                    turn_context["assistant_message"]["message_id"]
                    if turn_context is not None
                    else None
                )
                content_blocks_data = await run_in_thread(
                    artifact_service.persist_generated_artifacts,
                    content_blocks_data,
                    conversation_id=_require_conv_id(),
                    message_id=persist_message_id,
                )

            artifact_ids = ConversationService._extract_artifact_ids(content_blocks_data)

            saved_turn: Dict[str, Any] | None = None

            if action == "submit":
                turn_id = str(uuid.uuid4())

                # Check if this is a mobile-originated message
                mobile_origin = None
                if tab_state is not None:
                    from ..integrations.mobile_channel import mobile_channel_service

                    mobile_info = mobile_channel_service.get_mobile_tab_info(
                        tab_state.tab_id
                    )
                    if mobile_info:
                        platform_name, _sender_id, _thread_id = mobile_info
                        mobile_origin = {
                            "platform": platform_name,
                            "display_name": platform_name.title(),
                        }

                db.add_message(
                    _require_conv_id(),
                    "user",
                    display_query,
                    image_paths if image_paths else None,
                    turn_id=turn_id,
                    mobile_origin=mobile_origin,
                )

                if should_save_assistant:
                    save_text = response_text if response_text.strip() else ""
                    if not save_text and tool_calls and not content_blocks_data:
                        save_text = "[Tool calls completed]"
                    assistant_message = db.add_message(
                        _require_conv_id(),
                        "assistant",
                        save_text,
                        model=current_model,
                        content_blocks=content_blocks_data,
                        turn_id=turn_id,
                    )
                    if artifact_ids:
                        await run_in_thread(
                            artifact_service.link_artifacts_to_message,
                            artifact_ids,
                            message_id=assistant_message["message_id"],
                        )
                    db.save_response_version(
                        _require_conv_id(),
                        assistant_message["message_id"],
                        save_text,
                        model=current_model,
                        content_blocks=content_blocks_data,
                        created_at=assistant_message["timestamp"],
                        replace_history=True,
                    )

                saved_turn = db.get_turn_payload(_require_conv_id(), turn_id)
            else:
                assert turn_context is not None

                db.truncate_conversation_after_turn(
                    turn_context["conversation_id"], turn_context["turn_id"]
                )

                if action == "edit":
                    conversation_title = None
                    if db.is_first_user_message(
                        turn_context["conversation_id"],
                        turn_context["user_message"]["message_id"],
                    ):
                        conversation_title = ConversationService._conversation_title(
                            display_query
                        )

                    updated_user_message = db.update_user_message(
                        turn_context["conversation_id"],
                        turn_context["user_message"]["message_id"],
                        display_query,
                        conversation_title=conversation_title,
                    )
                    if updated_user_message is None:
                        raise ValueError("Selected turn could not be updated.")

                save_text = response_text if response_text.strip() else ""
                if not save_text and not content_blocks_data:
                    save_text = "[Model returned empty response]"
                db.save_response_version(
                    turn_context["conversation_id"],
                    turn_context["assistant_message"]["message_id"],
                    save_text,
                    model=current_model,
                    content_blocks=content_blocks_data,
                    replace_history=action == "edit",
                )

                saved_turn = db.get_turn_payload(
                    turn_context["conversation_id"], turn_context["turn_id"]
                )

            ConversationService._set_chat_history(
                _require_conv_id(), tab_state=tab_state
            )
            saved_turn = await ConversationService._hydrate_turn_payload(saved_turn)

            await broadcast_message(
                "conversation_saved",
                {
                    "conversation_id": _require_conv_id(),
                    "operation": action,
                    "truncate_after_turn": action in {"retry", "edit"},
                    "turn": saved_turn,
                },
            )

            logger.debug(
                "Chat history: %d messages",
                len(tab_state.chat_history if tab_state else app_state.chat_history),
            )

            return _require_conv_id()

        except Exception as e:
            await broadcast_message("error", f"Error processing: {e}")
            return None
        finally:
            # ── Always clear screenshots that were consumed ───────────
            # Covers normal, cancelled, AND exception paths so the
            # frontend chip container is never left stale.
            if should_clear_screenshots and _screenshot_list:
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
            from ..shell.terminal import terminal_service

            if terminal_service.session_mode:
                await terminal_service.end_session()
                logger.info("Session mode auto-expired after turn")

    @staticmethod
    def set_active_response_variant(
        message_id: str,
        response_index: int,
        tab_state: Optional["TabState"] = None,
    ) -> Dict[str, Any]:
        """Persist and apply the currently selected assistant response variant."""
        message = db.get_message_by_id(message_id)
        if message is None:
            raise ValueError("Assistant message not found.")
        if message["role"] != "assistant":
            raise ValueError("Only assistant responses can switch variants.")

        updated = db.set_active_response_version(
            message["conversation_id"], message_id, response_index
        )
        if updated is None:
            raise ValueError("Requested response variant does not exist.")

        ConversationService._set_chat_history(
            message["conversation_id"], tab_state=tab_state
        )
        return updated

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
        artifact_service.delete_artifacts_for_conversation(conversation_id)
        db.delete_conversation(conversation_id)

    @staticmethod
    def get_full_conversation(conversation_id: str) -> List[Dict]:
        """Get all messages from a conversation."""
        return db.get_full_conversation(conversation_id)
