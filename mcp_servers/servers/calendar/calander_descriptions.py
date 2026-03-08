from mcp_servers.servers.description_format import build_tool_description


GET_EVENTS_DESCRIPTION = build_tool_description(
    purpose="Get upcoming Google Calendar events from the next N days.",
    use_when=(
        "The user wants to browse their schedule by time range, review upcoming "
        "meetings, or get event IDs before inspecting or editing a specific "
        "event."
    ),
    inputs=(
        'days_ahead (default 7), max_results (default 20, capped at 100), '
        'calendar_id (default "primary").'
    ),
    returns=(
        "JSON with events, count, and period. Each event includes id, title, "
        "start, end, location, description, status, link, and may include "
        "attendees, meet_link, or recurrence."
    ),
    notes='Use list_calendars first if the user mentions a non-primary calendar.',
)

SEARCH_EVENTS_DESCRIPTION = build_tool_description(
    purpose="Search upcoming Google Calendar events by keyword.",
    use_when=(
        "The user wants to search upcoming events by keyword, person, topic, "
        "or appointment name and needs matching event IDs."
    ),
    inputs='query, days_ahead (default 30), calendar_id (default "primary").',
    returns=(
        "JSON with matching events and count. Event objects use the same shape "
        "as get_events."
    ),
    notes='Use list_calendars first if the user mentions a non-primary calendar.',
)

GET_EVENT_DESCRIPTION = build_tool_description(
    purpose="Get the full details for one calendar event by event_id.",
    use_when=(
        "You already know the event_id and need complete fields such as attendees, "
        "description, meet link, or recurrence."
    ),
    inputs='event_id, calendar_id (default "primary").',
    returns="JSON for the event with the same fields returned by get_events plus any extra metadata.",
    notes="Usually call get_events or search_events first to find the event_id.",
)

CREATE_EVENT_DESCRIPTION = build_tool_description(
    purpose="Create a new Google Calendar event.",
    use_when=(
        "The user wants to schedule a meeting, appointment, reminder, or time block "
        "with explicit details."
    ),
    inputs=(
        'title, start, end, description (optional), location (optional), '
        'attendees (optional comma-separated email string), calendar_id '
        '(default "primary").'
    ),
    returns="JSON with success, event_id, title, link, and a confirmation message.",
    notes=(
        "Confirm details before creating. Use ISO 8601 for timed events and "
        "YYYY-MM-DD for all-day events."
    ),
)

UPDATE_EVENT_DESCRIPTION = build_tool_description(
    purpose="Update selected fields on an existing Google Calendar event.",
    use_when=(
        "The user wants to reschedule an event or change its title, description, "
        "location, start, or end time."
    ),
    inputs=(
        'event_id, title (optional), start (optional), end (optional), '
        'description (optional), location (optional), calendar_id '
        '(default "primary").'
    ),
    returns="JSON with success, event_id, title, link, and a confirmation message.",
    notes=(
        "Confirm changes before updating. Only supplied fields change. start/end "
        "use the same formats as create_event."
    ),
)

DELETE_EVENT_DESCRIPTION = build_tool_description(
    purpose="Delete a Google Calendar event by event_id.",
    use_when="The user wants to cancel or remove a known calendar event.",
    inputs='event_id, calendar_id (default "primary").',
    returns="JSON with success and a confirmation message.",
    notes="Confirm with the user before deleting. This action cannot be undone.",
)

QUICK_ADD_EVENT_DESCRIPTION = build_tool_description(
    purpose="Create a Google Calendar event from one natural-language text string.",
    use_when=(
        "The user describes an event informally and you want Google to interpret "
        "the time and title for you."
    ),
    inputs='text, calendar_id (default "primary").',
    returns="JSON with success, the created event, and a confirmation message.",
    notes=(
        "Prefer create_event when you already have exact structured start/end "
        "times and want full control."
    ),
)

LIST_CALENDARS_DESCRIPTION = build_tool_description(
    purpose="List the calendars the user can access.",
    use_when=(
        "You need to discover available calendars or find the calendar_id for a "
        "tool call that should not use the primary calendar."
    ),
    inputs="None.",
    returns="JSON with calendars and count. Each calendar includes id, name, description, access_role, primary, and color.",
)

GET_FREE_BUSY_DESCRIPTION = build_tool_description(
    purpose="Check free/busy blocks for one or more calendars in a time range.",
    use_when=(
        "The user asks whether they are free at a given time or needs availability "
        "before scheduling."
    ),
    inputs=(
        'time_min (ISO 8601), time_max (ISO 8601), calendar_ids '
        '(optional comma-separated calendar IDs, default "primary").'
    ),
    returns="JSON with the requested time range and busy blocks for each calendar.",
    notes="Use list_calendars first if you need calendar IDs beyond the primary calendar.",
)
