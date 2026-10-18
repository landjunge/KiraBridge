"""Scoped existing-Store export; synthetic isolated state, no actual agent/tunnel."""

from __future__ import annotations

import importlib
import json
import os
import runpy
import sqlite3
import sys
from pathlib import Path

import pytest
from conftest import request, submit

from kirabridge.bridge_core.models import BridgeError, State, canonical
from kirabridge.observation_export import (
    EVENT_SCHEMA,
    MAX_PAGE_BYTES,
    export_configured_observations,
    export_workflow_observations,
)

SECRET = "DO_NOT_EXPORT_PRIVATE_DATA"


def queued(bridge, identity="owned-task", principal="local"):
    submit(bridge, request(arguments={"path": SECRET}, task_id=identity), principal=principal)


def audit(bridge, kind, metadata, task_id="owned-task", principal="local"):
    with bridge.store.transaction():
        bridge.store.audit(kind, principal, task_id, metadata)


def completed(bridge, identity="owned-task"):
    queued(bridge, identity)
    bridge.store.claim("synthetic-owner", 30)
    audit(
        bridge,
        "task.preflight",
        {
            "runtime": {
                "instance_id": "historical-instance",
                "version": "0.6.0rc2",
                "source_tree_sha256": "a" * 64,
                "config_sha256": "b" * 64,
                "config_path": "/" + SECRET,
                "environment": SECRET,
            },
            "checks": [{"path": "/" + SECRET}],
            "ready": True,
        },
        identity,
    )
    bridge.store.transition(identity, State.RUNNING, {"private": SECRET})
    bridge.store.transition(
        identity,
        State.COMPLETED,
        {"private": SECRET},
        result={"private": SECRET},
        error={"private": SECRET},
    )


def read(bridge, **changes):
    return export_workflow_observations(bridge, "local", task_ids=["owned-task"], **changes)


def test_existing_historical_states_and_runtime_not_current_reader_and_no_sensitive_columns(
    bridge, monkeypatch
):
    completed(bridge)
    bridge.runtime = {"instance_id": "NEW_READER", "source_tree_sha256": "c" * 64}
    original_connect = sqlite3.connect
    queries = []

    def connect(*args, **kwargs):
        assert kwargs["uri"] and args[0].endswith("?mode=ro")
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(queries.append)
        return connection

    monkeypatch.setattr("kirabridge.observation_export.sqlite3.connect", connect)
    before = {
        table: bridge.store.db.execute("SELECT count(*) FROM " + table).fetchone()[0]
        for table in ["tasks", "events", "audit", "approvals", "message_jobs"]
    }
    value = read(bridge)
    assert [e["event_type"] for e in value["events"]] == [
        "task.accepted",
        "task.running",
        "task.completed",
    ]
    assert "reported_status" not in value["events"][-1]  # file task is no agent turn
    assert not value["project_completion_verified"] and not value["rights_granted"]
    assert value["provenance"][0]["execution_runtime"]["basis"] == "unknown_no_prior_task_preflight"
    runtime = value["provenance"][-1]["execution_runtime"]
    assert runtime["fingerprints"]["instance_id"] == "historical-instance"
    assert runtime["fingerprints"]["source_tree_sha256"] == "a" * 64
    assert SECRET not in canonical(value) and "NEW_READER" not in canonical(value)
    assert "config_path" not in canonical(value) and "environment" not in canonical(value)
    assert value["coverage"]["external_tunnel"] == "unknown"
    assert "project_id" not in value["events"][-1] and "workflow_id" not in value["events"][-1]
    assert "PRAGMA query_only=ON" in queries
    assert not any("SELECT *" in q or "result" in q or "args" in q or "error" in q for q in queries)
    assert before == {
        table: bridge.store.db.execute("SELECT count(*) FROM " + table).fetchone()[0]
        for table in before
    }


@pytest.mark.parametrize("principal", ["other", "missing"])
def test_foreign_or_missing_tasks_are_indistinguishable_and_emit_nothing(bridge, principal):
    queued(bridge)
    with pytest.raises(BridgeError) as failure:
        export_workflow_observations(bridge, principal, task_ids=["owned-task"])
    assert failure.value.code in {"not_found", "forbidden"}
    with pytest.raises(BridgeError) as absent:
        export_workflow_observations(bridge, "other", task_ids=["missing-task"])
    assert absent.value.code == "not_found"


