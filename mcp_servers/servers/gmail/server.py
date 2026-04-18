"""
Gmail MCP Server.

Provides Gmail tools for the LLM to search, read, send, and manage emails
via the user's connected Google account.

Authentication is handled by the main app's OAuth flow. This server reads
the stored token from GOOGLE_TOKEN_FILE environment variable.
"""

import os
import json
import base64
import time
import threading
from email.mime.text import MIMEText
from typing import Optional, Any

from mcp.server.fastmcp import FastMCP
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from mcp_servers.servers.gmail.gmail_descriptions import (
    SEARCH_EMAILS_DESCRIPTION,
    READ_EMAIL_DESCRIPTION,
    SEND_EMAIL_DESCRIPTION,
    REPLY_TO_EMAIL_DESCRIPTION,
    CREATE_DRAFT_DESCRIPTION,
    TRASH_EMAIL_DESCRIPTION,
    LIST_LABELS_DESCRIPTION,
    MODIFY_LABELS_DESCRIPTION,
    GET_UNREAD_COUNT_DESCRIPTION,
    GET_EMAIL_THREAD_DESCRIPTION,
)

mcp = FastMCP("Gmail Tools")

# Token path from environment or default
TOKEN_FILE = os.environ.get("GOOGLE_TOKEN_FILE", "user_data/google/token.json")

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]

# ── Service singleton caching ──────────────────────────────────────────────
_gmail_service_cache: Any = None
_gmail_service_cache_time: float = 0.0
_gmail_service_cache_ttl: float = 1800.0  # 30 minutes
_gmail_service_lock = threading.Lock()


def _get_gmail_service():
    """Build and return an authenticated Gmail API service with caching.

    Reuses the service object for 30 minutes to avoid rebuilding on every call.
    Token refresh is checked and performed only when actually expired.
    Uses threading lock to prevent race conditions during initialization.
    """
    global _gmail_service_cache, _gmail_service_cache_time

    current_time = time.time()

    # Quick check without lock (common path)
    if _gmail_service_cache is not None and (current_time - _gmail_service_cache_time) < _gmail_service_cache_ttl:
        return _gmail_service_cache

    # Acquire lock for cache miss
    with _gmail_service_lock:
        # Double-check pattern: re-verify after acquiring lock
        current_time = time.time()
        if _gmail_service_cache is not None and (current_time - _gmail_service_cache_time) < _gmail_service_cache_ttl:
            return _gmail_service_cache

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
                _gmail_service_cache = None
                raise RuntimeError(
                    "Google authentication expired. Please reconnect your Google account in Settings > Connections."
                )

        if not creds or not creds.valid:
            _gmail_service_cache = None
            raise RuntimeError(
                "Google authentication expired. Please reconnect your Google account in Settings > Connections."
            )

        # Build and cache the service
        _gmail_service_cache = build("gmail", "v1", credentials=creds)
        _gmail_service_cache_time = current_time
        return _gmail_service_cache


def _parse_email_headers(headers: list) -> dict:
    """Extract common headers from a Gmail message's header list."""
    result = {}
    for header in headers:
        name = header.get("name", "").lower()
        if name in (
            "from",
            "to",
            "cc",
            "bcc",
            "subject",
            "date",
            "message-id",
            "references",
            "in-reply-to",
        ):
            result[name] = header.get("value", "")
    return result


def _split_csv_values(value: str | None) -> list[str]:
    """Split a comma-separated list while discarding blank entries."""
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _get_email_body(payload: dict) -> str:
    """Extract plain text body from a Gmail message payload."""
    # Simple single-part message
    if payload.get("mimeType") == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

    # Multipart message — search parts recursively
    parts = payload.get("parts", [])
    for part in parts:
        mime = part.get("mimeType", "")
        if mime == "text/plain":
            data = part.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        elif mime.startswith("multipart/"):
            # Recurse into nested multipart
            body = _get_email_body(part)
            if body:
                return body

    # Fallback: try HTML part
    for part in parts:
        if part.get("mimeType") == "text/html":
            data = part.get("body", {}).get("data", "")
            if data:
                html = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                # Strip HTML tags for plain text approximation
                import re

                text = re.sub(r"<[^>]+>", "", html)
                text = re.sub(r"\s+", " ", text).strip()
                return text

    return "(No readable text content)"


def _get_attachments_info(payload: dict) -> list:
    """Get list of attachment names and sizes from a message payload."""
    attachments = []
    parts = payload.get("parts", [])
    for part in parts:
        filename = part.get("filename", "")
        if filename:
            size = part.get("body", {}).get("size", 0)
            attachments.append({"name": filename, "size": size})
        # Recurse into nested multipart
        if part.get("mimeType", "").startswith("multipart/"):
            attachments.extend(_get_attachments_info(part))
    return attachments


