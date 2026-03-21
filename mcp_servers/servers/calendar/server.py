"""
Google Calendar MCP Server.

Provides Google Calendar tools for the LLM to view, create, update, and
manage calendar events via the user's connected Google account.

Authentication is handled by the main app's OAuth flow. This server reads
the stored token from GOOGLE_TOKEN_FILE environment variable.
"""

import os
import json
import time
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from mcp.server.fastmcp import FastMCP
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from mcp_servers.servers.calendar.calander_descriptions import (
    GET_EVENTS_DESCRIPTION,
    SEARCH_EVENTS_DESCRIPTION,
    GET_EVENT_DESCRIPTION,
    CREATE_EVENT_DESCRIPTION,
    UPDATE_EVENT_DESCRIPTION,
    DELETE_EVENT_DESCRIPTION,
    QUICK_ADD_EVENT_DESCRIPTION,
    LIST_CALENDARS_DESCRIPTION,
    GET_FREE_BUSY_DESCRIPTION,
)

mcp = FastMCP("Google Calendar Tools")

# Token path from environment or default
TOKEN_FILE = os.environ.get("GOOGLE_TOKEN_FILE", "user_data/google/token.json")

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
]

# ── Service singleton caching ──────────────────────────────────────────────
_calendar_service_cache: Any = None
_calendar_service_cache_time: float = 0.0
_calendar_service_cache_ttl: float = 1800.0  # 30 minutes
_calendar_service_lock = threading.Lock()


def _get_calendar_service():
    """Build and return an authenticated Google Calendar API service with caching.

    Reuses the service object for 30 minutes to avoid rebuilding on every call.
    Token refresh is checked and performed only when actually expired.
    Uses threading lock to prevent race conditions during initialization.
    """
    global _calendar_service_cache, _calendar_service_cache_time

    current_time = time.time()

    # Quick check without lock (common path)
    if _calendar_service_cache is not None and (current_time - _calendar_service_cache_time) < _calendar_service_cache_ttl:
        return _calendar_service_cache

    # Acquire lock for cache miss
    with _calendar_service_lock:
        # Double-check pattern: re-verify after acquiring lock
        current_time = time.time()
        if _calendar_service_cache is not None and (current_time - _calendar_service_cache_time) < _calendar_service_cache_ttl:
            return _calendar_service_cache

        if not os.path.exists(TOKEN_FILE):
            raise RuntimeError(
                "Google account not connected. Please connect your Google account in Settings > Connections."
            )

        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

        # Refresh only if actually expired
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                with open(TOKEN_FILE, "w") as f:
                    f.write(creds.to_json())
            except Exception:
                # Invalidate cache on refresh failure
                _calendar_service_cache = None
                raise RuntimeError(
                    "Google authentication expired. Please reconnect your Google account in Settings > Connections."
                )

        if not creds or not creds.valid:
            _calendar_service_cache = None
            raise RuntimeError(
                "Google authentication expired. Please reconnect your Google account in Settings > Connections."
            )

        # Build and cache the service
        _calendar_service_cache = build("calendar", "v3", credentials=creds)
        _calendar_service_cache_time = current_time
        return _calendar_service_cache


def _format_event(event: dict) -> dict:
    """Format a Google Calendar event into a clean dict."""
    start = event.get("start", {})
    end = event.get("end", {})

    # Handle all-day events (date) vs timed events (dateTime)
    start_time = start.get("dateTime", start.get("date", ""))
    end_time = end.get("dateTime", end.get("date", ""))

    attendees = []
    for a in event.get("attendees", []):
        attendees.append(
            {
                "email": a.get("email", ""),
                "name": a.get("displayName", ""),
                "status": a.get("responseStatus", ""),
            }
        )

    result = {
        "id": event.get("id", ""),
        "title": event.get("summary", "(No Title)"),
        "start": start_time,
        "end": end_time,
        "location": event.get("location", ""),
        "description": event.get("description", ""),
        "status": event.get("status", ""),
        "link": event.get("htmlLink", ""),
    }

    if attendees:
        result["attendees"] = attendees

    # Conference/meet link
    conference = event.get("conferenceData", {})
    entry_points = conference.get("entryPoints", [])
    for ep in entry_points:
        if ep.get("entryPointType") == "video":
            result["meet_link"] = ep.get("uri", "")
            break

    # Recurrence
    if event.get("recurrence"):
        result["recurrence"] = event["recurrence"]

    return result


