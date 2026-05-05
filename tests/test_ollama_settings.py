from unittest.mock import MagicMock, patch

import pytest


def test_get_local_ollama_context_size_uses_valid_db_setting():
    from source.llm.core.ollama_settings import get_local_ollama_context_size

    db_mock = MagicMock()
    db_mock.get_setting.return_value = "65536"

    with patch("source.infrastructure.database.db", db_mock):
        assert get_local_ollama_context_size() == 65536


def test_get_local_ollama_context_size_falls_back_for_invalid_setting():
    from source.llm.core.ollama_settings import get_local_ollama_context_size

    db_mock = MagicMock()
    db_mock.get_setting.return_value = "not-an-int"

    with patch("source.infrastructure.database.db", db_mock):
        assert get_local_ollama_context_size() == 32768


def test_get_ollama_settings_payload_reports_custom_state():
    from source.llm.core.ollama_settings import get_ollama_settings_payload

    db_mock = MagicMock()
    db_mock.get_setting.return_value = "131072"

    with patch("source.infrastructure.database.db", db_mock):
        payload = get_ollama_settings_payload()

    assert payload["local_context_size"] == 131072
    assert payload["default_local_context_size"] == 32768
    assert payload["is_custom"] is True


def test_set_local_ollama_context_size_persists_or_resets():
    from source.llm.core.ollama_settings import set_local_ollama_context_size

    db_mock = MagicMock()
    db_mock.get_setting.return_value = "65536"

    with patch("source.infrastructure.database.db", db_mock):
        payload = set_local_ollama_context_size(65536)

    db_mock.set_setting.assert_called_once_with("ollama_local_context_size", "65536")
    assert payload["local_context_size"] == 65536

    db_mock.reset_mock()
    db_mock.get_setting.return_value = None

    with patch("source.infrastructure.database.db", db_mock):
        payload = set_local_ollama_context_size(None)

    db_mock.delete_setting.assert_called_once_with("ollama_local_context_size")
    assert payload["local_context_size"] == 32768


def test_set_local_ollama_context_size_rejects_out_of_range_values():
    from source.llm.core.ollama_settings import set_local_ollama_context_size

    with patch("source.infrastructure.database.db", MagicMock()), pytest.raises(ValueError):
        set_local_ollama_context_size(1)
