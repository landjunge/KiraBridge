import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import ValidationError

from kirabridge.audit_manager import verify
from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import AgentConfig, TeamConfig, TeamWorkerConfig
from kirabridge.bridge_core.models import BridgeError, TaskRequest, canonical, digest
from kirabridge.team_manager import TeamManager
from kirabridge.team_manager.models import (
    TeamCreate,
    TeamMessageSend,
    TeamRoleSet,
    TeamSessionClear,
    TeamSessionGet,
    TeamWorkClaim,
    TeamWorkComplete,
    TeamWorkCreate,
    TeamWorkReprocess,
)


@pytest.fixture
def domain(bridge, config):
    for name in ("local", "codex", "grok", "chatgpt", "observer", "outsider"):
        policy = config.principals["local"].model_copy(deep=True)
        policy.capabilities += ["team.manage", "team.read", "team.write"]
        policy.approval_mode = "automatic"
        config.principals[name] = policy
    root = config.principals["local"].roots[0]
    config.agents = {name: AgentConfig(kind="codex") for name in ("codex", "grok")}
    config.team = TeamConfig(
        enabled=True,
        workers={
            "local": TeamWorkerConfig(),
            "chatgpt": TeamWorkerConfig(),
            "observer": TeamWorkerConfig(),
            "codex": TeamWorkerConfig(agent="codex", cwd=root),
            "grok": TeamWorkerConfig(agent="grok", cwd=root),
        },
    )
    manager = TeamManager(bridge)
    manager.create("local", create())
    return manager


def create(**changes):
    return TeamCreate(
        **{
            "team_id": "test-team",
            "name": "KiraBridge team",
            "members": {
                "local": "worker",
                "codex": "worker",
                "grok": "worker",
                "chatgpt": "coordinator",
                "observer": "observer",
            },
            "coordinator": "chatgpt",
            "idempotency_key": "create",
            **changes,
        }
    )


def test_operator_roster_removal_revokes_existing_shared_read_access(domain):
    shared = domain.delegate("local", work())
    domain.config.team.workers.pop("codex")
    for read in (
        lambda: domain.list("codex"),
        lambda: domain.get("codex", "test-team"),
        lambda: domain.messages("codex", "test-team"),
        lambda: domain.work_get("codex", "test-team", shared["id"]),
    ):
        with pytest.raises(BridgeError):
            read()


def work(**changes):
    return TeamWorkCreate(
        **{
            "team_id": "test-team",
            "assignee": "codex",
            "title": "Test work",
            "body": "Intentional shared request",
            "idempotency_key": "work",
            **changes,
        }
    )


def test_maintenance_drains_only_sealed_existing_team_work(domain):
    shared = domain.delegate("local", work())
    now = time.time()
    domain.store.db.execute(
        "INSERT INTO activation_runs VALUES('maintenance','draining',?,?,?,NULL)", (now, now, "{}")
    )
    with pytest.raises(BridgeError) as error:
        domain.delegate("local", work(idempotency_key="new-work"))
    assert error.value.code == "service_maintenance"
    claimed = domain.claim(shared["id"])
    root = domain.config.principals["codex"].roots[0]
    request = TaskRequest(
        task_id=claimed["core_task_id"],
        idempotency_key=claimed["core_task_id"],
        operation="agent.execute",
        arguments={"agent": "codex", "prompt": "existing work", "cwd": root},
    )
    domain.seal_request(shared["id"], request)
    wrong = request.model_copy(
        update={"arguments": {**request.arguments, "prompt": "different work"}}
    )
    with pytest.raises(BridgeError) as error:
        domain.bridge.prepare("codex", wrong)
    assert error.value.code == "service_maintenance"
    task = domain.bridge.prepare("codex", request)
    domain.bind_task(shared["id"], task)
    accepted = domain.store.claim("existing-team-worker", 30)
    assert accepted["id"] == request.task_id
    domain.store.assert_accepting(continuation_id=request.task_id, owned_execution=True)


def message(**changes):
    return TeamMessageSend(
        **{
            "team_id": "test-team",
            "recipient": "grok",
            "body": "Shared question",
            "kind": "question",
            "idempotency_key": "message",
            **changes,
        }
    )


def role(domain, member, selected, *, principal="local", active=True, key=None):
    return domain.set_role(
        principal,
        TeamRoleSet(
            team_id="test-team",
            member=member,
            role=selected,
            active=active,
            expected_revision=domain.get(principal, "test-team")["revision"],
            idempotency_key=key or f"{member}-{selected}-{active}",
        ),
    )


def core(domain, claimed, state="completed", **changes):
    value = {
        "id": claimed["core_task_id"],
        "principal": claimed["assignee"],
        "operation": "agent.execute",
        "state": state,
        "args": {
            "agent": claimed["assignee"],
            "cwd": domain.config.team.workers[claimed["assignee"]].cwd,
            "timeout": 90,
            "prompt": "PRIVATE TASK ARGS",
        },
        "evidence": {"kind": "turn.completed", "session_id": "native-session"},
        "result": {"final_message": "Actual shared result", "private": "DO NOT COPY"},
        "started": 1.0,
        "finished": 2.0 if state == "completed" else None,
    }
    request = TaskRequest(
        task_id=value["id"],
        idempotency_key="test-" + value["id"],
        operation="agent.execute",
        arguments=value["args"],
    )
    domain.seal_request(claimed["id"], request)
    with domain.store.transaction():
        domain.store.db.execute(
            "INSERT OR IGNORE INTO tasks(id,principal,idem,request_hash,operation,args,state,"
            "created,updated) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                value["id"],
                claimed["assignee"],
                request.idempotency_key,
                digest(request.model_dump()),
                "agent.execute",
                canonical(value["args"]),
                state,
                1,
                2,
            ),
        )
    return {**value, **changes}