def test_missing_task_read_denied_before_any_database_open(bridge, monkeypatch):
    bridge.config.principals["local"].capabilities.remove("task.read")

    def forbidden(*_, **__):
        raise AssertionError("no database lookup")

    monkeypatch.setattr("kirabridge.observation_export.sqlite3.connect", forbidden)
    with pytest.raises(BridgeError) as failure:
        read(bridge)
    assert failure.value.code == "forbidden"
    with pytest.raises(BridgeError):
        export_configured_observations(bridge.config, "local", task_ids=["owned-task"])


@pytest.mark.parametrize(
    "changes",
    [
        {"task_ids": []},
        {"task_ids": ["a"] * 2},
        {"task_ids": [str(i) for i in range(17)]},
        {"task_ids": ["td:task"]},
        {"task_ids": [True]},
        {"task_ids": "owned-task"},
        {"cursor": True},
        {"cursor": -1},
        {"cursor": 2**63},
        {"cursor": 1.0},
        {"limit": True},
        {"limit": 0},
        {"limit": 501},
        {"through_seq": True},
        {"through_seq": -1},
    ],
)
def test_strict_bounds_before_any_database_read(bridge, monkeypatch, changes):
    def forbidden(*_, **__):
        raise AssertionError("no database lookup")

    monkeypatch.setattr("kirabridge.observation_export.sqlite3.connect", forbidden)
    args = {"task_ids": ["owned-task"], **changes}
    with pytest.raises(BridgeError) as failure:
        export_workflow_observations(bridge, "local", **args)
    assert failure.value.code == "invalid_observation_request"


def test_cursor_snapshot_filter_gaps_stable_ids_and_restart_without_queue_mutation(bridge):
    completed(bridge)
    queued(bridge, "foreign-task", "other")
    audit(bridge, "task.transition", {"to": "running"}, "foreign-task", "other")
    first = read(bridge, limit=2)
    through = first["through_seq"]
    audit(bridge, "task.transition", {"to": "unknown"})
    combined = []
    page = first
    for _ in range(10):
        combined.extend(page["events"])
        if not page["has_more"]:
            break
        assert page["next_cursor"] > page["cursor"]
        page = read(bridge, cursor=page["next_cursor"], through_seq=through, limit=2)
    else:
        pytest.fail("bounded snapshot failed to terminate")
    assert [e["event_type"] for e in combined] == [
        "task.accepted",
        "task.running",
        "task.completed",
    ]
    again = export_configured_observations(
        bridge.config, "local", task_ids=["owned-task"], through_seq=through
    )
    assert again["events"] == combined
    assert all(e["event_id"].endswith(e["event_hash"]) for e in combined)
    assert "foreign-task" not in canonical(again)
    assert again["coverage"]["filtered_or_missing_sequence"]
    assert all(
        e["schema_version"] == EVENT_SCHEMA and e["source_tool"] == "kirabridge" for e in combined
    )
    assert read(bridge, cursor=through)["events"][-1]["event_type"] == "task.unknown"
    with pytest.raises(BridgeError):
        read(bridge, cursor=10**8)
    with pytest.raises(BridgeError):
        read(bridge, through_seq=10**8)


def test_current_correlations_separate_owned_and_never_overwrite_historical_metadata(bridge):
    queued(bridge)
    queued(bridge, "foreign-task", "other")
    queued(bridge, "other-owned")
    for owner, identity, first in [
        ("local", "binding-1", "owned-task"),
        ("other", "foreign-binding", "foreign-task"),
    ]:
        with bridge.store.transaction():
            bridge.store.db.execute(
                "INSERT INTO handoff_bindings VALUES(?,?,?,?,?,?,?,?)",
                (
                    identity,
                    owner,
                    "f" * 64,
                    "handoff-1",
                    1,
                    first,
                    "d" * 64,
                    canonical(
                        {
                            "cwd": "/" + SECRET,
                            "source_revision": 99,
                            "run_id": "CURRENT_NEW_RUN",
                            "return_payload": SECRET,
                        }
                    ),
                ),
            )
    audit(
        bridge,
        "handoff.bound",
        {
            "binding_ref": "binding-1",
            "handoff_id": "handoff-1",
            "handoff_revision": 1,
            "original_task_id": "td:task",
            "bridge_task_id": "owned-task",
            "run_id": "original-run",
            "source_hash": "a" * 64,
        },
    )
    audit(
        bridge,
        "handoff.delivered",
        {
            "binding_ref": "binding-1",
            "handoff_id": "handoff-1",
            "handoff_revision": 1,
            "original_task_id": "td:task",
            "bridge_task_id": "owned-task",
            "run_id": "original-run",
            "source_hash": "a" * 64,
        },
    )
    value = read(bridge)
    assert SECRET not in canonical(value) and "CURRENT_NEW_RUN" not in canonical(value)
    assert "foreign-binding" not in canonical(value) and "foreign-task" not in canonical(value)
    assert (
        value["current_correlations"]["basis"]
        == "current_persistent_correlation_not_historical_evidence"
    )
    assert value["current_correlations"]["items"][0]["correlation_ref"] == "binding-1"
    for event in value["events"]:
        assert event["task_id"] == "td:task" and event["bridge_task_id"] == "owned-task"
        assert event["run_id"] == "original-run" and "source_revision" not in event
        assert "request_hash" not in event  # step hash cannot masquerade as workflow hash
    assert value["events"][-1]["reported_status"] == "delivered_unverified"


