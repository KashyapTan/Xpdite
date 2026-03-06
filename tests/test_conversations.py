"""Tests for source/services/conversations.py."""

from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from source.services.conversations import (
    ConversationService,
    _extract_skill_slash_commands_sync,
)
from source.services.skills import Skill
from source.services.tab_manager import TabState


def _make_skill(name, slash_command, enabled=True):
    return Skill(
        name=name,
        description=f"{name.title()} skill",
        slash_command=slash_command,
        trigger_servers=[name],
        version="1.0.0",
        source="builtin",
        folder_path=Path(f"fake/{name}"),
        enabled=enabled,
    )


@pytest.fixture()
def db_manager(tmp_path):
    from source.database import DatabaseManager

    return DatabaseManager(database_path=str(tmp_path / "test.db"))


class TestExtractSkillSlashCommands:
    def _call(self, message, skills):
        mock_manager = MagicMock()
        mock_manager.get_all_skills.return_value = skills
        with patch("source.services.skills.get_skill_manager", return_value=mock_manager):
            return _extract_skill_slash_commands_sync(message)

    def test_no_slash_commands(self):
        matched, cleaned = self._call("hello world", [])
        assert matched == []
        assert cleaned == "hello world"

    def test_single_slash_command(self):
        skills = [_make_skill("terminal", "terminal")]
        matched, cleaned = self._call("/terminal run this", skills)
        assert len(matched) == 1
        assert matched[0].name == "terminal"
        assert cleaned == "run this"

    def test_multiple_slash_commands(self):
        skills = [
            _make_skill("terminal", "terminal"),
            _make_skill("websearch", "websearch"),
        ]
        matched, cleaned = self._call("/terminal /websearch do stuff", skills)
        assert len(matched) == 2
        names = {s.name for s in matched}
        assert names == {"terminal", "websearch"}
        assert cleaned == "do stuff"

    def test_unknown_slash_command_preserved(self):
        skills = [_make_skill("terminal", "terminal")]
        matched, cleaned = self._call("/unknown hello", skills)
        assert matched == []
        assert "/unknown" in cleaned
        assert "hello" in cleaned

    def test_disabled_skill_not_matched(self):
        skills = [_make_skill("terminal", "terminal", enabled=False)]
        matched, cleaned = self._call("/terminal run this", skills)
        assert matched == []
        assert cleaned == "run this"

    def test_slash_in_middle_of_message(self):
        skills = [_make_skill("websearch", "websearch")]
        matched, cleaned = self._call("please /websearch for python docs", skills)
        assert len(matched) == 1
        assert cleaned == "please for python docs"

    def test_empty_message(self):
        matched, cleaned = self._call("", [])
        assert matched == []
        assert cleaned == ""

    def test_case_sensitivity(self):
        """Slash command matching is case-sensitive (lowercase)."""
        skills = [_make_skill("terminal", "terminal")]
        matched, _ = self._call("/Terminal run this", skills)
        # "/Terminal" → token[1:].lower() = "terminal" → matches
        assert len(matched) == 1