def test_create_is_persistent_idempotent_and_does_not_change_store_schema(domain, bridge, config):
    original = domain.get("local", "test-team")
    assert original["owner"] == "local" and original["coordinator"] == "chatgpt"
    assert original["members"]["chatgpt"]["execution"] == "manual"
    assert domain.create("local", create())["created"] == original["created"]
    with pytest.raises(BridgeError, match="different"):
        domain.create("local", create(name="Conflict"))
    reopened = Bridge(config)
    try:
        manager = TeamManager(reopened)
        assert manager.get("grok", "test-team") == original
        assert reopened.store.db.execute("PRAGMA user_version").fetchone()[0] == 2
    finally:
        reopened.store.close()
    assert verify(bridge.store)["valid"]


def test_creation_requires_roster_and_does_not_allow_multiple_coordinators(domain):
    with pytest.raises(BridgeError, match="participation roster"):
        domain.create(
            "local", create(team_id="other", members={"outsider": "worker"}, coordinator="outsider")
        )
    with pytest.raises(BridgeError, match="exactly one"):
        domain.create(
            "local",
            create(team_id="other", members={"codex": "coordinator", "chatgpt": "coordinator"}),
        )
    domain.config.team.max_teams = 1
    with pytest.raises(BridgeError, match="archive"):
        domain.create("local", create(team_id="other", idempotency_key="other"))


def test_owner_immutable_and_coordinator_switch_is_atomic(domain):
    changed = role(domain, "grok", "coordinator")
    assert changed["coordinator"] == "grok" and changed["owner"] == "local"
    assert changed["members"]["chatgpt"]["role"] == "worker"
    assert sum(m["active"] and m["role"] == "coordinator" for m in changed["members"].values()) == 1
    with pytest.raises(BridgeError, match="owner or coordinator"):
        role(domain, "codex", "reviewer", principal="chatgpt")
    role(domain, "codex", "reviewer", principal="grok")
    with pytest.raises(BridgeError, match="different coordinator"):
        role(domain, "grok", "worker")
    with pytest.raises(BridgeError, match="immutable owner"):
        role(domain, "local", "worker", active=False)
    role(domain, "grok", "coordinator", principal="local", key="owner-retains-control")


def test_role_cas_and_idempotency(domain):
    request = TeamRoleSet(
        team_id="test-team",
        member="codex",
        role="reviewer",
        expected_revision=1,
        idempotency_key="reviewer",
    )
    assert domain.set_role("local", request)["revision"] == 2
    assert domain.set_role("local", request)["revision"] == 2
    with pytest.raises(BridgeError, match="roles changed"):
        domain.set_role("local", request.model_copy(update={"idempotency_key": "stale"}))
    with pytest.raises(BridgeError, match="different"):
        domain.set_role("local", request.model_copy(update={"role": "observer"}))


def test_observers_read_only_and_revoked_members_cannot_read(domain):
    item = domain.delegate("codex", work(assignee="grok"))
    assert domain.work_get("observer", "test-team", item["id"])["body"]
    for operation in (
        lambda: domain.send("observer", message()),
        lambda: domain.delegate("observer", work(idempotency_key="observe")),
        lambda: domain.delegate("codex", work(assignee="observer")),
        lambda: domain.send("codex", message(recipient="observer")),
    ):
        with pytest.raises(BridgeError, match="Observers"):
            operation()
    role(domain, "grok", "worker", active=False)
    for operation in (
        lambda: domain.get("grok", "test-team"),
        lambda: domain.work_get("grok", "test-team", item["id"]),
        lambda: domain.messages("grok", "test-team"),
        lambda: domain.events("grok", "test-team"),
    ):
        with pytest.raises(BridgeError, match="not found"):
            operation()
    assert not domain.list("grok")["teams"]


def test_foreign_team_and_private_tasks_remain_invisible(domain, bridge):
    item = domain.delegate("codex", work())
    for operation in (
        lambda: domain.work_get("outsider", "test-team", item["id"]),
        lambda: domain.messages("outsider", "test-team"),
        lambda: domain.events("outsider", "test-team"),
        lambda: domain.ack("outsider", "test-team", "guess"),
    ):
        with pytest.raises(BridgeError, match="not found"):
            operation()
    claimed = domain.claim(item["id"])
    observed = domain.bind_task(item["id"], core(domain, claimed))
    assert "PRIVATE TASK ARGS" not in json.dumps(observed)
    assert "DO NOT COPY" not in json.dumps(observed)
    assert "args" not in observed
    with pytest.raises(BridgeError, match="Task not found"):
        bridge.store.get(claimed["core_task_id"], "grok")


def test_shared_messages_order_idempotency_real_recipient_ack_and_no_auto_jobs(domain, bridge):
    first = domain.send("codex", message())
    assert first["sender"] == "codex" and first["acknowledged"] is None
    assert domain.send("codex", message())["id"] == first["id"]
    with pytest.raises(BridgeError, match="different"):
        domain.send("codex", message(body="Different"))
    assert domain.messages("chatgpt", "test-team")["messages"][0]["acknowledged"] is None
    with pytest.raises(BridgeError, match="Incoming"):
        domain.ack("codex", "test-team", first["id"])
    acknowledged = domain.ack("grok", "test-team", first["id"])
    assert (
        acknowledged["acknowledged"] == domain.ack("grok", "test-team", first["id"])["acknowledged"]
    )
    reply = domain.send(
        "grok",
        message(recipient="codex", kind="answer", reply_to=first["id"], idempotency_key="reply"),
    )
    assert reply["seq"] > first["seq"]
    assert domain.messages("observer", "test-team", after=first["seq"])["messages"] == [reply]
    assert not domain.pending()
    assert bridge.store.db.execute("SELECT count(*) FROM message_jobs").fetchone()[0] == 0
    assert verify(bridge.store)["valid"]
    audit = " ".join(row[0] for row in bridge.store.db.execute("SELECT metadata FROM audit"))
    assert "Shared question" not in audit and "Actual shared result" not in audit


