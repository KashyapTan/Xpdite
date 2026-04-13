"""Tests for source/services/chat/conversations.py."""

from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from source.services.chat.conversations import (
    ConversationService,
    _extract_skill_slash_commands_sync,
)
from source.services.skills_runtime.skills import Skill
from source.services.chat.tab_manager import TabState

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


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
    from source.infrastructure.database import DatabaseManager

    return DatabaseManager(database_path=str(tmp_path / "test.db"))


class TestExtractSkillSlashCommands:
    def _call(self, message, skills):
        mock_manager = MagicMock()
        mock_manager.get_all_skills.return_value = skills
        with patch(
            "source.services.skills_runtime.skills.get_skill_manager", return_value=mock_manager
        ):
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

    def test_namespaced_slash_command(self):
        skills = [_make_skill("planner:triage", "planner:triage")]
        matched, cleaned = self._call("/planner:triage review this", skills)
        assert len(matched) == 1
        assert matched[0].slash_command == "planner:triage"
        assert cleaned == "review this"

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

    def test_multiple_slash_commands_inline(self):
        skills = [
            _make_skill("terminal", "terminal"),
            _make_skill("websearch", "websearch"),
        ]
        matched, cleaned = self._call(
            "please /websearch then /terminal for docs",
            skills,
        )
        assert [skill.name for skill in matched] == ["websearch", "terminal"]
        assert cleaned == "please then for docs"

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

    def test_duplicate_slash_commands_only_force_once(self):
        skills = [_make_skill("terminal", "terminal")]
        matched, cleaned = self._call("/terminal /terminal run this", skills)
        assert len(matched) == 1
        assert matched[0].name == "terminal"
        assert cleaned == "run this"

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
    def _seed_turn(
        self, db_manager, conversation_id, user_content="Hello", assistant_content="Hi"
    ):
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

    @pytest.mark.anyio
    async def test_submit_query_persists_normal_turn(self, db_manager, monkeypatch):
        cid = db_manager.start_new_conversation("Existing chat")
        tab_state = TabState(tab_id="default")
        tab_state.conversation_id = cid
        tab_state.chat_history = []

        monkeypatch.setattr("source.services.chat.conversations.db", db_manager)
        monkeypatch.setattr(
            "source.services.chat.conversations.route_chat",
            AsyncMock(
                return_value=(
                    "Fresh answer",
                    {"prompt_eval_count": 2, "eval_count": 4},
                    [],
                    [{"type": "text", "content": "Fresh answer"}],
                )
            ),
        )
        monkeypatch.setattr(
            "source.services.chat.conversations.broadcast_message", AsyncMock()
        )

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

    @pytest.mark.anyio
    async def test_retry_message_creates_response_variant_and_truncates_later_turns(
        self, db_manager, monkeypatch
    ):
        cid = db_manager.start_new_conversation("Retry this")
        first_user, first_assistant = self._seed_turn(
            db_manager,
            cid,
            user_content="First question",
            assistant_content="First answer",
        )
        self._seed_turn(
            db_manager,
            cid,
            user_content="Second question",
            assistant_content="Second answer",
        )

        tab_state = TabState(tab_id="default")
        tab_state.conversation_id = cid
        tab_state.chat_history = db_manager.get_active_chat_history(cid)

        monkeypatch.setattr("source.services.chat.conversations.db", db_manager)
        monkeypatch.setattr(
            "source.services.chat.conversations.route_chat",
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
        monkeypatch.setattr(
            "source.services.chat.conversations.broadcast_message", broadcast_mock
        )

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

    @pytest.mark.anyio
    async def test_edit_message_replaces_prompt_and_resets_response_history(
        self, db_manager, monkeypatch
    ):
        cid = db_manager.start_new_conversation("Original prompt")
        first_user, first_assistant = self._seed_turn(
            db_manager,
            cid,
            user_content="Original prompt",
            assistant_content="Original answer",
        )
        db_manager.save_response_version(
            cid,
            first_assistant["message_id"],
            "Alternate original answer",
            model="model-a",
            content_blocks=[{"type": "text", "content": "Alternate original answer"}],
        )
        self._seed_turn(
            db_manager,
            cid,
            user_content="Follow up",
            assistant_content="Follow up answer",
        )

        tab_state = TabState(tab_id="default")
        tab_state.conversation_id = cid
        tab_state.chat_history = db_manager.get_active_chat_history(cid)

        monkeypatch.setattr("source.services.chat.conversations.db", db_manager)
        monkeypatch.setattr(
            "source.services.chat.conversations.route_chat",
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
            "source.services.chat.conversations.broadcast_message", AsyncMock()
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
        assert (
            db_manager.get_recent_conversations(limit=1)[0]["title"] == "Edited prompt"
        )
        assert tab_state.chat_history[0]["content"] == "Edited prompt"

    @pytest.mark.anyio
    async def test_resume_conversation_keeps_image_paths_in_backend_history(
        self, db_manager, monkeypatch, tmp_path
    ):
        cid = db_manager.start_new_conversation("Image chat")
        image_path = tmp_path / "image.png"
        image_path.write_bytes(b"fake-image")
        db_manager.add_message(cid, "user", "See this", images=[str(image_path)])

        tab_state = TabState(tab_id="default")
        broadcast_mock = AsyncMock()
        monkeypatch.setattr("source.services.chat.conversations.db", db_manager)
        monkeypatch.setattr(
            "source.services.chat.conversations.broadcast_message", broadcast_mock
        )
        monkeypatch.setattr(
            "source.services.chat.conversations._get_thumbnail_creator",
            lambda: (lambda path: "thumb-data"),
        )
        monkeypatch.setattr(
            "source.services.chat.conversations.run_in_thread",
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

    @pytest.mark.anyio
    async def test_resume_conversation_preserves_artifact_only_assistant_history(
        self, db_manager, monkeypatch
    ):
        cid = db_manager.start_new_conversation("Artifact resume")
        user_message = db_manager.add_message(cid, "user", "Build a file")
        assistant_message = db_manager.add_message(
            cid,
            "assistant",
            "",
            model="model-a",
            content_blocks=[
                {
                    "type": "artifact",
                    "artifact_id": "artifact-1",
                    "artifact_type": "code",
                    "title": "demo.py",
                    "language": "python",
                }
            ],
            turn_id=user_message["turn_id"],
        )
        db_manager.create_artifact(
            artifact_id="artifact-1",
            conversation_id=cid,
            message_id=assistant_message["message_id"],
            artifact_type="code",
            title="demo.py",
            language="python",
            storage_kind="inline",
            storage_path=None,
            inline_content='print("hi")',
            searchable_text='print("hi")',
            size_bytes=11,
            line_count=1,
        )

        tab_state = TabState(tab_id="default")
        monkeypatch.setattr("source.services.chat.conversations.db", db_manager)
        monkeypatch.setattr(
            "source.services.chat.conversations.broadcast_message", AsyncMock()
        )

        await ConversationService.resume_conversation(cid, tab_state=tab_state)

        assert tab_state.chat_history == [
            {"role": "user", "content": "Build a file"},
            {
                "role": "assistant",
                "content": '<artifact type="code" title="demo.py" language="python">print("hi")</artifact>',
                "model": "model-a",
            },
        ]

    @pytest.mark.anyio
    async def test_retry_message_keeps_artifact_only_assistant_history(
        self, db_manager, monkeypatch, tmp_path
    ):
        cid = db_manager.start_new_conversation("Artifact retry")
        first_user, first_assistant = self._seed_turn(
            db_manager,
            cid,
            user_content="Build a file",
            assistant_content="Initial answer",
        )

        tab_state = TabState(tab_id="default")
        tab_state.conversation_id = cid
        tab_state.chat_history = db_manager.get_active_chat_history(cid)

        artifact_reply = {
            "type": "artifact",
            "artifact_id": "artifact-2",
            "artifact_type": "code",
            "title": "demo.py",
            "language": "python",
            "size_bytes": 11,
            "line_count": 1,
            "status": "ready",
            "content": 'print("hi")',
        }

        monkeypatch.setattr("source.services.chat.conversations.db", db_manager)
        monkeypatch.setattr("source.services.artifacts.db", db_manager)
        monkeypatch.setattr("source.services.artifacts.ARTIFACTS_DIR", tmp_path / "artifacts")
        monkeypatch.setattr(
            "source.services.chat.conversations.route_chat",
            AsyncMock(
                return_value=(
                    "",
                    {"prompt_eval_count": 3, "eval_count": 5},
                    [],
                    [artifact_reply],
                )
            ),
        )
        monkeypatch.setattr(
            "source.services.chat.conversations.broadcast_message", AsyncMock()
        )
        async def fake_run_in_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        monkeypatch.setattr(
            "source.services.chat.conversations.run_in_thread",
            fake_run_in_thread,
        )

        await ConversationService.submit_query(
            user_query="Build a file",
            llm_query="Build a file",
            tab_state=tab_state,
            model="model-b",
            action="retry",
            target_message_id=first_assistant["message_id"],
        )

        assert tab_state.chat_history[-1] == {
            "role": "assistant",
            "content": '<artifact type="code" title="demo.py" language="python">print("hi")</artifact>',
            "model": "model-b",
        }
        assert tab_state.chat_history[0]["content"] == "Build a file"

    @pytest.mark.anyio
    async def test_submit_query_injects_and_truncates_attached_text(
        self, db_manager, monkeypatch, tmp_path
    ):
        cid = db_manager.start_new_conversation("Attach")
        tab_state = TabState(tab_id="default")
        tab_state.conversation_id = cid
        tab_state.chat_history = []

        text_path = tmp_path / "long.txt"
        text_path.write_text("a" * 12000, encoding="utf-8")

        route_mock = AsyncMock(
            return_value=(
                "ok",
                {"prompt_eval_count": 1, "eval_count": 1},
                [],
                [{"type": "text", "content": "ok"}],
            )
        )
        monkeypatch.setattr("source.services.chat.conversations.db", db_manager)
        monkeypatch.setattr("source.services.chat.conversations.route_chat", route_mock)
        monkeypatch.setattr(
            "source.services.chat.conversations.broadcast_message", AsyncMock()
        )

        await ConversationService.submit_query(
            user_query="Summarize",
            llm_query="Summarize",
            tab_state=tab_state,
            model="model-a",
            attached_files=[{"name": "long.txt", "path": str(text_path)}],
        )

        await_args = route_mock.await_args
        assert await_args is not None
        llm_query_sent = await_args.args[1]
        assert "--- Attached via read_file: long.txt" in llm_query_sent
        assert '"content"' in llm_query_sent
        assert '"has_more": true' in llm_query_sent
        assert "Summarize" in llm_query_sent
        assert await_args.kwargs["tool_retrieval_query"] == "Summarize"

    @pytest.mark.anyio
    async def test_submit_query_routes_image_attachment_to_image_paths(
        self, db_manager, monkeypatch, tmp_path
    ):
        cid = db_manager.start_new_conversation("Attach image")
        tab_state = TabState(tab_id="default")
        tab_state.conversation_id = cid
        tab_state.chat_history = []

        image_path = tmp_path / "photo.png"
        from PIL import Image

        Image.new("RGB", (20, 20), color="red").save(image_path)

        route_mock = AsyncMock(
            return_value=(
                "ok",
                {"prompt_eval_count": 1, "eval_count": 1},
                [],
                [{"type": "text", "content": "ok"}],
            )
        )
        monkeypatch.setattr("source.services.chat.conversations.db", db_manager)
        monkeypatch.setattr("source.services.chat.conversations.route_chat", route_mock)
        monkeypatch.setattr(
            "source.services.chat.conversations.broadcast_message", AsyncMock()
        )

        await ConversationService.submit_query(
            user_query="Describe",
            llm_query="Describe",
            tab_state=tab_state,
            model="model-a",
            attached_files=[{"name": "photo.png", "path": str(image_path)}],
        )

        await_args = route_mock.await_args
        assert await_args is not None
        llm_query_sent = await_args.args[1]
        image_paths_sent = await_args.args[2]
        assert "[This image was auto-attached as multimodal context" in llm_query_sent
        assert str(image_path) in image_paths_sent
        assert await_args.kwargs["tool_retrieval_query"] == "Describe"

    @pytest.mark.anyio
    async def test_submit_query_includes_read_file_payload_for_document_attachment(
        self, db_manager, monkeypatch, tmp_path
    ):
        cid = db_manager.start_new_conversation("Attach deck")
        tab_state = TabState(tab_id="default")
        tab_state.conversation_id = cid
        tab_state.chat_history = []

        deck_path = tmp_path / "deck.pptx"
        deck_path.write_text("fake", encoding="utf-8")

        extracted_image_path = tmp_path / "slideshot.png"
        extracted_image_path.write_bytes(b"png")

        read_file_payload = {
            "content": f"Slide 1 agenda\n[IMAGE: {extracted_image_path} (1280x720) - call read_file to view]",
            "total_chars": 96,
            "offset": 0,
            "chars_returned": 96,
            "has_more": False,
            "next_offset": None,
            "chunk_summary": "Showing characters 0-96 of 96 (100%)",
            "file_info": {
                "format": "pptx",
                "file_size_bytes": 1234,
                "page_count": 1,
                "title": None,
                "author": None,
                "extracted_images": [
                    {
                        "path": str(extracted_image_path),
                        "page": 1,
                        "index": 1,
                        "description": "",
                        "width": 1280,
                        "height": 720,
                    }
                ],
                "warnings": [],
            },
        }

        route_mock = AsyncMock(
            return_value=(
                "ok",
                {"prompt_eval_count": 1, "eval_count": 1},
                [],
                [{"type": "text", "content": "ok"}],
            )
        )

        monkeypatch.setattr("source.services.chat.conversations.db", db_manager)
        monkeypatch.setattr("source.services.chat.conversations.route_chat", route_mock)
        monkeypatch.setattr(
            "source.services.chat.conversations.broadcast_message", AsyncMock()
        )
        monkeypatch.setattr(
            "source.services.chat.conversations._run_read_file_for_attachment",
            AsyncMock(return_value=read_file_payload),
        )

        await ConversationService.submit_query(
            user_query="What is on slide 1 image?",
            llm_query="What is on slide 1 image?",
            tab_state=tab_state,
            model="model-a",
            attached_files=[{"name": "deck.pptx", "path": str(deck_path)}],
        )

        await_args = route_mock.await_args
        assert await_args is not None
        llm_query_sent = await_args.args[1]
        assert "--- Attached via read_file: deck.pptx" in llm_query_sent
        assert '"extracted_images"' in llm_query_sent
        assert str(extracted_image_path).replace("\\", "\\\\") in llm_query_sent
        assert await_args.kwargs["tool_retrieval_query"] == "What is on slide 1 image?"

    @pytest.mark.anyio
    async def test_submit_query_persists_artifact_only_assistant_response(
        self, db_manager, monkeypatch, tmp_path
    ):
        from source.services.artifacts import artifact_service

        cid = db_manager.start_new_conversation("Artifact only")
        tab_state = TabState(tab_id="default")
        tab_state.conversation_id = cid
        tab_state.chat_history = []

        async def fake_run_in_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        monkeypatch.setattr("source.services.chat.conversations.db", db_manager)
        monkeypatch.setattr("source.services.artifacts.db", db_manager)
        monkeypatch.setattr("source.services.artifacts.ARTIFACTS_DIR", tmp_path / "artifacts")
        monkeypatch.setattr(
            "source.services.chat.conversations.route_chat",
            AsyncMock(
                return_value=(
                    "",
                    {"prompt_eval_count": 2, "eval_count": 4},
                    [],
                    [
                        {
                            "type": "artifact",
                            "artifact_id": "artifact-1",
                            "artifact_type": "code",
                            "title": "demo.py",
                            "language": "python",
                            "content": 'print("hi")',
                        }
                    ],
                )
            ),
        )
        monkeypatch.setattr(
            "source.services.chat.conversations.run_in_thread",
            fake_run_in_thread,
        )
        monkeypatch.setattr(
            "source.services.chat.conversations.broadcast_message", AsyncMock()
        )

        conversation_id = await ConversationService.submit_query(
            user_query="Build it",
            llm_query="Build it",
            tab_state=tab_state,
            model="model-a",
        )

        assert conversation_id == cid
        messages = db_manager.get_full_conversation(cid)
        assert [message["content"] for message in messages] == ["Build it", ""]
        assistant = messages[1]
        assert assistant["content_blocks"] == [
            {
                "type": "artifact",
                "artifact_id": "artifact-1",
                "artifact_type": "code",
                "title": "demo.py",
                "language": "python",
                "size_bytes": 11,
                "line_count": 1,
                "status": "ready",
            }
        ]
        assert assistant["response_variants"][0]["content"] == ""

        artifact = artifact_service.get_artifact("artifact-1")
        assert artifact is not None
        assert artifact["content"] == 'print("hi")'
        assert artifact["message_id"] == assistant["message_id"]

    @pytest.mark.anyio
    async def test_edit_message_replaces_existing_artifacts_and_broadcasts_deletion(
        self, db_manager, monkeypatch, tmp_path
    ):
        cid = db_manager.start_new_conversation("Original prompt")
        user_message = db_manager.add_message(cid, "user", "Original prompt")

        old_blocks = [
            {
                "type": "artifact",
                "artifact_id": "artifact-old",
                "artifact_type": "markdown",
                "title": "Old spec",
                "language": None,
                "size_bytes": 5,
                "line_count": 1,
                "status": "ready",
            }
        ]
        assistant_message = db_manager.add_message(
            cid,
            "assistant",
            "",
            model="model-a",
            content_blocks=old_blocks,
            turn_id=user_message["turn_id"],
        )
        db_manager.create_artifact(
            artifact_id="artifact-old",
            conversation_id=cid,
            message_id=assistant_message["message_id"],
            artifact_type="markdown",
            title="Old spec",
            language=None,
            storage_kind="inline",
            storage_path=None,
            inline_content="# old",
            searchable_text="# old",
            size_bytes=5,
            line_count=1,
        )
        db_manager.save_response_version(
            cid,
            assistant_message["message_id"],
            "",
            model="model-a",
            content_blocks=old_blocks,
            replace_history=True,
        )

        tab_state = TabState(tab_id="default")
        tab_state.conversation_id = cid
        tab_state.chat_history = db_manager.get_active_chat_history(cid)

        async def fake_run_in_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        broadcast_mock = AsyncMock()
        monkeypatch.setattr("source.services.chat.conversations.db", db_manager)
        monkeypatch.setattr("source.services.artifacts.db", db_manager)
        monkeypatch.setattr("source.services.artifacts.ARTIFACTS_DIR", tmp_path / "artifacts")
        monkeypatch.setattr(
            "source.services.chat.conversations.route_chat",
            AsyncMock(
                return_value=(
                    "",
                    {"prompt_eval_count": 2, "eval_count": 4},
                    [],
                    [
                        {
                            "type": "artifact",
                            "artifact_id": "artifact-new",
                            "artifact_type": "markdown",
                            "title": "New spec",
                            "language": None,
                            "content": "# new",
                        }
                    ],
                )
            ),
        )
        monkeypatch.setattr(
            "source.services.chat.conversations.run_in_thread",
            fake_run_in_thread,
        )
        monkeypatch.setattr(
            "source.services.chat.conversations.broadcast_message", broadcast_mock
        )

        conversation_id = await ConversationService.submit_query(
            user_query="Edited prompt",
            llm_query="Edited prompt",
            tab_state=tab_state,
            model="model-b",
            action="edit",
            target_message_id=user_message["message_id"],
        )

        assert conversation_id == cid
        deleted_old_artifact = db_manager.get_artifact("artifact-old")
        assert deleted_old_artifact is not None
        assert deleted_old_artifact["status"] == "deleted"
        assert deleted_old_artifact["storage_path"] is None
        assert db_manager.get_artifact("artifact-new") is not None

        messages = db_manager.get_full_conversation(cid)
        assert [message["content"] for message in messages] == ["Edited prompt", ""]
        assert messages[1]["content_blocks"][0]["artifact_id"] == "artifact-new"
        broadcast_mock.assert_any_call(
            "artifact_deleted",
            {
                "artifact_id": "artifact-old",
                "conversation_id": cid,
                "message_id": assistant_message["message_id"],
            },
        )