def test_tampered_or_oversize_audit_skipped_with_bounded_diagnostic_and_progress(bridge):
    queued(bridge)
    audit(bridge, "task.transition", {"to": "completed"})
    with bridge.store.transaction():
        bridge.store.db.execute(
            "UPDATE audit SET metadata=? WHERE kind='task.transition'",
            (canonical({"to": "completed", "raw": SECRET}),),
        )
    value = read(bridge, limit=500)
    assert not value["events"] and value["diagnostics"]
    assert SECRET not in canonical(value) and not value["has_more"]
    audit(bridge, "task.transition", {"to": "completed", "oversize": SECRET * 2000})
    other = read(bridge)
    assert not other["events"] and not other["has_more"]
    assert other["next_cursor"] > value["next_cursor"]


def test_preflight_hash_tampering_never_supplies_historical_fingerprints(bridge):
    completed(bridge)
    with bridge.store.transaction():
        bridge.store.db.execute(
            "UPDATE audit SET metadata=? WHERE kind='task.preflight'",
            (canonical({"runtime": {"source_tree_sha256": "e" * 64}}),),
        )
    value = read(bridge)
    assert value["events"][-1]["event_type"] == "task.completed"
    assert value["provenance"][-1]["execution_runtime"]["basis"] == "unknown_invalid_task_preflight"
    assert "e" * 64 not in canonical(value)


def test_page_byte_cap_advances_and_individual_record_bound(bridge):
    queued(bridge)
    for index in range(120):
        audit(
            bridge,
            "task.transition",
            {"to": "running", "attempt_id": str(index), "project_id": "p" * 240},
        )
    page = read(bridge, limit=500)
    assert page["page_event_bytes"] <= MAX_PAGE_BYTES and page["has_more"]
    assert page["next_cursor"] > 0 and all(
        len((canonical(e) + "\n").encode()) <= 4096 for e in page["events"]
    )
    last = read(bridge, cursor=page["next_cursor"], through_seq=page["through_seq"], limit=500)
    assert not last["has_more"]
    assert set(e["event_id"] for e in page["events"]).isdisjoint(
        e["event_id"] for e in last["events"]
    )


def test_total_response_budget_includes_proofs_and_rewinds_without_loss(bridge, monkeypatch):
    from kirabridge import observation_export

    assert observation_export.MAX_RESPONSE_BYTES == 262144
    completed(bridge)
    for index in range(20):
        audit(bridge, "task.transition", {"to": "running", "attempt_id": str(index)})
        audit(bridge, "not_projected", {})
    expected = read(bridge, limit=500)
    assert len((canonical(expected) + "\n").encode()) > 8192
    monkeypatch.setattr(observation_export, "MAX_RESPONSE_BYTES", 8192)
    events, cursor, trimmed = [], 0, False
    for _ in range(30):
        page = read(bridge, cursor=cursor, through_seq=expected["through_seq"], limit=500)
        assert len((canonical(page) + "\n").encode()) <= 8192
        assert page["max_response_bytes"] == 8192
        assert page["page_event_bytes"] == sum(
            len((canonical(event) + "\n").encode()) for event in page["events"]
        )
        assert len(page["events"]) == len(page["provenance"])
        assert all(item["audit_seq"] <= page["next_cursor"] for item in page["diagnostics"])
        events.extend(page["events"])
        if not page["has_more"]:
            break
        trimmed = True
        assert cursor < page["next_cursor"]
        cursor = page["next_cursor"]
    else:
        pytest.fail("bounded response pagination did not terminate")
    assert trimmed and events == expected["events"]
    assert len({event["event_id"] for event in events}) == len(events)
    # An unusably small budget reports a prerequisite error, never endless pages.
    monkeypatch.setattr(observation_export, "MAX_RESPONSE_BYTES", 1)
    with pytest.raises(BridgeError) as failure:
        read(bridge)
    assert failure.value.code == "observation_response_budget"