def test_messages_and_work_utf8_bounds_apply_before_insertion(domain):
    domain.config.team.max_body_bytes = 256
    for operation in (
        lambda: domain.send("codex", message(body="😀" * 100)),
        lambda: domain.delegate("codex", work(body="😀" * 100)),
    ):
        with pytest.raises(BridgeError, match="byte limit"):
            operation()
    domain.config.team.max_pending_per_member = 1
    domain.send("codex", message())
    with pytest.raises(BridgeError, match="inbox"):
        domain.send("codex", message(idempotency_key="second"))
    domain.delegate("codex", work(assignee="grok"))
    with pytest.raises(BridgeError, match="queue"):
        domain.delegate("codex", work(assignee="grok", idempotency_key="second"))


def test_manual_chatgpt_receipt_is_not_execution_and_completion_is_assignee_report(domain):
    item = domain.delegate("codex", work(assignee="chatgpt"))
    assert item["state"] == "queued_manual" and not domain.pending()
    claim = TeamWorkClaim(team_id="test-team", work_id=item["id"], idempotency_key="receipt")
    with pytest.raises(BridgeError, match="manual assignee"):
        domain.work_claim("grok", claim)
    accepted = domain.work_claim("chatgpt", claim)
    assert accepted["state"] == "accepted_manual" and accepted["started"] is None
    assert domain.work_claim("chatgpt", claim) == accepted
    complete = TeamWorkComplete(
        team_id="test-team", work_id=item["id"], result="Manual answer", idempotency_key="complete"
    )
    done = domain.work_complete("chatgpt", complete)
    assert done["state"] == "completed" and done["evidence"]["kind"] == "assignee_report"
    assert done["evidence"]["project_completion_verified"] is False
    assert domain.work_complete("chatgpt", complete) == done


def test_automatic_work_cannot_be_falsely_completed_by_public_manual_tool(domain):
    item = domain.delegate("grok", work())
    with pytest.raises(BridgeError, match="external assignee"):
        domain.work_complete(
            "codex",
            TeamWorkComplete(
                team_id="test-team", work_id=item["id"], result="fake", idempotency_key="fake"
            ),
        )


def test_parent_lineage_root_budget_depth_and_actual_assignee(domain):
    root = domain.delegate("grok", work())
    child = domain.delegate(
        "codex", work(assignee="grok", parent_id=root["id"], idempotency_key="child")
    )
    assert child["root_id"] == root["id"] and child["depth"] == 1
    with pytest.raises(BridgeError, match="actual assignee"):
        domain.delegate("chatgpt", work(parent_id=root["id"], idempotency_key="fake-parent"))
    domain.config.team.max_hops = 1
    with pytest.raises(BridgeError, match="depth"):
        domain.delegate("grok", work(parent_id=child["id"], idempotency_key="too-deep"))
    domain.config.team.max_hops = 6
    domain.config.team.max_work_per_root = 2
    with pytest.raises(BridgeError, match="budget"):
        domain.delegate("grok", work(parent_id=child["id"], idempotency_key="renamed"))
    assert (
        domain.delegate(
            "codex", work(assignee="grok", parent_id=root["id"], idempotency_key="child")
        )["id"]
        == child["id"]
    )


def test_claim_persists_once_before_execution_and_restart_does_not_queue_again(domain, config):
    item = domain.delegate("grok", work())
    claimed = domain.claim(item["id"])
    assert claimed["state"] == "dispatching" and claimed["core_task_id"] == "team-" + item["id"]
    assert domain.claim(item["id"]) is None and not domain.pending()
    reopened = Bridge(config)
    try:
        manager = TeamManager(reopened)
        assert not manager.pending()
        assert manager.inflight()[0]["core_task_id"] == claimed["core_task_id"]
        manager.fail(item["id"], "unknown", "core_task_missing", {"reason": "restart"})
        assert not manager.inflight() and not manager.pending()
        assert manager.claim(item["id"]) is None
    finally:
        reopened.store.close()


def test_claim_revalidates_roles_permissions_and_hourly_budget(domain):
    item = domain.delegate("grok", work())
    role(domain, "codex", "observer")
    assert domain.claim(item["id"]) is None
    assert domain.work_get("local", "test-team", item["id"])["state"] == "blocked"
    role(domain, "codex", "worker", key="regrant")
    domain.config.team.max_runs_per_hour = 1
    first = domain.delegate("grok", work(idempotency_key="first"))
    second = domain.delegate("grok", work(idempotency_key="second"))
    assert domain.claim(first["id"])
    assert domain.claim(second["id"]) is None
    assert domain.work_get("local", "test-team", second["id"])["error"] == "team_rate_limit"


def test_running_task_scope_revalidation_blocks_role_and_roster_escalation(domain):
    item = domain.delegate("grok", work())
    claimed = domain.claim(item["id"])
    native = core(domain, claimed, "accepted")
    domain.authorize_execution(native)
    for changed in (
        {"principal": "grok"},
        {"args": {**native["args"], "agent": "grok"}},
        {"args": {**native["args"], "cwd": "/"}},
        {"args": {**native["args"], "local_tools": True}},
    ):
        with pytest.raises(BridgeError, match="fixed worker scope"):
            domain.authorize_execution({**native, **changed})
    domain.authorize_execution({"id": "ordinary-private-task", "principal": "outsider"})
    role(domain, "codex", "observer")
    with pytest.raises(BridgeError, match="Observers"):
        domain.authorize_execution(native)


