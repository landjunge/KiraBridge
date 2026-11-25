"""Receipt recovery and response projection use isolated synthetic peers only."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mcp.types import CallToolResult
from test_threaddesk_dynamic_lifecycle import (
    configured,
    declared,
    fake_peer,
    manage_contract,
    result,
)

from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.models import BridgeError
from kirabridge.threaddesk_dynamic import call


def arguments():
    return {
        "operation_id": "note-1",
        "action": "set_note",
        "id": "t1",
        "expected_revision": 3,
        "data": {"text": "new note", "append": True},
    }


def receipt(**changes):
    return {
        "operation_id": "note-1",
        "action": "set_note",
        "thread_id": "t1",
        "revision": 4,
        "deleted": False,
        "duplicate": False,
        "thread": {"id": "t1", "revision": 4, "context": {"notes": "history"}},
        **changes,
    }


@pytest.mark.parametrize("failure", ["decode", "peer_response"])
async def test_failed_response_observes_receipt_but_stays_unknown_without_replay(config, failure):
    configured(config)
    writes, reads = [], []

    async def peer(_, name, values, **kwargs):
        if name == "thread_operation_status":
            reads.append(values)
            return result(
                {
                    "operation_id": "note-1",
                    "found": True,
                    "result": receipt(),
                }
            )
        writes.append(values)
        if failure == "decode":
            return CallToolResult(content=[])
        return CallToolResult(
            content=[],
            isError=True,
            structuredContent={
                "code": "tool_error",
                "message": "secret must never be copied",
            },
        )

    async with Bridge(config) as bridge:
        fake_peer(bridge, manage_contract(), peer)
        outcome = await call(bridge, "local", "thread_manage", arguments(), "recover")
    assert not outcome["success"] and outcome["task"]["state"] == "unknown"
    assert outcome["evidence"]["provider_error"]["operation_receipt_found"]
    assert outcome["evidence"]["provider_error"]["request_hash_verified"] is False
    assert writes == [arguments()] and reads == [{"operation_id": "note-1"}]


async def test_unknown_exposes_sanitized_error_evidence_and_original_attempt(config):
    configured(config)

    async def peer(*args, **kwargs):
        return CallToolResult(
            content=[],
            isError=True,
            structuredContent={
                "code": "revision_conflict",
                "message": "SECRET remote message",
                "details": {
                    "actual_revision": 17,
                    "expected_revision": 3,
                    "password": "SECRET",
                    "field": "SECRET",
                },
            },
        )

    async with Bridge(config) as bridge:
        pool = fake_peer(bridge, [declared("new_writer")], peer)
        outcome = await call(bridge, "local", "new_writer", {"id": "one"}, "unknown")
        assert outcome["task"]["state"] == "unknown" and not outcome["success"]
        assert outcome["error"]["code"] == "threaddesk_dynamic_unknown"
        assert outcome["recovery"]["operation_id"] == "unknown"
        assert outcome["evidence"]["provider_error"] == {
            "stage": "peer_response",
            "code": "revision_conflict",
            "details": {"actual_revision": 17, "expected_revision": 3},
        }
        assert "SECRET" not in json.dumps(outcome)
        with pytest.raises(BridgeError) as conflict:
            await call(bridge, "local", "new_writer", {"id": "changed"}, "unknown")
        assert conflict.value.code == "idempotency_conflict"
        assert conflict.value.diagnostic["task_id"] == outcome["task"]["id"]
        assert conflict.value.diagnostic["automatic_retry"] is False
        assert pool.call.await_count == 1


@pytest.mark.parametrize(
    "bad", ["conflict", "wrong_operation", "wrong_thread", "bad_revision", "not_readonly"]
)
async def test_unbound_receipt_never_resolves_unknown(config, bad):
    configured(config)
    tools = manage_contract()
    if bad == "not_readonly":
        tools[1].annotations.readOnlyHint = False
    reads = []

    async def peer(_, name, values, **kwargs):
        if name == "thread_operation_status":
            reads.append(values)
            saved = receipt()
            if bad == "wrong_thread":
                saved["thread_id"] = "another"
            if bad == "bad_revision":
                saved["revision"] = True
            return result(
                {
                    "operation_id": "another" if bad == "wrong_operation" else "note-1",
                    "found": True,
                    "result": saved,
                }
            )
        if bad == "conflict":
            return CallToolResult(
                content=[], isError=True, structuredContent={"code": "operation_conflict"}
            )
        raise BridgeError("peer_unknown", "lost reply")

    async with Bridge(config) as bridge:
        fake_peer(bridge, tools, peer)
        outcome = await call(bridge, "local", "thread_manage", arguments(), "bad")
    assert outcome["task"]["state"] == "unknown" and not outcome["success"]
    assert len(reads) == (0 if bad in {"conflict", "not_readonly"} else 1)


def wrapper(name, readonly=False):
    return SimpleNamespace(
        name=name,
        description="Synthetic command envelope",
        annotations=SimpleNamespace(
            readOnlyHint=readonly, destructiveHint=False, openWorldHint=False
        ),
        inputSchema={
            "type": "object",
            "additionalProperties": False,
            "required": ["workspace_id", "arguments"],
            "properties": {
                "workspace_id": {"type": "string"},
                "arguments": {"type": "object"},
                "operation_id": {"type": "string"},
                "expected_revision": {"type": "integer"},
            },
        },
    )


def envelope(command, value, workspace="ws1", **fields):
    return {
        "schema": "threaddesk.command-result.v1",
        "workspace_id": workspace,
        "command": command,
        "result": value,
        "next_offset": None,
        **fields,
    }


@pytest.mark.parametrize(
    "variant", ["valid", "workspace", "pending", "paged", "operation", "state"]
)
async def test_modern_status_observation_requires_current_workspace_and_operation(config, variant):
    configured(config)
    domain = arguments()
    op = domain.pop("operation_id")
    revision = domain.pop("expected_revision")
    values = {
        "workspace_id": "ws1",
        "arguments": domain,
        "operation_id": op,
        "expected_revision": revision,
    }
    seen = []

    async def peer(_, name, payload, **kwargs):
        seen.append((name, payload))
        if name == "td_command__operation":
            status = {
                "operation_id": "different" if variant == "operation" else op,
                "found": True,
                "state": "unrecognized"
                if variant == "state"
                else ("pending" if variant == "pending" else "complete"),
                "result": receipt(),
            }
            response = envelope(
                "command.operation", status, workspace="other" if variant == "workspace" else "ws1"
            )
            if variant == "paged":
                response.pop("result")
                response.update(result_page="{}", next_offset=2)
            return result(response)
        raise BridgeError("peer_unknown", "lost reply")

    async with Bridge(config) as bridge:
        fake_peer(
            bridge, [wrapper("td_thread_umanage"), wrapper("td_command__operation", True)], peer
        )
        outcome = await call(bridge, "local", "td_thread_umanage", values, "modern")
    assert not outcome["success"] and outcome["task"]["state"] == "unknown"
    assert outcome["evidence"]["provider_error"].get("operation_receipt_found", False) is (
        variant in {"valid", "pending"}
    )
    assert len(seen) == 2
    assert seen[1] == (
        "td_command__operation",
        {"workspace_id": "ws1", "arguments": {"operation_id": op}},
    )


@pytest.mark.parametrize("compact", [False, True])
async def test_large_board_opt_in_compacts_persistence_and_requires_separate_readback(
    config, compact
):
    configured(config)
    board = {"id": "t1", "revision": 4, "context": {"notes": "history " * 50000}}
    tools = manage_contract() + [declared("get_thread", readonly=True)]
    reads = []

    async def peer(_, name, values, **kwargs):
        if name == "get_thread":
            reads.append(values)
            return result(board)
        return result(receipt(thread=board))

    async with Bridge(config) as bridge:
        fake_peer(bridge, tools, peer)
        outcome = await call(
            bridge, "local", "thread_manage", arguments(), "big-board", compact_response=compact
        )
        saved = bridge.task("local", outcome["task"]["id"])
        size = len(json.dumps(saved["result"]))
        assert outcome["effect_confirmed"]
        assert (size < 2000) if compact else (size > 350000)
        stored_request = bridge.store.get(outcome["task"]["id"])
        assert ("compact_response" in stored_request["args"]) is compact
        if compact:
            assert outcome["value"]["thread"] == {"id": "t1", "revision": 4}
            assert outcome["value"]["readback"]["tool"] == "get_thread"
            readback = await call(bridge, "local", "get_thread", {"id": "t1"})
            assert readback["value"] == board
    assert reads == ([{"id": "t1"}] if compact else [])


async def test_generic_success_is_never_claimed_or_projected_as_a_receipt(config):
    configured(config)
    async with Bridge(config) as bridge:
        fake_peer(bridge, [declared("new_writer")], lambda *a, **kw: result(receipt()))
        outcome = await call(
            bridge, "local", "new_writer", {"id": "one"}, "generic", compact_response=True
        )
    assert outcome["success"] and not outcome["effect_confirmed"]
    assert outcome["value"] == receipt()
    assert outcome["compact_response"] == {"applied": False}


@pytest.mark.parametrize("bad", ["operation", "thread", "revision", "duplicate"])
async def test_malformed_direct_receipt_is_never_confirmed_or_compacted(config, bad):
    configured(config)
    saved = receipt()
    saved[
        {
            "operation": "operation_id",
            "thread": "thread_id",
            "revision": "revision",
            "duplicate": "duplicate",
        }[bad]
    ] = "different" if bad in {"operation", "thread"} else 1 if bad == "duplicate" else True
    async with Bridge(config) as bridge:
        fake_peer(bridge, manage_contract(), lambda *a, **kw: result(saved))
        outcome = await call(
            bridge, "local", "thread_manage", arguments(), "invalid-receipt", compact_response=True
        )
    assert outcome["success"] and not outcome["effect_confirmed"]
    assert outcome["compact_response"] == {"applied": False}
    assert outcome["value"] == saved


async def test_modern_compact_receipt_keeps_original_digest_separate_from_projection(config):
    configured(config)
    original = arguments()
    op, revision = original.pop("operation_id"), original.pop("expected_revision")
    values = {
        "workspace_id": "ws1",
        "operation_id": op,
        "expected_revision": revision,
        "arguments": original,
    }
    remote = envelope(
        "thread_manage", receipt(), operation_id=op, result_digest="a" * 64, duplicate=False
    )
    async with Bridge(config) as bridge:
        fake_peer(bridge, [wrapper("td_thread_umanage")], lambda *a, **kw: result(remote))
        outcome = await call(
            bridge, "local", "td_thread_umanage", values, "modern-compact", compact_response=True
        )
    assert outcome["effect_confirmed"] and outcome["compact_response"]["applied"]
    projected = outcome["value"]
    assert projected["original_result_digest"] == "a" * 64 and "result_digest" not in projected
    assert projected["operation_id"] == op
    assert projected["result"]["readback"]["arguments"] == {
        "workspace_id": "ws1",
        "arguments": {"id": "t1"},
    }


async def test_modern_whiteboard_status_is_only_unverified_evidence(config):
    configured(config)
    domain = {
        "id": "t1",
        "actor": "Codex",
        "actor_type": "codex",
        "entry_type": "note",
        "content": "new note",
    }
    values = {
        "workspace_id": "ws1",
        "arguments": domain,
        "operation_id": "note-1",
        "expected_revision": 3,
    }
    saved = {"entry": {**domain, "id": "e1", "thread_id": "t1"}, "duplicate": False}

    async def peer(_, name, payload, **kwargs):
        if name == "td_command__operation":
            status = {"operation_id": "note-1", "found": True, "state": "complete", "result": saved}
            return result(envelope("command.operation", status))
        raise BridgeError("peer_unknown", "lost reply")

    async with Bridge(config) as bridge:
        fake_peer(
            bridge, [wrapper("td_whiteboard__append"), wrapper("td_command__operation", True)], peer
        )
        outcome = await call(bridge, "local", "td_whiteboard__append", values, "modern-note")
    assert not outcome["success"] and outcome["task"]["state"] == "unknown"
    assert outcome["evidence"]["provider_error"]["operation_receipt_found"]
    assert outcome["evidence"]["provider_error"]["request_hash_verified"] is False


async def test_hidden_conflict_receipt_with_same_identity_does_not_prove_request(config):
    configured(config)
    original = arguments()

    async def peer(_, name, payload, **kwargs):
        if name == "thread_operation_status":
            status = {"operation_id": "note-1", "found": True, "result": receipt()}
            return result(status)
        # The lost transport may conceal an operation_conflict from the peer.
        raise BridgeError("peer_unknown", "lost conflict response")

    async with Bridge(config) as bridge:
        pool = fake_peer(bridge, manage_contract(), peer)
        outcome = await call(bridge, "local", "thread_manage", original, "outer-attempt")
        assert outcome["task"]["state"] == "unknown" and not outcome["success"]
        assert outcome["evidence"]["provider_error"]["operation_receipt_found"]
        assert outcome["evidence"]["provider_error"]["request_hash_verified"] is False
        assert outcome["recovery"]["operation_id"] == "outer-attempt"
        assert outcome["recovery"]["peer_operation_id"] == "note-1"
        same = await call(bridge, "local", "thread_manage", original, "outer-attempt")
        assert same["task"] == outcome["task"]
        with pytest.raises(BridgeError) as conflict:
            await call(
                bridge,
                "local",
                "thread_manage",
                {**original, "operation_id": "replacement"},
                "outer-attempt",
            )
        assert conflict.value.diagnostic["recovery"]["peer_operation_id"] == "note-1"
        assert conflict.value.diagnostic["requested_peer_operation_id"] == "replacement"
        assert conflict.value.diagnostic["original_attempt"]["attempt"] == 1
        assert pool.call.await_count == 2


@pytest.mark.parametrize("change", ["missing", "mutating", "permission_revoked"])
async def test_recovery_revalidates_status_after_reconnect_or_permission_change(config, change):
    configured(config)
    tools = manage_contract()
    replacement = manage_contract()
    if change == "missing":
        replacement.pop()
    elif change == "mutating":
        replacement[1].annotations.readOnlyHint = False
    reads = []

    async with Bridge(config) as bridge:

        async def peer(_, name, payload, **kwargs):
            if name == "thread_operation_status":
                reads.append(payload)
                return result(
                    {
                        "operation_id": "note-1",
                        "found": True,
                        "result": receipt(),
                    }
                )
            if change == "permission_revoked":
                # Restore no authority through a stale pre-dispatch decision.
                config.principals["local"].capabilities.remove("threaddesk.read")
                config.principals["local"].permission_level = "ask"
            raise BridgeError("peer_unknown", "lost reply")

        fake_peer(bridge, tools, peer)
        bridge.threaddesk.read_operation_catalog = AsyncMock(
            side_effect=[tools, tools, replacement]
        )
        outcome = await call(bridge, "local", "thread_manage", arguments(), "new-generation")
    assert outcome["task"]["state"] == "unknown" and not outcome["success"]
    assert reads == []
