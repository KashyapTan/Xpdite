"""Tests for source/infrastructure/config.py — verify constants and CaptureMode."""

import importlib

from source.infrastructure.config import (
    DEFAULT_PORT,
    MAX_PORT_ATTEMPTS,
    DEFAULT_MODEL,
    MAX_MCP_TOOL_ROUNDS,
    OLLAMA_CTX_SIZE,
    MAX_TOOL_RESULT_LENGTH,
    THREAD_POOL_SIZE,
    TERMINAL_MAX_OUTPUT_SIZE,
    CaptureMode,
    SCREENSHOT_FOLDER,
    PROJECT_ROOT,
    SOURCE_DIR,
)


class TestConstants:
    def test_default_port(self):
        assert DEFAULT_PORT == 8000

    def test_max_port_attempts(self):
        assert MAX_PORT_ATTEMPTS == 10

    def test_default_model_is_string(self):
        assert isinstance(DEFAULT_MODEL, str)
        assert len(DEFAULT_MODEL) > 0

    def test_max_mcp_tool_rounds(self):
        assert MAX_MCP_TOOL_ROUNDS == 50

    def test_ollama_ctx_size(self):
        assert OLLAMA_CTX_SIZE == 32768

    def test_max_tool_result_length(self):
        assert MAX_TOOL_RESULT_LENGTH == 200_000

    def test_thread_pool_size_positive(self):
        assert THREAD_POOL_SIZE >= 1

    def test_terminal_max_output_size(self):
        assert TERMINAL_MAX_OUTPUT_SIZE == 50 * 1024

    def test_screenshot_folder_defined(self):
        assert isinstance(SCREENSHOT_FOLDER, str)
        assert "screenshots" in SCREENSHOT_FOLDER

    def test_project_root_exists(self):
        import os
        assert os.path.isdir(str(PROJECT_ROOT))

    def test_source_dir_exists(self):
        import os
        assert os.path.isdir(str(SOURCE_DIR))


class TestCaptureMode:
    def test_fullscreen(self):
        assert CaptureMode.FULLSCREEN == "fullscreen"

    def test_precision(self):
        assert CaptureMode.PRECISION == "precision"

    def test_none(self):
        assert CaptureMode.NONE == "none"


class TestRuntimeEnvLoading:
    def test_packaged_runtime_env_file_loads_google_credentials(
        self, tmp_path, monkeypatch
    ):
        env_file = tmp_path / "google-oauth.env"
        env_file.write_text(
            "GOOGLE_CLIENT_ID=test-client.apps.googleusercontent.com\n"
            "GOOGLE_CLIENT_SECRET=test-secret\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("XPDITE_RUNTIME_ROOT", str(tmp_path))
        monkeypatch.setenv("XPDITE_RUNTIME_ENV_FILE", str(env_file))
        monkeypatch.setenv("XPDITE_USER_DATA_DIR", str(tmp_path / "user-data"))
        monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
        monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)

        import source.infrastructure.config as config_module

        reloaded = importlib.reload(config_module)

        assert reloaded.IS_PACKAGED_RUNTIME is True
        assert reloaded.GOOGLE_CLIENT_ID == "test-client.apps.googleusercontent.com"
        assert reloaded.GOOGLE_CLIENT_SECRET == "test-secret"
        assert reloaded.GOOGLE_CLIENT_CONFIG is not None
        monkeypatch.delenv("XPDITE_RUNTIME_ROOT", raising=False)
        monkeypatch.delenv("XPDITE_RUNTIME_ENV_FILE", raising=False)
        monkeypatch.delenv("XPDITE_USER_DATA_DIR", raising=False)
        importlib.reload(config_module)

    def test_packaged_runtime_missing_google_credentials_sets_clear_error(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("XPDITE_RUNTIME_ROOT", str(tmp_path))
        monkeypatch.setenv("XPDITE_RUNTIME_ENV_FILE", str(tmp_path / "missing.env"))
        monkeypatch.setenv("XPDITE_USER_DATA_DIR", str(tmp_path / "user-data"))
        monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
        monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)

        import source.infrastructure.config as config_module

        reloaded = importlib.reload(config_module)

        assert reloaded.GOOGLE_CLIENT_CONFIG is None
        assert "packaged build" in reloaded.GOOGLE_CLIENT_CONFIG_ERROR
        monkeypatch.delenv("XPDITE_RUNTIME_ROOT", raising=False)
        monkeypatch.delenv("XPDITE_RUNTIME_ENV_FILE", raising=False)
        monkeypatch.delenv("XPDITE_USER_DATA_DIR", raising=False)
        importlib.reload(config_module)
