"""Tests for source/bootstrap/app_factory.py application factory wiring."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from source.bootstrap.app_factory import create_app


class TestCreateApp:
    def test_create_app_registers_cors_routes_and_lifespan_hooks(self):
        app = create_app()

        cors_middleware = [
            middleware
            for middleware in app.user_middleware
            if middleware.cls.__name__ == "CORSMiddleware"
        ]
        assert len(cors_middleware) == 1
        options = cors_middleware[0].kwargs
        assert options["allow_origins"] == [
            "http://127.0.0.1:5123",
            "http://localhost:5123",
            "null",
        ]
        assert options["allow_methods"] == ["*"]
        assert options["allow_headers"] == ["Content-Type", "X-Xpdite-Server-Token"]

        route_paths = {route.path for route in app.router.routes}
        assert "/ws" in route_paths
        assert "/api/health" in route_paths
        assert "/api/terminal/settings" in route_paths

        init_calls: list[str] = []
        sync_calls: list[str] = []
        file_browser_calls: list[str] = []

        async def _run_lifespan():
            async with app.router.lifespan_context(app):
                return None

        with (
            patch(
                "source.services.chat.tab_manager_instance.init_tab_manager",
                side_effect=lambda: init_calls.append("called") or SimpleNamespace(),
            ),
            patch(
                "source.services.integrations.mobile_channel.mobile_channel_service"
            ) as mobile_service,
            patch(
                "source.services.marketplace.service.get_marketplace_service"
            ) as get_marketplace_service,
            patch(
                "source.services.hooks_runtime.get_hooks_runtime"
            ) as get_hooks_runtime,
            patch(
                "source.api.http._write_mobile_channels_config_file",
                side_effect=lambda: sync_calls.append("called"),
            ),
            patch(
                "source.services.filesystem.file_browser.file_browser_service"
            ) as browser_service,
        ):
            import asyncio

            marketplace_service = get_marketplace_service.return_value
            hooks_runtime = get_hooks_runtime.return_value
            marketplace_service.initialize.return_value = None
            marketplace_service.list_installs.return_value = []
            hooks_runtime.rehydrate_enabled_installs_async = AsyncMock()
            marketplace_service.refresh_builtin_sources_async = AsyncMock()
            browser_service.start.side_effect = lambda: file_browser_calls.append(
                "start"
            )
            browser_service.shutdown.side_effect = lambda: file_browser_calls.append(
                "shutdown"
            )

            asyncio.run(_run_lifespan())

        assert init_calls == ["called"]
        assert sync_calls == ["called"]
        mobile_service.restore_sessions_from_db.assert_called_once_with()
        mobile_service.cleanup_expired_codes.assert_called_once_with()
        mobile_service.register_relay_callback.assert_called_once_with()
        marketplace_service.initialize.assert_called_once_with()
        marketplace_service.list_installs.assert_called_once_with()
        hooks_runtime.rehydrate_enabled_installs_async.assert_awaited_once_with([])
        assert file_browser_calls == ["start", "shutdown"]
