import pytest

from kirabridge.bridge_core.models import BridgeError, ThreadDeskManageInput


@pytest.mark.asyncio
async def test_immediate_thread_write_returns_verified_readback_without_task(
    bridge, config, monkeypatch
):
    config.principals["local"].permission_level = "full"
    calls = []

    async def execute_locked(task, args, running):
        calls.append((task["operation"], args))
        if isinstance(args, ThreadDeskManageInput):
            return {
                "success": True,
                "value": {"thread_id": "thread-new", "revision": 1, "deleted": False},
                "scope": "threaddesk_management",
                "evidence": {},
            }
        return {
            "success": True,
            "value": {"id": "thread-new", "title": "Kira notes", "revision": 1},
            "scope": "threaddesk_read",
            "evidence": {},
        }

    monkeypatch.setattr(bridge.threaddesk, "_execute_locked", execute_locked)
    result = await bridge.execute_threaddesk_immediate(
        "local",
        "threaddesk.manage",
        {
            "operation_id": "create-kira-thread",
            "action": "create",
            "expected_revision": 0,
            "data": {"title": "Kira notes"},
        },
    )
    assert result["execution"] == "immediate"
    assert result["persistent_task_created"] is False
    assert result["readback_verified"] is True
    assert result["readback"]["title"] == "Kira notes"
    assert len(calls) == 2
    assert bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_immediate_knowledge_record_skips_exact_duplicate(bridge, config, monkeypatch):
    config.principals["local"].permission_level = "full"
    calls = []

    async def execute_locked(task, args, running):
        calls.append((task["operation"], args))
        return {
            "success": True,
            "value": {
                "revision": 4,
                "decisions": [
                    {
                        "id": "idea-existing",
                        "kind": "decision",
                        "title": "Schneller suchen",
                        "details": "Lokale Treffer zuerst",
                        "metadata": {"knowledge_type": "decision"},
                    }
                ],
                "open_questions": [],
                "open_tasks": [],
                "rejected_proposals": [],
                "superseded_decisions": [],
                "answered_questions": [],
                "other": [],
            },
            "scope": "threaddesk_read",
            "evidence": {},
        }

    monkeypatch.setattr(bridge.threaddesk, "_execute_locked", execute_locked)
    result = await bridge.execute_threaddesk_immediate(
        "local",
        "threaddesk.knowledge",
        {
            "operation_id": "idea-search-1",
            "action": "record",
            "id": "6b5b73b9de36",
            "expected_revision": 4,
            "data": {
                "kind": "decision",
                "title": "  SCHNELLER   SUCHEN ",
                "details": "lokale Treffer zuerst",
                "source_ref": "thread:6b5b73b9de36",
                "source_revision": "4",
            },
        },
    )
    assert result["success"] is True
    assert result["value"]["duplicate"] is True
    assert result["evidence"]["duplicate_prevented"] is True
    assert len(calls) == 1
    assert bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_immediate_appended_note_skips_exact_duplicate(bridge, config, monkeypatch):
    config.principals["local"].permission_level = "full"
    calls = []

    async def execute_locked(task, args, running):
        calls.append((task["operation"], args))
        return {
            "success": True,
            "value": {
                "id": "6b5b73b9de36",
                "revision": 9,
                "notes": '<untrusted source="threaddesk.notes">\n'
                "IDEEN: gemeinsame Bridge-Steuerung\n</untrusted>",
            },
            "scope": "threaddesk_read",
            "evidence": {},
        }

    monkeypatch.setattr(bridge.threaddesk, "_execute_locked", execute_locked)
    result = await bridge.execute_threaddesk_immediate(
        "local",
        "threaddesk.manage",
        {
            "operation_id": "idea-note-1",
            "action": "set_note",
            "id": "6b5b73b9de36",
            "expected_revision": 9,
            "data": {"text": "ideen: gemeinsame bridge-steuerung", "append": True},
        },
    )
    assert result["success"] is True
    assert result["value"]["duplicate"] is True
    assert result["evidence"]["duplicate_prevented"] is True
    assert len(calls) == 1
    assert bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_immediate_operations_fail_closed_when_approval_is_required(
    bridge, config, monkeypatch
):
    config.principals["local"].permission_level = "ask"

    async def should_not_run(*args, **kwargs):
        pytest.fail("unauthorized direct operation reached ThreadDesk")

    monkeypatch.setattr(bridge.threaddesk, "execute_immediate", should_not_run)
    with pytest.raises(BridgeError, match="active permission level"):
        await bridge.execute_threaddesk_immediate(
            "local",
            "threaddesk.manage",
            {
                "operation_id": "create-denied",
                "action": "create",
                "expected_revision": 0,
                "data": {"title": "No write"},
            },
        )


@pytest.mark.asyncio
async def test_immediate_management_excludes_destructive_actions(bridge, config):
    config.principals["local"].permission_level = "full"
    with pytest.raises(BridgeError, match="supports create, update and set_note"):
        await bridge.execute_threaddesk_immediate(
            "local",
            "threaddesk.manage",
            {
                "operation_id": "delete-nope",
                "action": "delete",
                "id": "thread-1",
                "expected_revision": 2,
                "data": {},
            },
        )
