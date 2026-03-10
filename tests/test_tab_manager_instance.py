"""Tests for source/services/tab_manager_instance.py."""

from source.core.state import app_state
from source.services.tab_manager import TabSession, TabState
from source.services.tab_manager_instance import _adopt_global_screenshots


class TestAdoptGlobalScreenshots:
    """Verify legacy global screenshots are absorbed into a tab session."""

    def test_moves_global_screenshots_into_target_session(self):
        session = TabSession(tab_id="default", state=TabState(tab_id="default"), queue=object())
        saved_global_screenshots = list(app_state.screenshot_list)

        try:
            app_state.screenshot_list = [
                {"id": "ss_1", "path": "/tmp/a.png", "name": "a.png", "thumbnail": "thumb-a"},
                {"id": "ss_2", "path": "/tmp/b.png", "name": "b.png", "thumbnail": "thumb-b"},
            ]

            adopted_count = _adopt_global_screenshots(session)

            assert adopted_count == 2
            assert app_state.screenshot_list == []
            assert session.state.screenshot_list == [
                {"id": "ss_1", "path": "/tmp/a.png", "name": "a.png", "thumbnail": "thumb-a"},
                {"id": "ss_2", "path": "/tmp/b.png", "name": "b.png", "thumbnail": "thumb-b"},
            ]
        finally:
            app_state.screenshot_list = saved_global_screenshots

    def test_noop_when_global_list_is_empty(self):
        session = TabSession(tab_id="default", state=TabState(tab_id="default"), queue=object())
        saved_global_screenshots = list(app_state.screenshot_list)

        try:
            app_state.screenshot_list = []

            adopted_count = _adopt_global_screenshots(session)

            assert adopted_count == 0
            assert session.state.screenshot_list == []
        finally:
            app_state.screenshot_list = saved_global_screenshots
