"""Tests for MeetingAnalysisService — parsing, transcript extraction, and end-time calc."""

import json
import importlib
import sys
import types
from types import SimpleNamespace
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Import helpers — these static methods don't need any external services
# ---------------------------------------------------------------------------


def _get_service_class():
    """Import MeetingAnalysisService with startup recovery side effects neutralized."""
    with patch("source.database.db.get_meeting_recordings", return_value=[]):
        module = importlib.import_module("source.services.meeting_recorder")
    return module.MeetingAnalysisService


# ===========================================================================
# _parse_analysis_response
# ===========================================================================


class TestParseAnalysisResponse:
    """Test the LLM JSON parsing logic."""

    @pytest.fixture()
    def parse(self):
        cls = _get_service_class()
        return cls._parse_analysis_response

    def test_valid_json(self, parse):
        raw = json.dumps(
            {
                "summary": "They discussed the quarterly goals.",
                "actions": [
                    {
                        "type": "calendar_event",
                        "title": "Follow-up",
                        "date": "2025-04-01",
                    },
                    {"type": "email", "to": "alice@example.com", "subject": "Notes"},
                ],
            }
        )
        result = parse(raw)
        assert result["summary"] == "They discussed the quarterly goals."
        assert len(result["actions"]) == 2
        assert result["actions"][0]["type"] == "calendar_event"
        assert result["actions"][1]["type"] == "email"

    def test_json_in_code_fence(self, parse):
        raw = (
            "Here is my analysis:\n"
            "```json\n"
            '{"summary": "Short meeting.", "actions": []}\n'
            "```\n"
        )
        result = parse(raw)
        assert result["summary"] == "Short meeting."
        assert result["actions"] == []

    def test_json_in_bare_code_fence(self, parse):
        raw = '```\n{"summary": "Bare fence.", "actions": []}\n```'
        result = parse(raw)
        assert result["summary"] == "Bare fence."

    def test_unclosed_code_fence(self, parse):
        raw = '```json\n{"summary": "No closing fence.", "actions": []}'
        result = parse(raw)
        assert result["summary"] == "No closing fence."

    def test_invalid_json_falls_back_to_raw(self, parse):
        raw = "This is not JSON at all, just a plain text summary."
        result = parse(raw)
        assert result["summary"] == raw
        assert result["actions"] == []
        assert result.get("parse_error") is True

    def test_truncates_long_raw_fallback(self, parse):
        raw = "X" * 2000
        result = parse(raw)
        assert len(result["summary"]) == 1000

    def test_filters_unknown_action_types(self, parse):
        raw = json.dumps(
            {
                "summary": "Test",
                "actions": [
                    {"type": "calendar_event", "title": "OK"},
                    {"type": "invalid_type", "title": "Bad"},
                    {"type": "task", "description": "Also OK"},
                ],
            }
        )
        result = parse(raw)
        assert len(result["actions"]) == 2
        types = [a["type"] for a in result["actions"]]
        assert "invalid_type" not in types

    def test_filters_non_dict_actions(self, parse):
        raw = json.dumps(
            {
                "summary": "Test",
                "actions": ["not a dict", 42, {"type": "email", "to": "x@y.com"}],
            }
        )
        result = parse(raw)
        assert len(result["actions"]) == 1
        assert result["actions"][0]["type"] == "email"

    def test_empty_actions_array(self, parse):
        raw = json.dumps({"summary": "Nothing actionable.", "actions": []})
        result = parse(raw)
        assert result["summary"] == "Nothing actionable."
        assert result["actions"] == []

    def test_missing_summary_defaults_empty(self, parse):
        raw = json.dumps({"actions": [{"type": "task", "description": "do stuff"}]})
        result = parse(raw)
        assert result["summary"] == ""
        assert len(result["actions"]) == 1

    def test_missing_actions_defaults_empty(self, parse):
        raw = json.dumps({"summary": "Just a summary."})
        result = parse(raw)
        assert result["actions"] == []

    def test_non_list_actions_is_tolerated(self, parse):
        raw = json.dumps({"summary": "Test", "actions": "not-a-list"})
        result = parse(raw)
        assert result["summary"] == "Test"
        assert result["actions"] == []

    def test_json_code_fence_with_invalid_payload_falls_back(self, parse):
        raw = "```json\n{not valid json}\n```"
        result = parse(raw)
        assert result["summary"] == raw
        assert result["actions"] == []
        assert result.get("parse_error") is True


# ===========================================================================
# _extract_transcript_text
# ===========================================================================


