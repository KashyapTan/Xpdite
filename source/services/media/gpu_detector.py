"""GPU Compute Detection.

Detects the best available compute backend for Whisper model inference.
Called once at startup, cached as module-level singleton.
"""

import logging

logger = logging.getLogger(__name__)

# Cached result
_cached_backend: dict | None = None


def detect_compute_backend() -> str:
    """Detect the best GPU backend: 'cuda' or 'cpu'."""
    info = get_compute_info()
    return info["backend"]


def get_compute_info() -> dict:
    """Return detailed compute backend information.

    Returns dict with:
    - backend: 'cuda' | 'cpu'
    - device_name: GPU name or 'CPU'
    - vram_gb: float (0.0 for CPU)
    - compute_type: recommended compute type for faster-whisper
    """
    global _cached_backend
    if _cached_backend is not None:
        return _cached_backend

    # Try CUDA first
    try:
        import torch

        if torch.cuda.is_available():
            device_name = torch.cuda.get_device_name(0)
            vram = torch.cuda.get_device_properties(0).total_mem / (1024**3)
            _cached_backend = {
                "backend": "cuda",
                "device_name": device_name,
                "vram_gb": round(vram, 1),
                "compute_type": "float16" if vram >= 4.0 else "int8",
            }
            logger.info(
                "GPU detected: %s (%.1f GB VRAM) — using CUDA",
                device_name,
                vram,
            )
            return _cached_backend
    except ImportError:
        logger.debug("torch not installed — CUDA detection skipped")
    except Exception as e:
        logger.warning("CUDA detection failed: %s", e)

    # Fallback to CPU
    _cached_backend = {
        "backend": "cpu",
        "device_name": "CPU",
        "vram_gb": 0.0,
        "compute_type": "int8",
    }
    logger.info("No GPU detected — using CPU for transcription")
    return _cached_backend


def get_estimated_processing_time(audio_duration_seconds: float) -> float:
    """Estimate Tier 2 processing time based on compute backend.

    Returns estimated seconds.
    """
    info = get_compute_info()
    backend = info["backend"]

    if backend == "cuda":
        # ~0.15x audio duration
        return audio_duration_seconds * 0.15
    else:
        # ~1.5x audio duration for CPU
        return audio_duration_seconds * 1.5
