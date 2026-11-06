"""Real-provider acceptance must never substitute a fabricated/stale quota."""

import importlib.util
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[1] / "scripts/autonext_native_acceptance.py"
spec = importlib.util.spec_from_file_location("native_autonext_acceptance", PATH)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


def observation(tmp_path, *, age=0, used=4, spend=False):
    p = tmp_path / "actual-quota.jsonl"
    p.write_text(
        json.dumps(
            {
                "timestamp": datetime.fromtimestamp(time.time() - age, timezone.utc).isoformat(),
                "payload": {
                    "rate_limits": {
                        "limit_id": "codex",
                        "primary": {"used_percent": used},
                        "spend_control_reached": spend,
                    }
                },
            }
        )
        + "\n"
    )
    return p


@pytest.fixture(autouse=True)
def no_api_billing(monkeypatch):
    for key in ("OPENAI_API_KEY", "CODEX_API_KEY", "XAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)


def test_actual_fresh_quota_is_kept_as_observation(tmp_path):
    at, quota = helper.budget_observation(observation(tmp_path))
    assert time.time() - 5 < at <= time.time()
    assert quota["primary"]["used_percent"] == 4


@pytest.mark.parametrize(
    "options",
    [
        {"age": 901},
        {"age": -10},
        {"used": 100},
        {"used": -1},
        {"used": float("nan")},
        {"used": float("inf")},
        {"used": True},
        {"spend": True},
    ],
)
def test_stale_exhausted_or_invalid_quota_never_authorizes_a_turn(tmp_path, options):
    with pytest.raises(RuntimeError):
        helper.budget_observation(observation(tmp_path, **options))


@pytest.mark.parametrize("key", ["OPENAI_API_KEY", "CODEX_API_KEY", "XAI_API_KEY"])
def test_api_key_blocks_subscription_only_probe(tmp_path, monkeypatch, key):
    monkeypatch.setenv(key, "NOT_A_REAL_CREDENTIAL")
    with pytest.raises(RuntimeError):
        helper.budget_observation(observation(tmp_path))