class TestConversationBranching:
    def _seed_turn(self, db_manager, conversation_id, user_content="Hello", assistant_content="Hi"):
        user_message = db_manager.add_message(conversation_id, "user", user_content)
        assistant_message = db_manager.add_message(
            conversation_id,
            "assistant",
            assistant_content,
            model="model-a",
            content_blocks=[{"type": "text", "content": assistant_content}],
            turn_id=user_message["turn_id"],
        )
        db_manager.save_response_version(
            conversation_id,
            assistant_message["message_id"],
            assistant_content,
            model="model-a",
            content_blocks=[{"type": "text", "content": assistant_content}],
            created_at=assistant_message["timestamp"],
            replace_history=True,
        )
        return user_message, assistant_message

    @pytest.mark.asyncio
    async def test_submit_query_persists_normal_turn(self, db_manager, monkeypatch):
        cid = db_manager.start_new_conversation("Existing chat")
        tab_state = TabState(tab_id="default")
        tab_state.conversation_id = cid
        tab_state.chat_history = []

        monkeypatch.setattr("source.services.conversations.db", db_manager)
        monkeypatch.setattr(
            "source.services.conversations.route_chat",
            AsyncMock(
                return_value=(
                    "Fresh answer",
                    {"prompt_eval_count": 2, "eval_count": 4},
                    [],
                    [{"type": "text", "content": "Fresh answer"}],
                )
            ),
        )
        monkeypatch.setattr("source.services.conversations.broadcast_message", AsyncMock())

        conversation_id = await ConversationService.submit_query(
            user_query="Fresh question",
            llm_query="Fresh question",
            tab_state=tab_state,
            model="model-a",
        )

        assert conversation_id == cid
        messages = db_manager.get_full_conversation(cid)
        assert [message["content"] for message in messages] == [
            "Fresh question",
            "Fresh answer",
        ]
        assert messages[0]["turn_id"] == messages[1]["turn_id"]
        assert messages[1]["response_variants"][0]["content"] == "Fresh answer"

    @pytest.mark.asyncio
    async def test_retry_message_creates_response_variant_and_truncates_later_turns(
        self, db_manager, monkeypatch
    ):
        cid = db_manager.start_new_conversation("Retry this")
        first_user, first_assistant = self._seed_turn(
            db_manager, cid, user_content="First question", assistant_content="First answer"
        )
        self._seed_turn(
            db_manager, cid, user_content="Second question", assistant_content="Second answer"
        )

        tab_state = TabState(tab_id="default")
        tab_state.conversation_id = cid
        tab_state.chat_history = db_manager.get_active_chat_history(cid)

        monkeypatch.setattr("source.services.conversations.db", db_manager)
        monkeypatch.setattr(
            "source.services.conversations.route_chat",
            AsyncMock(
                return_value=(
                    "Retried answer",
                    {"prompt_eval_count": 3, "eval_count": 5},
                    [],
                    [{"type": "text", "content": "Retried answer"}],
                )
            ),
        )
        broadcast_mock = AsyncMock()
        monkeypatch.setattr("source.services.conversations.broadcast_message", broadcast_mock)

        conversation_id = await ConversationService.submit_query(
            user_query="First question",
            llm_query="First question",
            tab_state=tab_state,
            model="model-b",
            action="retry",
            target_message_id=first_assistant["message_id"],
        )

        assert conversation_id == cid
        messages = db_manager.get_full_conversation(cid)
        assert [message["content"] for message in messages] == [
            "First question",
            "Retried answer",
        ]
        assert messages[1]["active_response_index"] == 1
        assert [variant["content"] for variant in messages[1]["response_variants"]] == [
            "First answer",
            "Retried answer",
        ]
        assert tab_state.chat_history[-1]["content"] == "Retried answer"
        broadcast_mock.assert_any_call(
            "conversation_saved",
            {
                "conversation_id": cid,
                "operation": "retry",
                "truncate_after_turn": True,
                "turn": db_manager.get_turn_payload(cid, first_user["turn_id"]),
            },
        )

    @pytest.mark.asyncio
    async def test_edit_message_replaces_prompt_and_resets_response_history(
        self, db_manager, monkeypatch
    ):
        cid = db_manager.start_new_conversation("Original prompt")
        first_user, first_assistant = self._seed_turn(
            db_manager, cid, user_content="Original prompt", assistant_content="Original answer"
        )
        db_manager.save_response_version(
            cid,
            first_assistant["message_id"],
            "Alternate original answer",
            model="model-a",
            content_blocks=[{"type": "text", "content": "Alternate original answer"}],
        )
        self._seed_turn(
            db_manager, cid, user_content="Follow up", assistant_content="Follow up answer"
        )

        tab_state = TabState(tab_id="default")
        tab_state.conversation_id = cid
        tab_state.chat_history = db_manager.get_active_chat_history(cid)

        monkeypatch.setattr("source.services.conversations.db", db_manager)
        monkeypatch.setattr(
            "source.services.conversations.route_chat",
            AsyncMock(
                return_value=(
                    "Edited answer",
                    {"prompt_eval_count": 2, "eval_count": 4},
                    [],
                    [{"type": "text", "content": "Edited answer"}],
                )
            ),
        )
        monkeypatch.setattr(
            "source.services.conversations.broadcast_message", AsyncMock()
        )

        conversation_id = await ConversationService.submit_query(
            user_query="Edited prompt",
            llm_query="Edited prompt",
            tab_state=tab_state,
            model="model-c",
            action="edit",
            target_message_id=first_user["message_id"],
        )

        assert conversation_id == cid
        messages = db_manager.get_full_conversation(cid)
        assert [message["content"] for message in messages] == [
            "Edited prompt",
            "Edited answer",
        ]
        assert len(messages[1]["response_variants"]) == 1
        assert messages[1]["response_variants"][0]["content"] == "Edited answer"
        assert db_manager.get_recent_conversations(limit=1)[0]["title"] == "Edited prompt"
        assert tab_state.chat_history[0]["content"] == "Edited prompt"

    @pytest.mark.asyncio
    async def test_resume_conversation_keeps_image_paths_in_backend_history(
        self, db_manager, monkeypatch, tmp_path
    ):
        cid = db_manager.start_new_conversation("Image chat")
        image_path = tmp_path / "image.png"
        image_path.write_bytes(b"fake-image")
        db_manager.add_message(cid, "user", "See this", images=[str(image_path)])

        tab_state = TabState(tab_id="default")
        broadcast_mock = AsyncMock()
        monkeypatch.setattr("source.services.conversations.db", db_manager)
        monkeypatch.setattr("source.services.conversations.broadcast_message", broadcast_mock)
        monkeypatch.setattr(
            "source.services.conversations.run_in_thread",
            AsyncMock(return_value="thumb-data"),
        )

        await ConversationService.resume_conversation(cid, tab_state=tab_state)

        assert tab_state.chat_history[0]["images"] == [str(image_path)]
        resume_payload = broadcast_mock.await_args_list[0].args[1]
        assert resume_payload is not None
        if isinstance(resume_payload, str):
            import json

            resume_payload = json.loads(resume_payload)
        assert resume_payload["messages"][0]["images"] == [
            {"name": "image.png", "thumbnail": "thumb-data"}
        ]
