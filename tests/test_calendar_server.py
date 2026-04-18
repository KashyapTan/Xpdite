import json
from unittest.mock import MagicMock, mock_open, patch

import pytest

from mcp_servers.servers.calendar import server as calendar_server


def _parse_json(payload: str) -> dict:
    return json.loads(payload)


@pytest.fixture(autouse=True)
def reset_calendar_cache(monkeypatch):
    monkeypatch.setattr(calendar_server, "_calendar_service_cache", None)
    monkeypatch.setattr(calendar_server, "_calendar_service_cache_time", 0.0)


def test_get_calendar_service_reuses_cached_service(monkeypatch):
    creds = MagicMock(expired=False, valid=True)
    build_calls: list[tuple] = []

    monkeypatch.setattr(calendar_server.os.path, "exists", lambda _path: True)
    monkeypatch.setattr(
        calendar_server.Credentials,
        "from_authorized_user_file",
        lambda _path, _scopes: creds,
    )
    monkeypatch.setattr(
        calendar_server,
        "build",
        lambda *args, **kwargs: build_calls.append((args, kwargs)) or "service",
    )

    first = calendar_server._get_calendar_service()
    second = calendar_server._get_calendar_service()

    assert first == "service"
    assert second == "service"
    assert len(build_calls) == 1


def test_get_calendar_service_refreshes_expired_token(monkeypatch):
    creds = MagicMock(expired=True, refresh_token="refresh-token", valid=True)
    creds.to_json.return_value = '{"token":"fresh"}'

    monkeypatch.setattr(calendar_server.os.path, "exists", lambda _path: True)
    monkeypatch.setattr(
        calendar_server.Credentials,
        "from_authorized_user_file",
        lambda _path, _scopes: creds,
    )
    monkeypatch.setattr(calendar_server, "build", lambda *_args, **_kwargs: "service")

    with patch("builtins.open", mock_open()) as mocked_open:
        service = calendar_server._get_calendar_service()

    assert service == "service"
    creds.refresh.assert_called_once()
    mocked_open.assert_called_once_with(calendar_server.TOKEN_FILE, "w")


def test_get_calendar_service_refresh_failure_requires_reconnect(monkeypatch):
    creds = MagicMock(expired=True, refresh_token="refresh-token", valid=False)
    creds.refresh.side_effect = Exception("token refresh failed")

    monkeypatch.setattr(calendar_server.os.path, "exists", lambda _path: True)
    monkeypatch.setattr(
        calendar_server.Credentials,
        "from_authorized_user_file",
        lambda _path, _scopes: creds,
    )

    with pytest.raises(RuntimeError, match="Google authentication expired"):
        calendar_server._get_calendar_service()

    assert calendar_server._calendar_service_cache is None


def test_get_calendar_service_requires_existing_token_file(monkeypatch):
    monkeypatch.setattr(calendar_server.os.path, "exists", lambda _path: False)

    with pytest.raises(RuntimeError, match="Google account not connected"):
        calendar_server._get_calendar_service()


def test_format_event_includes_optional_fields():
    formatted = calendar_server._format_event(
        {
            "id": "evt-1",
            "summary": "Planning",
            "start": {"dateTime": "2026-04-18T09:00:00Z"},
            "end": {"dateTime": "2026-04-18T10:00:00Z"},
            "location": "Room 12",
            "description": "Weekly sync",
            "status": "confirmed",
            "htmlLink": "https://calendar.google.com/event?eid=1",
            "attendees": [
                {
                    "email": "user@example.com",
                    "displayName": "User",
                    "responseStatus": "accepted",
                }
            ],
            "conferenceData": {
                "entryPoints": [
                    {
                        "entryPointType": "video",
                        "uri": "https://meet.google.com/abc-defg-hij",
                    }
                ]
            },
            "recurrence": ["RRULE:FREQ=WEEKLY"],
        }
    )

    assert formatted["title"] == "Planning"
    assert formatted["attendees"] == [
        {
            "email": "user@example.com",
            "name": "User",
            "status": "accepted",
        }
    ]
    assert formatted["meet_link"] == "https://meet.google.com/abc-defg-hij"
    assert formatted["recurrence"] == ["RRULE:FREQ=WEEKLY"]