# ── TOOLS ──────────────────────────────────────────────────────────────


@mcp.tool(description=GET_EVENTS_DESCRIPTION)
def get_events(
    days_ahead: int = 7,
    max_results: int = 20,
    calendar_id: str = "primary",
) -> str:
    """Get upcoming events for the next N days."""
    try:
        service = _get_calendar_service()

        now = datetime.now(tz=timezone.utc).isoformat()
        end = (datetime.now(tz=timezone.utc) + timedelta(days=days_ahead)).isoformat()

        events_result = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=now,
                timeMax=end,
                maxResults=min(max_results, 100),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )

        events = events_result.get("items", [])

        if not events:
            return json.dumps(
                {
                    "message": f"No events found in the next {days_ahead} day(s)",
                    "count": 0,
                }
            )

        event_list = [_format_event(e) for e in events]

        return json.dumps(
            {
                "events": event_list,
                "count": len(event_list),
                "period": f"Next {days_ahead} day(s)",
            },
            indent=2,
        )

    except Exception as e:
        return json.dumps({"error": f"Failed to get events: {str(e)}"})


@mcp.tool(description=SEARCH_EVENTS_DESCRIPTION)
def search_events(
    query: str,
    days_ahead: int = 30,
    calendar_id: str = "primary",
) -> str:
    """Search events by keyword."""
    try:
        service = _get_calendar_service()

        now = datetime.now(tz=timezone.utc).isoformat()
        end = (datetime.now(tz=timezone.utc) + timedelta(days=days_ahead)).isoformat()

        events_result = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=now,
                timeMax=end,
                q=query,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )

        events = events_result.get("items", [])

        if not events:
            return json.dumps(
                {
                    "message": f"No events matching '{query}' in the next {days_ahead} day(s)",
                    "count": 0,
                }
            )

        event_list = [_format_event(e) for e in events]

        return json.dumps(
            {
                "events": event_list,
                "count": len(event_list),
                "query": query,
            },
            indent=2,
        )

    except Exception as e:
        return json.dumps({"error": f"Failed to search events: {str(e)}"})


@mcp.tool(description=GET_EVENT_DESCRIPTION)
def get_event(event_id: str, calendar_id: str = "primary") -> str:
    """Get detailed info about a specific event."""
    try:
        service = _get_calendar_service()

        event = service.events().get(calendarId=calendar_id, eventId=event_id).execute()

        return json.dumps(_format_event(event), indent=2)

    except Exception as e:
        return json.dumps({"error": f"Failed to get event: {str(e)}"})


@mcp.tool(description=CREATE_EVENT_DESCRIPTION)
def create_event(
    title: str,
    start: str,
    end: str,
    description: str = "",
    location: str = "",
    attendees: str = "",
    calendar_id: str = "primary",
) -> str:
    """Create a new calendar event."""
    try:
        service = _get_calendar_service()

        event_body = {
            "summary": title,
        }

        # Determine if this is an all-day event or timed event
        # All-day: "2025-03-15", Timed: "2025-03-15T10:00:00-05:00"
        if "T" in start:
            event_body["start"] = {"dateTime": start}
            event_body["end"] = {"dateTime": end}
        else:
            event_body["start"] = {"date": start}
            event_body["end"] = {"date": end}

        if description:
            event_body["description"] = description
        if location:
            event_body["location"] = location

        # Parse attendees from comma-separated string
        if attendees:
            attendee_list = [
                {"email": email.strip()}
                for email in attendees.split(",")
                if email.strip()
            ]
            if attendee_list:
                event_body["attendees"] = attendee_list

        created = (
            service.events().insert(calendarId=calendar_id, body=event_body).execute()
        )

        return json.dumps(
            {
                "success": True,
                "event_id": created["id"],
                "title": created.get("summary", ""),
                "link": created.get("htmlLink", ""),
                "info": f"Event '{title}' created successfully",
            }
        )

    except Exception as e:
        return json.dumps({"error": f"Failed to create event: {str(e)}"})


