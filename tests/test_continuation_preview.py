"""Offline Big Plan preview fixtures; never create Core or provider work."""

import json
import sys
from datetime import datetime, timedelta, timezone

import pytest

import scripts.bigplan_loop as loop
from kirabridge.autonext.continuation import ContinuationPolicy, grant_id
from kirabridge.autonext.manager import text_sha

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)


def fixture_files(
    tmp_path, *, state="READY", prior=None, activity=(), route_expired=False, worker=None
):
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / ".git").write_text("fixture only")
    checks = [{"argv": [sys.executable, "-c", "pass"], "timeout_seconds": 5}]
    card = {
        "autonext": 1,
        "task_id": "preview-task-1",
        "state": state,
        "product": "KiraBridge",
        "cwd": str(worktree),
        "sandbox": "read-only",
        "title": "Fixture task",
        "instruction": "Fixture only",
        "acceptance": {"kind": "coordinator_checks", "checks": checks},
    }
    content = json.dumps(card, separators=(",", ":"))
    entry = {"id": "task-entry-1", "entry_type": "task", "content": content}
    entries = [entry, *activity]
    source = {
        "task_id": card["task_id"],
        "entry_id": entry["id"],
        "content_sha256": text_sha(content),
    }
    checked = NOW - timedelta(minutes=5)
    expires = NOW + timedelta(hours=1)
    access_expires = checked if route_expired else expires
    runtime = {
        "schema_version": "bigplan.cli-runtime.v1",
        "access": [
            {
                "cli": "codex",
                "executable": "/usr/bin/codex",
                "version": "fixture-1",
                "models": ["small", "large"],
                "access_kind": "subscription",
                "verified_at": checked.isoformat(),
                "expires_at": access_expires.isoformat(),
                "evidence": "fixture",
            }
        ],
        "allowed_roots": [str(worktree)],
        "state_dir": str(tmp_path / "state"),
        "allow_write": False,
    }
    profile = {
        "cwd": str(worktree),
        "state_dir": str(tmp_path / "state"),
        "search_path": [],
        "codex": "/usr/bin/codex",
        "grok": "/usr/bin/grok",
        "workspace": "fixture-workspace",
        "threaddesk_source": "fixture-source",
        "report_cli": "/usr/bin/report",
        "instance": "preview-fixture",
        "board_id": "fixture-board",
        "sandbox": "read-only",
        "enabled": True,
        "cards": [],
        "completion_target": "fixture-completion",
        "continuation": {
            "authority_ref": "fixture-authority",
            "allowed_cwds": [str(worktree)],
            "products": ["KiraBridge"],
            "checks": checks,
            "sources": [source],
        },
        "routing": {
            "workspace": "fixture-workspace",
            "thread_id": "fixture-matrix",
            "runtime": runtime,
        },
        "worker_routing": {
            "codex": worker or {"workload": "implementation", "effort": "medium", "model": None}
        },
    }
    fixture = {
        "matrix": {
            "schema_version": "bigplan.cli-matrix.v1",
            "checked_at": checked.isoformat(),
            "expires_at": expires.isoformat(),
            "clis": [
                {
                    "id": "codex",
                    "installed_version": "fixture-1",
                    "capabilities": ["headless", "coding"],
                    "models": [
                        {
                            "id": "small",
                            "provider": "openai",
                            "efforts": ["medium", "high"],
                            "fit": {"implementation": 5},
                            "cost_rank": 0,
                            "evidence": "fixture",
                        },
                        {
                            "id": "large",
                            "provider": "openai",
                            "efforts": ["medium", "high"],
                            "fit": {"implementation": 5},
                            "cost_rank": 2,
                            "evidence": "fixture",
                        },
                    ],
                    "documented_models": [],
                    "sources": [],
                    "limitations": "fixture only",
                }
            ],
        },
        "snapshot": {"entries": entries, "prior": prior or {}, "attempts": {}, "leases": []},
    }
    profile_path = tmp_path / "profile.json"
    fixture_path = tmp_path / "snapshot.json"
    profile_path.write_text(json.dumps(profile))
    fixture_path.write_text(json.dumps(fixture))
    return profile_path, fixture_path, profile


def test_preview_selects_smallest_supported_route_without_global_change(tmp_path):
    profile_path, fixture_path, profile = fixture_files(tmp_path)
    original = profile_path.read_bytes()

    result = loop.preview_profile(profile_path, fixture_path, now=NOW)

    assert result["preview_only"] is True
    assert result["provider_calls"] == 0
    assert result["selected"]["task_id"] == "preview-task-1"
    assert result["selected"]["routing"] == {
        "cli": "codex",
        "model": "small",
        "effort": "medium",
        "effective_model": "unverified",
        "effective_effort": "unverified",
    }
    assert profile_path.read_bytes() == original
    assert profile["worker_routing"]["codex"]["model"] is None


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"state": "STALE"}, "card_stale"),
        ({"route_expired": True}, "routing_unavailable"),
        (
            {"worker": {"workload": "implementation", "effort": "medium", "model": "missing"}},
            "routing_unavailable",
        ),
        ({"prior": {"preview-task-1": "unknown"}}, "existing_claim"),
        (
            {
                "activity": (
                    {
                        "id": "late-result",
                        "entry_type": "result",
                        "content": "preview-task-1 late completion",
                    },
                    {
                        "id": "duplicate-result",
                        "entry_type": "result",
                        "content": "preview-task-1 duplicate completion",
                    },
                )
            },
            "external_activity",
        ),
    ],
)
def test_preview_holds_stale_unsupported_and_already_claimed_results(tmp_path, kwargs, reason):
    profile_path, fixture_path, _ = fixture_files(tmp_path, **kwargs)

    result = loop.preview_profile(profile_path, fixture_path, now=NOW)

    assert result["selected"] is None
    assert result["held"][0]["reason"] == reason
    assert result["provider_calls"] == 0