def test_completed_turn_processing_and_finish_preserve_actions_without_poll_audit_flood(
    domain, bridge
):
    item = domain.delegate("grok", work())
    claimed = domain.claim(item["id"])
    native = core(domain, claimed)
    observed = domain.bind_task(item["id"], native)
    assert observed["state"] == "processing_result" and observed["finished"] is None
    count = bridge.store.db.execute("SELECT count(*) FROM audit").fetchone()[0]
    assert domain.bind_task(item["id"], native) == observed
    assert bridge.store.db.execute("SELECT count(*) FROM audit").fetchone()[0] == count
    done = domain.finish(
        item["id"],
        "Processed result",
        {
            "actions": [{"type": "task", "id": "child-id", "error_code": None}],
            "api_key": "NEVER COPY",
        },
    )
    assert done["state"] == "completed" and done["evidence"]["actions"][0]["id"] == "child-id"
    assert "api_key" not in done["evidence"]
    assert done["evidence"]["completion_scope"] == "agent_turn"
    assert domain.finish(item["id"], "Processed result", {}) == done
    assert not domain.inflight()


def test_native_mismatched_identity_is_rejected_and_raw_errors_not_shared(domain):
    item = domain.delegate("grok", work())
    claimed = domain.claim(item["id"])
    with pytest.raises(BridgeError, match="identity"):
        domain.bind_task(item["id"], core(domain, claimed, principal="grok"))
    failed = domain.bind_task(
        item["id"],
        core(
            domain,
            claimed,
            "failed",
            error={"code": "provider_auth", "message": "SUPER SECRET RAW PROVIDER ERROR"},
        ),
    )
    assert failed["error"] == "provider_auth"
    assert "SUPER SECRET" not in json.dumps(failed)


@pytest.mark.parametrize("target", ["create", "send", "delegate", "role"])
def test_manual_authorization_cannot_be_laundered_through_automatic_assignee(domain, target):
    domain.config.principals["local"].approval_mode = "manual"
    operation = {
        "create": lambda: domain.create("local", create(team_id="manual")),
        "send": lambda: domain.send("local", message()),
        "delegate": lambda: domain.delegate("local", work()),
        "role": lambda: role(domain, "codex", "reviewer"),
    }[target]
    with pytest.raises(BridgeError, match="automatic authorization"):
        operation()


def test_explicit_full_team_permissions_override_legacy_manual_without_granting_access(domain):
    for level in ("ask", "medium"):
        domain.config.principals["local"].permission_level = level
        with pytest.raises(BridgeError) as error:
            domain.delegate("local", work(idempotency_key="nonautomatic-" + level))
        assert error.value.code == "approval_required"
    for name in ("local", "codex"):
        domain.config.principals[name].permission_level = "full"
        domain.config.principals[name].approval_mode = "manual"
    shared = domain.delegate("local", work(idempotency_key="effective-full"))
    assert domain.claim(shared["id"])
    domain.config.principals["codex"].agents = []
    blocked = domain.delegate("local", work(idempotency_key="missing-agent"))
    assert domain.claim(blocked["id"]) is None
    assert domain.work_get("local", "test-team", blocked["id"])["error"] == "team_worker_denied"
    domain.config.principals["local"].capabilities.remove("team.write")
    with pytest.raises(BridgeError) as error:
        domain.delegate("local", work(idempotency_key="missing-capability"))
    assert error.value.code == "forbidden"


def test_disabled_calls_are_denied_but_private_tasks_remain_unaffected(domain):
    domain.config.team.enabled = False
    with pytest.raises(BridgeError, match="disabled"):
        domain.list("local")
    assert not domain.pending()
    domain.authorize_execution({"id": "ordinary-private-task"})


def test_strict_inputs_forbid_identity_and_shell_fields():
    with pytest.raises(ValidationError):
        TeamMessageSend(**message().model_dump(), sender="chatgpt")
    with pytest.raises(ValidationError):
        TeamWorkCreate(**work().model_dump(), shell="rm -rf /")
    with pytest.raises(ValidationError):
        TeamRoleSet(
            team_id="t",
            member="grok",
            role="coordinator",
            expected_revision=True,
            idempotency_key="bool-revision",
        )


def test_concurrent_claim_is_exactly_once(domain, config):
    item = domain.delegate("grok", work())

    def claim_one(_):
        bridge = Bridge(config)
        try:
            return TeamManager(bridge).claim(item["id"])
        finally:
            bridge.store.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim_one, range(2)))
    assert sum(value is not None for value in results) == 1


def test_task_request_is_sealed_before_submission_and_cannot_be_replaced(domain):
    item = domain.delegate("grok", work())
    claimed = domain.claim(item["id"])
    native = core(domain, claimed, "accepted")
    domain.authorize_execution(native)
    request = TaskRequest(
        task_id=native["id"],
        idempotency_key="hijacked",
        operation="agent.execute",
        arguments=native["args"],
    )
    with pytest.raises(BridgeError, match="already sealed"):
        domain.seal_request(item["id"], request)
    domain.store.db.execute("UPDATE tasks SET request_hash='attacker' WHERE id=?", (native["id"],))
    with pytest.raises(BridgeError, match="sealed request"):
        domain.authorize_execution(native)
    with pytest.raises(BridgeError, match="sealed request"):
        domain.bind_task(item["id"], native)
    assert "core_request_hash" not in domain.work_get("grok", "test-team", item["id"])


def test_unsealed_task_and_team_only_worker_cannot_bypass_domain(domain):
    item = domain.delegate("grok", work())
    claimed = domain.claim(item["id"])
    worker = domain.config.team.workers["codex"]
    native = {
        "id": claimed["core_task_id"],
        "principal": "codex",
        "operation": "agent.execute",
        "args": {"agent": "codex", "cwd": worker.cwd, "timeout": worker.timeout},
    }
    with pytest.raises(BridgeError, match="sealed request"):
        domain.authorize_execution(native)
    domain.config.principals["codex"].team_only_execution = True
    with pytest.raises(BridgeError, match="sealed team tasks"):
        domain.authorize_execution({**native, "id": "unrelated-direct-task"})
    domain.config.principals["codex"].team_only_execution = False
    domain.authorize_execution({**native, "id": "unrelated-direct-task"})


