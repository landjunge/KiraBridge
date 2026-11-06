"""Bounded real AutoNext extension of the existing owned-window acceptance.

No daemon or alternative executor: two pinned read-only cards through the same
private Bridge, authenticated TeamDispatcher and existing visible Codex window.
"""

import asyncio
import hashlib
import json
import math
import os
import time
from datetime import datetime
from pathlib import Path

from kirabridge.autonext.models import AutoNextConfig, ReadyCard
from kirabridge.bridge_core.config import TeamWorkerConfig
from kirabridge.team_manager.models import (
    TeamCreate,
    TeamWorkClaim,
    TeamWorkComplete,
    TeamWorkCreate,
)
from kirabridge.whiteboard_read import append_whiteboard, read_whiteboard


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def budget_observation(path):
    latest = None
    with Path(path).open() as stream:
        for line in stream:
            record = json.loads(line)
            rate = record.get("payload", {}).get("rate_limits")
            if rate and rate.get("limit_id") == "codex":
                latest = (record["timestamp"], rate)
    if latest is None:
        raise RuntimeError("No actual Codex quota observation")
    timestamp, rate = latest
    observed = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp()
    now = time.time()
    windows = [rate.get(name) for name in ("primary", "secondary") if rate.get(name)]
    if (
        not now - 900 <= observed <= now + 2
        or not windows
        or any(
            type(window.get("used_percent")) not in (int, float)
            or not math.isfinite(window["used_percent"])
            or not 0 <= window["used_percent"] < 100
            for window in windows
        )
        or rate.get("spend_control_reached")
        or any(os.environ.get(key) for key in ("OPENAI_API_KEY", "CODEX_API_KEY", "XAI_API_KEY"))
    ):
        raise RuntimeError("Quota/billing observation unavailable for bounded native acceptance")
    return observed, rate


async def accept(bridge, args, workspace, binding, protocol, anchor, nonce, evidence, checkpoint):
    bridge.config.team.enabled = True
    try:
        await _accept(
            bridge, args, workspace, binding, protocol, anchor, nonce, evidence, checkpoint
        )
    finally:
        if bridge.autonext.worker is not None:
            await bridge.autonext.stop()
        if bridge.team_dispatcher.workers:
            await bridge.team_dispatcher.stop()
        bridge.config.team.enabled = False
        bridge.config.autonext.enabled = False
        checkpoint()


