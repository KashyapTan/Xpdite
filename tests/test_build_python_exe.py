"""Unit tests for profile-aware PyInstaller preparation and cache stamps."""

import importlib.util
import json
from pathlib import Path

import pytest


_SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "build-python-exe.py"
_SPEC = importlib.util.spec_from_file_location("xpdite_build_python_exe", _SCRIPT_PATH)
assert _SPEC and _SPEC.loader
build_python_exe = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(build_python_exe)


def _project_tree(tmp_path: Path) -> Path:
    for directory in ("source", "mcp_servers", "scripts"):
        (tmp_path / directory).mkdir()
    for relative_path in (
        "source/main.py",
        "mcp_servers/server.py",
        "build-server.spec",
        "scripts/build-python-exe.py",
        "pyproject.toml",
        "requirements.txt",
    ):
        (tmp_path / relative_path).write_text(relative_path, encoding="utf-8")
    (tmp_path / "uv.lock").write_text("lock-one", encoding="utf-8")
    return tmp_path


def test_profile_controls_bundled_embedding_requirement():
    assert build_python_exe.local_embeddings_enabled("full") is True
    assert (
        build_python_exe.local_embeddings_enabled("mac-intel-transcription") is False
    )


def test_python_architecture_validation_rejects_mismatch(monkeypatch):
    monkeypatch.setenv("XPDITE_TARGET_ARCH", "x64")
    with pytest.raises(RuntimeError, match="expected x86_64"):
        build_python_exe.validate_python_architecture({"machine": "arm64"})

    build_python_exe.validate_python_architecture({"machine": "AMD64"})


def test_cache_stamp_changes_with_profile_architecture_python_and_lockfile(
    tmp_path, monkeypatch
):
    project_root = _project_tree(tmp_path)
    identity = {
        "executable": "/python/3.13/bin/python",
        "machine": "arm64",
        "version": "3.13",
    }
    monkeypatch.setenv("XPDITE_TARGET_PLATFORM", "darwin")
    monkeypatch.setenv("XPDITE_TARGET_ARCH", "arm64")
    full = build_python_exe.build_stamp(project_root, "full", identity)

    monkeypatch.setenv("XPDITE_TARGET_ARCH", "x64")
    intel = build_python_exe.build_stamp(
        project_root,
        "mac-intel-transcription",
        {**identity, "machine": "x86_64"},
    )
    assert full != intel

    (project_root / "uv.lock").write_text("lock-two", encoding="utf-8")
    changed_lock = build_python_exe.build_stamp(project_root, "full", identity)
    assert changed_lock["lockfile_sha256"] != full["lockfile_sha256"]


def test_intel_cache_does_not_require_sentence_transformers(tmp_path):
    project_root = _project_tree(tmp_path)
    dist_dir = project_root / "dist-python"
    output_dir = dist_dir / "xpdite-server"
    output_dir.mkdir(parents=True)
    executable = output_dir / "xpdite-server"
    executable.write_text("binary", encoding="utf-8")
    (output_dir / "libportaudio.2.dylib").write_text("library", encoding="utf-8")
    stamp = {
        "profile": "mac-intel-transcription",
        "schema": 1,
        "target": {"platform": "darwin"},
    }
    (dist_dir / ".build-stamp.json").write_text(
        json.dumps(stamp), encoding="utf-8"
    )

    assert build_python_exe.is_python_server_up_to_date(
        project_root,
        executable,
        stamp,
        require_local_embeddings=False,
    )
    assert not build_python_exe.is_python_server_up_to_date(
        project_root,
        executable,
        stamp,
        require_local_embeddings=True,
    )
