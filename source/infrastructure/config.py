"""
Application configuration module.

Centralizes all configuration values and constants.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Project paths
_THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = _THIS_FILE.parents[2]
SOURCE_DIR = _THIS_FILE.parents[1]

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

# Memory directories
MEMORY_DIR = USER_DATA_DIR / "memory"
MEMORY_PROFILE_FILE = MEMORY_DIR / "profile" / "user_profile.md"
MEMORY_DEFAULT_FOLDERS = (
    "profile",
    "semantic",
    "episodic",
    "procedural",
)

# Server configuration
DEFAULT_PORT = 8000
MAX_PORT_ATTEMPTS = 10

# Model configuration
DEFAULT_MODEL = "qwen3-vl:8b-instruct"
MAX_MCP_TOOL_ROUNDS = 50

# Reasoning effort for thinking models ("low", "medium", "high")
# LiteLLM translates to native format per provider.
REASONING_EFFORT = "high"
OLLAMA_CTX_SIZE = 32768

# Tool result truncation
MAX_TOOL_RESULT_LENGTH = 100_000

# read_file pagination default chunk size (characters)
DEFAULT_READ_FILE_MAX_CHARS = 10_000

# Thread pool
THREAD_POOL_SIZE = int(os.environ.get("XPDITE_THREAD_POOL_SIZE", "4"))

# Terminal output
TERMINAL_MAX_OUTPUT_SIZE = 50 * 1024


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
