"""Actual private dispatcher/CLI receipts; no provider or productive state."""

import json
import sys

import pytest
from pydantic import ValidationError
from test_agents import fake_cli
from test_autonext import scenario, until  # noqa: F401
from test_mcp import http_bridge  # noqa: F401

from kirabridge.autonext.coordinator import CoordinatedAutoNext
from kirabridge.autonext.manager import AutoNextManager, text_sha
from kirabridge.autonext.models import Acceptance, AutoNextConfig, ReadyCard
from kirabridge.bridge_core.config import AgentConfig
from kirabridge.team_manager.models import TeamRoleSet
from kirabridge.whiteboard_read import append_whiteboard

CODEX = """import json,sys
prompt=sys.stdin.read(); data=json.loads(prompt.split("\\n",1)[1])
result="DONE:"+data["task_id"]
if "source_sha256" in data:
 result=json.dumps({"verdict":"pass","source_sha256":data["source_sha256"],
                    "summary":"fixture verified"})
# VERDICT_TRANSFORM
answer={"kirabridge_team":"1","result":result,"actions":[]}
for event in [{"type":"thread.started","thread_id":"fixture-coordinator"},
 {"type":"turn.started"},
 {"type":"item.completed","item":{"type":"agent_message","text":json.dumps(answer)}},
 {"type":"turn.completed"}]:print(json.dumps(event),flush=True)
"""
GROK = """import json,sys
for line in sys.stdin:
 msg=json.loads(line); method=msg.get("method")
 if method=="initialize": result={"protocolVersion":1,"authMethods":[{"id":"cached_token"}]}
 elif method=="authenticate": result={}
 elif method=="session/new": result={"sessionId":"fixture-review"}
 elif method=="session/prompt":
  prompt=msg["params"]["prompt"][0]["text"]; data=json.loads(prompt.split("\\n",1)[1])
  verdict={"verdict":"pass","source_sha256":data["source_sha256"],"summary":"fixture"}
  answer={"kirabridge_team":"1","actions":[],"result":json.dumps(verdict)}
  params={"sessionId":"fixture-review","update":{"sessionUpdate":"agent_message_chunk","content":{"type":"text","text":json.dumps(answer)}}}
  print(json.dumps({"jsonrpc":"2.0","method":"session/update","params":params}),flush=True)
  result={"stopReason":"end_turn"}
 else: continue
 print(json.dumps({"jsonrpc":"2.0","id":msg["id"],"result":result}),flush=True)
"""