def test_preview_holds_missing_source_pin(tmp_path):
    profile_path, fixture_path, profile = fixture_files(tmp_path)
    profile["continuation"]["sources"] = []
    profile_path.write_text(json.dumps(profile))

    result = loop.preview_profile(profile_path, fixture_path, now=NOW)

    assert result["selected"] is None
    assert result["held"][0]["reason"] == "unassigned_source"


def test_preview_does_not_call_effect_functions(tmp_path, monkeypatch):
    profile_path, fixture_path, _ = fixture_files(tmp_path)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("preview called an effectful runtime function")

    for name in ("Bridge", "advance", "process_completions", "quota"):
        monkeypatch.setattr(loop, name, forbidden)
    monkeypatch.setattr("kirabridge.autonext.continuation.board_entries", forbidden)

    result = loop.preview_profile(profile_path, fixture_path, now=NOW)
    assert result["selected"]["task_id"] == "preview-task-1"


def test_preview_cli_uses_fixture_only(tmp_path, monkeypatch, capsys):
    profile_path, fixture_path, _ = fixture_files(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["bigplan-loop", "--profile", str(profile_path), "preview", "--fixture", str(fixture_path)],
    )

    loop.main()

    output = json.loads(capsys.readouterr().out)
    assert output["preview_only"] is True
    assert output["authorizes_or_starts_work"] is False


def test_legacy_assignments_are_rejected_explicitly_without_rewrite(tmp_path):
    profile_path, _, profile = fixture_files(tmp_path)
    profile["continuation"]["assignments"] = [
        {
            "task_id": "old-task",
            "implementer": "grok",
            "model": "old-model",
            "effort": "high",
        }
    ]
    original = json.dumps(profile).encode()
    profile_path.write_bytes(original)

    with pytest.raises(
        ValueError, match=r"Legacy continuation\.assignments.*explicit profile migration"
    ):
        loop.load_profile(profile_path)
    assert profile_path.read_bytes() == original


def test_preview_accepts_readycard_task_id_with_dot(tmp_path):
    profile_path, fixture_path, profile = fixture_files(tmp_path)
    fixture = json.loads(fixture_path.read_text())
    entry = fixture["snapshot"]["entries"][0]
    card = json.loads(entry["content"])
    card["task_id"] = "followup.two"
    entry["content"] = json.dumps(card)
    profile["continuation"]["sources"][0].update(
        task_id=card["task_id"], content_sha256=text_sha(entry["content"])
    )
    profile_path.write_text(json.dumps(profile))
    fixture_path.write_text(json.dumps(fixture))

    result = loop.preview_profile(profile_path, fixture_path, now=NOW)

    assert result["selected"]["task_id"] == "followup.two"
    assert result["selected"]["routing"]["model"] == "small"


def test_preview_holds_fractional_timeout_without_rounding(tmp_path):
    profile_path, fixture_path, profile = fixture_files(tmp_path)
    profile["worker_timeouts"] = {"codex": 1.5}
    profile_path.write_text(json.dumps(profile))

    result = loop.preview_profile(profile_path, fixture_path, now=NOW)

    assert result["selected"] is None
    assert result["held"][0]["reason"] == "routing_unavailable"
    assert "exact whole seconds" in result["held"][0]["routing_reason"]


@pytest.mark.parametrize("state", ["unknown_attempt", "lease"])
def test_preview_keeps_original_attempts_and_leases_reserved(tmp_path, state):
    profile_path, fixture_path, profile = fixture_files(tmp_path)
    fixture = json.loads(fixture_path.read_text())
    if state == "unknown_attempt":
        policy = ContinuationPolicy.model_validate(profile["continuation"])
        identifier = grant_id(policy, profile["board_id"], "preview-task-1")
        fixture["snapshot"]["attempts"][identifier] = "unknown"
        expected = "existing_attempt_unknown"
    else:
        fixture["snapshot"]["leases"] = [profile["cwd"]]
        expected = "worktree_reserved"
    fixture_path.write_text(json.dumps(fixture))
    original = fixture_path.read_bytes()

    result = loop.preview_profile(profile_path, fixture_path, now=NOW)

    assert result["selected"] is None
    assert result["held"][0]["reason"] == expected
    assert fixture_path.read_bytes() == original


@pytest.mark.parametrize("invalid", ["model", "missing_global", "missing_runtime"])
def test_preview_holds_unsupported_task_route(tmp_path, invalid):
    profile_path, fixture_path, profile = fixture_files(tmp_path)
    profile["continuation"]["task_routing"] = {
        "preview-task-1": {"workload": "implementation", "model": "large", "effort": "high"}
    }
    if invalid == "model":
        profile["continuation"]["task_routing"]["preview-task-1"]["model"] = "missing"
    elif invalid == "missing_global":
        profile["worker_routing"] = {}
    else:
        profile["routing"] = None
    profile_path.write_text(json.dumps(profile))

    result = loop.preview_profile(profile_path, fixture_path, now=NOW)

    assert result["selected"] is None
    assert result["held"][0]["reason"] == "routing_unavailable"
