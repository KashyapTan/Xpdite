"""Tests for source/llm/core/key_manager.py — KeyManager."""

from unittest.mock import patch, MagicMock
import pytest
from cryptography.fernet import Fernet

from source.llm.core.key_manager import KeyManager, VALID_PROVIDERS


# ---------------------------------------------------------------------------
# Isolated KeyManager that uses an in-memory settings dict instead of the
# real database singleton.  key_manager.py does lazy `from ..infrastructure.database import db`
# inside each method, so we patch `source.infrastructure.database.db`.
# ---------------------------------------------------------------------------


def _make_key_manager():
    """Return a KeyManager backed by a fake in-memory DB."""
    settings: dict[str, str] = {}
    fake_db = MagicMock()
    fake_db.get_setting = MagicMock(side_effect=lambda k: settings.get(k))
    fake_db.set_setting = MagicMock(side_effect=lambda k, v: settings.__setitem__(k, v))
    fake_db.delete_setting = MagicMock(side_effect=lambda k: settings.pop(k, None))

    km = KeyManager()
    km._initialized = False  # force re-init
    return km, fake_db, settings


_DB_PATCH_TARGET = "source.infrastructure.database.db"


class TestMaskKey:
    def test_none(self):
        assert KeyManager.mask_key(None) == "****"

    def test_empty(self):
        assert KeyManager.mask_key("") == "****"

    def test_short_key(self):
        assert KeyManager.mask_key("12345678") == "****"

    def test_normal_key(self):
        result = KeyManager.mask_key("sk-abc123456xyz")
        assert result.startswith("sk-")
        assert result.endswith("xyz")
        assert "..." in result

    def test_nine_char_key(self):
        result = KeyManager.mask_key("123456789")
        assert result == "123...6789"


class TestEncryptDecrypt:
    def test_round_trip(self):
        km, fake_db, _ = _make_key_manager()
        with patch(_DB_PATCH_TARGET, fake_db):
            encrypted = km.encrypt_key("my-secret-key")
            assert encrypted != "my-secret-key"
            decrypted = km.decrypt_key(encrypted)
            assert decrypted == "my-secret-key"

    def test_decrypt_invalid_returns_none(self):
        km, fake_db, _ = _make_key_manager()
        with patch(_DB_PATCH_TARGET, fake_db):
            km._ensure_initialized()
            result = km.decrypt_key("not-a-valid-token")
            assert result is None

    def test_different_plaintexts_different_ciphertexts(self):
        km, fake_db, _ = _make_key_manager()
        with patch(_DB_PATCH_TARGET, fake_db):
            c1 = km.encrypt_key("key-one")
            c2 = km.encrypt_key("key-two")
            assert c1 != c2


class TestSaveGetDeleteApiKey:
    def test_save_and_get(self):
        km, fake_db, _ = _make_key_manager()
        with patch(_DB_PATCH_TARGET, fake_db):
            km.save_api_key("anthropic", "sk-ant-test-123")
            retrieved = km.get_api_key("anthropic")
            assert retrieved == "sk-ant-test-123"

    def test_save_and_get_huggingface(self):
        km, fake_db, _ = _make_key_manager()
        with patch(_DB_PATCH_TARGET, fake_db):
            km.save_api_key("huggingface", "hf-test-token")
            assert km.get_api_key("huggingface") == "hf-test-token"

    def test_get_missing_returns_none(self):
        km, fake_db, _ = _make_key_manager()
        with patch(_DB_PATCH_TARGET, fake_db):
            assert km.get_api_key("openai") is None

    def test_delete_api_key(self):
        km, fake_db, _ = _make_key_manager()
        with patch(_DB_PATCH_TARGET, fake_db):
            km.save_api_key("gemini", "gem-key")
            km.delete_api_key("gemini")
            assert km.get_api_key("gemini") is None

    def test_save_invalid_provider_raises(self):
        km, fake_db, _ = _make_key_manager()
        with patch(_DB_PATCH_TARGET, fake_db):
            with pytest.raises(ValueError, match="Invalid provider"):
                km.save_api_key("invalid_provider", "key")

    def test_delete_invalid_provider_raises(self):
        km, fake_db, _ = _make_key_manager()
        with patch(_DB_PATCH_TARGET, fake_db):
            with pytest.raises(ValueError, match="Invalid provider"):
                km.delete_api_key("invalid_provider")

    def test_get_invalid_provider_returns_none(self):
        km, fake_db, _ = _make_key_manager()
        with patch(_DB_PATCH_TARGET, fake_db):
            assert km.get_api_key("unknown") is None

    def test_get_api_key_decrypts_legacy_ciphertext_and_migrates(self):
        km, fake_db, settings = _make_key_manager()
        with patch(_DB_PATCH_TARGET, fake_db):
            # Seed a fixed salt so key derivation is deterministic in this test.
            salt = b"\x01" * 32
            settings["encryption_salt"] = salt.hex()

            app_paths = km._get_app_path_candidates()
            assert len(app_paths) >= 2

            legacy_key = km._derive_key(salt, app_paths[1])
            legacy_fernet = Fernet(legacy_key)
            legacy_cipher = legacy_fernet.encrypt(b"legacy-openai-key").decode("utf-8")
            settings["api_key_openai"] = legacy_cipher

            decrypted = km.get_api_key("openai")
            assert decrypted == "legacy-openai-key"

            # Value should be re-encrypted with canonical derivation.
            migrated_cipher = settings["api_key_openai"]
            assert migrated_cipher != legacy_cipher
            assert km.decrypt_key(migrated_cipher) == "legacy-openai-key"


class TestGetApiKeyStatus:
    def test_no_keys_configured(self):
        km, fake_db, _ = _make_key_manager()
        with patch(_DB_PATCH_TARGET, fake_db):
            status = km.get_api_key_status()
            for provider in VALID_PROVIDERS:
                assert status[provider]["has_key"] is False
                assert status[provider]["masked"] is None

    def test_with_key_configured(self):
        km, fake_db, _ = _make_key_manager()
        with patch(_DB_PATCH_TARGET, fake_db):
            km.save_api_key("anthropic", "sk-ant-very-long-key-here")
            status = km.get_api_key_status()
            assert status["anthropic"]["has_key"] is True
            assert "..." in status["anthropic"]["masked"]
            assert status["openai"]["has_key"] is False


class TestValidProviders:
    def test_contains_expected(self):
        assert "anthropic" in VALID_PROVIDERS
        assert "openai" in VALID_PROVIDERS
        assert "gemini" in VALID_PROVIDERS
        assert "openrouter" in VALID_PROVIDERS
        assert "huggingface" in VALID_PROVIDERS

    def test_no_extras(self):
        assert len(VALID_PROVIDERS) == 5
