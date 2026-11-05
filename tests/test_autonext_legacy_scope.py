"""Original session/progress pins bound scope only; UNKNOWN effects remain unknown."""
# Imported fixtures are used through pytest dependency injection.
# ruff: noqa: F811

import hashlib
import json
from pathlib import Path
from urllib.parse import quote

import pytest
from pydantic import ValidationError
from test_autonext import scenario, until  # noqa: F401
from test_mcp import http_bridge  # noqa: F401

from kirabridge.autonext import legacy_scope
from kirabridge.autonext.models import AutoNextConfig, LegacyScopePin
from kirabridge.bridge_core.models import canonical, digest
from kirabridge.message_manager import MessageSend

SESSION = "01a14b95-4787-79a3-b80a-5111ca19fe66"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def private_json(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(canonical(value))
    path.chmod(0o600)
    return sha(path.read_bytes())


@pytest.fixture
def legacy_case(scenario, monkeypatch):
    s, bridge = scenario, scenario["bridge"]
    s["grant"]([s["source"]("one")])
    home = s["root"].parent / "historical-home"
    monkeypatch.setattr(
        legacy_scope, "_provider_root", lambda recipient: home / recipient / "sessions"
    )

    def make(*, recipient="grok", overlap=False, encoded_observation=False, session_id=SESSION):
        for name, peer in (("local", recipient), (recipient, "local")):
            bridge.config.principals[name].capabilities += ["message.send", "message.read"]
            bridge.config.principals[name].message_peers = [peer]
        message = bridge.messages._send(
            "local",
            MessageSend(
                recipient=recipient,
                conversation_id="legacy-scope-" + session_id,
                idempotency_key="legacy-scope-" + session_id,
                body="Inert historical request; never replay",
                dispatch=False,
            ),
            visible_internal=True,
        )
        cwd = s["root"] if overlap else s["root"].parent / "old-agent-scope" / recipient
        cwd.mkdir(mode=0o700, parents=True, exist_ok=True)
        run_id = "channel-" + session_id
        observation = {
            "agent": recipient,
            "session_id": session_id,
            "event": "agent_thought_chunk" if recipient == "grok" else "turn.started",
        }
        old = {
            "run_id": run_id,
            "last_observation": canonical(observation) if encoded_observation else observation,
        }
        bridge.store.db.execute(
            "INSERT INTO message_jobs(message_id,state,run_id,error,evidence,finished) "
            "VALUES(?,'unknown',?,'agent_timeout',?,?)",
            (message["id"], run_id, canonical(old), 123),
        )
        bridge.messages._event(
            message["id"],
            "message.agent_progress",
            recipient,
            {
                "run_id": run_id,
                "evidence_sha256": digest(observation),
            },
        )
        binding = {
            "message_id": message["id"],
            "run_id": run_id,
            "recipient": recipient,
            "session_id": session_id,
            "observation_sha256": digest(observation),
            "cwd": str(cwd),
        }
        provider = home / recipient / "sessions"
        sources = []
        if recipient == "grok":
            folder = provider / quote(str(cwd), safe="") / session_id
            for kind, filename, value in (
                (
                    "grok_summary",
                    "summary.json",
                    {"info": {"id": session_id, "cwd": str(cwd)}, "num_messages": 3},
                ),
                (
                    "grok_context",
                    "prompt_context.json",
                    {"version": 1, "working_directory": str(cwd)},
                ),
            ):
                path = folder / filename
                sources.append(
                    {"kind": kind, "path": str(path), "sha256": private_json(path, value)}
                )
        else:
            path = (
                provider / "2026/10/19" / ("rollout-2026-10-19T21-24-12-" + session_id + ".jsonl")
            )
            raw = {
                "type": "session_meta",
                "payload": {"id": session_id, "session_id": session_id, "cwd": str(cwd)},
            }
            sources.append(
                {"kind": "codex_rollout", "path": str(path), "sha256": private_json(path, raw)}
            )
        attestation = {"schema_version": 1, "binding": binding, "sources": sources}
        path = s["root"].parent / "private-attestations" / (session_id + ".json")
        pin = LegacyScopePin(
            **binding,
            attestation_path=str(path),
            attestation_sha256=private_json(path, attestation),
        )
        bridge.config.autonext.legacy_scope_pins = [pin]
        return {
            "s": s,
            "b": bridge,
            "message_id": message["id"],
            "pin": pin,
            "attestation": attestation,
            "path": path,
            "sources": sources,
        }

    return make


def unchanged_history(b):
    return {
        table: [tuple(r) for r in b.store.db.execute("SELECT * FROM " + table)]
        for table in (
            "message_jobs",
            "messages",
            "message_events",
            "audit",
        )
    }


def resolve(case):
    b = case["b"]
    row = b.store.db.execute(
        "SELECT j.*,m.recipient FROM message_jobs j JOIN messages m ON m.id=j.message_id "
        "WHERE j.message_id=?",
        (case["message_id"],),
    ).fetchone()
    return legacy_scope.legacy_scope_for_job(b.config.autonext, row, b.store.db)


@pytest.mark.parametrize("recipient,encoded", [("grok", True), ("grok", False), ("codex", False)])
async def test_historical_scope_proof_allows_only_disjoint_new_work_without_rewriting_unknown(
    legacy_case, recipient, encoded
):
    case = legacy_case(recipient=recipient, encoded_observation=encoded)
    b, s = case["b"], case["s"]
    before = unchanged_history(b)
    assert resolve(case) == case["pin"].cwd
    assert resolve(case) == case["pin"].cwd
    assert unchanged_history(b) == before
    await s["start"]()
    await until(lambda: b.autonext.inspect()["state"] == "complete")
    assert [c["task_id"] for c in s["calls"]()] == ["one"]
    for table in ("message_jobs", "messages", "message_events"):
        assert [tuple(r) for r in b.store.db.execute("SELECT * FROM " + table)] == before[table]
    assert [tuple(r) for r in b.store.db.execute("SELECT * FROM audit")][
        : len(before["audit"])
    ] == before["audit"]
    assert b.store.db.execute("SELECT state FROM message_jobs").fetchone()[0] == "unknown"


async def test_proven_historical_scope_still_blocks_overlapping_work(legacy_case):
    case = legacy_case(overlap=True)
    b, s = case["b"], case["s"]
    await b.autonext.tick()
    assert b.autonext.inspect()["reason"] == "autonext_worktree_busy"
    assert s["calls"]() == []


async def test_all_seven_original_metadata_shapes_reserve_only_their_proven_scopes(legacy_case):
    # Historical inventory: six Grok sessions, one Codex rollout; first two
    # receiver observations were persisted as JSON strings instead of objects.
    cases = [
        legacy_case(
            recipient="codex" if i == 3 else "grok",
            encoded_observation=i < 2,
            session_id=f"01a14b95-4787-79a3-b80a-{i:012x}",
        )
        for i in range(7)
    ]
    b, s = cases[0]["b"], cases[0]["s"]
    pins = [case["pin"] for case in cases]
    AutoNextConfig(legacy_scope_pins=pins)  # Exact uniqueness contract at config load.
    b.config.autonext.legacy_scope_pins = pins
    before = unchanged_history(b)
    assert [resolve(case) for case in cases] == [pin.cwd for pin in pins]
    assert unchanged_history(b) == before
    await s["start"]()
    await until(lambda: b.autonext.inspect()["state"] == "complete")
    assert [c["task_id"] for c in s["calls"]()] == ["one"]
    for table in ("message_jobs", "messages", "message_events"):
        assert [tuple(r) for r in b.store.db.execute("SELECT * FROM " + table)] == before[table]
    assert (
        b.store.db.execute("SELECT count(*) FROM message_jobs WHERE state='unknown'").fetchone()[0]
        == 7
    )
    assert [tuple(r) for r in b.store.db.execute("SELECT * FROM audit")][
        : len(before["audit"])
    ] == before["audit"]


@pytest.mark.parametrize(
    "fault",
    [
        "default_empty",
        "wrong_run",
        "wrong_recipient",
        "wrong_session",
        "wrong_observation",
        "missing_progress",
        "wrong_progress_run",
        "wrong_progress_hash",
        "running",
        "other_error",
        "attestation_hash",
        "attestation_changed",
        "source_changed",
        "source_unprivate",
        "attestation_unprivate",
        "source_symlink",
        "attestation_symlink",
        "missing_source",
        "changed_metadata_scope",
        "changed_metadata_session",
        "changed_attestation_binding",
        "extra_attestation_field",
        "bool_attestation_version",
        "duplicate_source_kind",
        "ambiguous_runtime_pin",
    ],
)
async def test_missing_changed_or_ambiguous_proof_stops_without_replay(legacy_case, fault):
    case = legacy_case()
    b, s, pin = case["b"], case["s"], case["pin"]
    db = b.store.db
    rewrite_attestation = False
    if fault == "default_empty":
        b.config.autonext.legacy_scope_pins = []
    elif fault == "wrong_run":
        db.execute("UPDATE message_jobs SET run_id='different'")
    elif fault == "wrong_recipient":
        db.execute("UPDATE messages SET recipient='codex'")
    elif fault in {"wrong_session", "wrong_observation", "attestation_hash"}:
        key = {
            "wrong_session": "session_id",
            "wrong_observation": "observation_sha256",
            "attestation_hash": "attestation_sha256",
        }[fault]
        value = "01a14b95-4787-79a3-b80a-5111ca19fe67" if key == "session_id" else "0" * 64
        b.config.autonext.legacy_scope_pins = [pin.model_copy(update={key: value})]
    elif fault.startswith("wrong_progress") or fault == "missing_progress":
        if fault == "missing_progress":
            db.execute("DELETE FROM message_events WHERE kind='message.agent_progress'")
        else:
            e = {"run_id": pin.run_id, "evidence_sha256": pin.observation_sha256}
            e["run_id" if fault == "wrong_progress_run" else "evidence_sha256"] = "different"
            db.execute(
                "UPDATE message_events SET evidence=? WHERE kind='message.agent_progress'",
                (canonical(e),),
            )
    elif fault in {"running", "other_error"}:
        db.execute(
            "UPDATE message_jobs SET "
            + ("state='running'" if fault == "running" else "error='visible_reply_unknown'")
        )
    elif fault in {"source_changed", "attestation_changed"}:
        path = Path(case["sources"][0]["path"]) if fault == "source_changed" else case["path"]
        path.write_bytes(path.read_bytes() + b" ")
    elif fault in {"source_unprivate", "attestation_unprivate"}:
        path = Path(case["sources"][0]["path"]) if fault == "source_unprivate" else case["path"]
        path.chmod(0o644)
    elif fault in {"source_symlink", "attestation_symlink"}:
        path = Path(case["sources"][0]["path"]) if fault == "source_symlink" else case["path"]
        target = path.with_name("original-private.json")
        path.rename(target)
        path.symlink_to(target)
    elif fault == "missing_source":
        Path(case["sources"][0]["path"]).unlink()
    elif fault in {"changed_metadata_scope", "changed_metadata_session"}:
        source = case["sources"][0]
        value = json.loads(Path(source["path"]).read_text())
        value["info"]["cwd" if fault == "changed_metadata_scope" else "id"] = "different"
        source["sha256"] = private_json(Path(source["path"]), value)
        rewrite_attestation = True
    elif fault == "changed_attestation_binding":
        case["attestation"]["binding"]["cwd"] = str(s["root"])
        rewrite_attestation = True
    elif fault == "extra_attestation_field":
        case["attestation"]["operator_says_safe"] = True
        rewrite_attestation = True
    elif fault == "bool_attestation_version":
        case["attestation"]["schema_version"] = True
        rewrite_attestation = True
    elif fault == "duplicate_source_kind":
        case["attestation"]["sources"][1] = case["sources"][0].copy()
        rewrite_attestation = True
    elif fault == "ambiguous_runtime_pin":
        b.config.autonext.legacy_scope_pins = [pin, pin]
    if rewrite_attestation:
        b.config.autonext.legacy_scope_pins = [
            pin.model_copy(
                update={
                    "attestation_sha256": private_json(case["path"], case["attestation"]),
                }
            )
        ]
    before = unchanged_history(b)
    await b.autonext.tick()
    assert b.autonext.inspect()["reason"] == "autonext_scope_unknown"
    assert s["calls"]() == []
    for table in ("message_jobs", "messages", "message_events"):
        assert [tuple(r) for r in db.execute("SELECT * FROM " + table)] == before[table]


@pytest.mark.parametrize("duplicate", ["message_id", "run_id", "session_id"])
def test_scope_pin_schema_rejects_ambiguous_ids_even_when_disabled(legacy_case, duplicate):
    pin = legacy_case()["pin"]
    other = pin.model_copy(
        update={
            "message_id": "other-message",
            "run_id": "other-run",
            "session_id": "01a14b95-4787-79a3-b80a-5111ca19fe67",
        }
    )
    other = other.model_copy(update={duplicate: getattr(pin, duplicate)})
    with pytest.raises(ValidationError):
        AutoNextConfig(legacy_scope_pins=[pin, other])


@pytest.mark.parametrize(
    "field,value", [("cwd", "relative"), ("attestation_path", "relative"), ("extra", True)]
)
def test_scope_pin_rejects_relative_or_unknown_fields(legacy_case, field, value):
    pin = legacy_case()["pin"].model_dump()
    pin[field] = value
    with pytest.raises(ValidationError):
        LegacyScopePin.model_validate(pin)


def repin_attestation(case):
    pin = case["pin"].model_copy(
        update={
            "attestation_sha256": private_json(case["path"], case["attestation"]),
        }
    )
    case["b"].config.autonext.legacy_scope_pins = [pin]


@pytest.mark.parametrize(
    "field,value", [("id", "different"), ("cwd", "/different"), ("type", "event_msg")]
)
async def test_codex_metadata_identity_is_checked_after_all_hashes_match(legacy_case, field, value):
    case = legacy_case(recipient="codex")
    source = case["sources"][0]
    document = json.loads(Path(source["path"]).read_text())
    if field == "type":
        document["type"] = value
    else:
        document["payload"][field] = value
    source["sha256"] = private_json(Path(source["path"]), document)
    repin_attestation(case)
    await case["b"].autonext.tick()
    assert case["b"].autonext.inspect()["reason"] == "autonext_scope_unknown"
    assert case["s"]["calls"]() == []


async def test_owned_files_cannot_be_replaced_by_another_users_proof(legacy_case, monkeypatch):
    case = legacy_case()
    actual = legacy_scope.os.getuid()
    with monkeypatch.context() as scoped:
        scoped.setattr(legacy_scope.os, "getuid", lambda: actual + 1)
        await case["b"].autonext.tick()
    assert case["b"].autonext.inspect()["reason"] == "autonext_scope_unknown"
    assert case["s"]["calls"]() == []


async def test_attestation_size_bound_cannot_be_evaded_by_a_matching_hash(legacy_case):
    case = legacy_case()
    raw = b" " * (legacy_scope.MAX_ATTESTATION_BYTES + 1)
    case["path"].write_bytes(raw)
    case["b"].config.autonext.legacy_scope_pins = [
        case["pin"].model_copy(
            update={
                "attestation_sha256": sha(raw),
            }
        )
    ]
    await case["b"].autonext.tick()
    assert case["b"].autonext.inspect()["reason"] == "autonext_scope_unknown"


async def test_duplicate_attestation_fields_are_not_operator_evidence(legacy_case):
    case = legacy_case()
    raw = b'{"schema_version":1,' + canonical(case["attestation"]).encode()[1:]
    case["path"].write_bytes(raw)
    case["b"].config.autonext.legacy_scope_pins = [
        case["pin"].model_copy(
            update={
                "attestation_sha256": sha(raw),
            }
        )
    ]
    await case["b"].autonext.tick()
    assert case["b"].autonext.inspect()["reason"] == "autonext_scope_unknown"


async def test_existing_persisted_scope_cannot_be_overridden_by_historical_pin(legacy_case):
    case = legacy_case()
    case["b"].store.db.execute("UPDATE message_jobs SET execution_cwd=?", (str(case["s"]["root"]),))
    await case["b"].autonext.tick()
    assert case["b"].autonext.inspect()["reason"] == "autonext_worktree_busy"
    assert case["s"]["calls"]() == []


async def test_historical_evidence_is_rechecked_before_actual_executor_start(legacy_case):
    case = legacy_case()
    b, s = case["b"], case["s"]
    await b.autonext.tick()
    assert b.store.db.execute("SELECT count(*) FROM autonext_items").fetchone()[0] == 1
    path = Path(case["sources"][0]["path"])
    path.write_bytes(path.read_bytes() + b" ")
    await s["start"]()
    await until(lambda: b.autonext.inspect()["state"] == "stopped")
    assert s["calls"]() == []
    assert b.store.db.execute("SELECT state FROM message_jobs").fetchone()[0] == "unknown"
    core = b.store.db.execute("SELECT error FROM tasks WHERE operation='agent.execute'").fetchone()
    assert json.loads(core[0])["code"] == "autonext_scope_unknown"
