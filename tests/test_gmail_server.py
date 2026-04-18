import base64
import json
from unittest.mock import MagicMock, mock_open, patch

import pytest

from mcp_servers.servers.gmail import server as gmail_server


def _parse_json(payload: str) -> dict:
    return json.loads(payload)


def _decode_raw_message(raw: str) -> str:
    return base64.urlsafe_b64decode(raw.encode("utf-8")).decode(
        "utf-8", errors="replace"
    )


@pytest.fixture(autouse=True)
def reset_gmail_cache(monkeypatch):
    monkeypatch.setattr(gmail_server, "_gmail_service_cache", None)
    monkeypatch.setattr(gmail_server, "_gmail_service_cache_time", 0.0)


def test_get_gmail_service_reuses_cached_service(monkeypatch):
    creds = MagicMock(expired=False, valid=True)
    build_calls: list[tuple] = []

    monkeypatch.setattr(gmail_server.os.path, "exists", lambda _path: True)
    monkeypatch.setattr(
        gmail_server.Credentials,
        "from_authorized_user_file",
        lambda _path, _scopes: creds,
    )
    monkeypatch.setattr(
        gmail_server,
        "build",
        lambda *args, **kwargs: build_calls.append((args, kwargs)) or "service",
    )

    assert gmail_server._get_gmail_service() == "service"
    assert gmail_server._get_gmail_service() == "service"
    assert len(build_calls) == 1


def test_get_gmail_service_refreshes_expired_token(monkeypatch):
    creds = MagicMock(expired=True, refresh_token="refresh-token", valid=True)
    creds.to_json.return_value = '{"token":"fresh"}'

    monkeypatch.setattr(gmail_server.os.path, "exists", lambda _path: True)
    monkeypatch.setattr(
        gmail_server.Credentials,
        "from_authorized_user_file",
        lambda _path, _scopes: creds,
    )
    monkeypatch.setattr(gmail_server, "build", lambda *_args, **_kwargs: "service")

    with patch("builtins.open", mock_open()) as mocked_open:
        assert gmail_server._get_gmail_service() == "service"

    creds.refresh.assert_called_once()
    mocked_open.assert_called_once_with(gmail_server.TOKEN_FILE, "w")


def test_get_gmail_service_refresh_failure_requires_reconnect(monkeypatch):
    creds = MagicMock(expired=True, refresh_token="refresh-token", valid=False)
    creds.refresh.side_effect = Exception("token refresh failed")

    monkeypatch.setattr(gmail_server.os.path, "exists", lambda _path: True)
    monkeypatch.setattr(
        gmail_server.Credentials,
        "from_authorized_user_file",
        lambda _path, _scopes: creds,
    )

    with pytest.raises(RuntimeError, match="Google authentication expired"):
        gmail_server._get_gmail_service()

    assert gmail_server._gmail_service_cache is None


def test_parse_email_headers_includes_threading_headers():
    headers = gmail_server._parse_email_headers(
        [
            {"name": "From", "value": "sender@example.com"},
            {"name": "References", "value": "<root@example.com>"},
            {"name": "In-Reply-To", "value": "<prev@example.com>"},
        ]
    )

    assert headers["from"] == "sender@example.com"
    assert headers["references"] == "<root@example.com>"
    assert headers["in-reply-to"] == "<prev@example.com>"


def test_split_csv_values_discards_empty_entries():
    assert gmail_server._split_csv_values(" A , ,B ,, C ") == ["A", "B", "C"]
    assert gmail_server._split_csv_values(None) == []


def test_get_email_body_prefers_plain_text_and_falls_back_to_html():
    plain_body = gmail_server._get_email_body(
        {
            "mimeType": "text/plain",
            "body": {"data": base64.urlsafe_b64encode(b"hello").decode("utf-8")},
        }
    )
    html_body = gmail_server._get_email_body(
        {
            "parts": [
                {
                    "mimeType": "text/html",
                    "body": {
                        "data": base64.urlsafe_b64encode(
                            b"<p>Hello <strong>world</strong></p>"
                        ).decode("utf-8")
                    },
                }
            ]
        }
    )

    assert plain_body == "hello"
    assert html_body == "Hello world"


