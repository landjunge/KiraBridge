#!/usr/bin/env python3
"""Dedicated Codex coordinator profile using existing AutoNext, TeamWork and Core tasks."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import secrets
import signal
import socket
import subprocess
import time
from pathlib import Path
from typing import Literal

import uvicorn
from pydantic import BaseModel, ConfigDict, Field

from kirabridge.autonext.manager import digest, text_sha
from kirabridge.autonext.models import ApprovedCard, AutoNextConfig
from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import Config
from kirabridge.mcp_gateway.http import create_http_app
from kirabridge.team_manager.models import (
    TeamCreate,
    TeamWorkClaim,
    TeamWorkComplete,
    TeamWorkCreate,
)


class LoopProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    cwd: str
    state_dir: str
    search_path: list[str]
    codex: str
    grok: str
    workspace: str
    threaddesk_source: str
    report_cli: str
    instance: str = Field(pattern=r"^[A-Za-z0-9_-]{1,60}$")
    board_id: str
    sandbox: Literal["read-only", "workspace-write"] = "read-only"
    enabled: bool = False
    cards: list[ApprovedCard] = Field(default_factory=list, max_length=16)
    approval_revision: str = ""
    completion_target: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.:-]{1,128}$")


def load_profile(path):
    return LoopProfile.model_validate_json(path.read_text()).model_dump()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temporary.chmod(0o600)
    temporary.replace(path)


async def quota(codex):
    """Read account state only; never buys credits or issues a model request."""
    if any(os.environ.get(k) for k in ("OPENAI_API_KEY", "CODEX_API_KEY", "XAI_API_KEY")):
        raise RuntimeError("API-key billing is not authorized for this loop")
    process = await asyncio.create_subprocess_exec(
        codex,
        "app-server",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        limit=1048576,
    )

    async def rpc(number, method, params):
        process.stdin.write(
            (json.dumps(dict(id=number, method=method, params=params)) + "\n").encode()
        )
        await process.stdin.drain()
        async with asyncio.timeout(15):
            while True:
                line = await process.stdout.readline()
                if not line:
                    raise RuntimeError("Quota connection closed")
                row = json.loads(line)
                if row.get("id") == number:
                    if "error" in row:
                        raise RuntimeError("Quota observation rejected")
                    return row["result"]

    try:
        await rpc(
            1, "initialize", {"clientInfo": {"name": "threaddesk_bigplan_loop", "version": "1"}}
        )
        result = await rpc(2, "account/rateLimits/read", {})
        rate = result.get("rateLimits") or {}
        windows = [rate[k] for k in ("primary", "secondary") if rate.get(k)]
        if (
            not result.get("ordinaryUsageAllowed")
            or rate.get("spendControlReached")
            or not windows
            or rate.get("planType") in (None, "api")
            or any(
                type(w.get("usedPercent")) not in (int, float)
                or not math.isfinite(w["usedPercent"])
                or not 0 <= w["usedPercent"] < 100
                for w in windows
            )
        ):
            raise RuntimeError("Subscription quota unavailable or exhausted")
        # No account IDs, credentials or private usage details in public reports.
        return {
            "observed_at": time.time(),
            "source": "Codex account/rateLimits/read",
            "subscription_confirmed": True,
        }
    finally:
        if process.returncode is None:
            process.terminate()
        try:
            await asyncio.wait_for(process.wait(), 5)
        except TimeoutError:
            process.kill()
            await process.wait()


def configuration(profile):
    root = str(Path(profile["cwd"]).resolve(strict=True))
    state = Path(profile["state_dir"]).resolve()
    productive = Path.home() / ".local/share/kirabridge"
    if state == productive or state == productive / "state":
        raise ValueError("A dedicated state directory is required")
    if not Path(root, ".git").exists():
        raise ValueError("Dedicated worktree required")
    caps = [
        "bridge.health",
        "task.read",
        "agent.execute",
        "team.manage",
        "team.read",
        "team.write",
        "threaddesk.read",
        "threaddesk.manage",
    ]
    principals = {}
    for name in ("local", "codex", "grok", "codex_verify"):
        env_key = "BIGPLAN_LOOP_TOKEN_" + name.upper()
        os.environ[env_key] = secrets.token_urlsafe(40)
        principals[name] = {
            "approval_mode": "automatic",
            "capabilities": caps,
            "roots": [root],
            "read_roots": [root],
            "agents": [name] if name != "local" else [],
            "token_env": env_key,
            "message_peers": ["local", "codex", "grok", "codex_verify"],
        }
    return Config.model_validate(
        {
            "data_dir": str(state),
            "principals": principals,
            "terminal": {"home": str(Path.home()), "search_path": profile["search_path"]},
            "team": {
                "enabled": True,
                "concurrency": 1,
                "max_runs_per_hour": 24,
                "workers": {
                    "local": {},
                    **{
                        name: {
                            "agent": name,
                            "cwd": root,
                            "timeout": 120,
                            "execution_scope": "separate_managed_session",
                        }
                        for name in ("codex", "grok", "codex_verify")
                    },
                },
            },
            "agents": {
                "codex": {
                    "kind": "codex",
                    "executable": profile["codex"],
                    "output_schema": str(
                        Path(__file__).resolve().parents[1]
                        / "src/kirabridge/autonext/team_turn.schema.json"
                    ),
                    "sandbox_mode": profile.get("sandbox", "read-only"),
                    "api_key_env": "CODEX_API_KEY",
                },
                "codex_verify": {
                    "kind": "codex",
                    "executable": profile["codex"],
                    "output_schema": str(
                        Path(__file__).resolve().parents[1]
                        / "src/kirabridge/autonext/team_turn.schema.json"
                    ),
                    "sandbox_mode": "read-only",
                    "api_key_env": "CODEX_API_KEY",
                },
                "grok": {
                    "kind": "grok_structured",
                    "executable": profile["grok"],
                    "sandbox_mode": "read-only",
                    "api_key_env": "XAI_API_KEY",
                },
            },
            "threaddesk": {
                "enabled": True,
                "workspace": profile["workspace"],
                "source_root": profile["threaddesk_source"],
                "storage": "json",
            },
            "autonext": {
                "principal": "codex",
                "coordinator_mode": True,
                "completion_target": profile.get("completion_target"),
            },
        }
    )


def report(profile, done, text, status="working"):
    message = {
        "done": ", ".join(done)[-500:] or "Noch kein Aufgabenabschluss",
        "working": text[:600],
        "next": "Nächste gepinnte READY-Aufgabe nach erfolgreicher Prüfung",
    }
    subprocess.run(
        [
            profile["report_cli"],
            "report",
            "--instance",
            profile["instance"],
            "--agent",
            "Codex Loop",
            "--report-id",
            "loop-" + secrets.token_hex(12),
            "--status",
            status,
            "--done",
            message["done"],
            "--working",
            message["working"],
            "--next",
            message["next"],
        ],
        check=True,
        timeout=20,
        stdout=subprocess.DEVNULL,
    )


def report_worker(profile, work):
    state = work["state"]
    status = (
        "done"
        if state == "completed"
        else "blocked"
        if state in ("unknown", "blocked", "failed")
        else "stopped"
        if state == "cancelled"
        else "working"
        if state == "running"
        else "idle"
    )
    actor = (
        "Grok Review"
        if work["assignee"] == "grok"
        else "Codex Verifier"
        if work["assignee"] == "codex_verify"
        else "Codex Worker"
    )
    subprocess.run(
        [
            profile["report_cli"],
            "report",
            "--instance",
            profile["instance"] + "-" + work["id"],
            "--agent",
            actor,
            "--report-id",
            "observe-" + secrets.token_hex(12),
            "--status",
            status,
            "--done",
            "Modellturn beendet; fachliche Abnahme separat"
            if state == "completed"
            else "Kein fachlicher Abschluss bestätigt",
            "--working",
            "Vom Koordinator beobachteter TeamWorkstatus: " + state + "; Work-ID " + work["id"],
            "--next",
            "Koordinator prüft den gebundenen Core-Beleg " + str(work["core_task_id"]),
        ],
        check=True,
        timeout=20,
        stdout=subprocess.DEVNULL,
    )


def seed(bridge):
    team = bridge.teams.create(
        "codex",
        TeamCreate(
            team_id="bigplan-codex-loop",
            name="Big Plan Codex coordinator",
            coordinator="codex",
            members={
                "codex": "coordinator",
                "grok": "reviewer",
                "codex_verify": "reviewer",
                "local": "worker",
            },
            idempotency_key="loop-team-v1",
        ),
    )
    anchor = bridge.teams.delegate(
        "codex",
        TeamWorkCreate(
            team_id=team["id"],
            assignee="local",
            title="Coordinator bootstrap",
            body="Dedicated adapter profile validated; no project acceptance.",
            idempotency_key="loop-bootstrap-v1",
        ),
    )
    if anchor["state"] != "completed":
        bridge.teams.work_claim(
            "local",
            TeamWorkClaim(
                team_id=team["id"], work_id=anchor["id"], idempotency_key="bootstrap-claim"
            ),
        )
        bridge.teams.work_complete(
            "local",
            TeamWorkComplete(
                team_id=team["id"],
                work_id=anchor["id"],
                result="Dedicated coordinator profile validated",
                idempotency_key="bootstrap-complete",
            ),
        )
    return team, anchor


async def serve(path):
    import fcntl

    profile = load_profile(path)
    cfg = configuration(profile)
    cfg.state_path.mkdir(parents=True, exist_ok=True, mode=0o700)
    # One controller per dedicated profile; OS releases this lock after crash.
    lock = (cfg.state_path / "coordinator.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    marker = cfg.state_path / "coordinator-profile.json"
    identity = {
        "instance": profile["instance"],
        "cwd": str(Path(profile["cwd"]).resolve()),
        "workspace": str(Path(profile["workspace"]).resolve()),
    }
    if marker.exists():
        if json.loads(marker.read_text()) != identity:
            raise RuntimeError("Dedicated state profile identity changed")
    elif any(p.name != "coordinator.lock" for p in cfg.state_path.iterdir()):
        raise RuntimeError("Existing unowned state directory; refusing a second dispatcher")
    else:
        save(marker, identity)
    bridge = Bridge(cfg)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(64)
    cfg.port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(create_http_app(bridge), log_level="error", access_log=False)
    )
    from contextlib import nullcontext

    server.capture_signals = nullcontext
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop.set)
    active_revision = None
    last_report = 0
    last_summary = None
    worker_reports = {}
    async with bridge:
        http_task = asyncio.create_task(server.serve(sockets=[sock]))
        try:
            async with asyncio.timeout(15):
                while not server.started:
                    if http_task.done():
                        await http_task
                    await asyncio.sleep(0.05)
            team, anchor = seed(bridge)
            while not stop.is_set():
                if http_task.done():
                    await http_task
                    raise RuntimeError("Private loopback transport stopped")
                latest = load_profile(path)
                # Profile scope never changes while running. Only approval batches may be replaced.
                if {
                    k: v
                    for k, v in latest.items()
                    if k not in ("cards", "approval_revision", "enabled")
                } != {
                    k: v
                    for k, v in profile.items()
                    if k not in ("cards", "approval_revision", "enabled")
                }:
                    raise RuntimeError("Profile scope changed; explicit restart required")
                revision = digest([latest.get("approval_revision"), latest.get("cards", [])])
                state = bridge.autonext.inspect()
                if latest.get("enabled") and latest.get("cards") and revision != active_revision:
                    if state["state"] == "waiting":
                        raise RuntimeError("Cannot replace a grant while work is active")
                    await bridge.autonext.stop()
                    cache = cfg.state_path / ("grant-" + revision + ".json")
                    if cache.exists():
                        grant = AutoNextConfig.model_validate_json(cache.read_text())
                    else:
                        observation = await quota(latest["codex"])
                        grant = AutoNextConfig(
                            enabled=True,
                            coordinator_mode=True,
                            principal="codex",
                            grant_id="loop-" + revision[:40],
                            team_id=team["id"],
                            team_revision=team["revision"],
                            board_id=latest["board_id"],
                            after_work_id=anchor["id"],
                            after_result_sha256=text_sha("Dedicated coordinator profile validated"),
                            cards=latest["cards"],
                            max_tasks=len(latest["cards"]),
                            lease_seconds=900,
                            budget_state="available",
                            budget_observed_at=observation["observed_at"],
                            budget_valid_until=observation["observed_at"] + 3500,
                            budget_source_ref=observation["source"],
                            billing_evidence_ref="Cached ChatGPT subscription; API keys absent",
                            completion_target=latest.get("completion_target"),
                        )
                        save(cache, grant.model_dump())
                    cfg.autonext = grant
                    active_revision = revision
                    await bridge.autonext.start()
                if not latest.get("enabled") and cfg.autonext.enabled:
                    await bridge.autonext.stop()
                    cfg.autonext.enabled = False
                    active_revision = None
                state = bridge.autonext.inspect()
                for work in bridge.store.db.execute(
                    "SELECT id,assignee,state,core_task_id FROM team_work WHERE assignee!='local'"
                ).fetchall():
                    fingerprint = digest([work["state"], work["core_task_id"]])
                    previous = worker_reports.get(work["id"])
                    terminal = work["state"] in (
                        "completed",
                        "failed",
                        "blocked",
                        "unknown",
                        "cancelled",
                    )
                    if (
                        previous
                        and previous[0] == fingerprint
                        and (terminal or time.monotonic() - previous[1] < 60)
                    ):
                        continue
                    row = dict(work)
                    await asyncio.to_thread(report_worker, profile, row)
                    worker_reports[row["id"]] = (fingerprint, time.monotonic())
                save(
                    cfg.state_path / "status.json",
                    {
                        "observed_at": time.time(),
                        "pid": os.getpid(),
                        "execution_scope": "separate_managed_session",
                        "autonext": state,
                    },
                )
                done = [
                    r["task_id"]
                    for r in bridge.store.db.execute(
                        "SELECT task_id FROM autonext_items WHERE state='completed' ORDER BY rowid"
                    )
                ]
                summary = digest([state, done])
                if time.monotonic() - last_report >= 60 or summary != last_summary:
                    mode = (
                        "blocked"
                        if state["state"] == "stopped"
                        else "idle"
                        if state["state"] in ("disabled", "complete", "idle")
                        else "working"
                    )
                    await asyncio.to_thread(
                        report,
                        profile,
                        done,
                        "Koordinator: " + state["state"] + " / " + str(state.get("reason")),
                        mode,
                    )
                    last_report = time.monotonic()
                    last_summary = summary
                try:
                    await asyncio.wait_for(stop.wait(), 5)
                except TimeoutError:
                    pass
        finally:
            server.should_exit = True
            await http_task
            sock.close()


def approve(path, entries):
    from kirabridge.autonext.models import ReadyCard
    from kirabridge.whiteboard_read import read_whiteboard

    if not 1 <= len(entries) <= 16:
        raise ValueError("Select 1–16 explicitly approved entry IDs")
    profile = load_profile(path)
    pins = []
    for entry_id in entries:
        entry = read_whiteboard(profile["workspace"], profile["board_id"], entry_id)["entry"]
        if entry.get("truncated"):
            raise ValueError("Cannot approve a truncated source")
        card = ReadyCard.model_validate_json(entry["content"])
        if (
            entry["entry_type"] != "task"
            or card.state != "READY"
            or card.cwd != str(Path(profile["cwd"]).resolve())
            or card.sandbox != profile.get("sandbox", "read-only")
            or card.acceptance.kind != "coordinator_checks"
        ):
            raise ValueError("Card must match this dedicated coordinator scope and acceptance")
        pins.append(
            {
                "task_id": card.task_id,
                "entry_id": entry_id,
                "content_sha256": text_sha(entry["content"]),
            }
        )
    if len({p["task_id"] for p in pins}) != len(pins):
        raise ValueError("Duplicate task ID")
    profile.update(cards=pins, approval_revision=secrets.token_hex(16), enabled=True)
    save(path, profile)
    print(json.dumps({"approved": len(pins), "task_ids": [p["task_id"] for p in pins]}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("action", choices=["serve", "status", "quota", "approve"])
    parser.add_argument("--entry-id", action="append", default=[])
    args = parser.parse_args()
    if args.action == "serve":
        asyncio.run(serve(args.profile))
    elif args.action == "approve":
        approve(args.profile, args.entry_id)
    elif args.action == "quota":
        print(json.dumps(asyncio.run(quota(load_profile(args.profile)["codex"]))))
    else:
        profile = load_profile(args.profile)
        print((Path(profile["state_dir"]) / "status.json").read_text())


if __name__ == "__main__":
    main()
