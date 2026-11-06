"""Quota uses fresh native provider events, never board text or estimated usage."""

import json
import time
from datetime import datetime, timezone

import pytest
from test_coordinator_runtime import runtime


def event(*, age=0, used=35, plan="prolite", resets=None):
    return {
        "timestamp": datetime.fromtimestamp(time.time() - age, timezone.utc).isoformat(),
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "rate_limits": {
                "limit_id": "codex",
                "plan_type": plan,
                "primary": {"used_percent": used, "resets_at": resets or time.time() + 3600},
            },
        },
    }


def source(tmp_path, monkeypatch, records):
    monkeypatch.setattr(runtime, "QUOTA_LOG_ROOT", tmp_path)
    path = tmp_path / "native.jsonl"
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n")
    return path


async def test_fresh_native_quota_avoids_unavailable_rpc_without_model_call(tmp_path, monkeypatch):
    path = source(tmp_path, monkeypatch, [{"type": "response_item", "payload": event()}, event()])
    value = await runtime.quota("/bin/false", [str(path)])
    assert value["subscription_confirmed"]
    assert value["source"].startswith("Codex native rate_limits sha256:")
    assert 0 <= time.time() - value["observed_at"] < 2


@pytest.mark.parametrize(
    "used,plan",
    [
        (100, "prolite"),
        (-1, "prolite"),
        (True, "prolite"),
        (35, "api"),
        (35, None),
        (float("nan"), "prolite"),
    ],
)
def test_latest_unusable_observation_cannot_fall_back_to_earlier_available(
    tmp_path,
    monkeypatch,
    used,
    plan,
):
    path = source(tmp_path, monkeypatch, [event(age=5), event(used=used, plan=plan)])
    with pytest.raises(RuntimeError, match="unavailable or exhausted"):
        runtime.native_quota([str(path)])


def test_stale_and_model_embedded_observations_are_not_quota_proof(tmp_path, monkeypatch):
    path = source(
        tmp_path, monkeypatch, [event(age=301), {"type": "response_item", "payload": event()}]
    )
    assert runtime.native_quota([str(path)]) is None


async def test_native_quota_never_overrides_api_billing_denial(tmp_path, monkeypatch):
    path = source(tmp_path, monkeypatch, [event()])
    monkeypatch.setenv("CODEX_API_KEY", "fixture-never-output")
    with pytest.raises(RuntimeError, match="API-key billing"):
        await runtime.quota("/bin/false", [str(path)])


def test_quota_cannot_read_outside_native_source_or_follow_symlink(tmp_path, monkeypatch):
    path = source(tmp_path, monkeypatch, [event()])
    link = tmp_path / "linked.jsonl"
    link.symlink_to(path)
    with pytest.raises(ValueError, match="native Codex"):
        runtime.native_quota([str(link)])
    monkeypatch.setattr(runtime, "QUOTA_LOG_ROOT", tmp_path / "other")
    with pytest.raises(ValueError, match="native Codex"):
        runtime.native_quota([str(path)])


def test_only_latest_timestamp_conflict_can_block_quota(tmp_path, monkeypatch):
    earlier = event(age=5)
    contradictory = json.loads(json.dumps(earlier))
    contradictory["payload"]["rate_limits"]["primary"]["used_percent"] = 100
    path = source(tmp_path, monkeypatch, [earlier, contradictory])
    with pytest.raises(RuntimeError, match="Conflicting"):
        runtime.native_quota([str(path)])
    with path.open("a") as handle:
        handle.write(json.dumps(event()) + "\n")
    assert runtime.native_quota([str(path)])["subscription_confirmed"]
