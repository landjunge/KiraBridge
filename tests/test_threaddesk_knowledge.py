"""Actual pinned peer knowledge contracts, never a second knowledge implementation."""

import os

import pytest
from test_handoff import call, configure

from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.models import BridgeError, TaskRequest

pytestmark = pytest.mark.skipif(
    not os.environ.get("KIRABRIDGE_TEST_THREADDESK_SOURCE"),
    reason="Reviewed knowledge-capable ThreadDesk source required",
)


async def test_actual_knowledge_history_reentry_replay_and_scope(config, tmp_path):
    counter = configure(config, tmp_path)
    async with Bridge(config) as bridge:
        created = await call(
            bridge,
            "k-create",
            "threaddesk.manage",
            {
                "operation_id": "k-create",
                "action": "create",
                "expected_revision": 0,
                "data": {"title": "Synthetic knowledge acceptance"},
            },
        )
        thread = created["result"]["value"]
        source = {"source_ref": "synthetic-operator-decision", "source_revision": "revision-1"}
        arguments = {
            "operation_id": "k-record",
            "action": "record",
            "id": thread["thread_id"],
            "expected_revision": thread["revision"],
            "data": {
                **source,
                "kind": "decision",
                "status": "confirmed",
                "title": "First choice",
            },
        }
        first = (await call(bridge, "k-record", "threaddesk.knowledge", arguments))["result"][
            "value"
        ]
        replay = (await call(bridge, "k-replay", "threaddesk.knowledge", arguments))["result"][
            "value"
        ]
        assert replay["duplicate"] is True and replay["node_id"] == first["node_id"]
        conflict = await call(
            bridge,
            "k-conflict",
            "threaddesk.knowledge",
            {
                **arguments,
                "data": {**arguments["data"], "title": "Changed choice"},
            },
            expected="failed",
        )
        assert conflict["result"]["value"]["error"]["code"] == "operation_conflict"
        newer = (
            await call(
                bridge,
                "k-replace",
                "threaddesk.knowledge",
                {
                    "operation_id": "k-replace",
                    "action": "supersede",
                    "id": first["thread_id"],
                    "expected_revision": first["revision"],
                    "data": {
                        **source,
                        "node_id": first["node_id"],
                        "expected_node_revision": first["node"]["revision"],
                        "title": "Replacement choice",
                    },
                },
            )
        )["result"]["value"]
        question = (
            await call(
                bridge,
                "k-question",
                "threaddesk.knowledge",
                {
                    "operation_id": "k-question",
                    "action": "record",
                    "id": first["thread_id"],
                    "expected_revision": newer["revision"],
                    "data": {**source, "kind": "question", "title": "Which colour?"},
                },
            )
        )["result"]["value"]
        answer = (
            await call(
                bridge,
                "k-answer",
                "threaddesk.knowledge",
                {
                    "operation_id": "k-answer",
                    "action": "resolve_question",
                    "id": first["thread_id"],
                    "expected_revision": question["revision"],
                    "data": {
                        **source,
                        "node_id": question["node_id"],
                        "expected_node_revision": question["node"]["revision"],
                        "text": "Blue",
                    },
                },
            )
        )["result"]["value"]
        saved = (
            await call(
                bridge,
                "k-save",
                "threaddesk.knowledge",
                {
                    "operation_id": "k-save",
                    "action": "save_reentry",
                    "id": first["thread_id"],
                    "expected_revision": answer["revision"],
                    "data": {
                        **source,
                        "summary": "Synthetic decisions retained",
                        "next_step": "Review separately",
                    },
                },
            )
        )["result"]["value"]
        stale = await call(
            bridge,
            "k-stale",
            "threaddesk.knowledge",
            {
                **arguments,
                "operation_id": "k-stale",
            },
            expected="failed",
        )
        assert stale["result"]["value"]["error"]["code"] == "revision_conflict"
        other = (
            await call(
                bridge,
                "k-other",
                "threaddesk.manage",
                {
                    "operation_id": "k-other",
                    "action": "create",
                    "expected_revision": 0,
                    "data": {"title": "Other synthetic thread"},
                },
            )
        )["result"]["value"]
        foreign = await call(
            bridge,
            "k-foreign",
            "threaddesk.knowledge",
            {
                "operation_id": "k-foreign",
                "action": "supersede",
                "id": other["thread_id"],
                "expected_revision": other["revision"],
                "data": {
                    **source,
                    "node_id": newer["node_id"],
                    "expected_node_revision": newer["node"]["revision"],
                    "title": "Must not replace foreign knowledge",
                },
            },
            expected="failed",
        )
        assert foreign["result"]["value"]["error"]["code"] == "scope_conflict"
        await bridge.threaddesk.pool.disconnect("threaddesk")
        state = (
            await call(
                bridge,
                "k-read",
                "threaddesk.read",
                {
                    "tool": "get_reentry",
                    "arguments": {"id": first["thread_id"]},
                },
            )
        )["result"]["value"]
        assert state["revision"] == saved["revision"]
        assert [item["id"] for item in state["decisions"]] == [newer["node_id"]]
        assert [item["id"] for item in state["superseded_decisions"]] == [first["node_id"]]
        assert not state["open_questions"] and len(state["answered_questions"]) == 1
        assert state["answered_questions"][0]["title"] == "Which colour?"
        assert state["answered_questions"][0]["metadata"]["resolution"]["text"] == "Blue"
        assert state["saved"]["source_verification"] == "referenced_unverified"
        assert not counter.exists(), "Knowledge must not start an agent"


async def test_knowledge_requires_its_separate_capability(config, tmp_path):
    counter = configure(config, tmp_path)
    config.principals["local"].capabilities.remove("threaddesk.knowledge")
    async with Bridge(config) as bridge:
        with pytest.raises(BridgeError, match="Capability") as error:
            bridge.prepare(
                "local",
                TaskRequest(
                    task_id="k-denied",
                    idempotency_key="k-denied",
                    operation="threaddesk.knowledge",
                    arguments={
                        "operation_id": "k-denied",
                        "action": "record",
                        "id": "synthetic",
                        "expected_revision": 1,
                        "data": {},
                    },
                ),
            )
        assert error.value.code == "forbidden"
        assert not bridge.threaddesk.pool.sessions and not counter.exists()
