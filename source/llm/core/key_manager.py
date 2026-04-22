"""
API Key Manager.

Handles secure encryption/decryption of API keys using Fernet symmetric encryption.
Keys are stored encrypted in the SQLite database. The encryption key is derived
from machine-specific data + a random per-install salt.
"""

import os
import hashlib
import base64
import getpass
import socket
import logging
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


# Valid provider names
VALID_PROVIDERS = ("anthropic", "openai", "gemini", "openrouter", "huggingface")


class KeyManager:
    """
    Manages API key encryption and decryption using Fernet.

    The encryption key is derived from:
    - Machine username
    - Machine hostname
    - Application install path
    - A random salt (generated once, stored in DB)

    This means keys are tied to the machine and install location.
    Moving the DB file to another machine won't expose the keys.
    """

    def __init__(self):
        self._fernet: Optional[Fernet] = None
        self._legacy_fernets: list[Fernet] = []
        self._initialized = False

    @staticmethod
    def _find_source_root() -> str:
        """Return the absolute path to the source/ directory."""
        current = Path(__file__).resolve()
        for parent in current.parents:
            if parent.name == "source":
                return str(parent)
        # Fallback keeps behavior safe even if this module is relocated.
        return str(current.parent)

    def _get_app_path_candidates(self) -> list[str]:
        """Return canonical + legacy app paths used for key derivation.

        Canonical path is the source/ root so module moves inside source/
        do not rotate encryption keys.
        """
        current = Path(__file__).resolve()
        source_root = self._find_source_root()

        candidates = [source_root]

        # Legacy derivation used two parents from this file path.
        # With key_manager moved to source/llm/core/, that becomes source/llm.
        legacy_two_up = str(current.parent.parent)
        if legacy_two_up not in candidates:
            candidates.append(legacy_two_up)

        # Extra fallback for older layouts; duplicates are ignored.
        legacy_three_up = str(current.parent.parent.parent)
        if legacy_three_up not in candidates:
            candidates.append(legacy_three_up)

        return candidates

    def _get_or_create_salt(self) -> bytes:
        """Get the per-install salt from DB, or create one if it doesn't exist."""
        from ...infrastructure.database import db

        salt_hex = db.get_setting("encryption_salt")
        if salt_hex:
            return bytes.fromhex(salt_hex)

        # Generate a random 32-byte salt
        salt = os.urandom(32)
        db.set_setting("encryption_salt", salt.hex())
        return salt

    def _derive_key(self, salt: bytes, app_path: str) -> bytes:
        """
        Derive a Fernet-compatible key from machine-specific data + salt.

        Uses SHA-256 to hash the combined material, then base64-encodes
        the 32-byte digest to produce a valid Fernet key.
        """
        # Gather machine-specific material
        username = getpass.getuser()
        hostname = socket.gethostname()

        # Combine and hash — use PBKDF2 for brute-force resistance
        material = f"{username}:{hostname}:{app_path}".encode("utf-8")
        key = hashlib.pbkdf2_hmac("sha256", material, salt, iterations=100_000)

        # Fernet requires a 32-byte key, base64url-encoded
        return base64.urlsafe_b64encode(key)

    def _ensure_initialized(self):
        """Lazily initialize the Fernet instance."""
        if self._initialized:
            return

        salt = self._get_or_create_salt()
        app_paths = self._get_app_path_candidates()

        key = self._derive_key(salt, app_paths[0])
        self._fernet = Fernet(key)

        self._legacy_fernets = []
        for legacy_path in app_paths[1:]:
            legacy_key = self._derive_key(salt, legacy_path)
            self._legacy_fernets.append(Fernet(legacy_key))

        self._initialized = True

    @staticmethod
    def _try_decrypt_with_fernet(fernet: Fernet, ciphertext: str) -> Optional[str]:
        """Try one Fernet instance; return plaintext or None."""
        try:
            decrypted = fernet.decrypt(ciphertext.encode("utf-8"))
            return decrypted.decode("utf-8")
        except InvalidToken:
            return None
        except Exception as e:
            logger.error("Decryption failed: %s", e)
            return None

    def _decrypt_with_all_candidates(
        self, ciphertext: str
    ) -> tuple[Optional[str], bool]:
        """Decrypt with canonical key first, then legacy keys.

        Returns:
            (plaintext, used_legacy_key)
        """
        self._ensure_initialized()

        canonical_fernet = self._fernet
        if canonical_fernet is None:
            return None, False

        plaintext = self._try_decrypt_with_fernet(canonical_fernet, ciphertext)
        if plaintext is not None:
            return plaintext, False

        for legacy_fernet in self._legacy_fernets:
            plaintext = self._try_decrypt_with_fernet(legacy_fernet, ciphertext)
            if plaintext is not None:
                return plaintext, True

        return None, False

    def encrypt_key(self, plaintext: str) -> str:
        """Encrypt an API key. Returns a base64-encoded encrypted string."""
        self._ensure_initialized()
        if self._fernet is None:
            raise RuntimeError("Key manager failed to initialize encryption backend")
        encrypted = self._fernet.encrypt(plaintext.encode("utf-8"))
        return encrypted.decode("utf-8")

    def decrypt_key(self, ciphertext: str) -> Optional[str]:
        """
        Decrypt an API key. Returns the plaintext string.
        Returns None if decryption fails (e.g., key was corrupted or
        the machine-specific data changed).
        """
        plaintext, _used_legacy_key = self._decrypt_with_all_candidates(ciphertext)
        return plaintext

    @staticmethod
    def mask_key(plaintext: str | None) -> str:
        """
        Mask an API key for display purposes.
        Shows first 3 and last 4 characters: 'sk-...a1b2'
        """
        if not plaintext:
            return "****"
        if len(plaintext) <= 8:
            return "****"
        return f"{plaintext[:3]}...{plaintext[-4:]}"

    def save_api_key(self, provider: str, plaintext_key: str):
        """Encrypt and store an API key for a provider."""
        if provider not in VALID_PROVIDERS:
            raise ValueError(f"Invalid provider: {provider}")

        from ...infrastructure.database import db

        encrypted = self.encrypt_key(plaintext_key)
        db.set_setting(f"api_key_{provider}", encrypted)

    def get_api_key(self, provider: str) -> Optional[str]:
        """Retrieve and decrypt an API key for a provider. Returns None if not stored."""
        if provider not in VALID_PROVIDERS:
            return None

        from ...infrastructure.database import db

        encrypted = db.get_setting(f"api_key_{provider}")
        if not encrypted:
            return None

        decrypted, used_legacy_key = self._decrypt_with_all_candidates(encrypted)
        if decrypted is None:
            return None

        # Opportunistic migration: if a legacy derivation was needed,
        # re-encrypt with the canonical derivation so future reads are stable.
        if used_legacy_key:
            try:
                db.set_setting(f"api_key_{provider}", self.encrypt_key(decrypted))
                logger.info(
                    "Migrated encrypted API key to canonical derivation for provider '%s'",
                    provider,
                )
            except Exception as e:
                logger.warning(
                    "Failed to migrate encrypted API key for provider '%s': %s",
                    provider,
                    e,
                )

        return decrypted

    def delete_api_key(self, provider: str):
        """Remove a stored API key for a provider."""
        if provider not in VALID_PROVIDERS:
            raise ValueError(f"Invalid provider: {provider}")

        from ...infrastructure.database import db

        db.delete_setting(f"api_key_{provider}")

    def get_api_key_status(self) -> dict:
        """
        Get status of all provider API keys.
        Returns {provider: {has_key: bool, masked: str|None}} for each provider.
        """
        from ...infrastructure.database import db  # deferred: avoid circular import

        status = {}
        for provider in VALID_PROVIDERS:
            # Check for existence without decrypting to avoid unnecessary crypto ops
            encrypted = db.get_setting(f"api_key_{provider}")
            if encrypted:
                key = self.get_api_key(provider)
                if key:
                    status[provider] = {
                        "has_key": True,
                        "masked": self.mask_key(key),
                    }
                else:
                    status[provider] = {
                        "has_key": False,
                        "masked": None,
                    }
            else:
                status[provider] = {
                    "has_key": False,
                    "masked": None,
                }
        return status


# Global singleton
key_manager = KeyManager()