def test_roster_and_manual_authorization_revocation_are_rechecked_before_dispatch(domain):
    first = domain.delegate("grok", work())
    domain.config.principals["grok"].approval_mode = "manual"
    assert domain.claim(first["id"]) is None
    assert domain.work_get("local", "test-team", first["id"])["error"] == "approval_required"
    domain.config.principals["grok"].approval_mode = "automatic"
    second = domain.delegate("grok", work(idempotency_key="second"))
    domain.config.team.workers.pop("grok")
    assert domain.claim(second["id"]) is None
    with pytest.raises(BridgeError, match="not found"):
        domain.get("grok", "test-team")


def test_context_selects_recent_results_and_prioritizes_old_own_pending_with_byte_bound(domain):
    recent_work = []
    for index in range(21):
        item = domain.delegate(
            "codex", work(assignee="chatgpt", idempotency_key=f"context-{index}")
        )
        domain.work_complete(
            "chatgpt",
            TeamWorkComplete(
                team_id="test-team",
                work_id=item["id"],
                result=f"RESULT-{index}: " + "😀" * 1200,
                idempotency_key=f"complete-{index}",
            ),
        )
        recent_work.append(item)
    own_pending = [
        domain.send(
            "grok",
            message(recipient="codex", body="\x00" * 3000, idempotency_key=f"old-own-{index}"),
        )
        for index in range(18)
    ]
    latest = [
        domain.send("codex", message(body="ä" * 3000, idempotency_key=f"latest-{index}"))
        for index in range(16)
    ]
    audit_before = domain.store.db.execute("SELECT count(*) FROM audit").fetchone()[0]
    context = domain.context("codex", "test-team")
    assert len(canonical(context).encode("utf-8")) <= 32768
    assert context["truncated"]
    assert [item["id"] for item in context["work"]] == [
        item["id"] for item in reversed(recent_work[-16:])
    ]
    assert context["work"][0]["result"].startswith("RESULT-20:")
    assert context["messages"][:16] == [
        {**item, "body": context["messages"][index]["body"], "body_truncated": True}
        for index, item in enumerate(own_pending[:16])
    ]
    assert [item["id"] for item in context["messages"][16:]] == [
        item["id"] for item in reversed(latest)
    ]
    assert len({item["id"] for item in context["messages"]}) == 32
    assert all(item["acknowledged"] is None for item in context["messages"])
    assert all(len(item["body"].encode("utf-8")) <= 2048 for item in context["messages"])
    assert all(len(item["result"].encode("utf-8")) <= 2048 for item in context["work"])
    assert domain.store.db.execute("SELECT count(*) FROM audit").fetchone()[0] == audit_before
    assert len(domain.work_get("codex", "test-team", recent_work[-1]["id"])["result"]) > 1200
    with pytest.raises(BridgeError, match="not found"):
        domain.context("outsider", "test-team")
    domain.config.team.workers.pop("codex")
    with pytest.raises(BridgeError, match="not found"):
        domain.context("codex", "test-team")


def test_manual_receipt_has_claimed_timestamp_without_execution_or_automatic_approval(domain):
    item = domain.delegate("codex", work(assignee="chatgpt"))
    domain.config.principals["chatgpt"].approval_mode = "manual"
    request = TeamWorkClaim(
        team_id="test-team", work_id=item["id"], idempotency_key="manual-receipt"
    )
    accepted = domain.work_claim("chatgpt", request)
    assert accepted["claimed"] >= item["created"]
    assert accepted["started"] is None and accepted["core_task_id"] is None
    assert accepted["evidence"]["kind"] == "assignee_receipt"
    assert domain.work_claim("chatgpt", request)["claimed"] == accepted["claimed"]
    complete = domain.work_complete(
        "chatgpt",
        TeamWorkComplete(
            team_id="test-team",
            work_id=item["id"],
            result="External assignee report",
            idempotency_key="manual-complete",
        ),
    )
    assert complete["state"] == "completed" and complete["started"] is None
    assert complete["evidence"]["kind"] == "assignee_report"
    assert domain.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0
    # A human receipt does not spend the automatic model-turn budget.
    domain.config.team.max_runs_per_hour = 1
    automatic = domain.delegate("codex", work(idempotency_key="after-human-receipt"))
    assert domain.claim(automatic["id"])


def completed_for_reprocess(domain):
    created = domain.delegate("grok", work())
    claimed = domain.claim(created["id"])
    text = 'NATIVE_ACTION_HEADER\n{"kirabridge_team":"1","result":"Native proof ä","actions":[]}'
    native = core(domain, claimed, result={"success": True, "text": text, "final_message": text})
    with domain.store.transaction():
        domain.store.db.execute(
            "UPDATE tasks SET result=?,evidence=?,started=?,finished=? WHERE id=?",
            (canonical(native["result"]), canonical(native["evidence"]), 1, 2, native["id"]),
        )
    observed = domain.bind_task(created["id"], native)
    expected_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert observed["evidence"]["core_result_sha256"] == expected_hash
    finished = domain.finish(created["id"], text, {"actions": [], "model_turn_completed": True})
    assert finished["evidence"]["core_result_sha256"] == expected_hash
    request = TeamWorkReprocess(
        team_id="test-team",
        work_id=created["id"],
        core_task_id=native["id"],
        expected_result_sha256=expected_hash,
        idempotency_key="reprocess-once",
    )
    return finished, native, request


