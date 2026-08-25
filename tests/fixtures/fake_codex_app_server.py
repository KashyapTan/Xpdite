#!/usr/bin/env python3
"""Deterministic newline-delimited JSON-RPC fixture for connector tests."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


TRANSCRIPT = (
    Path(os.environ["XPDITE_FAKE_CODEX_TRANSCRIPT"])
    if os.environ.get("XPDITE_FAKE_CODEX_TRANSCRIPT")
    else None
)
pending_turn: dict[str, Any] | None = None
models_page = 0


def record(direction: str, payload: dict[str, Any]) -> None:
    if TRANSCRIPT is None:
        return
    with TRANSCRIPT.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"direction": direction, "payload": payload}) + "\n")


def send(payload: dict[str, Any]) -> None:
    record("out", payload)
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def finish_turn(request_id: int, params: dict[str, Any]) -> None:
    thread_id = str(params["threadId"])
    turn_id = "turn-1"
    send(
        {"id": request_id, "result": {"turn": {"id": turn_id, "status": "inProgress"}}}
    )
    send(
        {
            "method": "turn/started",
            "params": {
                "threadId": thread_id,
                "turn": {"id": turn_id, "status": "inProgress"},
            },
        }
    )
    if not os.environ.get("XPDITE_FAKE_REASONING_FINAL_ONLY"):
        send(
            {
                "method": "item/reasoning/summaryTextDelta",
                "params": {
                    "threadId": thread_id,
                    "turnId": turn_id,
                    "itemId": "reason-1",
                    "summaryIndex": 0,
                    "delta": "Checking. ",
                },
            }
        )
    if os.environ.get("XPDITE_FAKE_RAW_REASONING"):
        send(
            {
                "method": "item/reasoning/textDelta",
                "params": {
                    "threadId": thread_id,
                    "turnId": turn_id,
                    "itemId": "reason-1",
                    "delta": "PRIVATE RAW REASONING",
                },
            }
        )
    send(
        {
            "method": "item/completed",
            "params": {
                "threadId": thread_id,
                "turnId": turn_id,
                "item": {
                    "id": "reason-1",
                    "type": "reasoning",
                    "summary": ["Checking. "],
                    "content": [],
                },
            },
        }
    )
    if os.environ.get("XPDITE_FAKE_EMPTY_OUTPUT"):
        send(
            {
                "method": "turn/completed",
                "params": {
                    "threadId": thread_id,
                    "turn": {
                        "id": turn_id,
                        "items": [],
                        "status": "completed",
                        "error": None,
                    },
                },
            }
        )
        return
    if os.environ.get("XPDITE_FAKE_MULTIPLE_MESSAGES"):
        send(
            {
                "method": "item/agentMessage/delta",
                "params": {
                    "threadId": thread_id,
                    "turnId": turn_id,
                    "itemId": "message-1",
                    "delta": "First",
                },
            }
        )
        send(
            {
                "method": "item/completed",
                "params": {
                    "threadId": thread_id,
                    "turnId": turn_id,
                    "item": {
                        "id": "message-1",
                        "type": "agentMessage",
                        "text": "First",
                    },
                },
            }
        )
        send(
            {
                "method": "item/completed",
                "params": {
                    "threadId": thread_id,
                    "turnId": turn_id,
                    "item": {
                        "id": "message-2",
                        "type": "agentMessage",
                        "text": "Second",
                    },
                },
            }
        )
        send(
            {
                "method": "turn/completed",
                "params": {
                    "threadId": thread_id,
                    "turn": {
                        "id": turn_id,
                        "items": [],
                        "status": "completed",
                        "error": None,
                    },
                },
            }
        )
        return
    send(
        {
            "method": "item/agentMessage/delta",
            "params": {
                "threadId": thread_id,
                "turnId": turn_id,
                "itemId": "message-1",
                "delta": "Hello ",
            },
        }
    )
    send(
        {
            "method": "item/agentMessage/delta",
            "params": {
                "threadId": thread_id,
                "turnId": turn_id,
                "itemId": "message-1",
                "delta": "from ChatGPT",
            },
        }
    )
    send(
        {
            "method": "item/completed",
            "params": {
                "threadId": thread_id,
                "turnId": turn_id,
                "item": {
                    "id": "message-1",
                    "type": "agentMessage",
                    "text": "Hello from ChatGPT",
                },
            },
        }
    )
    send(
        {
            "method": "thread/tokenUsage/updated",
            "params": {
                "threadId": thread_id,
                "turnId": turn_id,
                "tokenUsage": {
                    "total": {
                        "totalTokens": 10,
                        "inputTokens": 6,
                        "cachedInputTokens": 2,
                        "outputTokens": 4,
                        "reasoningOutputTokens": 1,
                    },
                    "last": {},
                },
            },
        }
    )
    send(
        {
            "method": "turn/completed",
            "params": {
                "threadId": thread_id,
                "turn": {
                    "id": turn_id,
                    "items": [],
                    "status": "completed",
                    "error": None,
                },
            },
        }
    )


for raw_line in sys.stdin:
    try:
        message = json.loads(raw_line)
    except json.JSONDecodeError:
        continue
    if not isinstance(message, dict):
        continue
    record("in", message)
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}

    if method == "initialize":
        if os.environ.get("XPDITE_FAKE_MALFORMED_FRAME"):
            sys.stdout.write("{malformed-json\n")
            sys.stdout.flush()
        if os.environ.get("XPDITE_FAKE_STDERR_SECRETS"):
            for index in range(45):
                sys.stderr.write(f'line-{index} {{"access_token":"secret-{index}"}}\n')
            sys.stderr.flush()
        version = (
            "codex-cli/0.149.0"
            if os.environ.get("XPDITE_FAKE_BAD_VERSION")
            else "codex-cli/0.149.1"
        )
        platform_os = "" if os.environ.get("XPDITE_FAKE_MISSING_PLATFORM") else "test"
        send(
            {
                "id": request_id,
                "result": {
                    "userAgent": version,
                    "codexHome": os.environ.get("CODEX_HOME"),
                    "platformFamily": "unix",
                    "platformOs": platform_os,
                },
            }
        )
    elif method == "initialized":
        continue
    elif method == "account/read":
        if os.environ.get("XPDITE_FAKE_HANG_ACCOUNT"):
            continue
        crash_marker = os.environ.get("XPDITE_FAKE_CRASH_ONCE_MARKER")
        if crash_marker and not Path(crash_marker).exists():
            Path(crash_marker).touch()
            raise SystemExit(17)
        account_type = os.environ.get("XPDITE_FAKE_ACCOUNT_TYPE", "chatgpt")
        account = (
            None
            if account_type == "none"
            else {
                "type": account_type,
                "email": "fixture@example.com",
                "planType": "test",
            }
        )
        result = {"account": account, "requiresOpenaiAuth": account_type != "chatgpt"}
        if os.environ.get("XPDITE_FAKE_LARGE_FRAME"):
            result["padding"] = "x" * (128 * 1024)
        send({"id": request_id, "result": result})
    elif method == "account/rateLimits/read":
        send(
            {
                "id": request_id,
                "result": {"rateLimits": {"primary": {"usedPercent": 12}}},
            }
        )
    elif method == "model/list":
        auth_error_marker = os.environ.get("XPDITE_FAKE_AUTH_ERROR_ONCE_MARKER")
        if auth_error_marker and not Path(auth_error_marker).exists():
            Path(auth_error_marker).touch()
            send(
                {
                    "id": request_id,
                    "error": {"code": -32001, "message": "Unauthorized access token"},
                }
            )
            continue
        if params.get("cursor") == "page-2":
            send(
                {
                    "id": request_id,
                    "result": {
                        "data": [
                            {
                                "id": "hidden-model",
                                "model": "hidden-model",
                                "displayName": "Hidden",
                                "description": "hidden",
                                "hidden": True,
                                "supportedReasoningEfforts": [],
                                "defaultReasoningEffort": None,
                                "inputModalities": ["text"],
                                "isDefault": False,
                            }
                        ],
                        "nextCursor": None,
                    },
                }
            )
        else:
            modalities = (
                ["text"]
                if os.environ.get("XPDITE_FAKE_TEXT_ONLY_MODEL")
                else ["text", "image"]
            )
            send(
                {
                    "id": request_id,
                    "result": {
                        "data": [
                            {
                                "id": "fixture-model",
                                "model": "fixture-model",
                                "displayName": "Fixture Model",
                                "description": "Fixture subscription model",
                                "hidden": False,
                                "supportedReasoningEfforts": [
                                    {
                                        "reasoningEffort": "medium",
                                        "description": "Balanced",
                                    },
                                    {
                                        "reasoningEffort": "low",
                                        "description": "Fast",
                                    },
                                ],
                                "defaultReasoningEffort": "medium",
                                "inputModalities": modalities,
                                "supportsPersonality": True,
                                "additionalSpeedTiers": [],
                                "isDefault": True,
                            }
                        ],
                        "nextCursor": "page-2",
                    },
                }
            )
    elif method == "thread/start":
        send(
            {
                "id": request_id,
                "result": {
                    "thread": {"id": "thread-1"},
                    "model": params.get("model"),
                    "cwd": params.get("cwd"),
                },
            }
        )
    elif method == "thread/inject_items":
        send({"id": request_id, "result": {}})
    elif method == "turn/start":
        dynamic_tools = []
        if TRANSCRIPT and TRANSCRIPT.exists():
            entries = [
                json.loads(line)
                for line in TRANSCRIPT.read_text(encoding="utf-8").splitlines()
            ]
            starts = [
                entry["payload"]
                for entry in entries
                if entry["direction"] == "in"
                and entry["payload"].get("method") == "thread/start"
            ]
            dynamic_tools = (
                (starts[-1].get("params") or {}).get("dynamicTools") or []
                if starts
                else []
            )
        if os.environ.get("XPDITE_FAKE_FAILED_TURN"):
            send(
                {
                    "id": request_id,
                    "result": {"turn": {"id": "turn-1", "status": "inProgress"}},
                }
            )
            send(
                {
                    "method": "turn/completed",
                    "params": {
                        "threadId": params["threadId"],
                        "turn": {
                            "id": "turn-1",
                            "items": [],
                            "status": "failed",
                            "error": {"message": "internal fixture failure"},
                        },
                    },
                }
            )
        elif os.environ.get("XPDITE_FAKE_FORBIDDEN_ITEM"):
            send(
                {
                    "id": request_id,
                    "result": {"turn": {"id": "turn-1", "status": "inProgress"}},
                }
            )
            send(
                {
                    "method": "item/started",
                    "params": {
                        "threadId": params["threadId"],
                        "turnId": "turn-1",
                        "item": {"id": "command-1", "type": "commandExecution"},
                    },
                }
            )
        elif dynamic_tools:
            pending_turn = {"request_id": request_id, "params": params}
            if not os.environ.get("XPDITE_FAKE_COLLIDE_BEFORE_TURN"):
                send(
                    {
                        "id": request_id,
                        "result": {"turn": {"id": "turn-1", "status": "inProgress"}},
                    }
                )
            send(
                {
                    "id": request_id,
                    "method": "item/tool/call",
                    "params": {
                        "threadId": params["threadId"],
                        "turnId": "turn-1",
                        "callId": "call-1",
                        "tool": dynamic_tools[0]["name"],
                        "arguments": {"value": 7},
                    },
                }
            )
        else:
            finish_turn(request_id, params)
    elif method == "turn/interrupt":
        send({"id": request_id, "result": {}})
        send(
            {
                "method": "turn/completed",
                "params": {
                    "threadId": params["threadId"],
                    "turn": {
                        "id": params["turnId"],
                        "items": [],
                        "status": "interrupted",
                        "error": None,
                    },
                },
            }
        )
    elif request_id is not None and ("result" in message or "error" in message):
        if pending_turn is not None:
            current = pending_turn
            pending_turn = None
            if os.environ.get("XPDITE_FAKE_COLLIDE_BEFORE_TURN"):
                finish_turn(int(current["request_id"]), current["params"])
            else:
                thread_id = str(current["params"]["threadId"])
                turn_id = "turn-1"
                send(
                    {
                        "method": "turn/started",
                        "params": {
                            "threadId": thread_id,
                            "turn": {"id": turn_id, "status": "inProgress"},
                        },
                    }
                )
                if not os.environ.get("XPDITE_FAKE_REASONING_FINAL_ONLY"):
                    send(
                        {
                            "method": "item/reasoning/summaryTextDelta",
                            "params": {
                                "threadId": thread_id,
                                "turnId": turn_id,
                                "itemId": "reason-1",
                                "summaryIndex": 0,
                                "delta": "Checking. ",
                            },
                        }
                    )
                send(
                    {
                        "method": "item/completed",
                        "params": {
                            "threadId": thread_id,
                            "turnId": turn_id,
                            "item": {
                                "id": "reason-1",
                                "type": "reasoning",
                                "summary": ["Checking. "],
                                "content": [],
                            },
                        },
                    }
                )
                send(
                    {
                        "method": "item/agentMessage/delta",
                        "params": {
                            "threadId": thread_id,
                            "turnId": turn_id,
                            "itemId": "message-1",
                            "delta": "Hello ",
                        },
                    }
                )
                send(
                    {
                        "method": "item/agentMessage/delta",
                        "params": {
                            "threadId": thread_id,
                            "turnId": turn_id,
                            "itemId": "message-1",
                            "delta": "from ChatGPT",
                        },
                    }
                )
                send(
                    {
                        "method": "item/completed",
                        "params": {
                            "threadId": thread_id,
                            "turnId": turn_id,
                            "item": {
                                "id": "message-1",
                                "type": "agentMessage",
                                "text": "Hello from ChatGPT",
                            },
                        },
                    }
                )
                send(
                    {
                        "method": "thread/tokenUsage/updated",
                        "params": {
                            "threadId": thread_id,
                            "turnId": turn_id,
                            "tokenUsage": {
                                "total": {
                                    "totalTokens": 10,
                                    "inputTokens": 6,
                                    "cachedInputTokens": 2,
                                    "outputTokens": 4,
                                    "reasoningOutputTokens": 1,
                                },
                                "last": {},
                            },
                        },
                    }
                )
                send(
                    {
                        "method": "turn/completed",
                        "params": {
                            "threadId": thread_id,
                            "turn": {
                                "id": turn_id,
                                "items": [],
                                "status": "completed",
                                "error": None,
                            },
                        },
                    }
                )
    elif method == "account/logout":
        send({"id": request_id, "result": {}})
    elif method == "account/login/start":
        if params.get("type") == "chatgptDeviceCode":
            send(
                {
                    "id": request_id,
                    "result": {
                        "loginId": "login-1",
                        "verificationUrl": "https://example.test/device",
                        "userCode": "ABCD-EFGH",
                    },
                }
            )
        else:
            send(
                {
                    "id": request_id,
                    "result": {
                        "loginId": "login-1",
                        "authUrl": "https://example.test/login?secret=fixture",
                    },
                }
            )
    elif method == "account/login/cancel":
        send({"id": request_id, "result": {}})
