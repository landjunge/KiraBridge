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
import time
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

import uvicorn
from pydantic import BaseModel, ConfigDict, Field, model_validator

from kirabridge.autonext.continuation import (
    ContinuationPolicy,
    bind_scope,
    checks_allowed,
    discover,
    restore,
    validate_source,
)
from kirabridge.autonext.manager import digest, text_sha
from kirabridge.autonext.models import ApprovedCard, AutoNextConfig
from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import Config
from kirabridge.capability_routing.router import NativeRoutingSettings, WorkerRouting
from kirabridge.cli_adapters.claude import login_evidence
from kirabridge.coordinator_reporting import run_status_report
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
    continuation: ContinuationPolicy | None = None
    routing: NativeRoutingSettings | None = None
    worker_routing: dict[Literal["codex", "grok", "codex_verify"], WorkerRouting] = Field(
        default_factory=dict
    )
    quota_events: list[str] = Field(default_factory=list, max_length=16)
    # Opt-in role selection. "codex" (default) leaves every existing route unchanged.
    # "claude" runs worker and verifier as separate Claude Code headless turns; the
    # verifier is technically read-only. Budget is not decided here: every Claude turn
    # reserves/settles through the budget gate (TollGate BP-TG-01, fail closed until bound).
    coordinator_cli: Literal["codex", "claude"] = "codex"
    claude: str | None = None

    worker_timeouts: dict[
        Literal["codex", "grok", "codex_verify"], Annotated[float, Field(gt=0, le=300)]
    ] = Field(default_factory=dict)

    @model_validator(mode="after")
    def claude_profile(self):
        if self.coordinator_cli == "claude" and (
            not self.claude
            or not Path(self.claude).is_absolute()
            or self.routing is not None
            or self.worker_routing
        ):
            raise ValueError("Claude coordinator needs an absolute executable and no routing")
        return self


def load_profile(path):
    return LoopProfile.model_validate_json(path.read_text()).model_dump()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temporary.chmod(0o600)
    temporary.replace(path)


def fixed_profile(profile):
    fixed = {k: v for k, v in profile.items() if k not in ("cards", "approval_revision", "enabled")}
    if fixed.get("continuation"):
        fixed["continuation"] = {k: v for k, v in fixed["continuation"].items() if k != "sources"}
    return fixed


QUOTA_LOG_ROOT = Path.home() / ".codex/sessions"


def native_quota(paths):
    """Fresh native usage events only; no transcript or model-authored assertions."""
    latest = None
    for name in paths:
        path = Path(name)
        if not path.resolve().is_relative_to(QUOTA_LOG_ROOT.resolve()) or path.is_symlink():
            raise ValueError("Quota events must be native Codex session logs")
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            handle.seek(max(0, handle.tell() - 262144))
            for line in handle:
                try:
                    event = json.loads(line)
                    payload = event.get("payload") or {}
                    if event.get("type") != "event_msg" or payload.get("type") != "token_count":
                        continue
                    rate = payload.get("rate_limits") or {}
                    if rate.get("limit_id") != "codex":
                        continue
                    at = datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
                    if at.tzinfo is None:
                        continue
                    stamp = at.timestamp()
                    if not time.time() - 300 <= stamp <= time.time() + 2:
                        continue
                    if latest is None or stamp > latest[0]:
                        latest = (stamp, rate, text_sha(line.decode("utf-8")), False)
                    elif stamp == latest[0] and rate != latest[1]:
                        latest = (*latest[:3], True)
                except (ValueError, KeyError, TypeError):
                    continue
    if latest is None:
        return None
    stamp, rate, sha, conflict = latest
    if conflict:
        raise RuntimeError("Conflicting native quota observations at the latest timestamp")
    windows = [rate[key] for key in ("primary", "secondary") if rate.get(key)]
    if (
        rate.get("plan_type")
        not in {"plus", "pro", "prolite", "team", "business", "enterprise", "edu"}
        or not windows
        or rate.get("spend_control_reached")
        or rate.get("rate_limit_reached_type")
        or any(
            type(w.get("used_percent")) not in (int, float)
            or not math.isfinite(w["used_percent"])
            or not 0 <= w["used_percent"] < 100
            or type(w.get("resets_at")) not in (int, float)
            or not math.isfinite(w["resets_at"])
            or w["resets_at"] <= time.time()
            for w in windows
        )
    ):
        raise RuntimeError("Native subscription quota is unavailable or exhausted")
    return {
        "observed_at": stamp,
        "source": "Codex native rate_limits sha256:" + sha,
        "subscription_confirmed": True,
    }


