"""Tests for source/services/artifacts.py."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

import source.services.artifacts as artifacts_module


def test_slugify_and_file_extension_helpers():
    assert artifacts_module._slugify("  Hello, World!  ") == "hello-world"
    assert artifacts_module._slugify("   ") == "artifact"
    assert artifacts_module._file_extension("markdown", None) == ".md"
    assert artifacts_module._file_extension("html", "python") == ".html"
    assert artifacts_module._file_extension("code", "python") == ".py"
    assert artifacts_module._file_extension("code", "unknown") == ".txt"


def test_compute_stats_and_remove_file(tmp_path):
    sample = "line one\nline two"
    assert artifacts_module._compute_stats(sample) == (
        len(sample.encode("utf-8")),
        2,
    )

    target = tmp_path / "temp.txt"
    target.write_text("x", encoding="utf-8")
    artifacts_module._remove_file(str(target))
    artifacts_module._remove_file(str(target))
    assert not target.exists()


def test_persist_generated_artifacts_writes_file_and_inline_blocks(tmp_path, monkeypatch):
    recorded = []
    monkeypatch.setattr(artifacts_module, "ARTIFACTS_DIR", tmp_path / "artifacts")
    monkeypatch.setattr(
        artifacts_module,
        "db",
        MagicMock(create_artifact=lambda **kwargs: recorded.append(kwargs)),
    )

    persisted = artifacts_module.ArtifactService.persist_generated_artifacts(
        [
            {"type": "text", "content": "plain"},
            {
                "type": "artifact",
                "artifact_id": "art-code",
                "artifact_type": "code",
                "title": "Demo Script",
                "language": "python",
                "content": 'print("hi")\n',
            },
            {
                "type": "artifact",
                "artifact_id": "art-html",
                "artifact_type": "html",
                "title": "Demo Page",
                "language": "html",
                "content": "<div>ok</div>",
            },
            {
                "type": "artifact",
                "artifact_id": "",
                "artifact_type": "code",
                "title": "Invalid",
                "content": "skip",
            },
        ],
        conversation_id="conv-1",
        message_id="msg-1",
    )

    assert persisted == [
        {"type": "text", "content": "plain"},
        {
            "type": "artifact",
            "artifact_id": "art-code",
            "artifact_type": "code",
            "title": "Demo Script",
            "language": "python",
            "size_bytes": len('print("hi")\n'.encode("utf-8")),
            "line_count": 2,
            "status": "ready",
        },
        {
            "type": "artifact",
            "artifact_id": "art-html",
            "artifact_type": "html",
            "title": "Demo Page",
            "language": "html",
            "size_bytes": len("<div>ok</div>".encode("utf-8")),
            "line_count": 1,
            "status": "ready",
        },
        {
            "type": "artifact",
            "artifact_id": "",
            "artifact_type": "code",
            "title": "Invalid",
            "content": "skip",
        },
    ]

    assert len(recorded) == 2
    code_row = next(row for row in recorded if row["artifact_id"] == "art-code")
    html_row = next(row for row in recorded if row["artifact_id"] == "art-html")

    assert code_row["storage_kind"] == "file"
    assert code_row["storage_path"] is not None
    assert Path(code_row["storage_path"]).read_text(encoding="utf-8") == 'print("hi")\n'
    assert html_row["storage_kind"] == "inline"
    assert html_row["storage_path"] is None
    assert html_row["inline_content"] == "<div>ok</div>"


def test_link_and_list_artifacts_delegate_to_db(monkeypatch):
    db = MagicMock()
    db.list_artifacts.return_value = ([{"id": "a1"}], 1)
    monkeypatch.setattr(artifacts_module, "db", db)

    artifacts_module.ArtifactService.link_artifacts_to_message(
        ["a1", "", "a2"],
        message_id="msg-1",
    )
    listing = artifacts_module.ArtifactService.list_artifacts(
        query="demo",
        artifact_type="code",
        status="ready",
        page=2,
        page_size=10,
        conversation_id="conv-1",
    )

    db.link_artifacts_to_message.assert_called_once_with(["a1", "a2"], "msg-1")
    db.list_artifacts.assert_called_once_with(
        query="demo",
        artifact_type="code",
        status="ready",
        page=2,
        page_size=10,
        conversation_id="conv-1",
    )
    assert listing == {
        "artifacts": [{"id": "a1"}],
        "total": 1,
        "page": 2,
        "page_size": 10,
    }


def test_get_artifact_reads_file_storage_and_inline_storage(tmp_path, monkeypatch):
    storage_path = tmp_path / "artifact.py"
    storage_path.write_text("print('hi')", encoding="utf-8")

    db = MagicMock()
    db.get_artifact.side_effect = [
        {
            "id": "file-1",
            "artifact_type": "code",
            "title": "Demo",
            "language": "python",
            "storage_kind": "file",
            "storage_path": str(storage_path),
            "inline_content": None,
            "size_bytes": 11,
            "line_count": 1,
            "status": "ready",
            "conversation_id": "conv-1",
            "message_id": "msg-1",
            "created_at": "created",
            "updated_at": "updated",
        },
        {
            "id": "inline-1",
            "artifact_type": "html",
            "title": "Demo HTML",
            "language": None,
            "storage_kind": "inline",
            "storage_path": None,
            "inline_content": "<div>ok</div>",
            "size_bytes": 13,
            "line_count": 1,
            "status": "ready",
            "conversation_id": None,
            "message_id": None,
            "created_at": "created",
            "updated_at": "updated",
        },
        None,
    ]
    monkeypatch.setattr(artifacts_module, "db", db)

    file_artifact = artifacts_module.ArtifactService.get_artifact("file-1")
    inline_artifact = artifacts_module.ArtifactService.get_artifact("inline-1")

    assert file_artifact["content"] == "print('hi')"
    assert file_artifact["type"] == "code"
    assert inline_artifact["content"] == "<div>ok</div>"
    assert artifacts_module.ArtifactService.get_artifact("missing") is None


def test_create_artifact_raises_if_persisted_detail_missing(monkeypatch):
    db = MagicMock(generate_artifact_id=lambda: "generated-1")
    monkeypatch.setattr(artifacts_module, "db", db)
    monkeypatch.setattr(
        artifacts_module.ArtifactService,
        "persist_generated_artifacts",
        staticmethod(lambda *args, **kwargs: None),
    )
    monkeypatch.setattr(
        artifacts_module.ArtifactService,
        "get_artifact",
        staticmethod(lambda artifact_id: None),
    )

    with pytest.raises(ValueError, match="Artifact creation failed"):
        artifacts_module.ArtifactService.create_artifact(
            artifact_type="code",
            title="Demo",
            content="print('hi')",
        )


def test_create_artifact_returns_persisted_detail(monkeypatch):
    db = MagicMock(generate_artifact_id=lambda: "generated-2")
    persist_spy = MagicMock()
    monkeypatch.setattr(artifacts_module, "db", db)
    monkeypatch.setattr(
        artifacts_module.ArtifactService,
        "persist_generated_artifacts",
        staticmethod(persist_spy),
    )
    monkeypatch.setattr(
        artifacts_module.ArtifactService,
        "get_artifact",
        staticmethod(lambda artifact_id: {"id": artifact_id, "content": "ok"}),
    )

    result = artifacts_module.ArtifactService.create_artifact(
        artifact_type="code",
        title="Demo",
        content="print('hi')",
        language="python",
        conversation_id="conv-1",
        message_id="msg-1",
    )

    assert result == {"id": "generated-2", "content": "ok"}
    persist_spy.assert_called_once()


def test_update_artifact_updates_file_storage_and_removes_old_path(tmp_path, monkeypatch):
    old_path = tmp_path / "artifacts" / "code" / "artifact-1-old.py"
    old_path.parent.mkdir(parents=True, exist_ok=True)
    old_path.write_text("print('old')", encoding="utf-8")

    db = MagicMock()
    db.get_artifact.return_value = {
        "id": "artifact-1",
        "artifact_type": "code",
        "title": "Old Title",
        "language": "python",
        "storage_kind": "file",
        "storage_path": str(old_path),
        "inline_content": None,
    }
    updated_record = {
        "id": "artifact-1",
        "artifact_type": "code",
        "title": "New Title",
        "language": "python",
        "storage_kind": "file",
        "storage_path": str(tmp_path / "artifacts" / "code" / "artifact-1-new-title.ts"),
        "inline_content": None,
        "size_bytes": len("print('new')".encode("utf-8")),
        "line_count": 1,
        "status": "ready",
        "conversation_id": "conv-1",
        "message_id": "msg-1",
        "created_at": "created",
        "updated_at": "updated",
    }
    db.get_artifact.side_effect = [db.get_artifact.return_value, updated_record]

    monkeypatch.setattr(artifacts_module, "db", db)
    monkeypatch.setattr(artifacts_module, "ARTIFACTS_DIR", tmp_path / "artifacts")

    detail = artifacts_module.ArtifactService.update_artifact(
        "artifact-1",
        title="New Title",
        content="print('new')",
        language="typescript",
    )

    assert detail["title"] == "New Title"
    db.update_artifact.assert_called_once()
    update_kwargs = db.update_artifact.call_args.kwargs
    assert update_kwargs["language"] == "typescript"
    assert update_kwargs["storage_path"].endswith("artifact-1-new-title.ts")
    assert Path(update_kwargs["storage_path"]).read_text(encoding="utf-8") == "print('new')"
    assert not old_path.exists()


def test_update_artifact_cleans_up_new_file_when_db_update_fails(tmp_path, monkeypatch):
    old_path = tmp_path / "artifacts" / "code" / "artifact-2-old.py"
    old_path.parent.mkdir(parents=True, exist_ok=True)
    old_path.write_text("print('old')", encoding="utf-8")

    db = MagicMock()
    db.get_artifact.return_value = {
        "id": "artifact-2",
        "artifact_type": "code",
        "title": "Old Title",
        "language": "python",
        "storage_kind": "file",
        "storage_path": str(old_path),
        "inline_content": None,
    }
    db.update_artifact.side_effect = RuntimeError("db down")

    monkeypatch.setattr(artifacts_module, "db", db)
    monkeypatch.setattr(artifacts_module, "ARTIFACTS_DIR", tmp_path / "artifacts")

    with pytest.raises(RuntimeError, match="db down"):
        artifacts_module.ArtifactService.update_artifact(
            "artifact-2",
            title="New Title",
            content="print('new')",
            language="python",
        )

    assert old_path.exists()
    new_files = list((tmp_path / "artifacts" / "code").glob("artifact-2-new-title.py"))
    assert new_files == []


def test_update_artifact_handles_inline_storage(monkeypatch):
    existing = {
        "id": "artifact-inline",
        "artifact_type": "html",
        "title": "Old Title",
        "language": None,
        "storage_kind": "inline",
        "storage_path": None,
        "inline_content": "<div>old</div>",
    }
    db = MagicMock()
    db.get_artifact.side_effect = [
        existing,
        {
            **existing,
            "title": "Inline Title",
            "inline_content": "<div>new</div>",
            "size_bytes": len("<div>new</div>".encode("utf-8")),
            "line_count": 1,
            "status": "ready",
            "conversation_id": None,
            "message_id": None,
            "created_at": "created",
            "updated_at": "updated",
        },
    ]
    monkeypatch.setattr(artifacts_module, "db", db)

    detail = artifacts_module.ArtifactService.update_artifact(
        "artifact-inline",
        title="Inline Title",
        content="<div>new</div>",
        language="python",
    )

    assert detail["title"] == "Inline Title"
    update_kwargs = db.update_artifact.call_args.kwargs
    assert update_kwargs["language"] is None
    assert update_kwargs["inline_content"] == "<div>new</div>"
    assert update_kwargs["storage_path"] is None


def test_delete_artifact_and_bulk_delete_remove_files(tmp_path, monkeypatch):
    delete_path = tmp_path / "delete.py"
    delete_path.write_text("x", encoding="utf-8")
    message_path = tmp_path / "message.py"
    message_path.write_text("y", encoding="utf-8")
    conversation_path = tmp_path / "conversation.py"
    conversation_path.write_text("z", encoding="utf-8")

    db = MagicMock()
    db.delete_artifact.return_value = {"id": "a1", "storage_path": str(delete_path)}
    db.delete_artifacts_for_message.return_value = [
        {"id": "m1", "storage_path": str(message_path)},
    ]
    db.delete_artifacts_for_conversation.return_value = [
        {"id": "c1", "storage_path": str(conversation_path)},
    ]
    monkeypatch.setattr(artifacts_module, "db", db)

    deleted = artifacts_module.ArtifactService.delete_artifact("a1")
    deleted_for_message = artifacts_module.ArtifactService.delete_artifacts_for_message("msg-1")
    deleted_for_conversation = artifacts_module.ArtifactService.delete_artifacts_for_conversation("conv-1")

    assert deleted == {"id": "a1", "storage_path": str(delete_path)}
    assert deleted_for_message == [{"id": "m1", "storage_path": str(message_path)}]
    assert deleted_for_conversation == [{"id": "c1", "storage_path": str(conversation_path)}]
    assert not delete_path.exists()
    assert not message_path.exists()
    assert not conversation_path.exists()
