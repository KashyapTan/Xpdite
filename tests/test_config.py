"""Tests for source/infrastructure/config.py — verify constants and CaptureMode."""

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
