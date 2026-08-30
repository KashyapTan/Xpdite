"""Build capability metadata and effective native dependency probes."""

from __future__ import annotations

import importlib
import json
import logging
import platform
import sys
import threading
from pathlib import Path
from typing import Any, Callable

from .config import (
    BUILD_CAPABILITIES_PATH,
    IS_PACKAGED_RUNTIME,
    RUNTIME_ROOT,
)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
FEATURES = (
    "microphone_dictation",
    "meeting_transcription",
    "youtube_whisper_fallback",
    "whisperx_alignment",
    "speaker_diarization",
    "local_sentence_embeddings",
)
KNOWN_PROFILES = {"full", "mac-intel-transcription"}

_cache_lock = threading.Lock()
_cached_capabilities: dict[str, Any] | None = None


def _normalized_architecture() -> str:
    machine = platform.machine().lower()
    return "x64" if machine in {"x86_64", "amd64"} else "arm64" if machine in {
        "arm64",
        "aarch64",
    } else machine


def parse_capability_manifest(payload: Any) -> dict[str, Any]:
    """Validate immutable build metadata without accepting partial schemas."""
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported capability manifest schema")
    if payload.get("profile") not in KNOWN_PROFILES:
        raise ValueError("unknown capability build profile")
    if not isinstance(payload.get("platform"), str) or not payload["platform"]:
        raise ValueError("missing capability platform")
    if payload.get("architecture") not in {"arm64", "x64"}:
        raise ValueError("invalid capability architecture")

    features = payload.get("features")
    if not isinstance(features, dict) or set(features) != set(FEATURES):
        raise ValueError("invalid capability feature set")
    if not all(isinstance(features[name], bool) for name in FEATURES):
        raise ValueError("capability feature values must be booleans")

    return {
        "schema_version": SCHEMA_VERSION,
        "profile": payload["profile"],
        "platform": payload["platform"],
        "architecture": payload["architecture"],
        "features": {name: features[name] for name in FEATURES},
    }


def _read_manifest(manifest_path: str) -> dict[str, Any]:
    payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    return parse_capability_manifest(payload)


def _development_manifest() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "profile": "development",
        "platform": sys.platform,
        "architecture": _normalized_architecture(),
        "features": {name: True for name in FEATURES},
    }


def _safe_import(module_name: str) -> bool:
    try:
        importlib.import_module(module_name)
        return True
    except Exception as error:
        logger.warning(
            "Runtime capability probe failed: module=%s error_type=%s",
            module_name,
            type(error).__name__,
        )
        return False


def _probe_pyaudio() -> bool:
    try:
        pyaudio = importlib.import_module("pyaudio")
        audio = pyaudio.PyAudio()
        audio.terminate()
        return True
    except Exception as error:
        logger.warning(
            "Runtime capability probe failed: module=pyaudio error_type=%s",
            type(error).__name__,
        )
        return False


def _bundled_embedding_model_exists() -> bool:
    if not IS_PACKAGED_RUNTIME:
        return True
    candidates = [
        RUNTIME_ROOT / "embedding-models" / "all-MiniLM-L6-v2",
        Path(getattr(sys, "_MEIPASS", ""))
        / "embedding-models"
        / "all-MiniLM-L6-v2",
    ]
    required = ("config.json", "modules.json", "model.safetensors")
    return any(
        candidate.is_dir()
        and all((candidate / file_name).is_file() for file_name in required)
        for candidate in candidates
    )


def run_capability_probes() -> dict[str, bool]:
    """Probe native imports once; callers receive only product-level booleans."""
    return {
        "faster_whisper": _safe_import("faster_whisper"),
        "ctranslate2": _safe_import("ctranslate2"),
        "onnxruntime": _safe_import("onnxruntime"),
        "pyaudio": _probe_pyaudio(),
        "whisperx": _safe_import("whisperx"),
        "torch": _safe_import("torch"),
        "pyannote": _safe_import("pyannote.audio"),
        "sentence_transformers": _safe_import("sentence_transformers"),
        "bundled_embedding_model": _bundled_embedding_model_exists(),
    }


