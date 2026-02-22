"""
Google OAuth 2.0 Authentication Service.

Handles the OAuth flow for connecting the user's Google account
to enable Gmail and Calendar MCP tools.

Flow:
1. User clicks "Connect Google" in Settings > Connections
2. Backend runs InstalledAppFlow using embedded client config
3. Browser opens -> user logs in -> grants permissions
4. Token stored at user_data/google/token.json
5. Gmail + Calendar MCP servers are started with token access

The OAuth client_id and client_secret are embedded in config.py.
For desktop apps this is the standard Google-recommended pattern —
the client secret is NOT confidential (see:
https://developers.google.com/identity/protocols/oauth2/native-app).
"""

import os
import json
import threading
from typing import Optional

from ..config import (
    GOOGLE_CLIENT_CONFIG,
    GOOGLE_TOKEN_FILE,
    GOOGLE_SCOPES,
)


class GoogleAuthService:
    """Manages Google OAuth 2.0 lifecycle for the app."""

    def __init__(self):
        self._auth_in_progress = False
        self._auth_lock = threading.Lock()

    def has_token(self) -> bool:
        """Check if a valid (or refreshable) token.json exists."""
        return os.path.exists(GOOGLE_TOKEN_FILE)

    def get_status(self) -> dict:
        """
        Get the current Google connection status.

        Returns:
            {
                "connected": bool,
                "email": str | None,
                "auth_in_progress": bool,
            }
        """
        status = {
            "connected": False,
            "email": None,
            "auth_in_progress": self._auth_in_progress,
        }

        if not self.has_token():
            return status

        try:
            creds = self._load_credentials()
            if creds and (creds.valid or creds.refresh_token):
                status["connected"] = True
                # Try to get email from token info
                if hasattr(creds, "token") and creds.token:
                    email = self._get_email_from_token(creds)
                    if email:
                        status["email"] = email
        except Exception as e:
            print(f"[Google Auth] Error checking status: {e}")

        return status

    def _load_credentials(self):
        """Load and optionally refresh stored credentials."""
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request

        if not os.path.exists(GOOGLE_TOKEN_FILE):
            return None

        creds = Credentials.from_authorized_user_file(GOOGLE_TOKEN_FILE, GOOGLE_SCOPES)

        # Refresh if expired
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                # Save refreshed token
                with open(GOOGLE_TOKEN_FILE, "w") as token_file:
                    token_file.write(creds.to_json())
            except Exception as e:
                print(f"[Google Auth] Token refresh failed: {e}")
                # Remove invalid token to avoid a "connected but broken" state
                try:
                    os.remove(GOOGLE_TOKEN_FILE)
                    print("[Google Auth] Removed expired/invalid token file")
                except OSError:
                    pass
                return None

        return creds

    def _get_email_from_token(self, creds) -> Optional[str]:
        """Extract email from the Google user info endpoint."""
        try:
            from googleapiclient.discovery import build

            service = build("oauth2", "v2", credentials=creds)
            user_info = service.userinfo().get().execute()
            return user_info.get("email")
        except Exception:
            # Fall back: try reading from token JSON directly
            try:
                with open(GOOGLE_TOKEN_FILE, "r") as f:
                    token_data = json.load(f)
                    return token_data.get("email")
            except Exception:
                return None

    def start_oauth_flow(self) -> dict:
        """
        Initiate the Google OAuth 2.0 flow.

        Opens the user's browser for Google login and permission granting.
        Uses InstalledAppFlow.run_local_server() which starts a temporary
        local HTTP server to receive the OAuth callback.

        Returns:
            {"success": True, "email": "..."} or {"success": False, "error": "..."}
        """
        with self._auth_lock:
            if self._auth_in_progress:
                return {"success": False, "error": "Authentication already in progress"}
            self._auth_in_progress = True

        try:
            from google_auth_oauthlib.flow import InstalledAppFlow

            flow = InstalledAppFlow.from_client_config(
                GOOGLE_CLIENT_CONFIG, GOOGLE_SCOPES
            )

            # run_local_server opens the browser and waits for the callback
            # port=0 means pick a random available port
            creds = flow.run_local_server(
                port=0,
                prompt="consent",
                success_message="Authentication successful! You can close this tab and return to Xpdite.",
            )

            # Save the credentials
            with open(GOOGLE_TOKEN_FILE, "w") as token_file:
                token_file.write(creds.to_json())

            print("[Google Auth] OAuth flow completed successfully")

            # Get email
            email = self._get_email_from_token(creds)

            return {"success": True, "email": email}

        except Exception as e:
            error_msg = str(e)
            print(f"[Google Auth] OAuth flow failed: {error_msg}")
            return {"success": False, "error": error_msg}

        finally:
            self._auth_in_progress = False

    def disconnect(self) -> dict:
        """
        Disconnect Google account by revoking and deleting the token.

        Returns:
            {"success": True} or {"success": False, "error": "..."}
        """
        try:
            # Try to revoke the token
            if os.path.exists(GOOGLE_TOKEN_FILE):
                try:
                    creds = self._load_credentials()
                    if creds and creds.token:
                        import requests

                        requests.post(
                            "https://oauth2.googleapis.com/revoke",
                            params={"token": creds.token},
                            headers={
                                "Content-Type": "application/x-www-form-urlencoded"
                            },
                        )
                except Exception as e:
                    print(f"[Google Auth] Token revocation failed (non-fatal): {e}")

                # Delete token file regardless
                os.remove(GOOGLE_TOKEN_FILE)
                print("[Google Auth] Token removed")

            return {"success": True}

        except Exception as e:
            error_msg = str(e)
            print(f"[Google Auth] Disconnect failed: {error_msg}")
            return {"success": False, "error": error_msg}


# Singleton instance
google_auth = GoogleAuthService()
