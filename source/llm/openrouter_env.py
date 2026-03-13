"""Shared OpenRouter API key environment-scoping helpers."""

import asyncio
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

_openrouter_env_lock = asyncio.Lock()


@asynccontextmanager
async def scoped_openrouter_api_key(api_key: str) -> AsyncIterator[None]:
    """Set OPENROUTER_API_KEY for the duration of an async block.

    The env var is process-global, so we serialize access with a shared lock
    and always restore previous state in a finally block.
    """
    async with _openrouter_env_lock:
        previous_key = os.environ.get("OPENROUTER_API_KEY")
        os.environ["OPENROUTER_API_KEY"] = api_key
        try:
            yield
        finally:
            if previous_key is None:
                os.environ.pop("OPENROUTER_API_KEY", None)
            else:
                os.environ["OPENROUTER_API_KEY"] = previous_key
