"""High-value tests for source/api/http.py endpoints and helpers."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

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
    async def test_health_check_returns_healthy(self):
        result = await http_api.health_check()
        assert result == {"status": "healthy"}

    @pytest.mark.asyncio
    async def test_get_enabled_models_reads_from_db(self):
        with patch("source.database.db", MagicMock(get_enabled_models=lambda: ["a", "b"])):
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

        key_manager.save_api_key.assert_called_once_with("openrouter", "sk-openrouter-test")
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
            patch("source.llm.key_manager.VALID_PROVIDERS", ("openrouter", "openai", "anthropic")),
            patch("source.database.db", db_mock),
            patch.object(http_api, "_invalidate_model_cache") as invalidate_mock,
        ):
            result = await http_api.delete_api_key("openrouter")

        key_manager.delete_api_key.assert_called_once_with("openrouter")
        db_mock.set_enabled_models.assert_called_once_with(["openai/gpt-4", "anthropic/claude"])
        invalidate_mock.assert_called_once_with("openrouter")
        assert result == {"status": "deleted", "provider": "openrouter"}

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
