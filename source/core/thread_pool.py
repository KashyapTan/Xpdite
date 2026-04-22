"""
App-owned thread pool for running blocking functions.

Python's default ``ThreadPoolExecutor`` (the one ``asyncio.to_thread`` uses)
gets shut down when the event-loop or Uvicorn exits.  Once that happens every
subsequent ``asyncio.to_thread()`` call raises::

    RuntimeError: cannot schedule new futures after shutdown

By owning our own executor we avoid that entirely.  Every module that
previously called ``asyncio.to_thread(fn, ...)`` should instead::

    from source.core.thread_pool import run_in_thread
    result = await run_in_thread(fn, ...)
"""

import asyncio
import concurrent.futures
import functools
from typing import TypeVar, Callable, Any

from ..infrastructure.config import THREAD_POOL_SIZE

T = TypeVar("T")

# Shared executor for the whole application.
_app_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=THREAD_POOL_SIZE, thread_name_prefix="app-worker"
)


async def run_in_thread(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Run *func(*args, **kwargs)* in the app-owned thread pool.

    Drop-in replacement for ``asyncio.to_thread`` that is immune to the
    default executor being shut down.  Supports keyword arguments (which
    plain ``loop.run_in_executor`` does not).
    """
    loop = asyncio.get_running_loop()
    call = functools.partial(func, *args, **kwargs)
    return await loop.run_in_executor(_app_executor, call)


def shutdown_thread_pool(wait: bool = True, cancel_futures: bool = False) -> None:
    """Shut down the shared executor during application teardown."""
    _app_executor.shutdown(wait=wait, cancel_futures=cancel_futures)
