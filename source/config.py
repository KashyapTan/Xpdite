"""
Application configuration module.

Centralizes all configuration values and constants.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Project paths
PROJECT_ROOT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SOURCE_DIR = Path(os.path.dirname(os.path.abspath(__file__)))

# Load environment variables from .env file
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))


def _resolve_user_data_dir() -> Path:
    """Resolve the user data directory for both dev and production.

    Resolution order:
    1. ``XPDITE_USER_DATA_DIR`` env-var (set by Electron in production)
    2. ``<PROJECT_ROOT>/user_data`` (development fallback)
    """
    env_dir = os.environ.get("XPDITE_USER_DATA_DIR")
    if env_dir:
        return Path(env_dir)
    return PROJECT_ROOT / "user_data"


USER_DATA_DIR = _resolve_user_data_dir()

# Screenshot storage
SCREENSHOT_FOLDER = str(USER_DATA_DIR / "screenshots")
os.makedirs(SCREENSHOT_FOLDER, exist_ok=True)

# Skills directories
SKILLS_DIR = USER_DATA_DIR / "skills"
BUILTIN_SKILLS_DIR = SKILLS_DIR / "builtin"
USER_SKILLS_DIR = SKILLS_DIR / "user"
SKILLS_SEED_DIR = SOURCE_DIR / "skills_seed"
SKILLS_PREFERENCES_FILE = SKILLS_DIR / "preferences.json"

# Server configuration
DEFAULT_PORT = 8000
MAX_PORT_ATTEMPTS = 10

# Model configuration
DEFAULT_MODEL = "qwen3-vl:8b-instruct"
MAX_MCP_TOOL_ROUNDS = 30

# LLM token limits
CLOUD_MAX_TOKENS = 16384
CLOUD_TOOL_MAX_TOKENS = 4096
OLLAMA_CTX_SIZE = 32768

# Tool result truncation
MAX_TOOL_RESULT_LENGTH = 100_000

# Thread pool
THREAD_POOL_SIZE = int(os.environ.get("XPDITE_THREAD_POOL_SIZE", "4"))

# Terminal output
TERMINAL_MAX_OUTPUT_SIZE = 50 * 1024

# Thinking-capable model keywords/identifiers — used to decide whether to
# enable extended-thinking / budget_tokens parameters in cloud requests.
ANTHROPIC_THINKING_KEYWORDS = ("opus", "sonnet", "haiku")
GEMINI_THINKING_KEYWORDS = ("thinking", "2.5", "gemini-3")


# Capture modes
class CaptureMode:
    FULLSCREEN = "fullscreen"
    PRECISION = "precision"
    NONE = "none"


# Google OAuth configuration
GOOGLE_USER_DATA = str(USER_DATA_DIR / "google")
os.makedirs(GOOGLE_USER_DATA, exist_ok=True)
GOOGLE_TOKEN_FILE = os.path.join(GOOGLE_USER_DATA, "token.json")
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
]

# Google OAuth client configuration (Desktop app type).
# Get these from: Google Cloud Console > APIs & Services > Credentials
# Create an OAuth 2.0 Client ID with application type "Desktop app".
# For desktop apps the client secret is NOT confidential — this is the
# standard Google-recommended pattern (see:
# https://developers.google.com/identity/protocols/oauth2/native-app).
GOOGLE_CLIENT_CONFIG = {
    "installed": {
        "client_id": os.environ.get(
            "GOOGLE_CLIENT_ID", "YOUR_CLIENT_ID.apps.googleusercontent.com"
        ),
        "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET", "YOUR_CLIENT_SECRET"),
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"],
    }
}
