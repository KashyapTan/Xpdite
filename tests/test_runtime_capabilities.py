"""Tests for build capability manifest validation and effective probes."""

import json

import pytest

from source.infrastructure import runtime_capabilities as capabilities


@pytest.fixture(autouse=True)
def _reset_capability_cache(monkeypatch):
    monkeypatch.setattr(capabilities, "_cached_capabilities", None)
    yield
    monkeypatch.setattr(capabilities, "_cached_capabilities", None)


def _manifest(profile="mac-intel-transcription"):
    intel = profile == "mac-intel-transcription"
    return {
        "schema_version": 1,
        "profile": profile,
        "platform": "darwin",
        "architecture": "x64" if intel else "arm64",
        "features": {
            "microphone_dictation": True,
            "meeting_transcription": True,
            "youtube_whisper_fallback": True,
            "whisperx_alignment": not intel,
            "speaker_diarization": not intel,
            "local_sentence_embeddings": not intel,
        },
    }


def _passing_probes():
    return {
        "faster_whisper": True,
        "ctranslate2": True,
        "onnxruntime": True,
        "pyaudio": True,
        "whisperx": True,
        "torch": True,
        "pyannote": True,
        "sentence_transformers": True,
        "bundled_embedding_model": True,
    }


def test_manifest_parser_rejects_partial_and_malformed_schemas():
    valid = capabilities.parse_capability_manifest(_manifest())
    assert valid["profile"] == "mac-intel-transcription"

    malformed = _manifest()
    del malformed["features"]["meeting_transcription"]
    with pytest.raises(ValueError, match="feature set"):
        capabilities.parse_capability_manifest(malformed)

    malformed = _manifest()
    malformed["features"]["microphone_dictation"] = "yes"
    with pytest.raises(ValueError, match="booleans"):
        capabilities.parse_capability_manifest(malformed)


def test_intel_manifest_keeps_transcription_and_explains_advanced_omissions():
    result = capabilities.resolve_effective_capabilities(
        _manifest(), _passing_probes()
    )

    assert result["features"]["meeting_transcription"] == {
        "available": True,
        "reason": "",
    }
    assert result["features"]["speaker_diarization"] == {
        "available": False,
        "reason": "Unavailable in the Intel macOS build.",
    }
    assert result["features"]["local_sentence_embeddings"]["available"] is False


def test_probe_failure_downgrades_only_dependent_features():
    probes = _passing_probes()
    probes["pyaudio"] = False
    result = capabilities.resolve_effective_capabilities(_manifest("full"), probes)

    assert result["features"]["microphone_dictation"]["available"] is False
    assert result["features"]["meeting_transcription"]["available"] is True
    assert result["features"]["speaker_diarization"]["available"] is True


def test_initialize_reads_manifest_and_never_returns_build_paths(tmp_path):
    manifest_path = tmp_path / "build-capabilities.json"
    manifest_path.write_text(json.dumps(_manifest()), encoding="utf-8")

    result = capabilities.initialize_runtime_capabilities(
        force=True,
        manifest_path=str(manifest_path),
        probe_runner=_passing_probes,
    )

    assert result["architecture"] == "x64"
    assert str(tmp_path) not in json.dumps(result)


def test_invalid_packaged_manifest_fails_closed(tmp_path):
    manifest_path = tmp_path / "build-capabilities.json"
    manifest_path.write_text("{}", encoding="utf-8")

    result = capabilities.initialize_runtime_capabilities(
        force=True,
        manifest_path=str(manifest_path),
        probe_runner=_passing_probes,
    )

    assert result["profile"] == "unknown"
    assert all(not feature["available"] for feature in result["features"].values())