def test_get_attachments_info_recurses_nested_parts():
    attachments = gmail_server._get_attachments_info(
        {
            "parts": [
                {
                    "mimeType": "multipart/mixed",
                    "parts": [
                        {
                            "filename": "invoice.pdf",
                            "body": {"size": 1234},
                        }
                    ],
                }
            ]
        }
    )

    assert attachments == [{"name": "invoice.pdf", "size": 1234}]


def test_search_emails_returns_metadata_for_matches(monkeypatch):
    service = MagicMock()
    messages_api = service.users.return_value.messages.return_value
    messages_api.list.return_value.execute.return_value = {
        "messages": [{"id": "m1"}, {"id": "m2"}]
    }
    messages_api.get.return_value.execute.side_effect = [
        {
            "id": "m1",
            "threadId": "t1",
            "snippet": "snippet 1",
            "labelIds": ["INBOX"],
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "First"},
                    {"name": "From", "value": "a@example.com"},
                    {"name": "Date", "value": "Fri"},
                ]
            },
        },
        {
            "id": "m2",
            "threadId": "t2",
            "snippet": "snippet 2",
            "labelIds": ["UNREAD"],
            "payload": {"headers": []},
        },
    ]
    monkeypatch.setattr(gmail_server, "_get_gmail_service", lambda: service)

    payload = _parse_json(gmail_server.search_emails(query="label:inbox", max_results=5))

    assert payload["count"] == 2
    assert payload["emails"][0]["subject"] == "First"
    assert payload["emails"][1]["subject"] == "(No Subject)"


def test_read_email_returns_body_and_attachments(monkeypatch):
    service = MagicMock()
    service.users.return_value.messages.return_value.get.return_value.execute.return_value = {
        "id": "m3",
        "threadId": "t3",
        "labelIds": ["INBOX"],
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Hello"},
                {"name": "From", "value": "a@example.com"},
                {"name": "To", "value": "b@example.com"},
            ],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {
                        "data": base64.urlsafe_b64encode(b"Body text").decode("utf-8")
                    },
                },
                {"filename": "report.txt", "body": {"size": 42}},
            ],
        },
    }
    monkeypatch.setattr(gmail_server, "_get_gmail_service", lambda: service)

    payload = _parse_json(gmail_server.read_email("m3"))

    assert payload["subject"] == "Hello"
    assert payload["body"] == "Body text"
    assert payload["attachments"] == [{"name": "report.txt", "size": 42}]


def test_send_email_builds_mime_message(monkeypatch):
    service = MagicMock()
    service.users.return_value.messages.return_value.send.return_value.execute.return_value = {
        "id": "sent-1",
        "threadId": "thread-1",
    }
    monkeypatch.setattr(gmail_server, "_get_gmail_service", lambda: service)

    payload = _parse_json(
        gmail_server.send_email(
            to="to@example.com",
            subject="Status",
            body="All good",
            cc="cc@example.com",
            bcc="bcc@example.com",
        )
    )

    raw = service.users.return_value.messages.return_value.send.call_args.kwargs["body"][
        "raw"
    ]
    decoded = _decode_raw_message(raw)
    assert "to: to@example.com" in decoded
    assert "cc: cc@example.com" in decoded
    assert "bcc: bcc@example.com" in decoded
    assert payload["success"] is True


def test_reply_to_email_preserves_existing_references(monkeypatch):
    service = MagicMock()
    messages_api = service.users.return_value.messages.return_value
    messages_api.get.return_value.execute.return_value = {
        "threadId": "thread-2",
        "payload": {
            "headers": [
                {"name": "From", "value": "sender@example.com"},
                {"name": "Subject", "value": "Status"},
                {"name": "Message-ID", "value": "<msg-2@example.com>"},
                {"name": "References", "value": "<msg-1@example.com>"},
            ]
        },
    }
    messages_api.send.return_value.execute.return_value = {
        "id": "reply-1",
        "threadId": "thread-2",
    }
    monkeypatch.setattr(gmail_server, "_get_gmail_service", lambda: service)

    payload = _parse_json(gmail_server.reply_to_email("message-1", "Thanks!"))

    send_body = messages_api.send.call_args.kwargs["body"]
    decoded = _decode_raw_message(send_body["raw"])
    assert "subject: Re: Status" in decoded
    assert "In-Reply-To: <msg-2@example.com>" in decoded
    assert "References: <msg-1@example.com> <msg-2@example.com>" in decoded
    assert send_body["threadId"] == "thread-2"
    assert payload["success"] is True


