from mcp_servers.servers.description_format import build_tool_description


SEARCH_EMAILS_DESCRIPTION = build_tool_description(
    purpose="Search Gmail messages with Gmail query syntax.",
    use_when=(
        "You need to find candidate emails by sender, subject, keyword, label, "
        "date range, or status, or you want a quick unread list before reading "
        "or acting on one."
    ),
    inputs='query (default "is:unread"), max_results (default 10, capped at 50).',
    returns=(
        "JSON with emails and count. Each email includes id, threadId, subject, "
        "from, date, snippet, and labels."
    ),
    notes="Useful query operators include from:, subject:, is:unread, has:attachment, after:, before:, in:, and label:.",
)

READ_EMAIL_DESCRIPTION = build_tool_description(
    purpose="Read one Gmail message by message_id.",
    use_when=(
        "You already found a relevant message and need the full body, headers, "
        "labels, or attachment names."
    ),
    inputs="message_id.",
    returns=(
        "JSON with id, threadId, subject, from, to, cc, date, body, labels, "
        "and attachments."
    ),
    notes="Usually call search_emails first to get the message_id.",
)

SEND_EMAIL_DESCRIPTION = build_tool_description(
    purpose="Send a new plain-text email from the user's Gmail account.",
    use_when=(
        "The user wants to send a fresh email and has approved the recipients "
        "and content."
    ),
    inputs=(
        "to, subject, body, cc (optional comma-separated addresses), bcc "
        "(optional comma-separated addresses)."
    ),
    returns="JSON with success, message_id, thread_id, and a confirmation message.",
    notes=(
        "Confirm the recipient list and message content before sending. The "
        "email is sent immediately and cannot be recalled."
    ),
)

REPLY_TO_EMAIL_DESCRIPTION = build_tool_description(
    purpose="Reply to an existing Gmail message thread.",
    use_when=(
        "The user wants to answer a message and you already know which email "
        "the reply should attach to."
    ),
    inputs="message_id, body.",
    returns="JSON with success, message_id, thread_id, and a confirmation message.",
    notes="Call search_emails or read_email first to find the message_id, and confirm the reply before sending.",
)

CREATE_DRAFT_DESCRIPTION = build_tool_description(
    purpose="Create a Gmail draft without sending it.",
    use_when=(
        "The user wants a reviewable draft or wants to save an email for later "
        "instead of sending right now."
    ),
    inputs=(
        "to, subject, body, cc (optional comma-separated addresses), bcc "
        "(optional comma-separated addresses)."
    ),
    returns="JSON with success, draft_id, and a confirmation message.",
)

TRASH_EMAIL_DESCRIPTION = build_tool_description(
    purpose="Move a Gmail message to Trash by message_id.",
    use_when="The user wants to remove a known message from the inbox or another label view.",
    inputs="message_id.",
    returns="JSON with success and a confirmation message.",
    notes=(
        "Confirm with the user before trashing the message. Trashed emails can "
        "be recovered within 30 days."
    ),
)

LIST_LABELS_DESCRIPTION = build_tool_description(
    purpose="List Gmail labels available on the account.",
    use_when=(
        "You need label IDs before changing labels or want to show the user's "
        "available system and custom labels."
    ),
    inputs="None.",
    returns="JSON with labels and count. Each label includes id, name, and type.",
    notes="Use this before modify_labels because that tool expects label IDs, not display names.",
)

MODIFY_LABELS_DESCRIPTION = build_tool_description(
    purpose="Add or remove Gmail label IDs on a specific message.",
    use_when=(
        "You want to archive, mark read or unread, star, unstar, or apply/remove "
        "labels on a known message."
    ),
    inputs=(
        "message_id, add_labels (optional comma-separated label IDs), "
        "remove_labels (optional comma-separated label IDs)."
    ),
    returns="JSON with success plus the added and removed label ID lists.",
    notes="Use list_labels first to get label IDs. System IDs such as INBOX, UNREAD, and STARRED also work.",
)

GET_UNREAD_COUNT_DESCRIPTION = build_tool_description(
    purpose="Get the unread message count for the Gmail inbox.",
    use_when="The user wants a quick inbox status summary without listing individual emails.",
    inputs="None.",
    returns="JSON with unread, total_in_inbox, and a summary message.",
)

GET_EMAIL_THREAD_DESCRIPTION = build_tool_description(
    purpose="Read every message in a Gmail thread by thread_id.",
    use_when=(
        "You need the full conversation context instead of a single message."
    ),
    inputs="thread_id.",
    returns="JSON with thread_id, messages, and count. Each message includes id, from, to, date, subject, and body.",
    notes="Use search_emails first to find a relevant message and copy its threadId.",
)
