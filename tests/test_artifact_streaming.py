"""Tests for artifact streaming parsing helpers."""

from unittest.mock import AsyncMock

import pytest

from source.llm.core.artifacts import ArtifactStreamParser, emit_artifact_stream_events


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _collect_events(*chunks: str):
    parser = ArtifactStreamParser()
    events = []
    for chunk in chunks:
        events.extend(parser.feed(chunk))
    events.extend(parser.finalize())
    return events


def _text_from_events(events):
    return "".join(event["content"] for event in events if event.get("type") == "text")


class TestArtifactStreamParser:
    def test_plain_text_passes_through_unchanged(self):
        events = _collect_events("hello ", "world")

        assert _text_from_events(events) == "hello world"

    def test_single_artifact_is_emitted_with_clean_surrounding_text(self):
        events = _collect_events(
            "Intro <arti",
            'fact type="code" title="Demo" language="python">print("hi")',
            "</artifact> outro",
        )

        assert [event["type"] for event in events] == [
            "text",
            "artifact_start",
            "artifact_complete",
            "text",
        ]
        assert events[0]["content"] == "Intro "
        assert events[1]["artifact"]["status"] == "streaming"
        assert events[1]["artifact"]["artifact_type"] == "code"
        assert events[1]["artifact"]["title"] == "Demo"
        assert events[1]["artifact"]["language"] == "python"
        assert events[2]["artifact"]["status"] == "ready"
        assert events[2]["artifact"]["content"] == 'print("hi")'
        assert events[2]["artifact"]["line_count"] == 1
        assert events[3]["content"] == " outro"

    def test_multiple_artifacts_preserve_order(self):
        events = _collect_events(
            'A<artifact type="markdown" title="One"># One</artifact>'
            'B<artifact type="html" title="Two"><div>Two</div></artifact>C'
        )

        assert [event["type"] for event in events] == [
            "text",
            "artifact_start",
            "artifact_complete",
            "text",
            "artifact_start",
            "artifact_complete",
            "text",
        ]
        assert events[2]["artifact"]["artifact_type"] == "markdown"
        assert events[2]["artifact"]["content"] == "# One"
        assert events[5]["artifact"]["artifact_type"] == "html"
        assert events[5]["artifact"]["content"] == "<div>Two</div>"

    def test_malformed_artifact_tag_falls_back_to_plain_text(self):
        raw = '<artifact title="Missing type">bad</artifact>'
        events = _collect_events(raw)

        assert not any(event["type"].startswith("artifact_") for event in events)
        assert _text_from_events(events) == raw

    def test_unclosed_artifact_is_abandoned_and_returned_as_text(self):
        raw = '<artifact type="markdown" title="Draft">unfinished'
        events = _collect_events(raw)

        assert [event["type"] for event in events] == [
            "artifact_start",
            "artifact_abandoned",
            "text",
        ]
        assert events[2]["content"] == raw

    def test_nested_artifact_markup_is_kept_literal_inside_parent(self):
        events = _collect_events(
            '<artifact type="markdown" title="Outer">'
            'before <artifact type="code" title="Inner">x</artifact> after'
            "</artifact>"
        )

        assert [event["type"] for event in events] == [
            "artifact_start",
            "artifact_complete",
        ]
        assert events[1]["artifact"]["content"] == (
            'before <artifact type="code" title="Inner">x</artifact> after'
        )


class TestEmitArtifactStreamEvents:
    @pytest.mark.anyio
    async def test_emits_ws_messages_and_updates_interleaved_blocks(self, monkeypatch):
        artifact_payload = {
            "type": "artifact",
            "artifact_id": "artifact-1",
            "artifact_type": "code",
            "title": "Demo",
            "language": "python",
            "size_bytes": 11,
            "line_count": 1,
            "status": "ready",
            "content": 'print("hi")',
        }
        broadcast_mock = AsyncMock()
        monkeypatch.setattr(
            "source.llm.core.artifacts.broadcast_message",
            broadcast_mock,
        )

        interleaved_blocks = []
        text = await emit_artifact_stream_events(
            [
                {"type": "text", "content": "Intro "},
                {
                    "type": "artifact_start",
                    "artifact": {
                        **artifact_payload,
                        "status": "streaming",
                        "content": None,
                        "size_bytes": 0,
                        "line_count": 0,
                    },
                },
                {"type": "artifact_complete", "artifact": artifact_payload},
                {"type": "artifact_abandoned", "artifact_id": "artifact-2"},
            ],
            interleaved_blocks,
        )

        assert text == "Intro "
        assert interleaved_blocks == [
            {"type": "text", "content": "Intro "},
            artifact_payload,
        ]
        assert broadcast_mock.await_args_list[0].args == ("response_chunk", "Intro ")
        assert broadcast_mock.await_args_list[1].args == (
            "artifact_start",
            {
                **artifact_payload,
                "status": "streaming",
                "content": None,
                "size_bytes": 0,
                "line_count": 0,
            },
        )
        assert broadcast_mock.await_args_list[2].args == (
            "artifact_complete",
            artifact_payload,
        )
        assert broadcast_mock.await_args_list[3].args == (
            "artifact_deleted",
            {"artifact_id": "artifact-2", "reason": "abandoned"},
        )
