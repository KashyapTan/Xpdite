"""
Internal Mobile Channel HTTP API.

These endpoints are called by the Channel Bridge (TypeScript) service,
NOT by external clients. They handle:
- Message submission from mobile platforms
- Command execution (/new, /stop, /model, etc.)
- Pairing code verification
- Paired device management

All endpoints are under /internal/mobile to clearly distinguish them
from the public /api endpoints.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/internal/mobile")


# ============================================
# Request/Response Models
# ============================================


class MessageSubmission(BaseModel):
    """Request body for submitting a message from mobile."""

    platform: str
    sender_id: str
    message_text: str
    thread_id: Optional[str] = None


class CommandExecution(BaseModel):
    """Request body for executing a slash command."""

    platform: str
    sender_id: str
    command: str
    args: Optional[str] = None
    thread_id: Optional[str] = None


class PairingVerification(BaseModel):
    """Request body for verifying a pairing code."""

    platform: str
    sender_id: str
    display_name: Optional[str] = None
    code: str


class PairingCodeGeneration(BaseModel):
    """Request body for generating a pairing code."""

    expires_in_seconds: int = 600


class DeviceRevocation(BaseModel):
    """Request body for revoking a paired device."""

    device_id: int


class PairingCheck(BaseModel):
    """Request body for checking if a user is paired."""

    platform: str
    sender_id: str


class WhatsAppConnectionUpdate(BaseModel):
    """Request body for WhatsApp device connection status updates."""

    status: str  # "connected" or "disconnected"
    bot_user_id: Optional[str] = None  # WhatsApp JID when connected


# ============================================
# Message Endpoints
# ============================================


@router.post("/message")
async def submit_message(body: MessageSubmission):
    """
    Submit a message from a mobile platform.

    Called by Channel Bridge when a user sends a chat message (not a command).
    Looks up or creates a session, queues the message, returns immediately.
    """
    from ..services.mobile_channel import mobile_channel_service

    success, message, tab_id = await mobile_channel_service.handle_message(
        platform=body.platform,
        sender_id=body.sender_id,
        message_text=body.message_text,
        thread_id=body.thread_id,
    )

    if not success:
        # Not an HTTP error - just return the message for Channel Bridge to relay
        return {
            "success": False,
            "message": message,
            "tab_id": None,
        }

    return {
        "success": True,
        "message": message,
        "tab_id": tab_id,
    }


@router.post("/command")
async def execute_command(body: CommandExecution):
    """
    Execute a slash command from a mobile platform.

    Commands: /new, /stop, /status, /model, /help, /pair
    Returns the response text to send back to the user.
    """
    from ..services.mobile_channel import mobile_channel_service

    response_text = await mobile_channel_service.handle_command(
        platform=body.platform,
        sender_id=body.sender_id,
        command=body.command,
        args=body.args,
        thread_id=body.thread_id,
    )

    return {
        "response": response_text,
    }


# ============================================
# Pairing Endpoints
# ============================================


@router.post("/pair/verify")
async def verify_pairing(body: PairingVerification):
    """
    Verify a pairing code and create device pairing.

    Called by Channel Bridge when user sends /pair <code>.
    """
    from ..services.mobile_channel import mobile_channel_service

    success, message = mobile_channel_service.verify_pairing_code(
        platform=body.platform,
        sender_id=body.sender_id,
        display_name=body.display_name,
        code=body.code,
    )

    return {
        "success": success,
        "message": message,
    }


@router.post("/pair/check")
async def check_pairing(body: PairingCheck):
    """
    Check if a user is paired with this Xpdite instance.

    Called by Channel Bridge to determine if user needs to pair first.
    """
    from ..services.mobile_channel import mobile_channel_service

    is_paired = mobile_channel_service.is_paired(
        platform=body.platform,
        sender_id=body.sender_id,
    )

    return {
        "paired": is_paired,
    }


@router.post("/pair/generate")
async def generate_pairing_code(body: PairingCodeGeneration):
    """
    Generate a new pairing code.

    Called by the Settings UI to display a code for the user.
    """
    from ..services.mobile_channel import mobile_channel_service

    code = mobile_channel_service.generate_pairing_code(
        expires_in_seconds=body.expires_in_seconds
    )

    return {
        "code": code,
        "expires_in_seconds": body.expires_in_seconds,
    }


@router.get("/devices")
async def get_paired_devices():
    """
    Get all paired devices.

    Called by Settings UI to display paired devices.
    """
    from ..services.mobile_channel import mobile_channel_service

    devices = mobile_channel_service.get_all_paired_devices()

    return {
        "devices": devices,
    }


@router.delete("/devices/{device_id}")
async def revoke_device(device_id: int):
    """
    Revoke a paired device.

    Called by Settings UI when user removes a device.
    """
    from ..services.mobile_channel import mobile_channel_service

    mobile_channel_service.revoke_device(device_id)

    return {
        "success": True,
    }


# ============================================
# WhatsApp Connection Status
# ============================================


@router.post("/whatsapp/connection")
async def update_whatsapp_connection(body: WhatsAppConnectionUpdate):
    """
    Update WhatsApp device connection status.

    Called by Channel Bridge when WhatsApp connects or disconnects.
    When connected successfully, resets the forcePairing flag.
    """
    import json
    import logging

    from ..database import db

    logger = logging.getLogger(__name__)

    if body.status == "connected":
        # Reset forcePairing flag since pairing succeeded
        existing_raw = db.get_setting("mobile_channel_whatsapp")
        if existing_raw:
            try:
                existing = json.loads(existing_raw)
                if existing.get("forcePairing"):
                    existing["forcePairing"] = False
                    db.set_setting("mobile_channel_whatsapp", json.dumps(existing))
                    logger.info(
                        "Reset WhatsApp forcePairing flag after successful connection"
                    )

                    # Rewrite config file so Channel Bridge picks up the change
                    from .http import _write_mobile_channels_config_file

                    _write_mobile_channels_config_file()
            except Exception as e:
                logger.error(f"Error updating WhatsApp config: {e}")

    return {
        "success": True,
        "status": body.status,
    }


# ============================================
# Session Endpoints
# ============================================


@router.get("/sessions")
async def get_all_sessions():
    """
    Get all active mobile sessions.

    Called by Settings UI to display active sessions.
    """
    from ..database import db

    sessions = db.get_all_mobile_sessions()

    return {
        "sessions": sessions,
    }


@router.get("/session/{platform}/{sender_id}")
async def get_session(platform: str, sender_id: str):
    """
    Get a specific mobile session.
    """
    from ..services.mobile_channel import mobile_channel_service

    session = mobile_channel_service.get_session(platform, sender_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        "session": session,
    }


@router.delete("/session/{platform}/{sender_id}")
async def end_session(platform: str, sender_id: str):
    """
    End a mobile session.
    """
    from ..services.mobile_channel import mobile_channel_service

    success = mobile_channel_service.end_session(platform, sender_id)

    if not success:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        "success": True,
    }


# ============================================
# Health & Maintenance
# ============================================


@router.get("/health")
async def health_check():
    """
    Health check for Channel Bridge to verify Python backend is reachable.
    """
    return {
        "status": "ok",
    }


@router.post("/cleanup")
async def cleanup_expired():
    """
    Clean up expired pairing codes.

    Can be called periodically by Channel Bridge or by a scheduled task.
    """
    from ..services.mobile_channel import mobile_channel_service

    deleted_count = mobile_channel_service.cleanup_expired_codes()

    return {
        "deleted_codes": deleted_count,
    }
