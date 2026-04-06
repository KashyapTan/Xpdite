"""
Mobile Channel Service.

Coordinates communication between the Channel Bridge (Telegram/Discord/WhatsApp)
and Xpdite's core systems (tab manager, conversation queue, database).

Responsibilities:
- Session management: map (platform, sender_id) to Xpdite tabs
- Message routing: enqueue mobile messages into conversation queues
- Command handling: /new, /stop, /status, /model, /help, /pair
- Response relay: forward AI responses back to Channel Bridge for delivery
- Pairing verification: validate pairing codes from mobile users
"""

import logging
import re
import secrets
import uuid
from typing import Any, Optional

import httpx

from ...infrastructure.database import db
from ...core.connection import broadcast_to_tab

logger = logging.getLogger(__name__)


def canonical_sender_id(platform: str, sender_id: str) -> str:
    """Normalize sender IDs to a stable DB key per platform."""
    normalized = sender_id.strip()
    if platform != "whatsapp":
        return normalized

    # WhatsApp can include device suffixes in linked-device sessions:
    # 15551234567:12@s.whatsapp.net -> 15551234567@s.whatsapp.net
    return re.sub(r":[0-9]+@", "@", normalized)


class MobileChannelService:
    """
    Service for managing mobile channel integrations.

    Handles session state, message routing, and command processing
    for mobile messaging platforms (Telegram, Discord, WhatsApp).
    """

    def __init__(self):
        self._channel_bridge_url: str = "http://127.0.0.1:9000"
        self._http_client: Optional[httpx.AsyncClient] = None
        # Track which tabs are mobile-originated for response relay
        self._mobile_tabs: dict[
            str, tuple[str, str, Optional[str]]
        ] = {}  # tab_id -> (platform, sender_id, thread_id)
        # Streaming state per tab: tracks post+edit pattern for response chunks
        # tab_id -> {posted_message_id, accumulated_text, last_edit_time, platform, sender_id, thread_id, last_typing_time}
        self._streaming_state: dict[str, dict] = {}

    @property
    def channel_bridge_url(self) -> str:
        return self._channel_bridge_url

    @channel_bridge_url.setter
    def channel_bridge_url(self, url: str) -> None:
        self._channel_bridge_url = url

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client for Channel Bridge communication."""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=30.0)
        return self._http_client

    async def close(self) -> None:
        """Clean up resources."""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None

    # =========================================================================
    # Pairing
    # =========================================================================

    def is_paired(self, platform: str, sender_id: str) -> bool:
        """Check if a sender is paired with this Xpdite instance."""
        canonical_id = canonical_sender_id(platform, sender_id)
        device = db.get_paired_device(platform, canonical_id)
        is_paired = device is not None
        logger.info(
            "Pair check: platform=%s sender_id=%s canonical=%s paired=%s",
            platform,
            sender_id,
            canonical_id,
            is_paired,
        )
        return is_paired

    def verify_pairing_code(
        self, platform: str, sender_id: str, display_name: Optional[str], code: str
    ) -> tuple[bool, str]:
        """
        Verify a pairing code and create device pairing if valid.

        Returns:
            (success, message) tuple
        """
        canonical_id = canonical_sender_id(platform, sender_id)

        # Check if already paired
        if self.is_paired(platform, canonical_id):
            return True, "You're already paired with this Xpdite instance."

        # Verify the code
        if not db.verify_pairing_code(code):
            return (
                False,
                "Invalid or expired pairing code. Please get a new code from the Xpdite settings.",
            )

        # Create the pairing
        db.add_paired_device(platform, canonical_id, display_name)
        logger.info(
            "Paired new device: %s/%s (raw_sender=%s, display_name=%s)",
            platform,
            canonical_id,
            sender_id,
            display_name,
        )

        return (
            True,
            f"Successfully paired! You can now chat with Xpdite from {platform}.",
        )

    def generate_pairing_code(self, expires_in_seconds: int = 600) -> str:
        """Generate a new pairing code for display in settings UI."""
        # Generate a cryptographically secure 6-digit numeric code
        code = f"{secrets.randbelow(900000) + 100000}"
        db.create_pairing_code(code, expires_in_seconds)
        return code

    def get_all_paired_devices(self) -> list[dict]:
        """Get all paired devices for settings UI."""
        return db.get_all_paired_devices()

    def revoke_device(self, device_id: int) -> None:
        """Revoke a paired device."""
        db.delete_paired_device(device_id)
        # Also remove from mobile_tabs tracking
        # Note: We don't have a direct mapping, so tabs will be cleaned up lazily

    # =========================================================================
    # Session Management
    # =========================================================================

    def get_session(self, platform: str, sender_id: str) -> Optional[dict]:
        """Get existing session for a sender."""
        canonical_id = canonical_sender_id(platform, sender_id)
        return db.get_mobile_session(platform, canonical_id)

    def get_or_create_session(self, platform: str, sender_id: str) -> tuple[dict, bool]:
        """
        Get existing session or create a new one.

        Returns:
            (session_dict, is_new) tuple
        """
        canonical_id = canonical_sender_id(platform, sender_id)
        session = db.get_mobile_session(platform, canonical_id)
        if session:
            # Update activity timestamp on paired device
            db.update_paired_device_activity(platform, canonical_id)
            return session, False

        # Create new tab and session
        tab_id = f"mobile-{platform}-{uuid.uuid4().hex[:8]}"
        db.create_mobile_session(platform, canonical_id, tab_id)

        # Track for response relay
        self._mobile_tabs[tab_id] = (platform, canonical_id, None)

        # Update activity
        db.update_paired_device_activity(platform, canonical_id)

        session = db.get_mobile_session(platform, canonical_id)
        if session is None:
            raise RuntimeError(
                f"Failed to load created mobile session for {platform}/{canonical_id}"
            )
        logger.info(
            f"Created new mobile session: {platform}/{canonical_id} -> tab {tab_id}"
        )

        return session, True

    def end_session(self, platform: str, sender_id: str) -> bool:
        """
        End a mobile session (called on /new command).

        Returns True if session existed and was deleted.
        """
        canonical_id = canonical_sender_id(platform, sender_id)
        session = db.get_mobile_session(platform, canonical_id)
        if not session:
            return False

        tab_id = session["tab_id"]

        # Remove from tracking
        self._mobile_tabs.pop(tab_id, None)

        # Delete session from DB
        db.delete_mobile_session(platform, canonical_id)

        logger.info(f"Ended mobile session: {platform}/{canonical_id} (tab {tab_id})")
        return True

    def is_mobile_tab(self, tab_id: str) -> bool:
        """Check if a tab is mobile-originated."""
        return tab_id in self._mobile_tabs

    def get_mobile_tab_info(
        self, tab_id: str
    ) -> Optional[tuple[str, str, Optional[str]]]:
        """Get (platform, sender_id, thread_id) for a mobile tab."""
        return self._mobile_tabs.get(tab_id)

    # =========================================================================
    # Message Submission
    # =========================================================================

    async def handle_message(
        self,
        platform: str,
        sender_id: str,
        message_text: str,
        thread_id: Optional[str] = None,
    ) -> tuple[bool, str, Optional[str]]:
        """
        Submit a message from a mobile platform.

        Returns:
            (success, message, tab_id) tuple
        """
        canonical_id = canonical_sender_id(platform, sender_id)
        logger.info(
            "Inbound mobile message: platform=%s sender_id=%s canonical=%s thread_id=%s text=%s",
            platform,
            sender_id,
            canonical_id,
            thread_id,
            f"[len={len(message_text)}]",
        )

        # Check pairing
        if not self.is_paired(platform, canonical_id):
            return (
                False,
                "You need to pair first. Send /pair <code> with your pairing code.",
                None,
            )

        # Get or create session
        session, is_new = self.get_or_create_session(platform, canonical_id)
        tab_id = session["tab_id"]

        # Store thread_id for response relay
        if thread_id:
            # We can't easily store thread_id in _mobile_tabs without making it a dict
            # or changing the structure. Since _mobile_tabs is tab_id -> (platform, sender_id),
            # let's update it to tab_id -> (platform, sender_id, thread_id)
            self._mobile_tabs[tab_id] = (platform, canonical_id, thread_id)

        # Import here to avoid circular imports
        from ..chat.tab_manager_instance import tab_manager
        from ..chat.query_queue import QueuedQuery

        # Get the tab session (creates if needed)
        tab_session = tab_manager.get_or_create(tab_id)

        # Determine model to use
        model = session.get("model_override")
        if not model:
            # Check for device default model
            device_default = db.get_paired_device_default_model(platform, canonical_id)
            if device_default:
                model = device_default
            else:
                enabled_models = db.get_enabled_models()
                model = enabled_models[0] if enabled_models else "qwen3-vl:8b-instruct"

        # Create and enqueue the query
        query = QueuedQuery(
            tab_id=tab_id,
            content=message_text,
            model=model,
            capture_mode="none",
        )

        position = await tab_session.queue.enqueue(query)

        logger.info(
            f"Queued mobile message: {platform}/{canonical_id} (thread: {thread_id}) -> tab {tab_id}, "
            f"position {position}, model {model}"
        )

        status_msg = "Message received."
        if is_new:
            status_msg = "Started new conversation. " + status_msg
        if position > 1:
            status_msg += f" (Queue position: {position})"

        return True, status_msg, tab_id

    # =========================================================================
    # Command Handling
    # =========================================================================

    async def handle_command(
        self,
        platform: str,
        sender_id: str,
        command: str,
        args: Optional[str] = None,
        thread_id: Optional[str] = None,
    ) -> str:
        """
        Handle a slash command from mobile.

        Commands: /new, /stop, /status, /model, /help, /pair

        Returns the response message to send back.
        """
        command = command.lower().strip()
        canonical_id = canonical_sender_id(platform, sender_id)
        logger.info(
            "Inbound mobile command: platform=%s sender_id=%s canonical=%s command=/%s args=%s",
            platform,
            sender_id,
            canonical_id,
            command,
            "[REDACTED]" if command == "pair" and args else args,
        )

        if command == "help":
            return self._cmd_help()

        if command == "pair":
            if not args:
                return "Usage: /pair <code>\n\nGet a pairing code from Xpdite Settings > Mobile Channels."
            success, message = self.verify_pairing_code(
                platform, canonical_id, None, args.strip()
            )
            return message

        # All other commands require pairing
        if not self.is_paired(platform, canonical_id):
            return "You need to pair first. Send /pair <code> with your pairing code."

        if command == "new":
            return self._cmd_new(platform, canonical_id)

        if command == "stop":
            return await self._cmd_stop(platform, canonical_id)

        if command == "status":
            return self._cmd_status(platform, canonical_id)

        if command == "model":
            return self._cmd_model(platform, canonical_id, args)

        if command == "default":
            return self._cmd_default(platform, canonical_id, args)

        return f"Unknown command: /{command}\n\nSend /help for available commands."

    def _cmd_help(self) -> str:
        """Return help text."""
        return """Available commands:

/new - Start a fresh conversation
/stop - Stop the current generation
/model - Show available models
/model <name> - Switch to a different model
/default <name> - Set the default model for this device
/status - Show current session status
/pair <code> - Pair with your Xpdite instance
/help - Show this help message

Just send a message to chat with the AI."""

    def _cmd_new(self, platform: str, sender_id: str) -> str:
        """Handle /new command - start fresh conversation."""
        # End current session
        had_session = self.end_session(platform, sender_id)

        if had_session:
            return (
                "Started a fresh conversation. Your next message will begin a new chat."
            )
        else:
            return "Ready for a new conversation. Send a message to begin."

    async def _cmd_stop(self, platform: str, sender_id: str) -> str:
        """Handle /stop command - stop current generation."""
        session = self.get_session(platform, sender_id)
        if not session:
            return "No active conversation to stop."

        tab_id = session["tab_id"]

        # Import here to avoid circular imports
        from ..chat.tab_manager_instance import tab_manager

        tab_session = tab_manager.get_session(tab_id)
        if not tab_session:
            return "No active conversation to stop."

        # Cancel the current generation
        # The queue handles cancellation via the tab's stop flag
        from ...core.state import app_state

        app_state.stop_streaming = True

        # Broadcast stop to the tab
        await broadcast_to_tab(tab_id, "generation_stopped", {"source": "mobile"})

        return "Stopped the current generation."

    def _cmd_status(self, platform: str, sender_id: str) -> str:
        """Handle /status command - show session status."""
        session = self.get_session(platform, sender_id)

        if not session:
            return "No active session. Send a message to start chatting."

        # Get model info
        model = session.get("model_override")
        if not model:
            model = db.get_paired_device_default_model(platform, sender_id)
        if not model:
            enabled_models = db.get_enabled_models()
            model = enabled_models[0] if enabled_models else "default"
            
        tab_id = session["tab_id"]

        # Get queue info
        from ..chat.tab_manager_instance import tab_manager

        tab_session = tab_manager.get_session(tab_id)

        queue_size = 0
        if tab_session:
            queue_size = tab_session.queue.size()

        lines = [
            "Session: Active",
            f"Model: {model}",
            f"Tab: {tab_id}",
        ]

        if queue_size > 0:
            lines.append(f"Queue: {queue_size} message(s) waiting")

        return "\n".join(lines)

    def _cmd_model(self, platform: str, sender_id: str, args: Optional[str]) -> str:
        """Handle /model command - show or switch models."""
        enabled_models = db.get_enabled_models()

        if not enabled_models:
            return "No models are currently enabled. Please configure models in Xpdite settings."

        session = self.get_session(platform, sender_id)
        current_model = session.get("model_override") if session else None
        if not current_model:
            current_model = db.get_paired_device_default_model(platform, sender_id)
        if not current_model:
            current_model = enabled_models[0]

        # No args - show available models
        if not args:
            lines = ["Available models:"]
            for model in enabled_models:
                marker = " (active)" if model == current_model else ""
                lines.append(f"• {model}{marker}")
            lines.append("")
            lines.append("Reply /model <name> to switch.")
            return "\n".join(lines)

        # Try to match the model name
        target = args.strip().lower()
        matches = [m for m in enabled_models if target in m.lower()]

        if not matches:
            return (
                f"No model matches '{args}'.\n\nAvailable: {', '.join(enabled_models)}"
            )

        if len(matches) > 1:
            exact = [m for m in matches if m.lower() == target]
            if len(exact) == 1:
                matches = exact
            else:
                return f"Ambiguous match. Did you mean: {', '.join(matches)}?"

        new_model = matches[0]

        # Update session
        if session:
            db.update_mobile_session(platform, sender_id, model_override=new_model)
        else:
            # Create session first, then update
            self.get_or_create_session(platform, sender_id)
            db.update_mobile_session(platform, sender_id, model_override=new_model)

        return f"Switched to {new_model}"

    def _cmd_default(self, platform: str, sender_id: str, args: Optional[str]) -> str:
        """Handle /default command - set default model for device."""
        enabled_models = db.get_enabled_models()

        if not enabled_models:
            return "No models are currently enabled. Please configure models in Xpdite settings."

        current_default = db.get_paired_device_default_model(platform, sender_id)

        # No args - show current default
        if not args:
            if current_default:
                return f"Current default model is: {current_default}\n\nReply /default <name> to change."
            return "No default model set for this device.\n\nReply /default <name> to set one."

        # Try to match the model name
        target = args.strip().lower()
        matches = [m for m in enabled_models if target in m.lower()]

        if not matches:
            return (
                f"No model matches '{args}'.\n\nAvailable: {', '.join(enabled_models)}"
            )

        if len(matches) > 1:
            exact = [m for m in matches if m.lower() == target]
            if len(exact) == 1:
                matches = exact
            else:
                return f"Ambiguous match. Did you mean: {', '.join(matches)}?"

        new_model = matches[0]

        # Update paired device default
        db.set_paired_device_default_model(platform, sender_id, new_model)
        
        # Also update current session if exists
        session = self.get_session(platform, sender_id)
        if session:
            db.update_mobile_session(platform, sender_id, model_override=new_model)

        return f"Default model set to {new_model} for this device."

    # =========================================================================
    # Response Relay (outbound to Channel Bridge)
    # =========================================================================

    async def relay_to_platform(
        self,
        platform: str,
        sender_id: str,
        message_type: str,
        content: str,
        thread_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        Send a message to a mobile platform via the Channel Bridge.

        message_type: 'ack', 'status', 'response', 'error'

        Returns the posted message_id if successful, None otherwise.
        """
        try:
            client = await self._get_client()
            payload = {
                "platform": platform,
                "sender_id": sender_id,
                "message_type": message_type,
                "content": content,
            }
            if thread_id:
                payload["thread_id"] = thread_id

            response = await client.post(
                f"{self._channel_bridge_url}/outbound",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("message_id")
        except httpx.HTTPError as e:
            logger.warning(f"Failed to relay message to {platform}/{sender_id}: {e}")
            return None

    async def relay_acknowledgment(
        self, platform: str, sender_id: str, thread_id: Optional[str] = None
    ) -> Optional[str]:
        """Send acknowledgment that message was received.

        Note: The channel-bridge now handles acknowledgment via a checkmark
        reaction instead of a text message. This method is kept for backward
        compatibility but is no longer called by default.
        """
        return await self.relay_to_platform(
            platform, sender_id, "ack", "Got it, thinking...", thread_id
        )

    async def relay_tool_status(
        self,
        platform: str,
        sender_id: str,
        tool_name: str,
        thread_id: Optional[str] = None,
    ) -> Optional[str]:
        """Send tool execution status update."""
        # Convert tool name to friendly text
        friendly = tool_name.replace("_", " ").title()
        return await self.relay_to_platform(
            platform, sender_id, "status", f"Using {friendly}...", thread_id
        )

    async def relay_response(
        self,
        platform: str,
        sender_id: str,
        response_text: str,
        thread_id: Optional[str] = None,
    ) -> Optional[str]:
        """Send final AI response."""
        return await self.relay_to_platform(
            platform, sender_id, "response", response_text, thread_id
        )

    async def relay_error(
        self, platform: str, sender_id: str, error: str, thread_id: Optional[str] = None
    ) -> Optional[str]:
        """Send error message."""
        return await self.relay_to_platform(
            platform, sender_id, "error", f"Error: {error}", thread_id
        )

    async def relay_typing(
        self, platform: str, thread_id: Optional[str] = None
    ) -> bool:
        """Send typing indicator to a platform thread via the bridge."""
        if not thread_id:
            return False
        try:
            client = await self._get_client()
            response = await client.post(
                f"{self._channel_bridge_url}/outbound/typing",
                json={"platform": platform, "thread_id": thread_id},
            )
            response.raise_for_status()
            return True
        except httpx.HTTPError as e:
            logger.debug(f"Failed to send typing indicator to {platform}: {e}")
            return False

    async def relay_edit_message(
        self,
        platform: str,
        thread_id: str,
        message_id: str,
        content: str,
    ) -> bool:
        """Edit an existing message on a platform via the bridge."""
        try:
            client = await self._get_client()
            response = await client.post(
                f"{self._channel_bridge_url}/outbound/edit",
                json={
                    "platform": platform,
                    "thread_id": thread_id,
                    "message_id": message_id,
                    "content": content,
                },
            )
            response.raise_for_status()
            return True
        except httpx.HTTPError as e:
            logger.debug(f"Failed to edit message on {platform}: {e}")
            return False

    # =========================================================================
    # Startup / Restore
    # =========================================================================

    def restore_sessions_from_db(self) -> int:
        """
        Restore mobile tab tracking from database on startup.

        Returns count of restored sessions.
        """
        sessions = db.get_all_mobile_sessions()
        count = 0

        for session in sessions:
            tab_id = session["tab_id"]
            platform = session["platform"]
            sender_id = session["sender_id"]
            canonical_id = canonical_sender_id(platform, sender_id)
            self._mobile_tabs[tab_id] = (platform, canonical_id, None)
            count += 1

        if count > 0:
            logger.info(f"Restored {count} mobile session(s) from database")

        return count

    def cleanup_expired_codes(self) -> int:
        """Clean up expired pairing codes. Returns count deleted."""
        return db.cleanup_expired_pairing_codes()

    # =========================================================================
    # Broadcast Event Relay (called by connection.py hook)
    # =========================================================================

    async def handle_broadcast_event(
        self, message_type: str, content: Any, tab_id: Optional[str]
    ) -> None:
        """
        Handle a broadcast event and relay to mobile platform if applicable.

        This is called by the mobile relay hook in connection.py for EVERY
        broadcast. We filter to only relay events for mobile-originated tabs.

        Events we relay:
        - response_chunk: Streaming AI response (post+edit pattern)
        - response_complete: Final AI response
        - tool_call: Tool execution status (only 'calling' status)
        - error: Error messages

        Events we skip:
        - thinking_chunk/thinking_complete: Internal reasoning
        - token_usage: Stats not useful for mobile
        - queue_updated: Internal state
        """
        if tab_id is None:
            return

        # Check if this tab is mobile-originated
        mobile_info = self.get_mobile_tab_info(tab_id)
        if mobile_info is None:
            return

        platform, sender_id, thread_id = mobile_info

        # Route based on message type
        if message_type == "response_chunk":
            # Stream chunk to mobile platform using post+edit pattern
            await self._handle_streaming_chunk(tab_id, platform, sender_id, thread_id, content)

        elif message_type == "response_complete":
            # Send final edit with complete text, then clean up streaming state
            await self._finalize_streaming(tab_id, platform, sender_id, thread_id)

        elif message_type == "tool_call":
            # Relay tool status updates
            if isinstance(content, dict):
                tool_name = content.get("name", "tool")
                status = content.get("status", "")
                if status == "calling":
                    await self.relay_tool_status(platform, sender_id, tool_name, thread_id)
                elif status == "complete":
                    result = content.get("result", "")
                    # Send a brief result summary
                    result_text = str(result) if result else ""
                    if len(result_text) > 200:
                        result_text = result_text[:200] + "..."
                    if result_text:
                        friendly = tool_name.replace("_", " ").title()
                        await self.relay_to_platform(
                            platform, sender_id, "status",
                            f"\u2705 {friendly}: {result_text}", thread_id
                        )

        elif message_type == "error":
            # Relay errors and clean up any streaming state
            self._streaming_state.pop(tab_id, None)
            error_text = content if isinstance(content, str) else str(content)
            await self.relay_error(platform, sender_id, error_text, thread_id)

    async def _handle_streaming_chunk(
        self,
        tab_id: str,
        platform: str,
        sender_id: str,
        thread_id: Optional[str],
        content: Any,
    ) -> None:
        """Handle a streaming response chunk with post+edit pattern.

        On the first chunk, post an initial message and store its ID.
        On subsequent chunks, accumulate text and edit the posted message.
        Also refreshes typing indicator every ~5 seconds.
        """
        import time as _time

        chunk_text = content if isinstance(content, str) else str(content)
        now = _time.time()

        state = self._streaming_state.get(tab_id)

        if state is None:
            # First chunk — post initial message and capture the message ID
            state = {
                "accumulated_text": chunk_text,
                "last_edit_time": now,
                "last_typing_time": now,
                "platform": platform,
                "sender_id": sender_id,
                "thread_id": thread_id,
                "posted_message_id": None,
            }
            self._streaming_state[tab_id] = state

            # Post the initial message and capture the returned message ID
            sanitized = self._sanitize_for_platform(chunk_text, platform)
            message_id = await self.relay_to_platform(
                platform, sender_id, "response", sanitized, thread_id
            )
            if message_id:
                state["posted_message_id"] = message_id
                logger.debug(f"Streaming started for {tab_id}, posted message {message_id}")
            else:
                # Failed to post initial message, clean up
                self._streaming_state.pop(tab_id, None)
            return

        # Accumulate text
        state["accumulated_text"] += chunk_text

        # Refresh typing indicator every 5 seconds
        if now - state["last_typing_time"] >= 5.0:
            await self.relay_typing(platform, thread_id)
            state["last_typing_time"] = now

        # Edit the posted message every ~1 second
        time_since_edit = now - state["last_edit_time"]
        if time_since_edit >= 1.0 and state["posted_message_id"] and thread_id:
            sanitized = self._sanitize_for_platform(state["accumulated_text"], platform)
            await self.relay_edit_message(
                platform, thread_id, state["posted_message_id"], sanitized
            )
            state["last_edit_time"] = now

    async def _finalize_streaming(
        self,
        tab_id: str,
        platform: str,
        sender_id: str,
        thread_id: Optional[str],
    ) -> None:
        """Finalize streaming by editing the message with the complete response.

        If streaming was active, sends a final edit.
        Falls back to _relay_final_response if no streaming state exists.
        """
        state = self._streaming_state.pop(tab_id, None)

        if state is not None and state.get("posted_message_id") and thread_id:
            # Streaming was active — send final edit with complete text from chat history
            from ..chat.tab_manager_instance import tab_manager

            tab_session = tab_manager.get_session(tab_id)
            if tab_session and tab_session.state.chat_history:
                # Get the last assistant message for the final text
                response_text = ""
                for msg in reversed(tab_session.state.chat_history):
                    if msg.get("role") == "assistant":
                        content = msg.get("content", "")
                        if isinstance(content, str):
                            response_text = content
                        elif isinstance(content, list):
                            text_parts = []
                            for part in content:
                                if isinstance(part, dict) and part.get("type") == "text":
                                    text_parts.append(part.get("text", ""))
                                elif isinstance(part, str):
                                    text_parts.append(part)
                            response_text = "\n".join(text_parts)
                        break

                if response_text:
                    sanitized = self._sanitize_for_platform(response_text, platform)
                    await self.relay_edit_message(
                        platform, thread_id, state["posted_message_id"], sanitized
                    )
                    return

        # No streaming state or no message ID — fall back to posting full response
        await self._relay_final_response(platform, sender_id, tab_id, thread_id)

    async def _relay_final_response(
        self,
        platform: str,
        sender_id: str,
        tab_id: str,
        thread_id: Optional[str] = None,
    ) -> None:
        """
        Relay the final response for a completed generation.

        We need to get the actual response text from the conversation history,
        since response_complete doesn't include the content.
        """
        from ..chat.tab_manager_instance import tab_manager

        tab_session = tab_manager.get_session(tab_id)
        if not tab_session:
            return

        # Get the last assistant message from chat history
        state = tab_session.state
        if not state.chat_history:
            return

        # Find the last assistant message
        response_text = ""
        for msg in reversed(state.chat_history):
            if msg.get("role") == "assistant":
                content = msg.get("content", "")
                if isinstance(content, str):
                    response_text = content
                elif isinstance(content, list):
                    # Handle multi-part content
                    text_parts = []
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            text_parts.append(part.get("text", ""))
                        elif isinstance(part, str):
                            text_parts.append(part)
                    response_text = "\n".join(text_parts)
                break

        if response_text:
            # Sanitize for platform (strip excessive markdown, etc.)
            sanitized = self._sanitize_for_platform(response_text, platform)
            await self.relay_response(platform, sender_id, sanitized, thread_id)

    def _sanitize_for_platform(self, text: str, platform: str) -> str:
        """
        Sanitize response text for a specific platform.

        - Telegram: Supports basic markdown (bold, italic, code)
        - Discord: Supports full markdown
        - WhatsApp: Limited formatting, strip most markdown
        """
        # For now, just return as-is. Platform-specific sanitization
        # can be added later based on needs.
        #
        # Potential sanitizations:
        # - Strip HTML tags
        # - Convert code blocks to inline code on WhatsApp
        # - Truncate very long messages (Telegram has 4096 char limit)

        # Basic truncation for all platforms (most have limits around 4000-8000)
        max_length = 4000
        if len(text) > max_length:
            text = text[: max_length - 100] + "\n\n[Message truncated due to length]"

        return text

    def register_relay_callback(self) -> None:
        """
        Register the broadcast relay callback with the connection manager.

        Should be called once on startup after the service is initialized.
        """
        from ...core.connection import set_mobile_relay_callback

        set_mobile_relay_callback(self.handle_broadcast_event)
        logger.info("Mobile relay callback registered")

    def unregister_relay_callback(self) -> None:
        """Unregister the broadcast relay callback."""
        from ...core.connection import set_mobile_relay_callback

        set_mobile_relay_callback(None)


# Global singleton
mobile_channel_service = MobileChannelService()