def configure(
    s,
    tmp_path,
    monkeypatch,
    *,
    grok=False,
    exit_code=0,
    verdict="pass",
    review_files=None,
    main_mode="read-only",
):
    bridge, config = s["bridge"], s["config"]
    write_fixture = (
        'if "source_sha256" not in data and data.get("sandbox")=="workspace-write":\n'
        " import pathlib\n"
        ' for path in data["acceptance"].get("review_files",[]):\n'
        '  pathlib.Path(data["cwd"],path).write_text("controller artifact fixture")\n'
    )
    codex_body = CODEX.replace("# VERDICT_TRANSFORM", write_fixture + "# VERDICT_TRANSFORM")
    codex_body = codex_body.replace('verdict":"pass', 'verdict":"' + verdict)
    if verdict == "duplicate":
        codex_body = CODEX.replace(
            "# VERDICT_TRANSFORM",
            'if "source_sha256" in data:\n result = result[:-1] + \',"verdict":"pass"}\'',
        )
    for name, body, kind in [
        ("codex", codex_body, "codex"),
        ("grok", GROK, "grok_acp"),
    ]:
        directory = tmp_path / ("coordinator-" + name)
        directory.mkdir()
        config.agents[name] = AgentConfig(
            kind=kind,
            executable=fake_cli(directory, body),
            api_key_env="UNSET_COORDINATOR_API_KEY",
            sandbox_mode=main_mode if name == "codex" else "read-only",
        )
        config.team.workers[name].execution_scope = "separate_managed_session"
    config.agents["codex_verify"] = config.agents["codex"].model_copy(
        update={"sandbox_mode": "read-only"}, deep=True
    )
    config.team.workers["codex_verify"] = config.team.workers["codex"].model_copy(
        update={"agent": "codex_verify"}, deep=True
    )
    config.principals["codex_verify"] = config.principals["codex"].model_copy(
        update={"agents": ["codex_verify"], "token_env": "TEAM_VERIFY_TEST_TOKEN"}, deep=True
    )
    monkeypatch.setenv("TEAM_VERIFY_TEST_TOKEN", "verify-fixture-" + "v" * 40)
    bridge.teams.set_role(
        "local",
        TeamRoleSet(
            team_id="auto-team",
            member="codex_verify",
            role="reviewer",
            expected_revision=bridge.teams.get("local", "auto-team")["revision"],
            idempotency_key="verifier-member",
        ),
    )
    bridge.teams.set_role(
        "local",
        TeamRoleSet(
            team_id="auto-team",
            member="codex",
            role="coordinator",
            expected_revision=bridge.teams.get("local", "auto-team")["revision"],
            idempotency_key="codex-coordinator",
        ),
    )
    card = {
        "autonext": 1,
        "task_id": "coordinated-one",
        "state": "READY",
        "product": "KiraBridge",
        "cwd": str(s["root"]),
        "sandbox": main_mode,
        "title": "Read only fixture",
        "instruction": "Inspect fixture only",
        "acceptance": {
            "kind": "coordinator_checks",
            "review_with_grok": grok,
            "review_files": review_files or [],
            "checks": [
                {
                    "argv": [sys.executable, "-c", f"raise SystemExit({exit_code})"],
                    "timeout_seconds": 2,
                }
            ],
        },
    }
    content = json.dumps(card)
    entry = append_whiteboard(
        str(s["desk"]),
        "board",
        actor="operator",
        actor_type="human",
        entry_type="task",
        content=content,
        external_key="coordinator-card",
    )
    s["grant"](
        [{"task_id": card["task_id"], "entry_id": entry["id"], "content_sha256": text_sha(content)}]
    )
    config.autonext.principal = "codex"
    config.autonext.coordinator_mode = True
    config.autonext.lease_seconds = 60
    bridge.autonext = CoordinatedAutoNext(bridge)
    return card


@pytest.mark.parametrize("grok", [False, True])
async def test_codex_grok_codex_checks_reuse_existing_claim(scenario, tmp_path, grok, monkeypatch):  # noqa: F811
    s = scenario
    card = configure(s, tmp_path, monkeypatch, grok=grok)
    bridge = s["bridge"]
    await s["start"]()
    await until(lambda: bridge.autonext.inspect()["state"] in {"complete", "stopped"})
    assert bridge.autonext.inspect()["state"] == "complete", bridge.autonext.inspect()
    receipt = bridge.autonext.receipt("codex", card["task_id"])
    assert receipt["acceptance"] == "coordinator_checks"
    proof = receipt["coordinator"]
    assert proof["verify_work_id"]
    assert bool(proof["grok_work_id"]) is grok
    assert proof["checks"]["passed"] is True
    assert bridge.store.db.execute("SELECT count(*) FROM autonext_items").fetchone()[0] == 1
    assert bridge.store.db.execute("SELECT count(*) FROM autonext_confirmations").fetchone()[0] == 0
    count = bridge.store.db.execute("SELECT count(*) FROM team_work").fetchone()[0]
    await bridge.autonext.stop()
    bridge.autonext = CoordinatedAutoNext(bridge)
    await bridge.autonext.tick()
    assert bridge.store.db.execute("SELECT count(*) FROM team_work").fetchone()[0] == count