async def _accept(bridge, args, workspace, binding, protocol, anchor, nonce, evidence, checkpoint):
    observed, quota = budget_observation(args.autonext_budget_source)
    cfg = bridge.config
    principal = "chatgpt"
    cfg.threaddesk.enabled = True
    cfg.threaddesk.workspace = str(args.autonext_board_workspace)
    board = "482f593429ad"
    read_whiteboard(cfg.threaddesk.workspace, board)  # Existing board only.
    binding.codex_thread_id = protocol["thread_id"]
    binding.codex_rollout_path = protocol["rollout_path"]
    cfg.visible_handoffs.bindings["codex"] = binding
    cfg.team.workers["codex"] = TeamWorkerConfig(
        agent="codex", cwd=str(workspace), timeout=args.response_timeout
    )
    cfg.agents["codex"].sandbox_mode = "read-only"
    cfg.agents["codex"].bridge_tools = False
    cfg.team.workers[principal] = TeamWorkerConfig()
    team_id = "native-autonext-" + nonce
    bridge.teams.create(
        principal,
        TeamCreate(
            team_id=team_id,
            name="bounded native acceptance",
            coordinator=principal,
            members={principal: "coordinator", "codex": "worker"},
            idempotency_key=team_id,
        ),
    )
    seed = bridge.teams.delegate(
        principal,
        TeamWorkCreate(
            team_id=team_id,
            assignee=principal,
            title="Verified prior native handoff",
            body="Exact native task/rollout receipt independently checked by acceptance harness",
            idempotency_key=team_id + "-anchor",
        ),
    )
    bridge.teams.work_claim(
        principal,
        TeamWorkClaim(
            team_id=team_id,
            work_id=seed["id"],
            idempotency_key=team_id + "-claim",
        ),
    )
    anchor_text = json.dumps(anchor, sort_keys=True)
    bridge.teams.work_complete(
        principal,
        TeamWorkComplete(
            team_id=team_id,
            work_id=seed["id"],
            result=anchor_text,
            idempotency_key=team_id + "-confirmed",
        ),
    )
    cards = []
    answers = []
    for index in (1, 2):
        answer = "BIGPLAN_NATIVE_" + nonce + "_" + str(index)
        card = ReadyCard(
            autonext=1,
            task_id="native-" + nonce + "-" + str(index),
            state="READY",
            product="KiraBridge",
            cwd=str(workspace),
            sandbox="read-only",
            title="Bounded native continuation probe " + str(index),
            instruction="Do not use tools or change files. Return the required team JSON with "
            "result exactly " + answer + " and actions an empty array.",
            acceptance={"kind": "result_sha256", "expected_sha256": sha(answer)},
        )
        content = card.model_dump_json()
        entry = append_whiteboard(
            cfg.threaddesk.workspace,
            board,
            actor="Codex",
            actor_type="codex",
            entry_type="task",
            content=content,
            external_key=card.task_id,
        )
        reread = read_whiteboard(cfg.threaddesk.workspace, board, entry["id"])["entry"]
        if reread["content"] != content or reread["truncated"]:
            raise RuntimeError("Native probe card readback differs; never dispatch")
        cards.append(
            {"task_id": card.task_id, "entry_id": entry["id"], "content_sha256": sha(content)}
        )
        answers.append(answer)
    cfg.autonext = AutoNextConfig(
        enabled=True,
        grant_id="native-accept-" + nonce,
        principal=principal,
        team_id=team_id,
        team_revision=bridge.teams.get(principal, team_id)["revision"],
        board_id=board,
        after_work_id=seed["id"],
        after_result_sha256=sha(anchor_text),
        cards=cards,
        max_tasks=2,
        lease_seconds=360,
        budget_state="available",
        budget_observed_at=observed,
        budget_valid_until=observed + 900,
        budget_source_ref="private-native-quota-observation:" + str(args.autonext_budget_source),
        billing_evidence_ref="verified-existing-ChatGPT-login; no API keys; same visible CLI",
    )
    evidence["autonext"] = {
        "grant": cfg.autonext.model_dump(),
        "quota": quota,
        "source_cards": cards,
        "state": "prepared",
    }
    checkpoint()
    cfg.team.enabled = True
    try:
        await bridge.team_dispatcher.start()
        await bridge.autonext.start()
        async with asyncio.timeout(args.response_timeout * 2 + 45):
            while True:
                state = bridge.autonext.inspect()
                evidence["autonext"]["status"] = state
                checkpoint()
                if state["state"] in {"complete", "stopped"}:
                    break
                await asyncio.sleep(0.25)
        if state["state"] != "complete":
            raise RuntimeError("Native AutoNext stopped: " + str(state.get("reason")))
        receipts = [bridge.autonext.receipt(principal, card["task_id"]) for card in cards]
        if any(not receipt for receipt in receipts):
            raise RuntimeError("Native AutoNext lacks independent completion receipts")
        cores = [bridge.store.get(receipt["core_task_id"], "codex") for receipt in receipts]
        assert all(core["state"] == "completed" and core["attempt"] == 1 for core in cores)
        assert receipts[0]["accepted_at"] <= cores[1]["created"]
        assert [receipt["result_sha256"] for receipt in receipts] == [sha(x) for x in answers]
        assert bridge.store.db.execute("SELECT count(*) FROM autonext_items").fetchone()[0] == 2
        assert (
            bridge.store.db.execute(
                "SELECT count(*) FROM autonext_outbox WHERE verified=1"
            ).fetchone()[0]
            == 4
        )
        evidence["autonext"].update(
            state="passed", receipts=receipts, core_attempts=[core["attempt"] for core in cores]
        )
    finally:
        await bridge.autonext.stop()
        await bridge.team_dispatcher.stop()
        cfg.team.enabled = False
        cfg.autonext.enabled = False
        checkpoint()
