"""Tests for source/bootstrap/app_factory.py application factory wiring."""

import inspect
from types import SimpleNamespace
from unittest.mock import patch

from source.bootstrap.app_factory import create_app


class TestCreateApp:
    def test_create_app_registers_cors_routes_and_startup_hook(self):
        app = create_app()

        cors_middleware = [
            middleware
            for middleware in app.user_middleware
            if middleware.cls.__name__ == "CORSMiddleware"
        ]
        assert len(cors_middleware) == 1
        options = cors_middleware[0].kwargs
        assert options["allow_origins"] == ["*"]
        assert options["allow_methods"] == ["*"]
        assert options["allow_headers"] == ["*"]

        route_paths = {route.path for route in app.router.routes}
        assert "/ws" in route_paths
        assert "/api/health" in route_paths
        assert "/api/terminal/settings" in route_paths

        startup_handlers = app.router.on_startup
        assert startup_handlers, "Expected startup handlers to be registered"
        shutdown_handlers = app.router.on_shutdown
        assert shutdown_handlers, "Expected shutdown handlers to be registered"

        init_handler = next(
            handler
            for handler in startup_handlers
            if getattr(handler, "__name__", "") == "_init_tab_manager"
        )
        assert inspect.iscoroutinefunction(init_handler)

        init_calls: list[str] = []
        sync_calls: list[str] = []

        with patch(
            "source.services.chat.tab_manager_instance.init_tab_manager",
            side_effect=lambda: init_calls.append("called") or SimpleNamespace(),
        ):
            # Invoke the registered startup hook directly.
            import asyncio

            asyncio.run(init_handler())

        assert init_calls == ["called"]

        sync_handler = next(
            handler
            for handler in startup_handlers
            if getattr(handler, "__name__", "") == "_sync_mobile_channels_bridge_config"
        )
        assert inspect.iscoroutinefunction(sync_handler)

        with patch(
            "source.api.http._write_mobile_channels_config_file",
            side_effect=lambda: sync_calls.append("called"),
        ):
            import asyncio

            asyncio.run(sync_handler())

        assert sync_calls == ["called"]

        file_browser_start_handler = next(
            handler
            for handler in startup_handlers
            if getattr(handler, "__name__", "") == "_start_file_browser_indexer"
        )
        assert inspect.iscoroutinefunction(file_browser_start_handler)

        with patch(
            "source.services.filesystem.file_browser.file_browser_service"
        ) as browser_service:
            import asyncio

            asyncio.run(file_browser_start_handler())

        browser_service.start.assert_called_once_with()

        file_browser_shutdown_handler = next(
            handler
            for handler in shutdown_handlers
            if getattr(handler, "__name__", "") == "_stop_file_browser_indexer"
        )
        assert inspect.iscoroutinefunction(file_browser_shutdown_handler)

        with patch(
            "source.services.filesystem.file_browser.file_browser_service"
        ) as browser_service:
            import asyncio

            asyncio.run(file_browser_shutdown_handler())

        browser_service.shutdown.assert_called_once_with()