def _unavailable_in_build_reason(profile: str, feature: str) -> str:
    if profile == "mac-intel-transcription" and feature in {
        "whisperx_alignment",
        "speaker_diarization",
    }:
        return "Unavailable in the Intel macOS build."
    if feature == "local_sentence_embeddings":
        return "Bundled Sentence Transformers are unavailable in this build."
    return "Unavailable in this build."


def resolve_effective_capabilities(
    manifest: dict[str, Any], probes: dict[str, bool]
) -> dict[str, Any]:
    requirements = {
        "microphone_dictation": (
            "faster_whisper",
            "ctranslate2",
            "onnxruntime",
            "pyaudio",
        ),
        "meeting_transcription": ("faster_whisper", "ctranslate2", "onnxruntime"),
        "youtube_whisper_fallback": (
            "faster_whisper",
            "ctranslate2",
            "onnxruntime",
        ),
        "whisperx_alignment": ("whisperx", "torch"),
        "speaker_diarization": ("whisperx", "torch", "pyannote"),
        "local_sentence_embeddings": (
            "sentence_transformers",
            "bundled_embedding_model",
        ),
    }
    probe_failure_reasons = {
        "microphone_dictation": "Microphone audio components could not load.",
        "meeting_transcription": "Local transcription components could not load.",
        "youtube_whisper_fallback": "Local transcription components could not load.",
        "whisperx_alignment": "Advanced alignment components could not load.",
        "speaker_diarization": "Speaker diarization components could not load.",
        "local_sentence_embeddings": "Local embedding components could not load.",
    }

    effective_features: dict[str, dict[str, Any]] = {}
    for feature in FEATURES:
        if not manifest["features"][feature]:
            effective_features[feature] = {
                "available": False,
                "reason": _unavailable_in_build_reason(manifest["profile"], feature),
            }
            continue

        missing = [name for name in requirements[feature] if not probes.get(name, False)]
        if missing:
            logger.warning(
                "Runtime feature unavailable: feature=%s failed_probes=%s",
                feature,
                ",".join(missing),
            )
            effective_features[feature] = {
                "available": False,
                "reason": probe_failure_reasons[feature],
            }
        else:
            effective_features[feature] = {"available": True, "reason": ""}

    return {
        "profile": manifest["profile"],
        "platform": manifest["platform"],
        "architecture": manifest["architecture"],
        "features": effective_features,
    }


def initialize_runtime_capabilities(
    *,
    force: bool = False,
    manifest_path: str | None = None,
    probe_runner: Callable[[], dict[str, bool]] = run_capability_probes,
) -> dict[str, Any]:
    global _cached_capabilities

    with _cache_lock:
        if _cached_capabilities is not None and not force:
            return _cached_capabilities

        selected_path = BUILD_CAPABILITIES_PATH if manifest_path is None else manifest_path
        if selected_path:
            try:
                manifest = _read_manifest(selected_path)
            except (OSError, ValueError, json.JSONDecodeError) as error:
                logger.error(
                    "Invalid build capability manifest: error_type=%s",
                    type(error).__name__,
                )
                manifest = {
                    "schema_version": SCHEMA_VERSION,
                    "profile": "unknown",
                    "platform": sys.platform,
                    "architecture": _normalized_architecture(),
                    "features": {name: False for name in FEATURES},
                }
        else:
            manifest = _development_manifest()

        probes = probe_runner()
        _cached_capabilities = resolve_effective_capabilities(manifest, probes)
        return _cached_capabilities


def get_runtime_capabilities() -> dict[str, Any]:
    return initialize_runtime_capabilities()


def get_feature_status(feature: str) -> dict[str, Any]:
    if feature not in FEATURES:
        raise KeyError(f"Unknown runtime capability: {feature}")
    return get_runtime_capabilities()["features"][feature]


def feature_available(feature: str) -> bool:
    return bool(get_feature_status(feature)["available"])
