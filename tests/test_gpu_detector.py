"""Tests for source/services/media/gpu_detector.py."""

import sys
from types import SimpleNamespace

from source.services.media import gpu_detector


class _FakeCuda:
    def __init__(self, available: bool, total_mem_bytes: int = 0):
        self._available = available
        self._total_mem_bytes = total_mem_bytes

    def is_available(self):
        return self._available

    def get_device_name(self, _index: int):
        return "RTX Mock"

    def get_device_properties(self, _index: int):
        return SimpleNamespace(total_mem=self._total_mem_bytes)


class _FakeTorch:
    def __init__(self, cuda: _FakeCuda):
        self.cuda = cuda


class TestGpuDetector:
    def setup_method(self):
        gpu_detector._cached_backend = None

    def teardown_method(self):
        gpu_detector._cached_backend = None
        sys.modules.pop("torch", None)

    def test_detect_compute_backend_returns_backend_value(self, monkeypatch):
        monkeypatch.setattr(
            gpu_detector,
            "get_compute_info",
            lambda: {
                "backend": "cpu",
                "device_name": "CPU",
                "vram_gb": 0.0,
                "compute_type": "int8",
            },
        )
        assert gpu_detector.detect_compute_backend() == "cpu"

    def test_get_compute_info_uses_cache(self):
        gpu_detector._cached_backend = {
            "backend": "cpu",
            "device_name": "CPU",
            "vram_gb": 0.0,
            "compute_type": "int8",
        }
        result = gpu_detector.get_compute_info()
        assert result["backend"] == "cpu"
        assert result is gpu_detector._cached_backend

    def test_get_compute_info_detects_cuda_float16(self):
        sys.modules["torch"] = _FakeTorch(
            _FakeCuda(available=True, total_mem_bytes=int(6 * (1024**3)))
        )
        result = gpu_detector.get_compute_info()
        assert result["backend"] == "cuda"
        assert result["device_name"] == "RTX Mock"
        assert result["compute_type"] == "float16"
        assert result["vram_gb"] == 6.0

    def test_get_compute_info_detects_cuda_int8_for_low_vram(self):
        sys.modules["torch"] = _FakeTorch(
            _FakeCuda(available=True, total_mem_bytes=int(3.5 * (1024**3)))
        )
        result = gpu_detector.get_compute_info()
        assert result["backend"] == "cuda"
        assert result["compute_type"] == "int8"

    def test_get_compute_info_falls_back_when_torch_missing(self):
        sys.modules.pop("torch", None)
        result = gpu_detector.get_compute_info()
        assert result["backend"] == "cpu"
        assert result["compute_type"] == "int8"

    def test_get_compute_info_falls_back_on_cuda_error(self):
        class _BrokenCuda:
            def is_available(self):
                raise RuntimeError("cuda broken")

        sys.modules["torch"] = SimpleNamespace(cuda=_BrokenCuda())
        result = gpu_detector.get_compute_info()
        assert result["backend"] == "cpu"

    def test_estimated_processing_time_uses_backend_multiplier(self, monkeypatch):
        monkeypatch.setattr(
            gpu_detector, "get_compute_info", lambda: {"backend": "cuda"}
        )
        assert gpu_detector.get_estimated_processing_time(100.0) == 15.0

        monkeypatch.setattr(
            gpu_detector, "get_compute_info", lambda: {"backend": "cpu"}
        )
        assert gpu_detector.get_estimated_processing_time(10.0) == 15.0