@pytest.mark.skipif(os.name == "nt", reason="Unix owner/mode semantics")
def test_world_readable_or_symlink_state_refused(bridge, tmp_path):
    queued(bridge)
    db = bridge.config.state_path / "bridge.sqlite3"
    db.chmod(0o644)
    with pytest.raises(BridgeError) as failure:
        read(bridge)
    assert failure.value.code == "unsafe_state"
    db.chmod(0o600)
    link = tmp_path / "state-link"
    link.symlink_to(bridge.config.state_path, target_is_directory=True)
    cfg = bridge.config.model_copy(update={"data_dir": str(link)})
    with pytest.raises(BridgeError):
        export_configured_observations(cfg, "local", task_ids=["owned-task"])


def test_script_uses_config_policy_without_bridge_store_and_stdout_only_jsonl(
    bridge, tmp_path, monkeypatch, capsys
):
    completed(bridge)
    config = tmp_path / "read.toml"
    config.write_text(
        "data_dir = "
        + json.dumps(str(bridge.config.state_path))
        + '\n[principals.local]\ncapabilities=["task.read"]\n'
    )

    def forbidden(*_, **__):
        raise AssertionError("must not create/migrate Store")

    monkeypatch.setattr("kirabridge.task_manager.store.Store.__init__", forbidden)
    script = Path(__file__).resolve().parents[1] / "scripts/export_workflow_observations.py"
    main = runpy.run_path(str(script))["main"]
    assert main(["--config", str(config), "--principal", "local", "--task-id", "owned-task"]) == 0
    output = capsys.readouterr()
    assert all(
        json.loads(line)["schema_version"] == EVENT_SCHEMA for line in output.out.splitlines()
    )
    assert json.loads(output.err)["next_cursor"] > 0
    assert SECRET not in output.out + output.err
    assert str(config) not in output.out + output.err
    config.write_text(
        "data_dir = "
        + json.dumps(str(bridge.config.state_path))
        + "\n[principals.local]\ncapabilities=[]\n"
    )
    assert main(["--config", str(config), "--principal", "local", "--task-id", "owned-task"]) == 2
    denied = capsys.readouterr()
    assert not denied.out and json.loads(denied.err)["code"] == "forbidden"


def test_optional_fixed_actual_aa_reader_accepts_existing_event_contract(bridge):
    root = os.environ.get("KIRABRIDGE_TEST_AA_SOURCE")
    if not root:
        pytest.skip("Optional existing reviewed AA source required; no CI token dependency")
    import hashlib

    expected = {
        "agent_authority/workflow.py": (
            "50d222c156d535cfd3f502b498146d63f5681945898c03f8e9dd51b6c53e8c80"
        ),
        "agent_authority/workflow_rules.py": (
            "44a85a86f8d016b508df186f23634590245ca9ad81dbdf301e151a83026bdf86"
        ),
    }
    for relative, sha in expected.items():
        assert hashlib.sha256((Path(root) / relative).read_bytes()).hexdigest() == sha
    completed(bridge)
    sys.path.insert(0, root)
    try:
        module = importlib.import_module("agent_authority.workflow")
        for event in read(bridge)["events"]:
            claim = module.project_record(
                event,
                source_tool="kirabridge",
                source_id=event["source_id"],
                segment_id="selected-export",
                file_sha256="0" * 64,
            )
            assert claim.event_type == event["event_type"] and not claim.identity_claimed
    finally:
        sys.path.remove(root)


def test_claimed_answer_does_not_become_delivered_answer_and_only_agent_turns_get_turn_label(
    bridge,
):
    completed(bridge)
    audit(bridge, "handoff.answer_claimed", {"phase": "answer_dispatching"})
    value = read(bridge)
    assert "task.answer_recorded" not in [e["event_type"] for e in value["events"]]
    assert all(e.get("reported_status") != "turn_completed" for e in value["events"])
    audit(bridge, "handoff.turn_ended", {"phase": "delivering"})
    assert read(bridge)["events"][-1]["reported_status"] == "turn_completed"