def test_get_events_returns_empty_message(monkeypatch):
    service = MagicMock()
    service.events.return_value.list.return_value.execute.return_value = {"items": []}
    monkeypatch.setattr(calendar_server, "_get_calendar_service", lambda: service)

    payload = _parse_json(calendar_server.get_events(days_ahead=3))

    assert payload["count"] == 0
    assert "No events found" in payload["message"]


def test_get_events_caps_max_results_and_formats_events(monkeypatch):
    service = MagicMock()
    service.events.return_value.list.return_value.execute.return_value = {
        "items": [
            {
                "id": "evt-1",
                "summary": "Demo",
                "start": {"date": "2026-04-18"},
                "end": {"date": "2026-04-19"},
            }
        ]
    }
    monkeypatch.setattr(calendar_server, "_get_calendar_service", lambda: service)

    payload = _parse_json(calendar_server.get_events(days_ahead=5, max_results=999))

    assert payload["count"] == 1
    assert payload["events"][0]["title"] == "Demo"
    assert (
        service.events.return_value.list.call_args.kwargs["maxResults"] == 100
    )


def test_search_events_returns_matches(monkeypatch):
    service = MagicMock()
    service.events.return_value.list.return_value.execute.return_value = {
        "items": [
            {
                "id": "evt-1",
                "summary": "Standup",
                "start": {"dateTime": "2026-04-18T09:00:00Z"},
                "end": {"dateTime": "2026-04-18T09:15:00Z"},
            }
        ]
    }
    monkeypatch.setattr(calendar_server, "_get_calendar_service", lambda: service)

    payload = _parse_json(calendar_server.search_events("standup"))

    assert payload["query"] == "standup"
    assert payload["events"][0]["title"] == "Standup"


def test_get_event_returns_formatted_event(monkeypatch):
    service = MagicMock()
    service.events.return_value.get.return_value.execute.return_value = {
        "id": "evt-2",
        "summary": "Review",
        "start": {"dateTime": "2026-04-18T11:00:00Z"},
        "end": {"dateTime": "2026-04-18T12:00:00Z"},
    }
    monkeypatch.setattr(calendar_server, "_get_calendar_service", lambda: service)

    payload = _parse_json(calendar_server.get_event("evt-2"))

    assert payload["id"] == "evt-2"
    assert payload["title"] == "Review"


def test_create_event_builds_timed_event_with_attendees(monkeypatch):
    service = MagicMock()
    service.events.return_value.insert.return_value.execute.return_value = {
        "id": "evt-3",
        "summary": "Interview",
        "htmlLink": "https://calendar.google.com/event?eid=3",
    }
    monkeypatch.setattr(calendar_server, "_get_calendar_service", lambda: service)

    payload = _parse_json(
        calendar_server.create_event(
            title="Interview",
            start="2026-04-18T13:00:00Z",
            end="2026-04-18T14:00:00Z",
            description="Panel interview",
            location="Meet",
            attendees="a@example.com, b@example.com",
        )
    )

    body = service.events.return_value.insert.call_args.kwargs["body"]
    assert body["start"] == {"dateTime": "2026-04-18T13:00:00Z"}
    assert body["attendees"] == [
        {"email": "a@example.com"},
        {"email": "b@example.com"},
    ]
    assert payload["success"] is True