async def test_failed_pinned_check_stops_and_does_not_forge_receipt(
    scenario,  # noqa: F811
    tmp_path,
    monkeypatch,
):  # noqa: F811
    s = scenario
    card = configure(s, tmp_path, monkeypatch, exit_code=7)
    bridge = s["bridge"]
    await s["start"]()
    await until(lambda: bridge.autonext.inspect()["state"] == "stopped")
    assert bridge.autonext.inspect()["reason"] == "autonext_check_failed"
    assert bridge.autonext.receipt("codex", card["task_id"]) is None
    row = bridge.store.db.execute("SELECT checks_result FROM autonext_coordinator").fetchone()
    assert json.loads(row["checks_result"])["checks"][0]["exit_code"] == 7


def test_opt_in_checks_and_identity_are_explicit():
    with pytest.raises(ValidationError):
        AutoNextConfig(principal="codex", enabled=True)
    with pytest.raises(ValidationError):
        AutoNextConfig(principal="local", coordinator_mode=True)
    with pytest.raises(ValidationError):
        Acceptance(kind="coordinator_checks")
    with pytest.raises(ValidationError):
        Acceptance(kind="coordinator_checks", checks=[{"argv": ["relative-command"]}])
    with pytest.raises(ValidationError):
        Acceptance(kind="operator_receipt", checks=[{"argv": [sys.executable]}])


async def test_rejected_verdict_never_runs_pinned_checks(scenario, tmp_path, monkeypatch):  # noqa: F811
    s = scenario
    card = configure(s, tmp_path, monkeypatch, verdict="fail")
    bridge = s["bridge"]
    await s["start"]()
    await until(lambda: bridge.autonext.inspect()["state"] == "stopped")
    assert bridge.autonext.inspect()["reason"] == "autonext_review_rejected"
    assert bridge.autonext.receipt("codex", card["task_id"]) is None
    row = bridge.store.db.execute("SELECT checks_state FROM autonext_coordinator").fetchone()
    assert row["checks_state"] == "not_started"


async def test_interrupted_check_is_unknown_and_never_replayed(scenario, tmp_path, monkeypatch):  # noqa: F811
    import asyncio

    s = scenario
    card = configure(s, tmp_path, monkeypatch)
    bridge = s["bridge"]
    invocations = []

    async def slow_check(card):
        invocations.append(card.task_id)
        await asyncio.sleep(0.5)
        return {"passed": True, "checks": []}

    monkeypatch.setattr(bridge.autonext, "_run_checks", slow_check)
    await s["start"]()
    await until(
        lambda: bridge.store.db.execute(
            "SELECT 1 FROM autonext_coordinator WHERE checks_state='running'"
        ).fetchone()
    )
    await bridge.autonext.stop()
    bridge.autonext = CoordinatedAutoNext(bridge)
    await bridge.autonext.tick()
    assert bridge.autonext.inspect()["reason"] == "autonext_check_unknown"
    assert bridge.autonext.receipt("codex", card["task_id"]) is None
    assert invocations == [card["task_id"]]


async def test_duplicate_review_keys_rejected(scenario, tmp_path, monkeypatch):  # noqa: F811
    s = scenario
    configure(s, tmp_path, monkeypatch, verdict="duplicate")
    bridge = s["bridge"]
    await s["start"]()
    await until(lambda: bridge.autonext.inspect()["state"] == "stopped")
    assert bridge.autonext.inspect()["reason"] == "autonext_review_rejected"


async def test_check_timeout_reaps_its_child_process(tmp_path):
    import os

    pid_path = tmp_path / "child.pid"
    script = (
        "import subprocess,sys,time,pathlib; "
        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
        f"pathlib.Path({str(pid_path)!r}).write_text(str(p.pid)); time.sleep(30)"
    )
    card = ReadyCard.model_validate(
        {
            "autonext": 1,
            "task_id": "timeout",
            "state": "READY",
            "product": "KiraBridge",
            "cwd": str(tmp_path),
            "title": "timeout",
            "instruction": "fixture",
            "acceptance": {
                "kind": "coordinator_checks",
                "checks": [{"argv": [sys.executable, "-c", script], "timeout_seconds": 0.5}],
            },
        }
    )
    result = await CoordinatedAutoNext._run_checks(card)
    assert result["passed"] is False
    assert result["reason"] == "TimeoutError"
    child = int(pid_path.read_text())
    try:
        os.kill(child, 0)
    except ProcessLookupError:
        return
    # Some hosts retain a reaped orphan briefly as a zombie, which cannot execute.
    import asyncio
    import subprocess

    probe = await asyncio.to_thread(
        subprocess.run,
        ["/bin/ps", "-p", str(child), "-o", "stat="],
        capture_output=True,
        text=True,
        check=False,
    )
    status = probe.stdout.strip()
    assert not status or status.startswith("Z")