async def quota(codex, events=None):
    """Read account state only; never buys credits or issues a model request."""
    if any(os.environ.get(k) for k in ("OPENAI_API_KEY", "CODEX_API_KEY", "XAI_API_KEY")):
        raise RuntimeError("API-key billing is not authorized for this loop")
    if events and (observed := native_quota(events)) is not None:
        return observed
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
        process.stdin.write((json.dumps({"method": "initialized", "params": {}}) + "\n").encode())
        await process.stdin.drain()
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


def claude_mode(profile):
    return profile.get("coordinator_cli") == "claude"


async def grant_quota(profile, gate=None):
    """Quota evidence for a new grant. Claude budget is TollGate's, never estimated here."""
    if claude_mode(profile):
        from kirabridge.autonext.budget import FailClosedBudgetGate

        if not (gate or FailClosedBudgetGate()).ready:
            raise RuntimeError("Claude budget authority (TollGate BP-TG-01) is not bound")
        return await asyncio.to_thread(login_evidence, profile["claude"])
    if profile.get("quota_events"):
        return await quota(profile["codex"], profile["quota_events"])
    return await quota(profile["codex"])


def agent_profiles(profile):
    claude = profile.get("coordinator_cli") == "claude"
    schema = str(
        Path(__file__).resolve().parents[1] / "src/kirabridge/autonext/team_turn.schema.json"
    )
    if claude:
        main = {
            "codex": {
                "kind": "claude_worker",
                "executable": profile["claude"],
                "sandbox_mode": profile.get("sandbox", "read-only"),
                "api_key_env": "ANTHROPIC_API_KEY",
            },
            "codex_verify": {
                "kind": "claude_verify",
                "executable": profile["claude"],
                "sandbox_mode": "read-only",
                "api_key_env": "ANTHROPIC_API_KEY",
            },
        }
    else:
        main = {
            "codex": {
                "kind": "codex",
                "executable": profile["codex"],
                "output_schema": schema,
                "sandbox_mode": profile.get("sandbox", "read-only"),
                "api_key_env": "CODEX_API_KEY",
            },
            "codex_verify": {
                "kind": "codex",
                "executable": profile["codex"],
                "output_schema": schema,
                "sandbox_mode": "read-only",
                "api_key_env": "CODEX_API_KEY",
            },
        }
    return {
        **main,
        "grok": {
            "kind": "grok_structured",
            "executable": profile["grok"],
            "sandbox_mode": "read-only",
            "api_key_env": "XAI_API_KEY",
        },
    }


def configuration(profile):
    root = str(Path(profile["cwd"]).resolve(strict=True))
    roots = [root]
    if profile.get("continuation"):
        roots = sorted(set(roots + profile["continuation"]["allowed_cwds"]))
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
            "roots": roots,
            "read_roots": roots,
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
                "routing": profile.get("routing"),
                "concurrency": 1,
                "max_runs_per_hour": 24,
                "workers": {
                    "local": {},
                    **{
                        name: {
                            "agent": name,
                            "cwd": root,
                            "timeout": profile.get("worker_timeouts", {}).get(name, 120),
                            "execution_scope": "separate_managed_session",
                            "routing": profile.get("worker_routing", {}).get(name),
                        }
                        for name in ("codex", "grok", "codex_verify")
                    },
                },
            },
            "agents": agent_profiles(profile),
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
    report_id = "loop-" + secrets.token_hex(12)
    message = {
        "done": ", ".join(done)[-500:] or "Noch kein Aufgabenabschluss",
        "working": text[:600],
        "next": "Nächste passende bestehende Aufgabe im beauftragten Umfang",
    }
    return run_status_report(
        [
            profile["report_cli"],
            "report",
            "--instance",
            profile["instance"],
            "--agent",
            "Codex Loop",
            "--report-id",
            report_id,
            "--status",
            status,
            "--done",
            message["done"],
            "--working",
            message["working"],
            "--next",
            message["next"],
        ],
        report_id=report_id,
    )


