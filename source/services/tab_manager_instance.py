"""
Tab manager singleton.

Lazily initialised on first access.  ``app.py`` calls ``init_tab_manager()``
during startup to create the singleton with the correct ``process_fn``.
"""

from __future__ import annotations

import logging
from typing import Optional

from .tab_manager import TabManager, TabSession

logger = logging.getLogger(__name__)

tab_manager: Optional[TabManager] = None  # type: ignore[assignment]


def _adopt_global_screenshots(target_session: TabSession) -> int:
    """Move legacy global screenshots into a concrete tab session."""
    from ..core.state import app_state

    if not app_state.screenshot_list:
        return 0

    adopted_screenshots = list(app_state.screenshot_list)
    target_session.state.screenshot_list.extend(adopted_screenshots)
    app_state.screenshot_list = []
    return len(adopted_screenshots)


def init_tab_manager() -> TabManager:
    """Create and store the tab-manager singleton.

    Called once from ``app.py`` after all services are importable.
    """
    global tab_manager

    if tab_manager is not None:
        return tab_manager

    from ..core.connection import (
        broadcast_to_tab,
        reset_current_tab_id,
        set_current_tab_id,
    )
    from ..core.state import app_state
    from ..services.conversations import ConversationService
    from .query_queue import QueuedQuery
    from ..llm.router import is_local_ollama_model

    async def _process_fn(query: QueuedQuery) -> Optional[str]:
        """Bridge between the queue and ConversationService.submit_query.

        Sets the contextvar so all broadcasts emitted during processing
        are stamped with the correct ``tab_id``.

        Local Ollama queries are routed through the global Ollama queue so that
        only one local-GPU request runs at a time.
        """
        from .ollama_global_queue import ollama_global_queue

        tm: TabManager = tab_manager  # type: ignore[assignment]
        session = tm.get_or_create(query.tab_id)

        model_name = query.model or app_state.selected_model

        async def _do_submit() -> Optional[str]:
            token = set_current_tab_id(query.tab_id)
            try:
                return await ConversationService.submit_query(
                    user_query=query.content,
                    capture_mode=query.capture_mode,
                    forced_skills=query.forced_skills,
                    llm_query=query.llm_query,
                    tab_state=session.state,
                    queue=session.queue,
                    model=query.model,
                    action=query.action,
                    target_message_id=query.target_message_id,
                )
            finally:
                reset_current_tab_id(token)

        if is_local_ollama_model(model_name):
            # Serialize local Ollama requests globally (single local GPU).
            # Ollama cloud models ("-cloud") bypass this and run concurrently.
            return await ollama_global_queue.run(query.tab_id, _do_submit)
        else:
            # Cloud providers and Ollama cloud models can run concurrently.
            return await _do_submit()

    tab_manager = TabManager(
        process_fn=_process_fn,
        broadcast_fn=broadcast_to_tab,
    )

    # Also wire the global Ollama queue broadcast function.
    # The Ollama queue broadcasts globally (not tab-scoped), so we use
    # broadcast_message which auto-stamps tab_id from the contextvar.
    from .ollama_global_queue import ollama_global_queue
    from ..core.connection import broadcast_message as _broadcast_msg

    ollama_global_queue.set_broadcast_fn(_broadcast_msg)

    # Create the default tab and absorb any screenshots that were captured
    # before the tab manager became available.
    default_session = tab_manager.ensure_default_tab()
    adopted_count = _adopt_global_screenshots(default_session)
    if adopted_count:
        logger.info(
            "Adopted %d legacy screenshot(s) into the default tab", adopted_count
        )

    logger.info("TabManager initialised with default tab")
    return tab_manager