@pytest.mark.parametrize("api_env", ["XAI_API_KEY", "COORDINATOR_GROK_API_KEY"])
async def test_grok_api_billing_refused_before_claim(scenario, tmp_path, monkeypatch, api_env):  # noqa: F811
    s = scenario
    configure(s, tmp_path, monkeypatch, grok=True)
    s["config"].agents["grok"].api_key_env = "COORDINATOR_GROK_API_KEY"
    monkeypatch.setenv(api_env, "fixture-key-must-not-be-used")
    await s["bridge"].autonext.tick()
    assert s["bridge"].autonext.inspect()["reason"] == "autonext_billing_unknown"
    assert s["bridge"].store.db.execute("SELECT count(*) FROM autonext_items").fetchone()[0] == 0


async def test_codex_must_be_actual_coordinator(scenario, tmp_path, monkeypatch):  # noqa: F811
    s = scenario
    configure(s, tmp_path, monkeypatch)
    bridge = s["bridge"]
    team = bridge.teams.set_role(
        "local",
        TeamRoleSet(
            team_id="auto-team",
            member="local",
            role="coordinator",
            expected_revision=bridge.teams.get("local", "auto-team")["revision"],
            idempotency_key="restore-local-coordinator",
        ),
    )
    s["config"].autonext.team_revision = team["revision"]
    await bridge.autonext.tick()
    assert bridge.autonext.inspect()["reason"] == "autonext_coordinator_required"
    assert bridge.store.db.execute("SELECT count(*) FROM autonext_items").fetchone()[0] == 0


async def test_base_manager_rejects_coordinator_card_before_execution(
    scenario,  # noqa: F811
    tmp_path,
    monkeypatch,
):
    s = scenario
    configure(s, tmp_path, monkeypatch)
    bridge = s["bridge"]
    bridge.autonext = AutoNextManager(bridge)
    await bridge.autonext.tick()
    assert bridge.autonext.inspect()["reason"] == "autonext_coordinator_required"
    assert bridge.store.db.execute("SELECT count(*) FROM autonext_items").fetchone()[0] == 0


async def test_writing_main_turn_has_shared_persistent_artifact_evidence(
    scenario,  # noqa: F811
    tmp_path,
    monkeypatch,
):
    import hashlib

    s = scenario
    card = configure(
        s,
        tmp_path,
        monkeypatch,
        grok=True,
        review_files=["result.txt"],
        main_mode="workspace-write",
    )
    bridge = s["bridge"]
    await s["start"]()
    await until(lambda: bridge.autonext.inspect()["state"] in {"complete", "stopped"})
    assert bridge.autonext.inspect()["state"] == "complete", bridge.autonext.inspect()
    receipt = bridge.autonext.receipt("codex", card["task_id"])["coordinator"]
    expected = hashlib.sha256(b"controller artifact fixture").hexdigest()
    assert receipt["artifacts"] == [{"path": "result.txt", "sha256": expected}]
    snapshots = []
    for work_id in (receipt["grok_work_id"], receipt["verify_work_id"]):
        work = bridge.teams.work_get("codex", "auto-team", work_id)
        core = bridge.store.get(work["core_task_id"])
        context = json.loads(core["args"]["prompt"].split("\n", 1)[1])
        snapshots.append(context["source_artifacts"])
        assert context["source_execution"]["native_success"] is True
        assert context["source_execution"]["native_sandbox_mode"] == "workspace-write"
    assert (
        snapshots[0]
        == snapshots[1]
        == [{"path": "result.txt", "sha256": expected, "content": "controller artifact fixture"}]
    )