# ── TOOLS ──────────────────────────────────────────────────────────────


@mcp.tool(description=SEARCH_EMAILS_DESCRIPTION)
def search_emails(query: str = "is:unread", max_results: int = 10) -> str:
    """Search emails using Gmail query syntax."""
    try:
        service = _get_gmail_service()
        results = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=min(max_results, 50))
            .execute()
        )

        messages = results.get("messages", [])
        if not messages:
            return json.dumps(
                {"message": f"No emails found for query: {query}", "count": 0}
            )

        email_list = []
        for msg_ref in messages:
            msg = (
                service.users()
                .messages()
                .get(
                    userId="me",
                    id=msg_ref["id"],
                    format="metadata",
                    metadataHeaders=["From", "To", "Subject", "Date"],
                )
                .execute()
            )

            headers = _parse_email_headers(msg.get("payload", {}).get("headers", []))
            email_list.append(
                {
                    "id": msg["id"],
                    "threadId": msg.get("threadId", ""),
                    "subject": headers.get("subject", "(No Subject)"),
                    "from": headers.get("from", ""),
                    "date": headers.get("date", ""),
                    "snippet": msg.get("snippet", ""),
                    "labels": msg.get("labelIds", []),
                }
            )

        return json.dumps({"emails": email_list, "count": len(email_list)}, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Failed to search emails: {str(e)}"})


@mcp.tool(description=READ_EMAIL_DESCRIPTION)
def read_email(message_id: str) -> str:
    """Get full content of a specific email."""
    try:
        service = _get_gmail_service()
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )

        payload = msg.get("payload", {})
        headers = _parse_email_headers(payload.get("headers", []))
        body = _get_email_body(payload)
        attachments = _get_attachments_info(payload)

        result = {
            "id": msg["id"],
            "threadId": msg.get("threadId", ""),
            "subject": headers.get("subject", "(No Subject)"),
            "from": headers.get("from", ""),
            "to": headers.get("to", ""),
            "cc": headers.get("cc", ""),
            "date": headers.get("date", ""),
            "body": body,
            "labels": msg.get("labelIds", []),
            "attachments": attachments,
        }

        return json.dumps(result, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Failed to read email: {str(e)}"})


@mcp.tool(description=SEND_EMAIL_DESCRIPTION)
def send_email(
    to: str,
    subject: str,
    body: str,
    cc: str = "",
    bcc: str = "",
) -> str:
    """Compose and send a new email."""
    try:
        service = _get_gmail_service()

        message = MIMEText(body)
        message["to"] = to
        message["subject"] = subject
        if cc:
            message["cc"] = cc
        if bcc:
            message["bcc"] = bcc

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
        sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()

        return json.dumps(
            {
                "success": True,
                "message_id": sent["id"],
                "thread_id": sent.get("threadId", ""),
                "info": f"Email sent to {to}",
            }
        )

    except Exception as e:
        return json.dumps({"error": f"Failed to send email: {str(e)}"})


@mcp.tool(description=REPLY_TO_EMAIL_DESCRIPTION)
def reply_to_email(message_id: str, body: str) -> str:
    """Reply to a specific email thread."""
    try:
        service = _get_gmail_service()

        # Get original message for threading info
        original = (
            service.users()
            .messages()
            .get(
                userId="me",
                id=message_id,
                format="metadata",
                metadataHeaders=[
                    "From",
                    "To",
                    "Subject",
                    "Message-ID",
                    "References",
                    "In-Reply-To",
                ],
            )
            .execute()
        )

        orig_headers = _parse_email_headers(
            original.get("payload", {}).get("headers", [])
        )
        thread_id = original.get("threadId", "")

        # Build reply
        reply = MIMEText(body)
        reply["to"] = orig_headers.get("from", "")
        subject = orig_headers.get("subject", "")
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"
        reply["subject"] = subject

        # Threading headers
        msg_id = orig_headers.get("message-id", "")
        existing_references = orig_headers.get("references", "").strip()
        if msg_id:
            reply["In-Reply-To"] = msg_id
            references = [ref for ref in existing_references.split() if ref]
            if msg_id not in references:
                references.append(msg_id)
            reply["References"] = " ".join(references)
        elif existing_references:
            reply["References"] = existing_references

        raw = base64.urlsafe_b64encode(reply.as_bytes()).decode("utf-8")
        sent = (
            service.users()
            .messages()
            .send(userId="me", body={"raw": raw, "threadId": thread_id})
            .execute()
        )

        return json.dumps(
            {
                "success": True,
                "message_id": sent["id"],
                "thread_id": sent.get("threadId", ""),
                "info": f"Reply sent to {orig_headers.get('from', 'unknown')}",
            }
        )

    except Exception as e:
        return json.dumps({"error": f"Failed to reply: {str(e)}"})


@mcp.tool(description=CREATE_DRAFT_DESCRIPTION)
def create_draft(
    to: str,
    subject: str,
    body: str,
    cc: str = "",
    bcc: str = "",
) -> str:
    """Create a draft email without sending."""
    try:
        service = _get_gmail_service()

        message = MIMEText(body)
        message["to"] = to
        message["subject"] = subject
        if cc:
            message["cc"] = cc
        if bcc:
            message["bcc"] = bcc

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
        draft = (
            service.users()
            .drafts()
            .create(userId="me", body={"message": {"raw": raw}})
            .execute()
        )

        return json.dumps(
            {
                "success": True,
                "draft_id": draft["id"],
                "info": f"Draft created for {to}",
            }
        )

    except Exception as e:
        return json.dumps({"error": f"Failed to create draft: {str(e)}"})


@mcp.tool(description=TRASH_EMAIL_DESCRIPTION)
def trash_email(message_id: str) -> str:
    """Move an email to trash."""
    try:
        service = _get_gmail_service()
        service.users().messages().trash(userId="me", id=message_id).execute()

        return json.dumps(
            {
                "success": True,
                "info": f"Email {message_id} moved to trash",
            }
        )

    except Exception as e:
        return json.dumps({"error": f"Failed to trash email: {str(e)}"})


@mcp.tool(description=LIST_LABELS_DESCRIPTION)
def list_labels() -> str:
    """List all Gmail labels/folders."""
    try:
        service = _get_gmail_service()
        results = service.users().labels().list(userId="me").execute()
        labels = results.get("labels", [])

        label_list = []
        for label in labels:
            label_list.append(
                {
                    "id": label["id"],
                    "name": label["name"],
                    "type": label.get("type", "user"),
                }
            )

        # Sort: system labels first, then user labels alphabetically
        label_list.sort(key=lambda x: (0 if x["type"] == "system" else 1, x["name"]))

        return json.dumps({"labels": label_list, "count": len(label_list)}, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Failed to list labels: {str(e)}"})


@mcp.tool(description=MODIFY_LABELS_DESCRIPTION)
def modify_labels(
    message_id: str,
    add_labels: Optional[str] = None,
    remove_labels: Optional[str] = None,
) -> str:
    """Add or remove labels from an email."""
    try:
        service = _get_gmail_service()

        # Parse comma-separated label strings into lists
        add_list = _split_csv_values(add_labels)
        remove_list = _split_csv_values(remove_labels)

        if not add_list and not remove_list:
            return json.dumps(
                {"error": "Must specify at least one label to add or remove"}
            )

        body = {}
        if add_list:
            body["addLabelIds"] = add_list
        if remove_list:
            body["removeLabelIds"] = remove_list

        service.users().messages().modify(
            userId="me", id=message_id, body=body
        ).execute()

        return json.dumps(
            {
                "success": True,
                "info": f"Labels updated for email {message_id}",
                "added": add_list,
                "removed": remove_list,
            }
        )

    except Exception as e:
        return json.dumps({"error": f"Failed to modify labels: {str(e)}"})


@mcp.tool(description=GET_UNREAD_COUNT_DESCRIPTION)
def get_unread_count() -> str:
    """Get count of unread emails in inbox."""
    try:
        service = _get_gmail_service()

        # Use label info which includes unread count
        label = service.users().labels().get(userId="me", id="INBOX").execute()

        unread = label.get("messagesUnread", 0)
        total = label.get("messagesTotal", 0)

        return json.dumps(
            {
                "unread": unread,
                "total_in_inbox": total,
                "info": f"You have {unread} unread email(s) in your inbox (out of {total} total)",
            }
        )

    except Exception as e:
        return json.dumps({"error": f"Failed to get unread count: {str(e)}"})


@mcp.tool(description=GET_EMAIL_THREAD_DESCRIPTION)
def get_email_thread(thread_id: str) -> str:
    """Get all messages in a conversation thread."""
    try:
        service = _get_gmail_service()
        thread = (
            service.users()
            .threads()
            .get(userId="me", id=thread_id, format="full")
            .execute()
        )

        messages = []
        for msg in thread.get("messages", []):
            payload = msg.get("payload", {})
            headers = _parse_email_headers(payload.get("headers", []))
            body = _get_email_body(payload)

            messages.append(
                {
                    "id": msg["id"],
                    "from": headers.get("from", ""),
                    "to": headers.get("to", ""),
                    "date": headers.get("date", ""),
                    "subject": headers.get("subject", ""),
                    "body": body,
                }
            )

        return json.dumps(
            {
                "thread_id": thread_id,
                "messages": messages,
                "count": len(messages),
            },
            indent=2,
        )

    except Exception as e:
        return json.dumps({"error": f"Failed to get thread: {str(e)}"})


if __name__ == "__main__":
    mcp.run()
