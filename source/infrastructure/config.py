"""
Application configuration module.

Centralizes all configuration values and constants.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Project paths
_THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = _THIS_FILE.parents[2]
SOURCE_DIR = _THIS_FILE.parents[1]


def _resolve_runtime_root() -> Path:
    """Resolve the filesystem root for runtime assets.

    In development this is the repository root. In packaged builds Electron
    passes ``XPDITE_RUNTIME_ROOT`` pointing at bundled plain files such as
    ``source/`` and ``mcp_servers/`` that child Python interpreters can import.
    """
    runtime_root = os.environ.get("XPDITE_RUNTIME_ROOT", "").strip()
    if runtime_root:
        return Path(runtime_root).resolve()
    return PROJECT_ROOT


RUNTIME_ROOT = _resolve_runtime_root()
IS_PACKAGED_RUNTIME = bool(
    getattr(sys, "frozen", False)
    or os.environ.get("XPDITE_RUNTIME_ROOT")
    or os.environ.get("XPDITE_RUNTIME_ENV_FILE")
)
RUNTIME_ENV_FILE = os.environ.get("XPDITE_RUNTIME_ENV_FILE", "").strip()
CHILD_PYTHON_EXECUTABLE = os.environ.get("XPDITE_CHILD_PYTHON_EXECUTABLE", "").strip()


def _load_runtime_environment() -> None:
    """Load environment variables for the current runtime shape.

    Resolution order:
    1. Explicit packaged env file path supplied by Electron
    2. Repository ``.env`` file during development only
    """
    if RUNTIME_ENV_FILE:
        load_dotenv(RUNTIME_ENV_FILE, override=False)

    if not IS_PACKAGED_RUNTIME:
        load_dotenv(PROJECT_ROOT / ".env", override=False)


_load_runtime_environment()


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
SKILLS_SEED_DIR = (
    RUNTIME_ROOT / "source" / "skills_seed"
    if (RUNTIME_ROOT / "source" / "skills_seed").exists()
    else SOURCE_DIR / "skills_seed"
)
SKILLS_PREFERENCES_FILE = SKILLS_DIR / "preferences.json"

# Marketplace directories
MARKETPLACE_DIR = USER_DATA_DIR / "marketplace"
MARKETPLACE_PLUGINS_DIR = MARKETPLACE_DIR / "plugins"
MARKETPLACE_SKILLS_DIR = MARKETPLACE_DIR / "skills"
MARKETPLACE_MCP_DIR = MARKETPLACE_DIR / "mcp"
MARKETPLACE_PLUGIN_DATA_DIR = MARKETPLACE_DIR / "plugin-data"
MARKETPLACE_HOOK_TRANSCRIPTS_DIR = MARKETPLACE_DIR / "hook-transcripts"
for _marketplace_dir in (
    MARKETPLACE_DIR,
    MARKETPLACE_PLUGINS_DIR,
    MARKETPLACE_SKILLS_DIR,
    MARKETPLACE_MCP_DIR,
    MARKETPLACE_PLUGIN_DATA_DIR,
    MARKETPLACE_HOOK_TRANSCRIPTS_DIR,
):
    os.makedirs(_marketplace_dir, exist_ok=True)

# Memory directories
MEMORY_DIR = USER_DATA_DIR / "memory"
MEMORY_PROFILE_FILE = MEMORY_DIR / "profile" / "user_profile.md"
MEMORY_DEFAULT_FOLDERS = (
    "profile",
    "semantic",
    "episodic",
    "procedural",
)

# Artifact directories
ARTIFACTS_DIR = USER_DATA_DIR / "artifacts"
os.makedirs(ARTIFACTS_DIR, exist_ok=True)

# Server configuration
DEFAULT_PORT = 8000
MAX_PORT_ATTEMPTS = 10
SERVER_BIND_HOST = os.environ.get("XPDITE_SERVER_HOST", "127.0.0.1")
SERVER_SESSION_TOKEN = os.environ.get("XPDITE_SERVER_TOKEN", "")

# Model configuration
DEFAULT_MODEL = "qwen3-vl:8b-instruct"
MAX_MCP_TOOL_ROUNDS = 50

# Reasoning effort for thinking models ("low", "medium", "high")
# LiteLLM translates to native format per provider.
REASONING_EFFORT = "high"
OLLAMA_CTX_SIZE = 32768

# Tool result truncation
MAX_TOOL_RESULT_LENGTH = 200_000

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
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
]
GOOGLE_OAUTH_REDIRECT_HOST = "127.0.0.1"
GOOGLE_OAUTH_REDIRECT_URI = f"http://{GOOGLE_OAUTH_REDIRECT_HOST}"


def _build_google_client_config() -> dict | None:
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        return None
    return {
        "installed": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [GOOGLE_OAUTH_REDIRECT_URI],
        }
    }


def _build_google_config_error() -> str:
    if IS_PACKAGED_RUNTIME:
        return (
            "Google OAuth is not configured in this packaged build. Rebuild the app "
            "with GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET present in the root .env "
            "so the packaged runtime env resource can be generated."
        )
    return (
        "Google OAuth is not configured. Add GOOGLE_CLIENT_ID and "
        "GOOGLE_CLIENT_SECRET to the project .env file."
    )


# Google OAuth client configuration (Desktop app type).
# Get these from: Google Cloud Console > APIs & Services > Credentials
# Create an OAuth 2.0 Client ID with application type "Desktop app".
# For desktop apps the client secret is NOT confidential — this is the
# standard Google-recommended pattern (see:
# https://developers.google.com/identity/protocols/oauth2/native-app).
GOOGLE_CLIENT_CONFIG = _build_google_client_config()
GOOGLE_CLIENT_CONFIG_ERROR = _build_google_config_error()
