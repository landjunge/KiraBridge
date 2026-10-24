"""Real stdio MCP acceptance adapter; no Codex subprocess or provider calls."""

import json
from pathlib import Path

import pytest

from kirabridge.review_demo import REVIEW, Demo, sha


async def test_staged_mcp_review_rework_result_and_duplicate_guards(tmp_path):
    demo = Demo(tmp_path / "demo")
    started = await demo.run("start")
    assert started["delivery"]["acknowledged"]
    with pytest.raises(FileExistsError):
        await demo.run("start")
    page = demo.root / "index.html"
    page.write_text("initial Codex artifact")
    reviewed = await demo.run("review")
    reply = reviewed["rework_delivery"]
    assert reply["body"] == REVIEW and reply["sender"] == "grok-sim"
    assert reply["reply_to"] == reviewed["review_request"]["id"]
    assert reply["acknowledged"]
    with pytest.raises(RuntimeError, match="Stage blocked"):
        await demo.run("review")
    with pytest.raises(RuntimeError, match="No Codex rework"):
        await demo.run("finish")
    page.write_text("changed artifact")
    checks = demo.root / "checks.json"
    checks.write_text(json.dumps({"passed": True, "page_sha256": "stale"}))
    with pytest.raises(RuntimeError, match="Passing checks"):
        await demo.run("finish")
    checks.write_text(json.dumps({"passed": True, "page_sha256": sha(page)}))
    final = await demo.run("finish")
    assert final["phase"] == "completed"
    assert final["result_delivery"]["acknowledged"]
    assert final["result"]["reply_to"] == started["request"]["id"]
    assert json.loads(final["result"]["body"])["review_reply_id"] == reply["id"]
    with pytest.raises(RuntimeError, match="Stage blocked"):
        await demo.run("finish")
    # Verify exactly four archived messages, receipts and audit from isolated state.
    from kirabridge.audit_manager import verify
    from kirabridge.bridge_core.bridge import Bridge
    from kirabridge.bridge_core.config import load_config

    bridge = Bridge(load_config(str(demo.config)))
    try:
        assert bridge.store.db.execute("SELECT count(*) FROM messages").fetchone()[0] == 4
        assert verify(bridge.store)["valid"]
    finally:
        bridge.store.close()


async def test_stop_prevents_review_without_starting_agents(tmp_path):
    demo = Demo(tmp_path / "stopped")
    await demo.run("start")
    assert (await demo.run("stop"))["phase"] == "stopped"
    with pytest.raises(RuntimeError, match="Stage blocked"):
        await demo.run("review")
    assert "[agents]\n[principals" in demo.config.read_text()


def test_delivered_demo_artifacts_match_evidence():
    root = Path(__file__).resolve().parents[1] / "examples/review-demo/run-20261019"
    evidence = json.loads((root / "evidence.json").read_text())
    assert sha(root / "index.html") == evidence["final_sha256"]
    assert sha(root / "initial.html") == evidence["initial_sha256"]
    assert evidence["initial_sha256"] != evidence["final_sha256"]
    assert not evidence["codex_cli_run_verified"]
    assert not evidence["chatgpt_connector_verified"]