@mcp.tool(description=UPDATE_EVENT_DESCRIPTION)
def update_event(
    event_id: str,
    title: str = "",
    start: str = "",
    end: str = "",
    description: str = "",
    location: str = "",
    calendar_id: str = "primary",
) -> str:
    """Update an existing calendar event."""
    try:
        service = _get_calendar_service()

        # Get existing event
        event = service.events().get(calendarId=calendar_id, eventId=event_id).execute()

        # Update only provided fields
        if title:
            event["summary"] = title
        if description:
            event["description"] = description
        if location:
            event["location"] = location
        if start:
            if "T" in start:
                event["start"] = {"dateTime": start}
            else:
                event["start"] = {"date": start}
        if end:
            if "T" in end:
                event["end"] = {"dateTime": end}
            else:
                event["end"] = {"date": end}

        updated = (
            service.events()
            .update(calendarId=calendar_id, eventId=event_id, body=event)
            .execute()
        )

        return json.dumps(
            {
                "success": True,
                "event_id": updated["id"],
                "title": updated.get("summary", ""),
                "link": updated.get("htmlLink", ""),
                "info": f"Event '{updated.get('summary', '')}' updated successfully",
            }
        )

    except Exception as e:
        return json.dumps({"error": f"Failed to update event: {str(e)}"})


@mcp.tool(description=DELETE_EVENT_DESCRIPTION)
def delete_event(event_id: str, calendar_id: str = "primary") -> str:
    """Delete a calendar event."""
    try:
        service = _get_calendar_service()

        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()

        return json.dumps(
            {
                "success": True,
                "info": f"Event {event_id} deleted successfully",
            }
        )

    except Exception as e:
        return json.dumps({"error": f"Failed to delete event: {str(e)}"})


@mcp.tool(description=QUICK_ADD_EVENT_DESCRIPTION)
def quick_add_event(text: str, calendar_id: str = "primary") -> str:
    """Create event from natural language text."""
    try:
        service = _get_calendar_service()

        created = service.events().quickAdd(calendarId=calendar_id, text=text).execute()

        return json.dumps(
            {
                "success": True,
                "event": _format_event(created),
                "info": f"Event created from: '{text}'",
            }
        )

    except Exception as e:
        return json.dumps({"error": f"Failed to quick-add event: {str(e)}"})


@mcp.tool(description=LIST_CALENDARS_DESCRIPTION)
def list_calendars() -> str:
    """List all available calendars."""
    try:
        service = _get_calendar_service()

        calendars_result = service.calendarList().list().execute()
        calendars = calendars_result.get("items", [])

        calendar_list = []
        for cal in calendars:
            calendar_list.append(
                {
                    "id": cal.get("id", ""),
                    "name": cal.get("summary", ""),
                    "description": cal.get("description", ""),
                    "access_role": cal.get("accessRole", ""),
                    "primary": cal.get("primary", False),
                    "color": cal.get("backgroundColor", ""),
                }
            )

        # Sort: primary first, then by name
        calendar_list.sort(key=lambda x: (0 if x["primary"] else 1, x["name"]))

        return json.dumps(
            {
                "calendars": calendar_list,
                "count": len(calendar_list),
            },
            indent=2,
        )

    except Exception as e:
        return json.dumps({"error": f"Failed to list calendars: {str(e)}"})


@mcp.tool(description=GET_FREE_BUSY_DESCRIPTION)
def get_free_busy(
    time_min: str,
    time_max: str,
    calendar_ids: str = "primary",
) -> str:
    """Check free/busy status for a time range."""
    try:
        service = _get_calendar_service()

        # Parse calendar_ids from comma-separated string
        cal_ids = [c.strip() for c in calendar_ids.split(",") if c.strip()]

        body = {
            "timeMin": time_min,
            "timeMax": time_max,
            "items": [{"id": cid} for cid in cal_ids],
        }

        result = service.freebusy().query(body=body).execute()

        calendars = result.get("calendars", {})
        busy_info = {}
        for cal_id, cal_data in calendars.items():
            busy_blocks = cal_data.get("busy", [])
            busy_info[cal_id] = {
                "busy_blocks": busy_blocks,
                "is_free": len(busy_blocks) == 0,
            }

        return json.dumps(
            {
                "time_range": {"start": time_min, "end": time_max},
                "calendars": busy_info,
            },
            indent=2,
        )

    except Exception as e:
        return json.dumps({"error": f"Failed to check free/busy: {str(e)}"})


if __name__ == "__main__":
    mcp.run()