@pytest.mark.parametrize("principal", ["local", "chatgpt"])
def test_owner_or_coordinator_can_reprocess_exact_existing_result_without_new_core_work(
    domain, principal
):
    previous, native, request = completed_for_reprocess(domain)
    before_tasks = [tuple(row) for row in domain.store.db.execute("SELECT * FROM tasks")]
    before_events = [tuple(row) for row in domain.store.db.execute("SELECT * FROM events")]
    reprocessed = domain.work_reprocess(principal, request)
    assert reprocessed["state"] == "processing_result" and reprocessed["finished"] is None
    assert reprocessed["started"] == previous["started"]
    assert reprocessed["core_task_id"] == previous["core_task_id"]
    assert reprocessed["result"] == previous["result"]
    assert reprocessed["evidence"]["core_result_sha256"] == request.expected_result_sha256
    assert domain.inflight()[0]["id"] == request.work_id
    assert not domain.pending()
    assert [tuple(row) for row in domain.store.db.execute("SELECT * FROM tasks")] == before_tasks
    assert [tuple(row) for row in domain.store.db.execute("SELECT * FROM events")] == before_events
    snapshot = dict(domain.store.db.execute("SELECT * FROM team_work_reprocess_history").fetchone())
    assert snapshot["previous_result"] == previous["result"]
    assert json.loads(snapshot["previous_evidence"]) == previous["evidence"]
    assert snapshot["previous_state"] == "completed"
    assert snapshot["previous_finished"] == previous["finished"]
    assert "PRIVATE TASK ARGS" not in json.dumps(snapshot)
    audit = " ".join(row[0] for row in domain.store.db.execute("SELECT metadata FROM audit"))
    assert "Native proof" not in audit and "PRIVATE TASK ARGS" not in audit
    assert domain.work_reprocess(principal, request) == reprocessed
    assert (
        dict(domain.store.db.execute("SELECT * FROM team_work_reprocess_history").fetchone())
        == snapshot
    )
    assert verify(domain.store)["valid"]
    domain.bind_task(request.work_id, native)
    domain.finish(
        request.work_id, "Processed result", {"actions": [{"type": "message", "id": "sent"}]}
    )
    # Retrying the accepted request returns its current result, without replaying actions.
    assert domain.work_reprocess(principal, request)["result"] == "Processed result"
    assert (
        dict(domain.store.db.execute("SELECT * FROM team_work_reprocess_history").fetchone())
        == snapshot
    )


@pytest.mark.parametrize(
    "principal,code",
    [("codex", "team_role_denied"), ("observer", "team_role_denied"), ("outsider", "not_found")],
)
def test_reprocess_requires_owner_or_coordinator_and_current_membership(domain, principal, code):
    _, _, request = completed_for_reprocess(domain)
    with pytest.raises(BridgeError) as error:
        domain.work_reprocess(principal, request)
    assert error.value.code == code
    assert (
        domain.store.db.execute("SELECT count(*) FROM team_work_reprocess_history").fetchone()[0]
        == 0
    )


@pytest.mark.parametrize(
    "change,code",
    [
        ("expected_hash", "team_result_conflict"),
        ("core_id", "team_task_conflict"),
        ("seal", "team_task_conflict"),
        ("native_unknown", "team_reprocess_denied"),
        ("native_failed", "team_reprocess_denied"),
        ("missing_success", "team_reprocess_denied"),
        ("missing_actions", "team_reprocess_denied"),
        ("prior_action", "team_reprocess_denied"),
        ("not_completed", "state_conflict"),
        ("assignee_identity", "team_task_conflict"),
    ],
)
def test_reprocess_rejects_changed_or_unproven_native_result_and_prior_actions(
    domain, change, code
):
    _, _, request = completed_for_reprocess(domain)
    if change == "expected_hash":
        request = request.model_copy(update={"expected_result_sha256": "0" * 64})
    elif change == "core_id":
        request = request.model_copy(update={"core_task_id": "another-core"})
    elif change == "seal":
        domain.store.db.execute("UPDATE tasks SET request_hash='changed'")
    elif change == "native_unknown":
        domain.store.db.execute("UPDATE tasks SET state='unknown'")
    elif change in {"native_failed", "missing_success"}:
        native = domain.store.get(request.core_task_id)["result"]
        if change == "missing_success":
            native.pop("success")
        else:
            native["success"] = False
        domain.store.db.execute("UPDATE tasks SET result=?", (canonical(native),))
    elif change in {"missing_actions", "prior_action"}:
        evidence = (
            {}
            if change == "missing_actions"
            else {"actions": [{"type": "message", "id": "already-sent"}]}
        )
        domain.store.db.execute("UPDATE team_work SET evidence=?", (canonical(evidence),))
    elif change == "not_completed":
        domain.store.db.execute("UPDATE team_work SET state='unknown'")
    elif change == "assignee_identity":
        domain.store.db.execute("UPDATE tasks SET principal='grok'")
    with pytest.raises(BridgeError) as error:
        domain.work_reprocess("local", request)
    assert error.value.code == code
    assert (
        domain.store.db.execute("SELECT count(*) FROM team_work_reprocess_history").fetchone()[0]
        == 0
    )


def test_reprocess_idempotency_conflicts_and_second_distinct_request_cannot_reopen_again(domain):
    _, native, request = completed_for_reprocess(domain)
    domain.work_reprocess("local", request)
    with pytest.raises(BridgeError) as error:
        domain.work_reprocess(
            "local", request.model_copy(update={"expected_result_sha256": "0" * 64})
        )
    assert error.value.code == "idempotency_conflict"
    domain.bind_task(request.work_id, native)
    domain.finish(request.work_id, "No actions", {"actions": []})
    with pytest.raises(BridgeError) as error:
        domain.work_reprocess("local", request.model_copy(update={"idempotency_key": "different"}))
    assert error.value.code == "team_reprocess_conflict"
    assert domain.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 1
    assert (
        domain.store.db.execute("SELECT count(*) FROM team_work_reprocess_history").fetchone()[0]
        == 1
    )