def test_create_draft_builds_draft_message(monkeypatch):
    service = MagicMock()
    service.users.return_value.drafts.return_value.create.return_value.execute.return_value = {
        "id": "draft-1"
    }
    monkeypatch.setattr(gmail_server, "_get_gmail_service", lambda: service)

    payload = _parse_json(
        gmail_server.create_draft(
            to="to@example.com",
            subject="Draft",
            body="Review later",
        )
    )

    raw = service.users.return_value.drafts.return_value.create.call_args.kwargs["body"][
        "message"
    ]["raw"]
    assert "subject: Draft" in _decode_raw_message(raw)
    assert payload["draft_id"] == "draft-1"


def test_trash_email_returns_success(monkeypatch):
    service = MagicMock()
    service.users.return_value.messages.return_value.trash.return_value.execute.return_value = {}
    monkeypatch.setattr(gmail_server, "_get_gmail_service", lambda: service)

    payload = _parse_json(gmail_server.trash_email("m4"))

    assert payload["success"] is True
    assert "m4" in payload["info"]


def test_list_labels_sorts_system_labels_first(monkeypatch):
    service = MagicMock()
    service.users.return_value.labels.return_value.list.return_value.execute.return_value = {
        "labels": [
            {"id": "LBL1", "name": "Projects", "type": "user"},
            {"id": "INBOX", "name": "INBOX", "type": "system"},
        ]
    }
    monkeypatch.setattr(gmail_server, "_get_gmail_service", lambda: service)

    payload = _parse_json(gmail_server.list_labels())

    assert [label["id"] for label in payload["labels"]] == ["INBOX", "LBL1"]


def test_modify_labels_filters_blank_values_and_requires_work(monkeypatch):
    service = MagicMock()
    service.users.return_value.messages.return_value.modify.return_value.execute.return_value = {}
    monkeypatch.setattr(gmail_server, "_get_gmail_service", lambda: service)

    payload = _parse_json(
        gmail_server.modify_labels(
            "m5",
            add_labels="LBL1, ,LBL2",
            remove_labels=" ,INBOX",
        )
    )

    modify_body = service.users.return_value.messages.return_value.modify.call_args.kwargs[
        "body"
    ]
    assert modify_body == {
        "addLabelIds": ["LBL1", "LBL2"],
        "removeLabelIds": ["INBOX"],
    }
    assert payload["added"] == ["LBL1", "LBL2"]
    assert payload["removed"] == ["INBOX"]

    empty_payload = _parse_json(gmail_server.modify_labels("m5", add_labels=" , "))
    assert "Must specify" in empty_payload["error"]


def test_get_unread_count_returns_label_summary(monkeypatch):
    service = MagicMock()
    service.users.return_value.labels.return_value.get.return_value.execute.return_value = {
        "messagesUnread": 7,
        "messagesTotal": 20,
    }
    monkeypatch.setattr(gmail_server, "_get_gmail_service", lambda: service)

    payload = _parse_json(gmail_server.get_unread_count())

    assert payload["unread"] == 7
    assert payload["total_in_inbox"] == 20


def test_get_email_thread_returns_message_bodies(monkeypatch):
    service = MagicMock()
    service.users.return_value.threads.return_value.get.return_value.execute.return_value = {
        "messages": [
            {
                "id": "m6",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "a@example.com"},
                        {"name": "To", "value": "b@example.com"},
                        {"name": "Subject", "value": "Thread"},
                    ],
                    "parts": [
                        {
                            "mimeType": "text/plain",
                            "body": {
                                "data": base64.urlsafe_b64encode(
                                    b"Thread body"
                                ).decode("utf-8")
                            },
                        }
                    ],
                },
            }
        ]
    }
    monkeypatch.setattr(gmail_server, "_get_gmail_service", lambda: service)

    payload = _parse_json(gmail_server.get_email_thread("thread-6"))

    assert payload["thread_id"] == "thread-6"
    assert payload["messages"][0]["body"] == "Thread body"