def report_worker(profile, work):
    report_id = "observe-" + secrets.token_hex(12)
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
    return run_status_report(
        [
            profile["report_cli"],
            "report",
            "--instance",
            profile["instance"] + "-" + work["id"],
            "--agent",
            actor,
            "--report-id",
            report_id,
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
        report_id=report_id,
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
    return team, bridge.teams.work_get("codex", team["id"], anchor["id"])


async def advance(bridge, profile, team, anchor, active_revision):
    """One deterministic supervisor step; only a selected task probes quota."""
    cfg = bridge.config
    if profile.get("continuation"):
        if not profile["enabled"]:
            await bridge.autonext.stop()
            cfg.autonext.enabled = False
            cfg.team.enabled = False
            return active_revision, None
        was_disabled = not cfg.team.enabled
        cfg.team.enabled = True
        if was_disabled:
            await bridge.team_dispatcher.start()
        if active_revision and not cfg.autonext.enabled:
            cfg.autonext.enabled = True
            await bridge.autonext.start()
    state = bridge.autonext.inspect()
    intake, candidate = None, None
    revision = digest([profile.get("approval_revision"), profile.get("cards", [])])
    if profile.get("enabled") and profile.get("continuation"):
        intake = discover(bridge, profile)
        if state["state"] != "waiting":
            candidate = intake["selected"]
        if candidate and not bind_scope(bridge, candidate["card"]):
            candidate = None
        revision = candidate["grant_id"] if candidate else active_revision
    pins = [candidate["pin"].model_dump()] if candidate else profile.get("cards", [])
    if (
        profile.get("enabled")
        and pins
        and revision != active_revision
        and (not profile.get("continuation") or candidate)
    ):
        if state["state"] == "waiting":
            raise RuntimeError("Cannot replace a grant while work is active")
        await bridge.autonext.stop()
        cache = cfg.state_path / ("grant-" + revision + ".json")
        if cache.exists():
            grant = AutoNextConfig.model_validate_json(cache.read_text())
        else:
            failure = getattr(bridge, "continuation_resource_stop", None)
            if intake and failure and time.time() < failure["retry_after"]:
                intake["resource_stop"] = failure
                return active_revision, intake
            try:
                observation = await grant_quota(
                    profile, getattr(bridge.agents, "budget_gate", None)
                )
            except (TimeoutError, RuntimeError, OSError, ValueError) as error:
                if intake is None:
                    raise
                failure = {
                    "reason": "subscription_observation_unavailable",
                    "error_type": type(error).__name__,
                    "observed_at": time.time(),
                    "retry_after": time.time() + 60,
                }
                bridge.continuation_resource_stop = failure
                intake["resource_stop"] = failure
                return active_revision, intake
            bridge.continuation_resource_stop = None
            grant = AutoNextConfig(
                enabled=True,
                coordinator_mode=True,
                principal="codex",
                grant_id=candidate["grant_id"] if candidate else "loop-" + revision[:40],
                team_id=team["id"],
                team_revision=team["revision"],
                board_id=profile["board_id"],
                after_work_id=anchor["id"],
                after_result_sha256=text_sha(anchor["result"]),
                cards=pins,
                max_tasks=len(pins),
                lease_seconds=900,
                budget_state="available",
                budget_observed_at=observation["observed_at"],
                budget_valid_until=observation["observed_at"] + 3500,
                budget_source_ref=observation["source"],
                billing_evidence_ref=(
                    "Claude subscription login (claude.ai); API keys absent"
                    if claude_mode(profile)
                    else "Cached ChatGPT subscription; API keys absent"
                ),
                completion_target=profile.get("completion_target"),
            )
            save(cache, grant.model_dump())
        cfg.autonext = grant
        active_revision = revision
        await bridge.autonext.start()
    if not profile.get("enabled") and cfg.autonext.enabled:
        await bridge.autonext.stop()
        cfg.autonext.enabled = False
        active_revision = None
    return active_revision, intake


def process_completions(bridge, profile):
    """Consume the existing durable inbox after validating its original outbox."""
    target = profile.get("completion_target")
    if not target:
        return {"processed": [], "pending": 0}
    processed = []
    sources = bridge.store.db.execute(
        "SELECT DISTINCT source_id FROM completion_notices WHERE principal='codex' AND target=? "
        "AND source='autonext' AND acknowledged IS NULL ORDER BY seq LIMIT 20",
        (target,),
    ).fetchall()
    notices = []
    for row in sources:
        notices.extend(
            bridge.completions.receive("codex", target, limit=50, source_id=row["source_id"])[
                "notices"
            ]
        )
    for notice in notices:
        payload = notice["payload"]
        if payload.get("source") != "autonext":
            continue
        refs = payload.get("evidence_refs", {})
        outbox = bridge.store.db.execute(
            "SELECT * FROM autonext_outbox WHERE key=? AND grant_id=? AND task_id=?",
            (refs.get("autonext_outbox_key"), payload.get("grant_id"), payload.get("task_id")),
        ).fetchone()
        if (
            not outbox
            or not outbox["verified"]
            or outbox["phase"] != payload.get("phase")
            or text_sha(outbox["content"]) != refs.get("content_sha256")
        ):
            continue  # Keep the original notice pending until its board readback is known.
        bridge.completions.ack("codex", notice["id"], notice["receipt"])
        processed.append(notice["id"])
    return {"processed": processed, "pending": len(notices) - len(processed)}


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
    if profile.get("continuation"):
        bridge.autonext.continuation_guard = lambda card: validate_source(
            bridge, load_profile(path), card
        )
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
    reporting = {"coordinator": None, "workers": {}}
    team, anchor = seed(bridge)
    if profile.get("continuation"):
        active_revision = restore(bridge, profile)
        cfg.team.enabled = profile["enabled"]
    async with bridge:
        http_task = asyncio.create_task(server.serve(sockets=[sock]))
        try:
            async with asyncio.timeout(15):
                while not server.started:
                    if http_task.done():
                        await http_task
                    await asyncio.sleep(0.05)
            while not stop.is_set():
                if http_task.done():
                    await http_task
                    raise RuntimeError("Private loopback transport stopped")
                latest = load_profile(path)
                # Profile scope never changes while running. Only approval batches may be replaced.
                if fixed_profile(latest) != fixed_profile(profile):
                    raise RuntimeError("Profile scope changed; explicit restart required")
                active_revision, intake = await advance(
                    bridge, latest, team, anchor, active_revision
                )
                processed = process_completions(bridge, latest)
                state = bridge.autonext.inspect()
                for work in bridge.store.db.execute(
                    "SELECT id,assignee,state,core_task_id FROM team_work WHERE assignee!='local'"
                ).fetchall():
                    if stop.is_set():
                        break
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
                    reporting["workers"][row["id"]] = await asyncio.to_thread(
                        report_worker, profile, row
                    )
                    worker_reports[row["id"]] = (fingerprint, time.monotonic())
                    # A stop signal queued from another thread may not have run yet when the
                    # report thread returns; let it run before deciding to start another report.
                    await asyncio.sleep(0)
                done = [
                    r["task_id"]
                    for r in bridge.store.db.execute(
                        "SELECT task_id FROM autonext_items WHERE state='completed' ORDER BY rowid"
                    )
                ]
                summary = digest([state, done])
                if not stop.is_set() and (
                    time.monotonic() - last_report >= 60 or summary != last_summary
                ):
                    mode = (
                        "blocked"
                        if (state["state"] == "stopped" and not intake)
                        or (intake and intake.get("resource_stop"))
                        else "idle"
                        if state["state"] in ("disabled", "complete", "idle")
                        else "working"
                    )
                    reporting["coordinator"] = await asyncio.to_thread(
                        report,
                        profile,
                        done,
                        "Koordinator: " + state["state"] + " / " + str(state.get("reason")),
                        mode,
                    )
                    last_report = time.monotonic()
                    last_summary = summary
                    await asyncio.sleep(0)  # let a pending stop signal run (see worker reports)
                save(
                    cfg.state_path / "status.json",
                    {
                        "observed_at": time.time(),
                        "pid": os.getpid(),
                        "execution_scope": "separate_managed_session",
                        "autonext": state,
                        "completions": processed,
                        "reporting": reporting,
                        "continuation": {
                            "authority_ref": intake["authority_ref"],
                            "source_revision": intake["source_revision"],
                            "held": intake["held"],
                            "selected_task": intake["selected"]["card"].task_id
                            if intake["selected"]
                            else None,
                            "state": "working" if state["state"] == "waiting" else "watching",
                            "resource_stop": intake.get("resource_stop"),
                        }
                        if intake
                        else None,
                    },
                )
                if stop.is_set():
                    break
                try:
                    if (
                        latest.get("completion_target")
                        and not processed["pending"]
                        and cfg.autonext.cards
                    ):
                        await bridge.completions.wait(
                            "codex",
                            latest["completion_target"],
                            wait_seconds=5,
                            source_id=cfg.autonext.cards[0].task_id,
                        )
                    else:
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


def adopt(path, entries):
    """Coordinator assignment under the existing mandate; no new user approval."""
    from kirabridge.autonext.models import ReadyCard
    from kirabridge.whiteboard_read import read_whiteboard

    profile = load_profile(path)
    policy = ContinuationPolicy.model_validate(profile["continuation"])
    if not entries:
        raise ValueError("Select existing task entries to assign")
    for entry_id in entries:
        entry = read_whiteboard(profile["workspace"], profile["board_id"], entry_id)["entry"]
        card = ReadyCard.model_validate_json(entry["content"])
        if (
            entry["entry_type"] != "task"
            or entry.get("truncated")
            or card.state != "READY"
            or card.cwd not in policy.allowed_cwds
            or card.product not in policy.products
            or card.acceptance.kind != "coordinator_checks"
            or not checks_allowed(policy, card)
            or (card.sandbox == "workspace-write" and profile["sandbox"] != "workspace-write")
        ):
            raise ValueError("Task does not match the existing continuation mandate")
        pin = ApprovedCard(
            task_id=card.task_id, entry_id=entry_id, content_sha256=text_sha(entry["content"])
        )
        if any(source.task_id == pin.task_id and source != pin for source in policy.sources):
            raise ValueError("Logical task already has another source assignment")
        if pin not in policy.sources:
            policy.sources.append(pin)
    profile["continuation"] = policy.model_dump()
    save(path, profile)
    print(json.dumps({"assigned": len(entries), "authority_ref": policy.authority_ref}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("action", choices=["serve", "status", "quota", "approve", "adopt"])
    parser.add_argument("--entry-id", action="append", default=[])
    args = parser.parse_args()
    if args.action == "serve":
        asyncio.run(serve(args.profile))
    elif args.action == "approve":
        approve(args.profile, args.entry_id)
    elif args.action == "adopt":
        adopt(args.profile, args.entry_id)
    elif args.action == "quota":
        profile = load_profile(args.profile)
        print(json.dumps(asyncio.run(grant_quota(profile))))
    else:
        profile = load_profile(args.profile)
        print((Path(profile["state_dir"]) / "status.json").read_text())


if __name__ == "__main__":
    main()