class TestExtractTranscriptText:
    """Test transcript extraction from recording dicts."""

    @pytest.fixture()
    def extract(self):
        cls = _get_service_class()
        # Instance method — create lightweight instance
        service = cls.__new__(cls)
        return service._extract_transcript_text

    def test_tier2_json_string(self, extract):
        recording = {
            "tier2_transcript_json": json.dumps(
                [
                    {"speaker": "Alice", "text": "Hello."},
                    {"speaker": "Bob", "text": "Hi there."},
                ]
            ),
            "tier1_transcript": "hello hi there",
        }
        result = extract(recording)
        assert "Alice: Hello." in result
        assert "Bob: Hi there." in result

    def test_tier2_list_directly(self, extract):
        recording = {
            "tier2_transcript_json": [
                {"speaker": "Alice", "text": "OK"},
            ],
            "tier1_transcript": "",
        }
        result = extract(recording)
        assert "Alice: OK" in result

    def test_tier2_without_speaker(self, extract):
        recording = {
            "tier2_transcript_json": json.dumps(
                [
                    {"text": "No speaker label."},
                ]
            ),
            "tier1_transcript": "",
        }
        result = extract(recording)
        assert result == "No speaker label."

    def test_falls_back_to_tier1(self, extract):
        recording = {
            "tier2_transcript_json": None,
            "tier1_transcript": "Just basic transcription text.",
        }
        result = extract(recording)
        assert result == "Just basic transcription text."

    def test_tier2_empty_list_falls_back(self, extract):
        recording = {
            "tier2_transcript_json": "[]",
            "tier1_transcript": "Tier 1 fallback.",
        }
        result = extract(recording)
        assert result == "Tier 1 fallback."

    def test_tier2_corrupted_json(self, extract):
        recording = {
            "tier2_transcript_json": "not valid json {{{",
            "tier1_transcript": "Safe fallback.",
        }
        result = extract(recording)
        assert result == "Safe fallback."

    def test_both_empty(self, extract):
        recording = {
            "tier2_transcript_json": None,
            "tier1_transcript": "",
        }
        result = extract(recording)
        assert result == ""

    def test_tier1_missing_key(self, extract):
        recording = {"tier2_transcript_json": None}
        result = extract(recording)
        assert result == ""


# ===========================================================================
# _calc_end_time (from handlers)
# ===========================================================================


class TestCalcEndTime:
    """Test the end-time calculation helper on the handler."""

    @pytest.fixture()
    def calc(self):
        from source.api.handlers import MessageHandler

        return MessageHandler._calc_end_time

    def test_30_min_duration(self, calc):
        result = calc("2025-04-01", "09:00", 30)
        assert result == "2025-04-01T09:30:00"

    def test_60_min_duration(self, calc):
        result = calc("2025-04-01", "14:30", 60)
        assert result == "2025-04-01T15:30:00"

    def test_crosses_hour_boundary(self, calc):
        result = calc("2025-04-01", "23:45", 30)
        assert result == "2025-04-02T00:15:00"

    def test_zero_duration(self, calc):
        result = calc("2025-04-01", "10:00", 0)
        assert result == "2025-04-01T10:00:00"

    def test_invalid_date_returns_fallback(self, calc):
        result = calc("not-a-date", "09:00", 30)
        assert result == "not-a-dateT09:00:00"

    def test_invalid_time_returns_fallback(self, calc):
        result = calc("2025-04-01", "xx:yy", 30)
        assert result == "2025-04-01Txx:yy:00"


# ===========================================================================
# _build_analysis_prompt
# ===========================================================================


class TestBuildAnalysisPrompt:
    """Test the prompt builder."""

    @pytest.fixture()
    def build(self):
        cls = _get_service_class()
        service = cls.__new__(cls)
        return service._build_analysis_prompt

    def test_includes_transcript(self, build):
        prompt = build("Alice: Let's schedule the review.")
        assert "Alice: Let's schedule the review." in prompt

    def test_includes_json_format(self, build):
        prompt = build("test transcript")
        assert '"summary"' in prompt
        assert '"actions"' in prompt
        assert '"calendar_event"' in prompt
        assert '"email"' in prompt
        assert '"task"' in prompt

    def test_includes_instructions(self, build):
        prompt = build("test transcript")
        assert "concise summary" in prompt.lower() or "3-5 sentences" in prompt

    def test_prompt_is_string(self, build):
        prompt = build("test")
        assert isinstance(prompt, str)
        assert len(prompt) > 100


# ===========================================================================
# _merge_results — speaker label mapping
# ===========================================================================


def _get_pipeline_class():
    """Import PostProcessingPipeline with startup recovery side effects neutralized."""
    with patch("source.database.db.get_meeting_recordings", return_value=[]):
        module = importlib.import_module("source.services.meeting_recorder")
    return module.PostProcessingPipeline