def test_real_cli_process_reads_synthetic_state_and_denies_bad_cli_without_echo(bridge, tmp_path):
    import subprocess

    completed(bridge)
    root = Path(__file__).resolve().parents[1]
    config = tmp_path / "read.toml"
    config.write_text(
        "data_dir = "
        + json.dumps(str(bridge.config.state_path))
        + '\n[principals.local]\ncapabilities=["task.read"]\n'
    )
    env = {**os.environ, "PYTHONPATH": str(root / "src")}
    args = [
        sys.executable,
        str(root / "scripts/export_workflow_observations.py"),
        "--config",
        str(config),
        "--principal",
        "local",
        "--task-id",
        "owned-task",
    ]
    result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=5, check=False)
    assert result.returncode == 0
    assert len([json.loads(line) for line in result.stdout.splitlines()]) == 3
    assert json.loads(result.stderr)["has_more"] is False
    assert SECRET not in result.stdout + result.stderr
    bad = subprocess.run(
        [*args, "--limit", SECRET], env=env, capture_output=True, text=True, timeout=5, check=False
    )
    assert bad.returncode == 2 and not bad.stdout
    assert json.loads(bad.stderr)["code"] == "invalid_cli_arguments"
    assert SECRET not in bad.stderr


def test_closed_writer_restart_retains_same_event_ids_and_untouched_schema(bridge):
    completed(bridge)
    before = read(bridge)
    bridge.store.close()
    after = export_configured_observations(bridge.config, "local", task_ids=["owned-task"])
    assert before["events"] == after["events"]
    assert before["source_id"] == after["source_id"]
    connection = sqlite3.connect(
        (bridge.config.state_path / "bridge.sqlite3").as_uri() + "?mode=ro", uri=True
    )
    try:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        assert connection.execute("SELECT state FROM tasks").fetchone()[0] == "completed"
    finally:
        connection.close()


def test_diagnostic_limit_reports_omitted_and_still_advances_cursor(bridge):
    queued(bridge)
    for _ in range(66):
        audit(bridge, "task.transition", {"to": "completed"})
    with bridge.store.transaction():
        bridge.store.db.execute("UPDATE audit SET hash=? WHERE kind='task.transition'", ("f" * 64,))
    value = read(bridge, limit=500)
    assert len(value["diagnostics"]) == 64 and value["diagnostics_omitted"] == 2
    assert not value["has_more"] and not value["events"]


@pytest.mark.skipif(os.name == "nt", reason="Unix symlink semantics")
def test_symlink_sqlite_sidecar_is_not_opened_or_written(bridge, tmp_path):
    completed(bridge)
    bridge.store.close()
    sentinel = tmp_path / "sentinel"
    sentinel.write_text(SECRET)
    side = bridge.config.state_path / "bridge.sqlite3-shm"
    side.symlink_to(sentinel)
    with pytest.raises(BridgeError) as failure:
        read(bridge)
    assert failure.value.code == "unsafe_state"
    assert sentinel.read_text() == SECRET


def test_sqlite_error_sanitized_without_retry_or_task_mutation(bridge, monkeypatch):
    queued(bridge)
    calls = []

    def broken(*_, **__):
        calls.append(1)
        raise sqlite3.OperationalError(SECRET)

    monkeypatch.setattr("kirabridge.observation_export.sqlite3.connect", broken)
    with pytest.raises(BridgeError) as failure:
        read(bridge)
    assert failure.value.code == "observation_state_unavailable"
    assert SECRET not in str(failure.value) and calls == [1]
    assert bridge.store.get("owned-task")["state"] == "queued"


def test_cli_help_does_not_pollute_data_stdout(capsys):
    script = Path(__file__).resolve().parents[1] / "scripts/export_workflow_observations.py"
    main = runpy.run_path(str(script))["main"]
    with pytest.raises(SystemExit) as finished:
        main(["--help"])
    assert finished.value.code == 0
    output = capsys.readouterr()
    assert not output.out and "--task-id" in output.err
    assert str(script) not in output.err


def test_snapshot_boundary_inside_filtered_gap_never_reports_endless_more(bridge):
    queued(bridge)
    queued(bridge, "foreign-gap", "other")
    audit(bridge, "task.transition", {"to": "running"})
    first = read(bridge, through_seq=3)
    assert first["next_cursor"] == 2 and not first["has_more"]
    empty = read(bridge, cursor=first["next_cursor"], through_seq=3)
    assert not empty["events"] and not empty["has_more"]
    fresh = read(bridge, cursor=first["next_cursor"])
    assert fresh["events"][-1]["event_type"] == "task.running"
