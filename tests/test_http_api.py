"""High-value tests for source/api/http.py endpoints and helpers."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import sys

import pytest
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.testclient import TestClient

import source.api.http as http_api


class TestHttpApiHelpers:
    def test_extract_openrouter_error_prefers_nested_error_message(self):
        response = MagicMock()
        response.status_code = 500
        response.json.return_value = {"error": {"message": "bad gateway"}}
        response.text = ""

        detail = http_api._extract_openrouter_error(response)
        assert detail == "bad gateway"

    def test_extract_openrouter_error_uses_body_fallback(self):
        response = MagicMock()
        response.status_code = 418
        response.json.side_effect = ValueError("not json")
        response.text = "teapot body"

        detail = http_api._extract_openrouter_error(response)
        assert detail == "teapot body"

    @pytest.mark.asyncio
    async def test_model_cache_returns_cached_payload_when_ttl_valid(self):
        with patch.object(http_api, "_MODEL_CACHE", {}):
            first_fetcher = AsyncMock(return_value=[{"id": "a"}])
            second_fetcher = AsyncMock(return_value=[{"id": "b"}])

            first = await http_api._get_cached_or_fetch_models(
                "openai", False, first_fetcher
            )
            second = await http_api._get_cached_or_fetch_models(
                "openai", False, second_fetcher
            )

        assert first == [{"id": "a"}]
        assert second == [{"id": "a"}]
        first_fetcher.assert_awaited_once()
        second_fetcher.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_model_cache_refresh_forces_refetch(self):
        with patch.object(http_api, "_MODEL_CACHE", {}):
            first_fetcher = AsyncMock(return_value=[{"id": "first"}])
            second_fetcher = AsyncMock(return_value=[{"id": "second"}])

            await http_api._get_cached_or_fetch_models("gemini", False, first_fetcher)
            refreshed = await http_api._get_cached_or_fetch_models(
                "gemini", True, second_fetcher
            )

        assert refreshed == [{"id": "second"}]
        first_fetcher.assert_awaited_once()
        second_fetcher.assert_awaited_once()


class TestHttpApiEndpoints:
    @pytest.mark.asyncio
    async def test_browse_files_lists_directory(self):
        fake_result = SimpleNamespace(
            entries=[SimpleNamespace(to_dict=lambda: {"name": "a.txt"})],
            current_path="/home/user",
            parent_path=None,
        )

        async def fake_run_in_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        service = MagicMock()
        service.search.return_value = fake_result

        with (
            patch("source.services.file_browser.file_browser_service", service),
            patch.object(http_api, "_run_in_thread", new=fake_run_in_thread),
        ):
            result = await http_api.browse_files()

        assert result == {
            "entries": [{"name": "a.txt"}],
            "current_path": "/home/user",
            "parent_path": None,
        }

    @pytest.mark.asyncio
    async def test_browse_files_search_mode_uses_query(self):
        fake_result = SimpleNamespace(entries=[], current_path="/h", parent_path="/")

        async def fake_run_in_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        service = MagicMock()
        service.search.return_value = fake_result

        with (
            patch("source.services.file_browser.file_browser_service", service),
            patch.object(http_api, "_run_in_thread", new=fake_run_in_thread),
        ):
            result = await http_api.browse_files(query="foo")

        assert result["entries"] == []
        service.search.assert_called_once_with("foo", None)

    def test_scheduled_job_conversations_route_returns_job_conversations(self):
        app = FastAPI()
        app.include_router(http_api.router)

        conversations_payload = [
            {
                "id": "conv-1",
                "title": "[Job] Daily Summary",
                "created_at": 123.0,
                "updated_at": 124.0,
                "job_id": "job-1",
                "job_name": "Daily Summary",
            }
        ]

        with patch(
            "source.database.db.get_job_conversations",
            return_value=conversations_payload,
        ) as get_job_conversations:
            client = TestClient(app)
            response = client.get("/api/scheduled-jobs/conversations")

        assert response.status_code == 200
        assert response.json() == {"conversations": conversations_payload}
        get_job_conversations.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_health_check_returns_healthy(self):
        result = await http_api.health_check()
        assert result == {"status": "healthy"}

    @pytest.mark.asyncio
    async def test_get_enabled_models_reads_from_db(self):
        with patch(
            "source.database.db", MagicMock(get_enabled_models=lambda: ["a", "b"])
        ):
            result = await http_api.get_enabled_models()
        assert result == ["a", "b"]

    @pytest.mark.asyncio
    async def test_set_enabled_models_persists_and_returns_payload(self):
        db_mock = MagicMock()
        with patch("source.database.db", db_mock):
            body = http_api.EnabledModelsUpdate(models=["m1", "m2"])
            result = await http_api.set_enabled_models(body)

        db_mock.set_enabled_models.assert_called_once_with(["m1", "m2"])
        assert result == {"status": "updated", "models": ["m1", "m2"]}

    @pytest.mark.asyncio
    async def test_get_api_key_status_delegates_to_key_manager(self):
        key_manager = MagicMock()
        key_manager.get_api_key_status.return_value = {"openai": {"has_key": False}}
        with patch("source.llm.key_manager.key_manager", key_manager):
            result = await http_api.get_api_key_status()

        assert result == {"openai": {"has_key": False}}
        key_manager.get_api_key_status.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_save_api_key_rejects_invalid_provider(self):
        body = http_api.ApiKeyUpdate(key="sk-test")
        with pytest.raises(HTTPException) as exc:
            await http_api.save_api_key("bogus", body)
        assert exc.value.status_code == 400
        assert "Invalid provider" in str(exc.value.detail)

    @pytest.mark.asyncio
    async def test_save_api_key_rejects_empty_key_after_trim(self):
        body = http_api.ApiKeyUpdate(key="   ")
        with pytest.raises(HTTPException) as exc:
            await http_api.save_api_key("openrouter", body)
        assert exc.value.status_code == 400
        assert "cannot be empty" in str(exc.value.detail)

    @pytest.mark.asyncio
    async def test_save_api_key_openrouter_success_saves_and_masks(self):
        key_manager = MagicMock()
        key_manager.mask_key.return_value = "sk-...1234"
        response = SimpleNamespace(status_code=200, json=lambda: {"data": []}, text="")

        async def fake_run_in_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        with (
            patch("source.llm.key_manager.key_manager", key_manager),
            patch("source.llm.key_manager.VALID_PROVIDERS", ("openrouter",)),
            patch.object(http_api, "_run_in_thread", new=fake_run_in_thread),
            patch.object(http_api.requests, "get", return_value=response),
            patch.object(http_api, "_invalidate_model_cache") as invalidate_mock,
        ):
            body = http_api.ApiKeyUpdate(key="  sk-openrouter-test  ")
            result = await http_api.save_api_key("openrouter", body)

        key_manager.save_api_key.assert_called_once_with(
            "openrouter", "sk-openrouter-test"
        )
        invalidate_mock.assert_called_once_with("openrouter")
        assert result == {
            "status": "saved",
            "provider": "openrouter",
            "masked": "sk-...1234",
        }

    @pytest.mark.asyncio
    async def test_save_api_key_openrouter_validation_failure_returns_401(self):
        key_manager = MagicMock()
        response = SimpleNamespace(
            status_code=401,
            json=lambda: {"error": {"message": "bad auth"}},
            text="",
        )

        async def fake_run_in_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        with (
            patch("source.llm.key_manager.key_manager", key_manager),
            patch("source.llm.key_manager.VALID_PROVIDERS", ("openrouter",)),
            patch.object(http_api, "_run_in_thread", new=fake_run_in_thread),
            patch.object(http_api.requests, "get", return_value=response),
        ):
            with pytest.raises(HTTPException) as exc:
                await http_api.save_api_key(
                    "openrouter", http_api.ApiKeyUpdate(key="sk-invalid")
                )

        assert exc.value.status_code == 401
        assert "Invalid API key" in str(exc.value.detail)
        key_manager.save_api_key.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_api_key_rejects_invalid_provider(self):
        with pytest.raises(HTTPException) as exc:
            await http_api.delete_api_key("invalid-provider")
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_delete_api_key_filters_enabled_models_and_invalidates_cache(self):
        key_manager = MagicMock()
        db_mock = MagicMock()
        db_mock.get_enabled_models.return_value = [
            "openai/gpt-4",
            "openrouter/deepseek/model",
            "anthropic/claude",
        ]

        with (
            patch("source.llm.key_manager.key_manager", key_manager),
            patch(
                "source.llm.key_manager.VALID_PROVIDERS",
                ("openrouter", "openai", "anthropic"),
            ),
            patch("source.database.db", db_mock),
            patch.object(http_api, "_invalidate_model_cache") as invalidate_mock,
        ):
            result = await http_api.delete_api_key("openrouter")

        key_manager.delete_api_key.assert_called_once_with("openrouter")
        db_mock.set_enabled_models.assert_called_once_with(
            ["openai/gpt-4", "anthropic/claude"]
        )
        invalidate_mock.assert_called_once_with("openrouter")
        assert result == {"status": "deleted", "provider": "openrouter"}

    @pytest.mark.asyncio
    async def test_get_openrouter_models_maps_403_to_401(self):
        key_manager = MagicMock()
        key_manager.get_api_key.return_value = "sk-openrouter"
        response = SimpleNamespace(
            status_code=403,
            json=lambda: {"error": {"message": "forbidden"}},
            text="",
        )

        async def fake_run_in_thread(fn, *args, **kwargs):
            return response

        with (
            patch("source.llm.key_manager.key_manager", key_manager),
            patch.object(http_api, "_MODEL_CACHE", {}),
            patch.object(http_api, "_run_in_thread", new=fake_run_in_thread),
        ):
            with pytest.raises(HTTPException) as exc:
                await http_api.get_openrouter_models(refresh=True)

        assert exc.value.status_code == 401
        assert "Failed to fetch OpenRouter models: forbidden" in str(exc.value.detail)

    @pytest.mark.asyncio
    async def test_get_openrouter_models_maps_500_to_502(self):
        key_manager = MagicMock()
        key_manager.get_api_key.return_value = "sk-openrouter"
        response = SimpleNamespace(
            status_code=500,
            json=lambda: {"error": {"message": "upstream error"}},
            text="",
        )

        async def fake_run_in_thread(fn, *args, **kwargs):
            return response

        with (
            patch("source.llm.key_manager.key_manager", key_manager),
            patch.object(http_api, "_MODEL_CACHE", {}),
            patch.object(http_api, "_run_in_thread", new=fake_run_in_thread),
        ):
            with pytest.raises(HTTPException) as exc:
                await http_api.get_openrouter_models(refresh=True)

        assert exc.value.status_code == 502
        assert "Failed to fetch OpenRouter models: upstream error" in str(
            exc.value.detail
        )

    @pytest.mark.asyncio
    async def test_get_openrouter_models_rejects_invalid_data_payload(self):
        key_manager = MagicMock()
        key_manager.get_api_key.return_value = "sk-openrouter"
        response = SimpleNamespace(
            status_code=200, json=lambda: {"data": {"id": "x"}}, text=""
        )

        async def fake_run_in_thread(fn, *args, **kwargs):
            return response

        with (
            patch("source.llm.key_manager.key_manager", key_manager),
            patch.object(http_api, "_MODEL_CACHE", {}),
            patch.object(http_api, "_run_in_thread", new=fake_run_in_thread),
        ):
            with pytest.raises(HTTPException) as exc:
                await http_api.get_openrouter_models(refresh=True)

        assert exc.value.status_code == 502
        assert "unexpected model list format" in str(exc.value.detail)

    @pytest.mark.asyncio
    async def test_get_openai_models_filters_to_chat_capable_models(self):
        key_manager = MagicMock()
        key_manager.get_api_key.return_value = "sk-openai"

        fake_response = SimpleNamespace(
            data=[
                SimpleNamespace(id="gpt-4o"),
                SimpleNamespace(id="text-embedding-3-small"),
                SimpleNamespace(id="o3-mini"),
                SimpleNamespace(id="gpt-4o-realtime-preview"),
                SimpleNamespace(id="chatgpt-4o-latest"),
                SimpleNamespace(id="o1-mini"),
                SimpleNamespace(id="gpt-5"),
                SimpleNamespace(id="gpt-4o-mini-tts"),
            ]
        )

        fake_client = SimpleNamespace(
            models=SimpleNamespace(list=AsyncMock(return_value=fake_response))
        )
        fake_openai = SimpleNamespace(AsyncOpenAI=MagicMock(return_value=fake_client))

        with (
            patch("source.llm.key_manager.key_manager", key_manager),
            patch.object(http_api, "_MODEL_CACHE", {}),
            patch.dict(sys.modules, {"openai": fake_openai}),
        ):
            models = await http_api.get_openai_models(refresh=True)

        assert [m["id"] for m in models] == [
            "openai/chatgpt-4o-latest",
            "openai/gpt-4o",
            "openai/gpt-5",
            "openai/o1-mini",
            "openai/o3-mini",
        ]

    @pytest.mark.asyncio
    async def test_get_gemini_models_filters_by_supported_actions(self):
        key_manager = MagicMock()
        key_manager.get_api_key.return_value = "sk-gemini"

        fake_models = [
            SimpleNamespace(
                name="models/gemini-2.0-flash",
                supported_actions=["generateContent"],
                display_name="Gemini Flash",
            ),
            SimpleNamespace(
                name="models/gemini-1.5-pro",
                supported_actions=["generateContent", "countTokens"],
                display_name="Gemini Pro",
            ),
            SimpleNamespace(
                name="models/gemini-embedding-001",
                supported_actions=["generateContent"],
                display_name="Embedding",
            ),
            SimpleNamespace(
                name="models/gemini-2.0-image",
                supported_actions=["embedContent"],
                display_name="Image",
            ),
        ]

        fake_client = SimpleNamespace(
            models=SimpleNamespace(list=MagicMock(return_value=fake_models))
        )
        fake_genai = SimpleNamespace(Client=MagicMock(return_value=fake_client))
        fake_google = SimpleNamespace(genai=fake_genai)

        async def fake_run_in_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        with (
            patch("source.llm.key_manager.key_manager", key_manager),
            patch.object(http_api, "_MODEL_CACHE", {}),
            patch.object(http_api, "_run_in_thread", new=fake_run_in_thread),
            patch.dict(sys.modules, {"google": fake_google}),
        ):
            models = await http_api.get_gemini_models(refresh=True)

        assert [m["id"] for m in models] == [
            "gemini/gemini-1.5-pro",
            "gemini/gemini-2.0-flash",
        ]

    @pytest.mark.asyncio
    async def test_connect_google_success_starts_mcp_servers(self):
        google_auth = MagicMock()
        google_auth.start_oauth_flow.return_value = {
            "success": True,
            "account_email": "user@example.com",
        }
        mcp_manager = SimpleNamespace(connect_google_servers=AsyncMock())

        async def fake_run_in_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        with (
            patch("source.services.google_auth.google_auth", google_auth),
            patch("source.mcp_integration.manager.mcp_manager", mcp_manager),
            patch.object(http_api, "_run_in_thread", new=fake_run_in_thread),
        ):
            result = await http_api.connect_google()

        assert result == {"success": True, "account_email": "user@example.com"}
        mcp_manager.connect_google_servers.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_connect_google_returns_400_when_oauth_reports_failure(self):
        google_auth = MagicMock()
        google_auth.start_oauth_flow.return_value = {
            "success": False,
            "error": "access_denied",
        }

        async def fake_run_in_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        with (
            patch("source.services.google_auth.google_auth", google_auth),
            patch.object(http_api, "_run_in_thread", new=fake_run_in_thread),
        ):
            with pytest.raises(HTTPException) as exc:
                await http_api.connect_google()

        assert exc.value.status_code == 400
        assert exc.value.detail == "access_denied"

    @pytest.mark.asyncio
    async def test_connect_google_returns_500_when_oauth_raises(self):
        google_auth = MagicMock()
        google_auth.start_oauth_flow.side_effect = RuntimeError("callback timeout")

        async def fake_run_in_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        with (
            patch("source.services.google_auth.google_auth", google_auth),
            patch.object(http_api, "_run_in_thread", new=fake_run_in_thread),
        ):
            with pytest.raises(HTTPException) as exc:
                await http_api.connect_google()

        assert exc.value.status_code == 500
        assert "OAuth flow failed" in str(exc.value.detail)

    @pytest.mark.asyncio
    async def test_disconnect_google_returns_result_on_success(self):
        google_auth = MagicMock()
        google_auth.disconnect.return_value = {"success": True}
        mcp_manager = SimpleNamespace(disconnect_google_servers=AsyncMock())

        with (
            patch("source.services.google_auth.google_auth", google_auth),
            patch("source.mcp_integration.manager.mcp_manager", mcp_manager),
        ):
            result = await http_api.disconnect_google()

        assert result == {"success": True}
        mcp_manager.disconnect_google_servers.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_disconnect_google_ignores_mcp_disconnect_failures(self):
        google_auth = MagicMock()
        google_auth.disconnect.return_value = {"success": True, "disconnected": True}
        mcp_manager = SimpleNamespace(
            disconnect_google_servers=AsyncMock(
                side_effect=RuntimeError("shutdown failure")
            )
        )

        with (
            patch("source.services.google_auth.google_auth", google_auth),
            patch("source.mcp_integration.manager.mcp_manager", mcp_manager),
        ):
            result = await http_api.disconnect_google()

        assert result == {"success": True, "disconnected": True}
        mcp_manager.disconnect_google_servers.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_get_tools_settings_parses_json_and_defaults_top_k(self):
        db_mock = MagicMock()
        db_mock.get_setting.side_effect = lambda key: {
            "tool_always_on": '["filesystem","terminal"]',
            "tool_retriever_top_k": None,
        }.get(key)

        with patch("source.database.db", db_mock):
            result = await http_api.get_tools_settings()

        assert result == {"always_on": ["filesystem", "terminal"], "top_k": 5}

    @pytest.mark.asyncio
    async def test_get_tools_settings_handles_invalid_json(self):
        db_mock = MagicMock()
        db_mock.get_setting.side_effect = lambda key: {
            "tool_always_on": "{not-json",
            "tool_retriever_top_k": "9",
        }.get(key)

        with patch("source.database.db", db_mock):
            result = await http_api.get_tools_settings()

        assert result == {"always_on": [], "top_k": 9}

    @pytest.mark.asyncio
    async def test_set_tools_settings_persists_values(self):
        db_mock = MagicMock()
        body = http_api.ToolsSettingsUpdate(always_on=["a", "b"], top_k=3)

        with patch("source.database.db", db_mock):
            result = await http_api.set_tools_settings(body)

        db_mock.set_setting.assert_any_call("tool_always_on", '["a", "b"]')
        db_mock.set_setting.assert_any_call("tool_retriever_top_k", "3")
        assert result["status"] == "updated"
        assert result["settings"] == {"always_on": ["a", "b"], "top_k": 3}

    @pytest.mark.asyncio
    async def test_get_mobile_channels_config_parses_json_and_defaults(self):
        db_mock = MagicMock()
        db_mock.get_setting.side_effect = lambda key: {
            "mobile_channel_telegram": '{"enabled": true, "token": "tg-token", "status": "connected"}',
            "mobile_channel_discord": None,
            "mobile_channel_whatsapp": "{bad-json",
        }.get(key)

        with patch("source.database.db", db_mock):
            result = await http_api.get_mobile_channels_config()

        assert result == {
            "platforms": {
                "telegram": {
                    "enabled": True,
                    "token": "***",
                    "status": "connected",
                },
                "discord": {
                    "enabled": False,
                    "status": "disconnected",
                },
                "whatsapp": {
                    "enabled": False,
                    "status": "disconnected",
                },
            }
        }

    @pytest.mark.asyncio
    async def test_set_mobile_platform_config_serializes_dict_for_storage(self):
        db_mock = MagicMock()
        db_mock.get_setting.return_value = (
            '{"enabled": false, "token": "old-token", "status": "connected"}'
        )

        body = http_api.MobilePlatformConfig(enabled=True)
        with (
            patch("source.database.db", db_mock),
            patch.object(http_api, "_write_mobile_channels_config_file"),
        ):
            result = await http_api.set_mobile_platform_config("telegram", body)

        args = db_mock.set_setting.call_args.args
        assert args[0] == "mobile_channel_telegram"
        assert isinstance(args[1], str)
        assert json.loads(args[1]) == {
            "enabled": True,
            "token": "old-token",
            "status": "connected",
        }
        assert result == {"success": True}

    @pytest.mark.asyncio
    async def test_set_mobile_platform_config_recovers_from_invalid_existing_json(self):
        db_mock = MagicMock()
        db_mock.get_setting.return_value = "{bad-json"

        body = http_api.MobilePlatformConfig(token="new-token", enabled=True)
        with (
            patch("source.database.db", db_mock),
            patch.object(http_api, "_write_mobile_channels_config_file"),
        ):
            result = await http_api.set_mobile_platform_config("telegram", body)

        args = db_mock.set_setting.call_args.args
        assert args[0] == "mobile_channel_telegram"
        assert json.loads(args[1]) == {
            "token": "new-token",
            "enabled": True,
            "status": "disconnected",
        }
        assert result == {"success": True}

    @pytest.mark.asyncio
    async def test_set_mobile_platform_config_returns_500_when_bridge_sync_fails(self):
        db_mock = MagicMock()
        db_mock.get_setting.return_value = '{"enabled": false}'

        body = http_api.MobilePlatformConfig(enabled=True)
        with (
            patch("source.database.db", db_mock),
            patch.object(
                http_api,
                "_write_mobile_channels_config_file",
                side_effect=OSError("disk full"),
            ),
        ):
            with pytest.raises(HTTPException) as exc:
                await http_api.set_mobile_platform_config("telegram", body)

        assert exc.value.status_code == 500
        assert "failed to sync mobile bridge config" in str(exc.value.detail).lower()

    def test_write_mobile_channels_config_file_serializes_defaults_and_db_values(
        self, tmp_path
    ):
        db_mock = MagicMock()
        db_mock.get_setting.side_effect = lambda key: {
            "mobile_channel_telegram": '{"enabled": true, "token": "tg-token"}',
            "mobile_channel_discord": "{bad-json",
            "mobile_channel_whatsapp": '{"enabled": true, "phoneNumber": "15551234567", "forcePairing": true}',
        }.get(key)

        fake_state = SimpleNamespace(server_loop_holder={"port": 8012})

        with (
            patch("source.database.db", db_mock),
            patch("source.config.USER_DATA_DIR", tmp_path),
            patch("source.core.state.app_state", fake_state),
        ):
            http_api._write_mobile_channels_config_file()

        config_path = tmp_path / "mobile_channels_config.json"
        payload = json.loads(config_path.read_text(encoding="utf-8"))

        assert payload == {
            "version": 1,
            "pythonServerPort": 8012,
            "platforms": {
                "telegram": {
                    "enabled": True,
                    "botToken": "tg-token",
                    "botUsername": "xpdite-bot",
                },
                "discord": {
                    "enabled": False,
                    "botToken": "",
                    "publicKey": "",
                    "applicationId": "",
                },
                "whatsapp": {
                    "enabled": True,
                    "authMethod": "pairing_code",
                    "phoneNumber": "15551234567",
                    "forcePairing": True,
                },
            },
        }

    def test_write_mobile_channels_config_file_uses_atomic_replace(self, tmp_path):
        db_mock = MagicMock()
        db_mock.get_setting.return_value = None
        fake_state = SimpleNamespace(server_loop_holder={"port": 8000})

        with (
            patch("source.database.db", db_mock),
            patch("source.config.USER_DATA_DIR", tmp_path),
            patch("source.core.state.app_state", fake_state),
            patch.object(http_api.os, "replace") as replace_mock,
        ):
            http_api._write_mobile_channels_config_file()

        assert replace_mock.call_count == 1
        src_path, dst_path = replace_mock.call_args.args
        assert src_path.name.endswith(".tmp")
        assert dst_path == tmp_path / "mobile_channels_config.json"

    @pytest.mark.asyncio
    async def test_get_sub_agent_settings_uses_empty_defaults(self):
        db_mock = MagicMock()
        db_mock.get_setting.return_value = None

        with patch("source.database.db", db_mock):
            result = await http_api.get_sub_agent_settings()

        assert result == {"fast_model": "", "smart_model": ""}

    @pytest.mark.asyncio
    async def test_set_sub_agent_settings_sets_and_deletes_based_on_trim(self):
        db_mock = MagicMock()
        body = http_api.SubAgentSettingsUpdate(fast_model=" fast-1 ", smart_model="   ")

        with patch("source.database.db", db_mock):
            result = await http_api.set_sub_agent_settings(body)

        db_mock.set_setting.assert_called_once_with("sub_agent_tier_fast", "fast-1")
        db_mock.delete_setting.assert_called_once_with("sub_agent_tier_smart")
        assert result == {"status": "updated"}

    @pytest.mark.asyncio
    async def test_get_memory_settings_defaults_to_enabled(self):
        db_mock = MagicMock()
        db_mock.get_setting.return_value = None

        with patch("source.database.db", db_mock):
            result = await http_api.get_memory_settings()

        assert result == {"profile_auto_inject": True}

    @pytest.mark.asyncio
    async def test_set_memory_settings_persists_boolean_flag(self):
        db_mock = MagicMock()

        with patch("source.database.db", db_mock):
            result = await http_api.set_memory_settings(
                http_api.MemorySettingsUpdate(profile_auto_inject=False)
            )

        db_mock.set_setting.assert_called_once_with(
            "memory_profile_auto_inject", "false"
        )
        assert result == {
            "status": "updated",
            "settings": {"profile_auto_inject": False},
        }

    @pytest.mark.asyncio
    async def test_list_memories_returns_payload_from_service(self):
        memory_service = MagicMock()
        memory_service.list_memories.return_value = [{"path": "semantic/prefs.md"}]

        async def fake_run_in_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        with (
            patch("source.services.memory.memory_service", memory_service),
            patch.object(http_api, "_run_in_thread", new=fake_run_in_thread),
        ):
            result = await http_api.list_memories(folder="semantic")

        memory_service.list_memories.assert_called_once_with("semantic")
        assert result == {"memories": [{"path": "semantic/prefs.md"}]}

    @pytest.mark.asyncio
    async def test_list_memories_maps_filesystem_errors_to_500(self):
        memory_service = MagicMock()
        memory_service.list_memories.side_effect = OSError("disk failure")

        async def fake_run_in_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        with (
            patch("source.services.memory.memory_service", memory_service),
            patch.object(http_api, "_run_in_thread", new=fake_run_in_thread),
        ):
            with pytest.raises(HTTPException) as exc:
                await http_api.list_memories(folder="semantic")

        assert exc.value.status_code == 500
        assert exc.value.detail == "Memory listing failed. See server logs for details."

    @pytest.mark.asyncio
    async def test_get_memory_file_maps_missing_files_to_404(self):
        memory_service = MagicMock()
        memory_service.read_memory.side_effect = FileNotFoundError

        async def fake_run_in_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        with (
            patch("source.services.memory.memory_service", memory_service),
            patch.object(http_api, "_run_in_thread", new=fake_run_in_thread),
        ):
            with pytest.raises(HTTPException) as exc:
                await http_api.get_memory_file("semantic/prefs.md")

        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_memory_file_maps_decode_errors_to_500(self):
        memory_service = MagicMock()
        memory_service.read_memory.side_effect = UnicodeDecodeError(
            "utf-8", b"\xff", 0, 1, "invalid start byte"
        )

        async def fake_run_in_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        with (
            patch("source.services.memory.memory_service", memory_service),
            patch.object(http_api, "_run_in_thread", new=fake_run_in_thread),
        ):
            with pytest.raises(HTTPException) as exc:
                await http_api.get_memory_file("semantic/prefs.md")

        assert exc.value.status_code == 500
        assert exc.value.detail == "Memory read failed. See server logs for details."

    @pytest.mark.asyncio
    async def test_update_memory_file_delegates_to_service(self):
        memory_service = MagicMock()
        memory_service.upsert_memory.return_value = {"path": "semantic/prefs.md"}

        async def fake_run_in_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        body = http_api.MemoryFileUpdate(
            path="semantic/prefs.md",
            title="Prefs",
            category="semantic",
            importance=0.7,
            tags=["prefs"],
            abstract="Stores a preference.",
            body="Be concise.",
        )

        with (
            patch("source.services.memory.memory_service", memory_service),
            patch.object(http_api, "_run_in_thread", new=fake_run_in_thread),
        ):
            result = await http_api.update_memory_file(body)

        memory_service.upsert_memory.assert_called_once_with(
            path="semantic/prefs.md",
            title="Prefs",
            category="semantic",
            importance=0.7,
            tags=["prefs"],
            abstract="Stores a preference.",
            body="Be concise.",
        )
        assert result == {"path": "semantic/prefs.md"}

    @pytest.mark.asyncio
    async def test_delete_memory_file_returns_not_found_when_missing(self):
        memory_service = MagicMock()
        memory_service.delete_memory.return_value = False

        async def fake_run_in_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        with (
            patch("source.services.memory.memory_service", memory_service),
            patch.object(http_api, "_run_in_thread", new=fake_run_in_thread),
        ):
            with pytest.raises(HTTPException) as exc:
                await http_api.delete_memory_file("semantic/prefs.md")

        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_clear_all_memories_returns_deleted_count(self):
        memory_service = MagicMock()
        memory_service.clear_all_memories.return_value = 3

        async def fake_run_in_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        with (
            patch("source.services.memory.memory_service", memory_service),
            patch.object(http_api, "_run_in_thread", new=fake_run_in_thread),
        ):
            result = await http_api.clear_all_memories()

        memory_service.clear_all_memories.assert_called_once_with()
        assert result == {"success": True, "deleted_count": 3}

    @pytest.mark.asyncio
    async def test_clear_all_memories_maps_filesystem_errors_to_500(self):
        memory_service = MagicMock()
        memory_service.clear_all_memories.side_effect = OSError("permission denied")

        async def fake_run_in_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        with (
            patch("source.services.memory.memory_service", memory_service),
            patch.object(http_api, "_run_in_thread", new=fake_run_in_thread),
        ):
            with pytest.raises(HTTPException) as exc:
                await http_api.clear_all_memories()

        assert exc.value.status_code == 500
        assert exc.value.detail == "Memory clear failed. See server logs for details."

    @pytest.mark.asyncio
    async def test_get_system_prompt_returns_default_when_not_custom(self):
        db_mock = MagicMock()
        db_mock.get_system_prompt_template.return_value = None

        with (
            patch("source.database.db", db_mock),
            patch("source.llm.prompt._BASE_TEMPLATE", "DEFAULT-TEMPLATE"),
        ):
            result = await http_api.get_system_prompt()

        assert result == {"template": "DEFAULT-TEMPLATE", "is_custom": False}

    @pytest.mark.asyncio
    async def test_get_system_prompt_returns_custom_when_present(self):
        db_mock = MagicMock()
        db_mock.get_system_prompt_template.return_value = "CUSTOM"

        with patch("source.database.db", db_mock):
            result = await http_api.get_system_prompt()

        assert result == {"template": "CUSTOM", "is_custom": True}

    @pytest.mark.asyncio
    async def test_update_system_prompt_strips_and_stores(self):
        db_mock = MagicMock()
        with patch("source.database.db", db_mock):
            result = await http_api.update_system_prompt(
                http_api.SystemPromptUpdate(template="  Hello prompt  ")
            )

        db_mock.set_system_prompt_template.assert_called_once_with("Hello prompt")
        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_update_system_prompt_empty_resets_to_default(self):
        db_mock = MagicMock()
        with patch("source.database.db", db_mock):
            result = await http_api.update_system_prompt(
                http_api.SystemPromptUpdate(template="   ")
            )

        db_mock.set_system_prompt_template.assert_called_once_with(None)
        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_skills_endpoints_handle_success_and_errors(self):
        manager = MagicMock()
        manager.get_all_skills_with_overrides.return_value = [{"name": "terminal"}]
        manager.get_skill_content.return_value = "skill content"
        manager.create_user_skill.return_value = SimpleNamespace(
            to_dict=lambda: {"name": "new-skill"}
        )
        manager.update_user_skill.return_value = SimpleNamespace(
            to_dict=lambda: {"name": "edited-skill"}
        )
        manager.toggle_skill.return_value = True
        manager.delete_user_skill.return_value = True

        async def fake_run_in_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        with (
            patch("source.services.skills.get_skill_manager", return_value=manager),
            patch.object(http_api, "_run_in_thread", new=fake_run_in_thread),
        ):
            all_skills = await http_api.get_skills()
            content = await http_api.get_skill_content("terminal")
            created = await http_api.create_skill(
                http_api.SkillCreate(
                    name="new-skill",
                    description="desc",
                    slash_command="new",
                    content="hello",
                    trigger_servers=["filesystem"],
                )
            )
            updated = await http_api.update_skill(
                "new-skill",
                http_api.SkillUpdate(description="updated"),
            )
            toggled = await http_api.toggle_skill(
                "new-skill", http_api.SkillToggle(enabled=True)
            )
            deleted = await http_api.delete_skill("new-skill")
            ref_added = await http_api.add_reference_file(
                "new-skill",
                http_api.ReferenceFileCreate(filename="notes.md", content="content"),
            )

        assert all_skills == [{"name": "terminal"}]
        assert content == {"name": "terminal", "content": "skill content"}
        assert created == {"status": "created", "skill": {"name": "new-skill"}}
        assert updated == {"status": "updated", "skill": {"name": "edited-skill"}}
        assert toggled == {"status": "toggled", "name": "new-skill", "enabled": True}
        assert deleted == {"status": "deleted"}
        assert ref_added == {"status": "created", "filename": "notes.md"}

    @pytest.mark.asyncio
    async def test_skills_endpoints_raise_expected_http_errors(self):
        manager = MagicMock()
        manager.get_skill_content.return_value = None
        manager.create_user_skill.side_effect = ValueError("duplicate")
        manager.update_user_skill.side_effect = ValueError("invalid update")
        manager.toggle_skill.return_value = False
        manager.delete_user_skill.return_value = False
        manager.add_reference_file.side_effect = ValueError("nope")

        async def fake_run_in_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        with (
            patch("source.services.skills.get_skill_manager", return_value=manager),
            patch.object(http_api, "_run_in_thread", new=fake_run_in_thread),
        ):
            with pytest.raises(HTTPException) as not_found:
                await http_api.get_skill_content("missing")
            with pytest.raises(HTTPException) as create_err:
                await http_api.create_skill(
                    http_api.SkillCreate(
                        name="x",
                        description="d",
                        slash_command=None,
                        content="body",
                        trigger_servers=[],
                    )
                )
            with pytest.raises(HTTPException) as update_err:
                await http_api.update_skill("x", http_api.SkillUpdate(description="d"))
            with pytest.raises(HTTPException) as toggle_err:
                await http_api.toggle_skill("x", http_api.SkillToggle(enabled=False))
            with pytest.raises(HTTPException) as delete_err:
                await http_api.delete_skill("x")
            with pytest.raises(HTTPException) as bad_extension:
                await http_api.add_reference_file(
                    "x", http_api.ReferenceFileCreate(filename="bad.txt", content="x")
                )
            with pytest.raises(HTTPException) as add_ref_err:
                await http_api.add_reference_file(
                    "x", http_api.ReferenceFileCreate(filename="ok.md", content="x")
                )

        assert not_found.value.status_code == 404
        assert create_err.value.status_code == 400
        assert update_err.value.status_code == 400
        assert toggle_err.value.status_code == 404
        assert delete_err.value.status_code == 400
        assert bad_extension.value.status_code == 400
        assert add_ref_err.value.status_code == 400