class TestMergeResultsSpeakerLabels:
    """Test that _merge_results maps SPEAKER_XX to friendly labels."""

    @pytest.fixture()
    def pipeline(self):
        cls = _get_pipeline_class()
        # _merge_results is called on an instance but only uses self for the
        # logger; we can create one with a mock recorder.
        from unittest.mock import MagicMock

        return cls(MagicMock())

    def test_no_diarization_returns_base(self, pipeline):
        segments = [{"text": "hello", "start": 0, "end": 1}]
        result = pipeline._merge_results(segments, None, None)
        assert result == segments

    def test_aligned_preferred_over_transcript(self, pipeline):
        transcript = [{"text": "raw", "start": 0, "end": 1}]
        aligned = [{"text": "aligned", "start": 0, "end": 1}]
        result = pipeline._merge_results(transcript, aligned, None)
        assert result == aligned

    def test_speaker_labels_are_mapped_when_assignment_succeeds(
        self, pipeline, monkeypatch
    ):
        segments = [
            {"text": "hi", "start": 0, "end": 1, "speaker": "SPEAKER_00"},
            {"text": "hey", "start": 1, "end": 2, "speaker": "SPEAKER_01"},
        ]

        def _assign_word_speakers(_diarization, payload):
            return {"segments": payload["segments"]}

        monkeypatch.setitem(
            sys.modules,
            "whisperx",
            types.SimpleNamespace(assign_word_speakers=_assign_word_speakers),
        )

        result = pipeline._merge_results(segments, None, {"mock": True})
        assert [seg.get("speaker") for seg in result] == ["Speaker 1", "Speaker 2"]

    def test_speaker_labels_fall_back_when_assignment_fails(
        self, pipeline, monkeypatch
    ):
        segments = [
            {"text": "hi", "start": 0, "end": 1, "speaker": "SPEAKER_00"},
            {"text": "hey", "start": 1, "end": 2, "speaker": "SPEAKER_01"},
        ]

        def _assign_word_speakers(_diarization, _payload):
            raise RuntimeError("assignment failed")

        monkeypatch.setitem(
            sys.modules,
            "whisperx",
            types.SimpleNamespace(assign_word_speakers=_assign_word_speakers),
        )

        result = pipeline._merge_results(segments, None, {"mock": True})
        assert [seg.get("speaker") for seg in result] == ["SPEAKER_00", "SPEAKER_01"]


# ===========================================================================
# _call_llm — provider routing
# ===========================================================================


class TestCallLlm:
    @pytest.fixture()
    def call_llm(self):
        cls = _get_service_class()
        return cls._call_llm

    def test_openrouter_uses_litellm(self, call_llm):
        fake_response = SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content="OpenRouter summary"))
            ]
        )

        with (
            patch("source.llm.key_manager.key_manager") as mock_key_manager,
            patch("litellm.completion", return_value=fake_response) as mock_completion,
        ):
            mock_key_manager.get_api_key.return_value = "or-test-key"

            result = call_llm(
                "Summarize this meeting",
                model="openrouter/anthropic/claude-3-5-sonnet",
            )

        assert result == "OpenRouter summary"
        kwargs = mock_completion.call_args.kwargs
        assert kwargs["model"] == "openrouter/anthropic/claude-3-5-sonnet"
        assert kwargs["api_key"] == "or-test-key"
        assert kwargs["timeout"] == 120

    def test_ollama_uses_litellm_with_api_base(self, call_llm, monkeypatch):
        fake_response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Ollama summary"))]
        )
        monkeypatch.setenv("OLLAMA_API_BASE", "https://ollama.example.com")
        monkeypatch.setenv("OLLAMA_API_KEY", "test-key")

        with patch("litellm.completion", return_value=fake_response) as mock_completion:
            result = call_llm(
                "Summarize this meeting",
                model="ollama/qwen3-coder-next:cloud",
            )

        assert result == "Ollama summary"
        kwargs = mock_completion.call_args.kwargs
        assert kwargs["model"] == "ollama_chat/qwen3-coder-next:cloud"
        assert kwargs["api_base"] == "http://localhost:11434"
        assert kwargs["timeout"] == 120
        assert "api_key" not in kwargs

    def test_anthropic_includes_max_tokens(self, call_llm):
        fake_response = SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content="Anthropic summary"))
            ]
        )

        with (
            patch("source.llm.key_manager.key_manager") as mock_key_manager,
            patch("litellm.get_model_info", return_value={"max_output_tokens": 8192}),
            patch("litellm.completion", return_value=fake_response) as mock_completion,
        ):
            mock_key_manager.get_api_key.return_value = "anthropic-test-key"

            result = call_llm(
                "Summarize this meeting",
                model="anthropic/claude-sonnet-4-20250514",
            )

        assert result == "Anthropic summary"
        kwargs = mock_completion.call_args.kwargs
        assert kwargs["model"] == "anthropic/claude-sonnet-4-20250514"
        assert kwargs["api_key"] == "anthropic-test-key"
        assert kwargs["max_tokens"] == 8192
        assert kwargs["timeout"] == 120