async def test_review_artifact_mutation_stops_before_acceptance(
    scenario,  # noqa: F811
    tmp_path,
    monkeypatch,
):
    s = scenario
    configure(s, tmp_path, monkeypatch, review_files=["result.txt"])
    artifact = s["root"] / "result.txt"
    artifact.write_text("first snapshot")
    bridge = s["bridge"]
    await s["start"]()
    await until(
        lambda: bridge.store.db.execute(
            "SELECT 1 FROM autonext_coordinator WHERE review_artifacts IS NOT NULL"
        ).fetchone()
    )
    artifact.write_text("changed after snapshot")
    await until(lambda: bridge.autonext.inspect()["state"] == "stopped")
    assert bridge.autonext.inspect()["reason"] == "autonext_review_artifacts_changed"
    saved = json.loads(
        bridge.store.db.execute("SELECT review_artifacts FROM autonext_coordinator").fetchone()[0]
    )
    assert saved["files"][0]["content"] == "first snapshot"


def artifact_card(tmp_path, paths):
    return ReadyCard.model_validate(
        {
            "autonext": 1,
            "task_id": "artifact-read",
            "state": "READY",
            "product": "KiraBridge",
            "cwd": str(tmp_path),
            "title": "artifact",
            "instruction": "fixture",
            "acceptance": {
                "kind": "coordinator_checks",
                "checks": [{"argv": [sys.executable]}],
                "review_files": paths,
            },
        }
    )


@pytest.mark.parametrize(
    "path",
    [
        "../outside",
        "/absolute",
        ".env",
        ".env.local",
        "auth.json",
        "credentials.json",
        ".credentials",
        "Keys/keyfile",
        "secret.key",
        "a/../b",
    ],
)
def test_review_paths_reject_traversal_and_secrets(tmp_path, path):
    with pytest.raises(ValidationError):
        artifact_card(tmp_path, [path])


@pytest.mark.parametrize("unsafe", ["symlink", "too_large", "binary", "combined"])
def test_artifact_reads_are_bounded_and_do_not_follow_symlinks(tmp_path, unsafe):
    from kirabridge.bridge_core.models import BridgeError

    path = tmp_path / "artifact.txt"
    paths = [path.name]
    if unsafe == "symlink":
        outside = tmp_path.parent / "outside-review-artifact"
        outside.write_text("must not copy")
        path.symlink_to(outside)
    elif unsafe == "too_large":
        path.write_text("x" * 8193)
    elif unsafe == "binary":
        path.write_bytes(b"binary\x00data")
    else:
        paths = [f"artifact-{n}.txt" for n in range(5)]
        for name in paths:
            (tmp_path / name).write_text("x" * 8192)
    with pytest.raises(BridgeError) as error:
        CoordinatedAutoNext._capture_artifacts(artifact_card(tmp_path, paths))
    assert error.value.code == "autonext_review_artifacts_invalid"


def test_artifact_column_is_additively_migrated(tmp_path):
    from types import SimpleNamespace

    from kirabridge.task_manager.store import Store

    store = Store(tmp_path / "migration.sqlite3")
    bridge = SimpleNamespace(store=store)
    try:
        AutoNextManager(bridge)
        store.db.execute(
            "CREATE TABLE autonext_coordinator (task_id TEXT PRIMARY KEY, "
            "source_sha TEXT NOT NULL, grok_work_id TEXT, verify_work_id TEXT, "
            "checks_state TEXT, checks_result TEXT)"
        )
        store.db.execute(
            "INSERT INTO autonext_coordinator VALUES('old','old-hash',NULL,NULL,'running',NULL)"
        )
        CoordinatedAutoNext(bridge)
        row = store.db.execute("SELECT * FROM autonext_coordinator").fetchone()
        assert row["source_sha"] == "old-hash" and row["checks_state"] == "running"
        assert row["review_artifacts"] is None
    finally:
        store.close()