def test_create_event_supports_all_day_events(monkeypatch):
    service = MagicMock()
    service.events.return_value.insert.return_value.execute.return_value = {
        "id": "evt-4",
        "summary": "Holiday",
        "htmlLink": "",
    }
    monkeypatch.setattr(calendar_server, "_get_calendar_service", lambda: service)

    calendar_server.create_event(
        title="Holiday",
        start="2026-12-25",
        end="2026-12-26",
    )

    body = service.events.return_value.insert.call_args.kwargs["body"]
    assert body["start"] == {"date": "2026-12-25"}
    assert body["end"] == {"date": "2026-12-26"}


def test_update_event_only_changes_supplied_fields(monkeypatch):
    service = MagicMock()
    existing = {
        "id": "evt-5",
        "summary": "Lunch",
        "start": {"dateTime": "2026-04-18T12:00:00Z"},
        "end": {"dateTime": "2026-04-18T13:00:00Z"},
        "location": "Old room",
    }
    service.events.return_value.get.return_value.execute.return_value = existing
    service.events.return_value.update.return_value.execute.return_value = {
        "id": "evt-5",
        "summary": "Updated Lunch",
        "htmlLink": "https://calendar.google.com/event?eid=5",
    }
    monkeypatch.setattr(calendar_server, "_get_calendar_service", lambda: service)

    payload = _parse_json(
        calendar_server.update_event(
            "evt-5",
            title="Updated Lunch",
            start="2026-04-18",
            end="2026-04-19",
            location="New room",
        )
    )

    update_body = service.events.return_value.update.call_args.kwargs["body"]
    assert update_body["summary"] == "Updated Lunch"
    assert update_body["start"] == {"date": "2026-04-18"}
    assert update_body["end"] == {"date": "2026-04-19"}
    assert update_body["location"] == "New room"
    assert payload["success"] is True


def test_delete_event_returns_success(monkeypatch):
    service = MagicMock()
    service.events.return_value.delete.return_value.execute.return_value = {}
    monkeypatch.setattr(calendar_server, "_get_calendar_service", lambda: service)

    payload = _parse_json(calendar_server.delete_event("evt-6"))

    assert payload == {"success": True, "info": "Event evt-6 deleted successfully"}


def test_quick_add_event_returns_formatted_event(monkeypatch):
    service = MagicMock()
    service.events.return_value.quickAdd.return_value.execute.return_value = {
        "id": "evt-7",
        "summary": "Dinner",
        "start": {"dateTime": "2026-04-18T18:00:00Z"},
        "end": {"dateTime": "2026-04-18T19:00:00Z"},
    }
    monkeypatch.setattr(calendar_server, "_get_calendar_service", lambda: service)

    payload = _parse_json(calendar_server.quick_add_event("Dinner tomorrow at 6pm"))

    assert payload["success"] is True
    assert payload["event"]["title"] == "Dinner"


def test_list_calendars_sorts_primary_first(monkeypatch):
    service = MagicMock()
    service.calendarList.return_value.list.return_value.execute.return_value = {
        "items": [
            {"id": "work", "summary": "Work", "accessRole": "owner"},
            {
                "id": "primary",
                "summary": "Personal",
                "accessRole": "owner",
                "primary": True,
            },
        ]
    }
    monkeypatch.setattr(calendar_server, "_get_calendar_service", lambda: service)

    payload = _parse_json(calendar_server.list_calendars())

    assert [item["id"] for item in payload["calendars"]] == ["primary", "work"]


def test_get_free_busy_parses_multiple_calendar_ids(monkeypatch):
    service = MagicMock()
    service.freebusy.return_value.query.return_value.execute.return_value = {
        "calendars": {
            "primary": {"busy": []},
            "team": {"busy": [{"start": "a", "end": "b"}]},
        }
    }
    monkeypatch.setattr(calendar_server, "_get_calendar_service", lambda: service)

    payload = _parse_json(
        calendar_server.get_free_busy(
            "2026-04-18T00:00:00Z",
            "2026-04-18T23:59:59Z",
            calendar_ids="primary, team",
        )
    )

    assert payload["calendars"]["primary"]["is_free"] is True
    assert payload["calendars"]["team"]["is_free"] is False