def test_reprocess_rechecks_automatic_approval_and_assignee_roster(domain):
    _, _, request = completed_for_reprocess(domain)
    domain.config.principals["local"].approval_mode = "manual"
    with pytest.raises(BridgeError) as error:
        domain.work_reprocess("local", request)
    assert error.value.code == "approval_required"
    domain.config.principals["local"].approval_mode = "automatic"
    domain.config.team.workers.pop("codex")
    with pytest.raises(BridgeError) as error:
        domain.work_reprocess("local", request)
    assert error.value.code == "team_member_denied"
    assert (
        domain.store.db.execute("SELECT count(*) FROM team_work_reprocess_history").fetchone()[0]
        == 0
    )


def session_request(**changes):
    return TeamSessionGet(**{"team_id": "test-team", "member": None, **changes})


def test_proven_worker_session_is_reused_only_for_managed_team_work(domain):
    domain.config.team.workers["codex"].execution_scope = "separate_managed_session"
    shared = domain.delegate("local", work())
    assert domain.resume_session(shared) is None
    idle = {"session_id": "codex-session-1", "adapter": "codex"}
    # A completed turn records an idle session.
    domain.record_session({**shared, "state": "completed"}, idle)
    read = domain.session("codex", session_request())
    assert read["session"]["session_id"] == "codex-session-1"
    assert read["session"]["agent"] == "codex"
    assert read["session"]["state"] == "idle"
    # The first follow-up reserves the idle session exclusively.
    assert domain.resume_session(shared) == "codex-session-1"
    assert domain.session("codex", session_request())["session"]["state"] == "active"
    # A reserved (active) session is never handed to a second follow-up.
    assert domain.resume_session(shared) is None
    # Non-managed execution scope never resumes.
    domain.record_session({**shared, "state": "completed"}, idle)
    domain.config.team.workers["codex"].execution_scope = "existing_visible_terminal"
    assert domain.resume_session(shared) is None
    domain.config.team.workers["codex"].execution_scope = "separate_managed_session"
    # A changed worker cwd never resumes a session recorded for another cwd.
    domain.record_session({**shared, "state": "completed"}, idle)
    domain.config.team.workers["codex"].cwd = "/tmp/other"
    assert domain.resume_session(shared) is None


def test_session_read_and_clear_are_role_scoped_and_idempotent(domain):
    domain.config.team.workers["codex"].execution_scope = "separate_managed_session"
    shared = domain.delegate("local", work())
    domain.record_session(shared, {"session_id": "codex-session-2"})
    with pytest.raises(BridgeError) as error:
        domain.session("observer", session_request(member="codex"))
    assert error.value.code == "team_role_denied"
    assert (
        domain.session("chatgpt", session_request(member="*"))["sessions"][0]["session_id"]
        == "codex-session-2"
    )
    first = domain.clear_session(
        "codex",
        TeamSessionClear(team_id="test-team", idempotency_key="clear-codex"),
    )
    assert first["cleared"] is True
    second = domain.clear_session(
        "codex",
        TeamSessionClear(team_id="test-team", idempotency_key="clear-codex"),
    )
    assert second == {"cleared": False, "idempotent": True, "member": "codex"}
    assert domain.session("codex", session_request())["session"] is None
    with pytest.raises(BridgeError) as error:
        domain.clear_session(
            "observer",
            TeamSessionClear(team_id="test-team", member="codex", idempotency_key="clear-other"),
        )
    assert error.value.code == "team_role_denied"


def test_resumed_session_identity_cannot_be_silently_replaced(domain):
    domain.config.team.workers["codex"].execution_scope = "separate_managed_session"
    shared = domain.delegate("local", work())
    domain.record_session(shared, {"session_id": "codex-session-3"})
    resumed = {**shared, "resume_session": "codex-session-3", "state": "dispatching"}
    domain.record_session(resumed, {"session_id": "different-session"})
    assert domain.session("codex", session_request())["session"]["session_id"] == "codex-session-3"
    completed = {**shared, "resume_session": None, "state": "completed"}
    domain.record_session(completed, {"session_id": "codex-session-4"})
    assert domain.session("codex", session_request())["session"]["session_id"] == "codex-session-4"
    assert domain.session("codex", session_request())["session"]["state"] == "idle"


def test_unknown_session_is_never_resumed(domain):
    domain.config.team.workers["codex"].execution_scope = "separate_managed_session"
    shared = domain.delegate("local", work())
    domain.record_session(
        {**shared, "state": "unknown"}, {"session_id": "codex-session-x", "adapter": "codex"}
    )
    assert domain.session("codex", session_request())["session"]["state"] == "unknown"
    assert domain.resume_session(shared) is None


def test_resume_rejects_a_changed_adapter(domain):
    domain.config.team.workers["codex"].execution_scope = "separate_managed_session"
    shared = domain.delegate("local", work())
    domain.record_session(
        {**shared, "state": "completed"}, {"session_id": "codex-session-1", "adapter": "codex"}
    )
    # The worker agent's adapter kind changes after the session was recorded.
    domain.config.agents["codex"] = AgentConfig(kind="grok_acp")
    assert domain.resume_session(shared) is None


def test_cleared_session_is_never_resurrected_by_a_running_turn(domain):
    domain.config.team.workers["codex"].execution_scope = "separate_managed_session"
    shared = domain.delegate("local", work())
    domain.record_session(
        {**shared, "state": "active"}, {"session_id": "codex-session-1", "adapter": "codex"}
    )
    domain.clear_session(
        "codex", TeamSessionClear(team_id="test-team", idempotency_key="clear-running")
    )
    assert domain.session("codex", session_request())["session"] is None
    # The still-running turn's completion must not resurrect the tombstone.
    domain.record_session(
        {**shared, "state": "completed"}, {"session_id": "codex-session-1", "adapter": "codex"}
    )
    assert domain.session("codex", session_request())["session"] is None


