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
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken


# Valid provider names
VALID_PROVIDERS = ("anthropic", "openai", "gemini")


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
        self._initialized = False

    def _get_or_create_salt(self) -> bytes:
        """Get the per-install salt from DB, or create one if it doesn't exist."""
        from ..database import db

        salt_hex = db.get_setting("encryption_salt")
        if salt_hex:
            return bytes.fromhex(salt_hex)

        # Generate a random 32-byte salt
        salt = os.urandom(32)
        db.set_setting("encryption_salt", salt.hex())
        return salt

    def _derive_key(self, salt: bytes) -> bytes:
        """
        Derive a Fernet-compatible key from machine-specific data + salt.

        Uses SHA-256 to hash the combined material, then base64-encodes
        the 32-byte digest to produce a valid Fernet key.
        """
        # Gather machine-specific material
        username = getpass.getuser()
        hostname = socket.gethostname()
        app_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        # Combine and hash — use PBKDF2 for brute-force resistance
        material = f"{username}:{hostname}:{app_path}".encode("utf-8")
        key = hashlib.pbkdf2_hmac('sha256', material, salt, iterations=100_000)

        # Fernet requires a 32-byte key, base64url-encoded
        return base64.urlsafe_b64encode(key)

    def _ensure_initialized(self):
        """Lazily initialize the Fernet instance."""
        if self._initialized:
            return

        salt = self._get_or_create_salt()
        key = self._derive_key(salt)
        self._fernet = Fernet(key)
        self._initialized = True

    def encrypt_key(self, plaintext: str) -> str:
        """Encrypt an API key. Returns a base64-encoded encrypted string."""
        self._ensure_initialized()
        encrypted = self._fernet.encrypt(plaintext.encode("utf-8"))
        return encrypted.decode("utf-8")

    def decrypt_key(self, ciphertext: str) -> Optional[str]:
        """
        Decrypt an API key. Returns the plaintext string.
        Returns None if decryption fails (e.g., key was corrupted or
        the machine-specific data changed).
        """
        self._ensure_initialized()
        try:
            decrypted = self._fernet.decrypt(ciphertext.encode("utf-8"))
            return decrypted.decode("utf-8")
        except (InvalidToken, Exception) as e:
            print(f"[KeyManager] Decryption failed: {e}")
            return None

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

        from ..database import db

        encrypted = self.encrypt_key(plaintext_key)
        db.set_setting(f"api_key_{provider}", encrypted)

    def get_api_key(self, provider: str) -> Optional[str]:
        """Retrieve and decrypt an API key for a provider. Returns None if not stored."""
        if provider not in VALID_PROVIDERS:
            return None

        from ..database import db

        encrypted = db.get_setting(f"api_key_{provider}")
        if not encrypted:
            return None

        return self.decrypt_key(encrypted)

    def delete_api_key(self, provider: str):
        """Remove a stored API key for a provider."""
        if provider not in VALID_PROVIDERS:
            raise ValueError(f"Invalid provider: {provider}")

        from ..database import db

        db.delete_setting(f"api_key_{provider}")

    def get_api_key_status(self) -> dict:
        """
        Get status of all provider API keys.
        Returns {provider: {has_key: bool, masked: str|None}} for each provider.
        """
        from ..database import db  # deferred: avoid circular import

        status = {}
        for provider in VALID_PROVIDERS:
            # Check for existence without decrypting to avoid unnecessary crypto ops
            encrypted = db.get_setting(f"api_key_{provider}")
            if encrypted:
                key = self.get_api_key(provider)
                status[provider] = {
                    "has_key": True,
                    "masked": self.mask_key(key),
                }
            else:
                status[provider] = {
                    "has_key": False,
                    "masked": None,
                }
        return status


# Global singleton
key_manager = KeyManager()
