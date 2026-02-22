"""
Terminal API endpoints.

Provides REST endpoints for terminal-related operations:
- Get/set ask level
- Get approval count
- Clear approval history
- Get terminal settings
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Literal

from ..services.terminal import terminal_service
from ..services.approval_history import get_approval_count, clear_approvals


router = APIRouter(prefix="/api/terminal")


class AskLevelRequest(BaseModel):
    level: Literal['always', 'on-miss', 'off']


@router.get("/settings")
async def get_terminal_settings():
    """Get current terminal settings."""
    return {
        "ask_level": terminal_service.ask_level,
        "session_mode": terminal_service.session_mode,
        "approval_count": get_approval_count(),
    }


@router.put("/settings/ask-level")
async def set_ask_level(request: AskLevelRequest):
    """Set the terminal ask level."""
    if request.level not in ("always", "on-miss", "off"):
        raise HTTPException(status_code=400, detail="Invalid ask level. Must be 'always', 'on-miss', or 'off'")

    terminal_service.ask_level = request.level
    return {"ask_level": terminal_service.ask_level}


@router.delete("/approvals")
async def clear_approval_history():
    """Clear all remembered command approvals."""
    clear_approvals()
    return {"cleared": True, "approval_count": 0}