def test_recorded_session_cwd_is_the_proven_core_task_cwd(domain):
    import json as _json

    domain.config.team.workers["codex"].execution_scope = "separate_managed_session"
    shared = domain.delegate("local", work())
    task_id = "team-" + shared["id"]
    now = time.time()
    domain.store.db.execute(
        "INSERT INTO tasks(id,principal,idem,request_hash,operation,args,state,created,updated,"
        "attempt) VALUES(?,?,?,?,?,?,?,?,?,1)",
        (
            task_id,
            "codex",
            task_id,
            "fixture-request-hash",
            "agent.execute",
            _json.dumps(
                {"agent": "codex", "prompt": "fixture", "cwd": "/proven/core/cwd", "timeout": 2}
            ),
            "completed",
            now,
            now,
        ),
    )
    domain.record_session(
        {**shared, "state": "completed", "core_task_id": task_id},
        {"session_id": "codex-session-1", "adapter": "codex"},
    )
    assert domain._session_row("test-team", "codex")["cwd"] == "/proven/core/cwd"


def test_late_completion_callback_cannot_release_a_newer_reservation(domain):
    domain.config.team.workers["codex"].execution_scope = "separate_managed_session"
    w0 = domain.delegate("local", work(idempotency_key="w0"))
    domain.record_session({**w0, "state": "completed"}, {"session_id": "s1", "adapter": "codex"})
    assert domain.session("codex", session_request())["session"]["state"] == "idle"
    # A second work reserves the idle session (owner becomes w1).
    w1 = domain.delegate("local", work(idempotency_key="w1"))
    assert domain.resume_session(w1) == "s1"
    assert domain.session("codex", session_request())["session"]["state"] == "active"
    # A stale completion callback from w0 must not release w1's reservation.
    domain.record_session({**w0, "state": "completed"}, {"session_id": "s1", "adapter": "codex"})
    assert domain.session("codex", session_request())["session"]["state"] == "active"


def test_clear_before_first_record_fences_pre_clear_work(domain):
    domain.config.team.workers["codex"].execution_scope = "separate_managed_session"
    # Clear before any session row exists still creates a durable boundary.
    domain.clear_session(
        "codex", TeamSessionClear(team_id="test-team", idempotency_key="clear-early")
    )
    w_old = domain.delegate("local", work(idempotency_key="w-old"))
    domain.record_session(
        {**w_old, "state": "completed", "session_generation": 0},
        {"session_id": "s-old", "adapter": "codex"},
    )
    assert domain.session("codex", session_request())["session"] is None
    # A work claimed after the clear (generation 1) records a fresh session.
    w_new = domain.delegate("local", work(idempotency_key="w-new"))
    domain.record_session(
        {**w_new, "state": "completed", "session_generation": 1},
        {"session_id": "s-new", "adapter": "codex"},
    )
    assert domain.session("codex", session_request())["session"]["session_id"] == "s-new"


def test_unknown_recovery_keeps_the_reservation_identity(domain):
    from kirabridge.team_manager import _native_evidence

    domain.config.team.workers["codex"].execution_scope = "separate_managed_session"
    w1 = domain.delegate("local", work(idempotency_key="w1"))
    domain.record_session({**w1, "state": "active"}, {"session_id": "s1", "adapter": "codex"})
    # Crash recovery nests the last observation; record_session extracts it.
    native = _native_evidence(
        {
            "reason": "dispatcher_restart",
            "last_observation": {"session_id": "s1", "adapter": "codex"},
        }
    )
    domain.record_session({**w1, "state": "unknown"}, native)
    row = domain._session_row("test-team", "codex")
    assert row["state"] == "unknown" and row["session_id"] == "s1"


def test_unknown_recovery_without_a_fresh_session_id_keeps_identity(domain):
    domain.config.team.workers["codex"].execution_scope = "separate_managed_session"
    w1 = domain.delegate("local", work(idempotency_key="w1"))
    domain.record_session({**w1, "state": "active"}, {"session_id": "s1", "adapter": "codex"})
    domain.record_session({**w1, "state": "unknown"}, {})
    row = domain._session_row("test-team", "codex")
    assert row["state"] == "unknown" and row["session_id"] == "s1"


def test_unsupported_resume_adapter_never_stores_or_resumes(domain):
    domain.config.team.workers["codex"].execution_scope = "separate_managed_session"
    domain.config.agents["codex"] = AgentConfig(kind="opencode_acp")
    shared = domain.delegate("local", work())
    domain.record_session(
        {**shared, "state": "completed"}, {"session_id": "s1", "adapter": "opencode_acp"}
    )
    assert domain.session("codex", session_request())["session"] is None
    assert domain.resume_session(shared) is None


def test_authorize_execution_rejects_a_changed_adapter_after_claim(domain):
    import json as _json

    domain.config.team.workers["codex"].execution_scope = "separate_managed_session"
    shared = domain.delegate("local", work(idempotency_key="w-sealed"))
    domain.record_session(
        {**shared, "state": "completed"}, {"session_id": "s1", "adapter": "codex"}
    )
    task_id = "team-" + shared["id"]
    domain.store.db.execute(
        "UPDATE team_work SET core_task_id=?, resume_session=? WHERE id=?",
        (task_id, "s1", shared["id"]),
    )
    now = time.time()
    domain.store.db.execute(
        "INSERT INTO tasks(id,principal,idem,request_hash,operation,args,state,created,updated,"
        "attempt) VALUES(?,?,?,?,?,?,?,?,?,1)",
        (
            task_id,
            "codex",
            task_id,
            "sealed-request-hash",
            "agent.execute",
            _json.dumps(
                {
                    "agent": "codex",
                    "prompt": "fixture",
                    "cwd": str(domain.config.team.workers["codex"].cwd),
                    "timeout": 2,
                    "resume_session": "s1",
                }
            ),
            "queued",
            now,
            now,
        ),
    )
    # The adapter changes between the sealed claim and the actual execution.
    domain.config.agents["codex"] = AgentConfig(kind="grok_acp")
    with pytest.raises(BridgeError) as error:
        domain.authorize_execution(domain.store.get(task_id, "codex"))
    assert error.value.code == "team_task_conflict"
