"""Bounded event-driven continuation; TeamDispatcher remains the sole executor.

Trusted configuration pins immutable board cards. Claims, CWD leases, outbox and
acceptance receipts share the existing Store transaction. No board/model string
is interpreted as an operation, shell command, permission or provider choice.
"""

import asyncio
import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from kirabridge.autonext.models import SHA, ReadyCard
from kirabridge.bridge_core.models import BridgeError, canonical, digest
from kirabridge.completion_manager import record_notice, valid_target
from kirabridge.filesystem_manager import PathScope
from kirabridge.team_manager.models import TeamWorkCreate
from kirabridge.whiteboard_read import append_whiteboard, read_whiteboard

SCHEMA = """
CREATE TABLE IF NOT EXISTS autonext_runs (
 grant_id TEXT PRIMARY KEY, config_ref TEXT NOT NULL, state TEXT NOT NULL,
 reason TEXT, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS autonext_items (
 task_id TEXT PRIMARY KEY, grant_id TEXT NOT NULL, source_ref TEXT NOT NULL,
 card TEXT NOT NULL, work_id TEXT UNIQUE NOT NULL, cwd TEXT NOT NULL,
 cwd_ref TEXT NOT NULL, state TEXT NOT NULL, lease_until REAL NOT NULL,
 claim_published INTEGER NOT NULL DEFAULT 0, receipt TEXT
);
CREATE TABLE IF NOT EXISTS autonext_leases (
 cwd TEXT PRIMARY KEY, task_id TEXT UNIQUE NOT NULL, owner TEXT NOT NULL,
 expires REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS autonext_outbox (
 key TEXT PRIMARY KEY, grant_id TEXT NOT NULL, task_id TEXT NOT NULL, phase TEXT NOT NULL,
 content TEXT NOT NULL, entry_id TEXT, verified INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS autonext_confirmations (
 task_id TEXT PRIMARY KEY, result_sha256 TEXT NOT NULL, actor TEXT NOT NULL,
 evidence_sha256 TEXT NOT NULL, created REAL NOT NULL
);
"""
TERMINAL = {"failed", "blocked", "unknown", "cancelled"}


def text_sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def worktree_root(path):
    path = Path(path).resolve()
    for candidate in (path, *path.parents):
        marker = candidate / ".git"
        if marker.is_symlink():
            raise BridgeError("autonext_identity_changed", "Git worktree marker is ambiguous")
        if marker.is_file() or marker.is_dir():
            return candidate
    return path


def overlaps(first, second):
    a, b = worktree_root(first), worktree_root(second)
    return a.is_relative_to(b) or b.is_relative_to(a)


class AutoNextManager:
    def __init__(self, bridge):
        self.bridge, self.store = bridge, bridge.store
        self.owner = uuid4().hex
        self.wake = asyncio.Event()
        self.loop = self.worker = None
        self.stopping = False
        self.faulted = False
        self.lock = asyncio.Lock()
        with self.store.transaction():
            for statement in SCHEMA.split(";"):
                if statement.strip():
                    self.store.db.execute(statement)

    @property
    def settings(self):
        return self.bridge.config.autonext

    def _run(self):
        return self.store.db.execute(
            "SELECT * FROM autonext_runs WHERE grant_id=?", (self.settings.grant_id,)
        ).fetchone()

    def inspect(self):
        run = self._run()
        return {
            "enabled": self.settings.enabled,
            "state": "stopped"
            if self.faulted
            else run["state"]
            if run
            else "idle"
            if self.settings.enabled
            else "disabled",
            "reason": "autonext_state_unknown"
            if self.faulted
            else run["reason"]
            if run
            else "not_started",
            "grant_id": self.settings.grant_id or None,
            "source": "explicit operator-pinned board entries only",
            "scope": "continuation status; not project acceptance or provider quota proof",
        }

    def notify(self):
        if self.loop is not None and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self.wake.set)

    async def start(self):
        if not self.settings.enabled or self.worker is not None:
            return
        self.loop = asyncio.get_running_loop()
        self.stopping = False
        self.bridge.teams.on_change = self.notify
        self.worker = asyncio.create_task(self._loop())

    async def stop(self):
        self.stopping = True
        self.wake.set()
        try:
            if self.worker is not None:
                outcomes = await asyncio.gather(self.worker, return_exceptions=True)
                self.faulted |= any(isinstance(value, BaseException) for value in outcomes)
        finally:
            self.worker = None
            if self.bridge.teams.on_change == self.notify:
                self.bridge.teams.on_change = None
            self.loop = None

    async def _loop(self):
        while not self.stopping:
            self.wake.clear()
            try:
                await self.tick()
            except Exception:
                self.faulted = True
                try:
                    self._setup()
                    self._stop("autonext_state_unknown")
                    self._flush()
                except Exception:
                    pass
                return
            if self.stopping:
                return
            active = self.store.db.execute(
                "SELECT min(lease_until) FROM autonext_items WHERE grant_id=? AND state='waiting'",
                (self.settings.grant_id,),
            ).fetchone()[0]
            deadline = min(active, self.settings.budget_valid_until) if active else None
            try:
                if deadline is None or self.inspect()["state"] in {"stopped", "complete"}:
                    await self.wake.wait()
                else:
                    await asyncio.wait_for(self.wake.wait(), max(0.01, deadline - time.time()))
            except TimeoutError:
                pass  # One lease/budget deadline, never periodic whiteboard polling.

    def _workspace(self, capability):
        self.bridge.security.principal(self.settings.principal, capability)
        desk = self.bridge.config.threaddesk
        if not desk.enabled or not desk.workspace:
            raise BridgeError(
                "autonext_source_unavailable", "Configured board source is unavailable"
            )
        return desk.workspace

    def _card(self, approved):
        entry = read_whiteboard(
            self._workspace("threaddesk.read"), self.settings.board_id, approved.entry_id
        )["entry"]
        if entry["truncated"] or text_sha(entry["content"]) != approved.content_sha256:
            raise BridgeError("autonext_source_changed", "Approved card bytes changed")
        try:
            card = ReadyCard.model_validate_json(entry["content"])
        except (ValidationError, ValueError, RecursionError):
            raise BridgeError(
                "autonext_card_invalid", "Expected one complete typed task card"
            ) from None
        if card.task_id != approved.task_id:
            raise BridgeError("autonext_identity_changed", "Approved task identity differs")
        return card

    def _identity(self, card):
        if card.acceptance.kind == "coordinator_checks" and not getattr(
            self, "supports_coordinator_checks", False
        ):
            raise BridgeError(
                "autonext_coordinator_required", "Explicit coordinator adapter required"
            )
        cfg = self.bridge.config
        team = self.bridge.teams.get(self.settings.principal, self.settings.team_id)
        if team["revision"] != self.settings.team_revision:
            raise BridgeError("autonext_identity_changed", "Team revision changed")
        worker = cfg.team.workers.get("codex")
        agent = cfg.agents.get("codex")
        if (
            not worker
            or worker.agent != "codex"
            or not agent
            or agent.kind not in {"codex", "claude_worker"}
        ):
            raise BridgeError("autonext_worker_unavailable", "Fixed worker is unavailable")
        path = Path(card.cwd)
        if not path.is_absolute() or path.is_symlink() or path.resolve(strict=True) != path:
            raise BridgeError("autonext_identity_changed", "Task worktree identity is ambiguous")
        if Path(worker.cwd).resolve(strict=True) != path:
            raise BridgeError("autonext_scope_changed", "Fixed worker worktree differs")
        policy = self.bridge.security.principal("codex", "agent.execute")
        PathScope(policy.roots).split(str(path))
        if agent.sandbox_mode != card.sandbox or agent.bridge_tools:
            raise BridgeError(
                "autonext_scope_changed", "Executor exceeds the approved sandbox scope"
            )
        stat = path.stat()
        root = worktree_root(path)
        root_stat = root.stat()
        marker = root / ".git"
        marker_stat = marker.stat() if marker.exists() else None
        return str(path), digest(
            [
                str(path),
                stat.st_dev,
                stat.st_ino,
                str(root),
                root_stat.st_dev,
                root_stat.st_ino,
                [marker_stat.st_dev, marker_stat.st_ino] if marker_stat else None,
            ]
        )

    def _budget(self):
        cfg, now = self.settings, time.time()
        agent = self.bridge.config.agents.get("codex")
        claude = bool(agent and agent.kind == "claude_worker")
        if (
            cfg.budget_state != ("user_acknowledged_unknown" if claude else "available")
            or not cfg.budget_source_ref
            or not 0 < cfg.budget_observed_at <= now + 2
            or not now < cfg.budget_valid_until <= cfg.budget_observed_at + 3600
        ):
            raise BridgeError("autonext_budget_stop", "Budget availability is unknown or expired")
        keys = (
            {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"}
            if claude
            else {"OPENAI_API_KEY", "CODEX_API_KEY"}
        ) | {agent.api_key_env if agent else ""}
        from kirabridge.agent_manager import agent_environment

        effective = agent_environment(agent, self.bridge.terminal) if agent else {}
        if not cfg.billing_evidence_ref or any(
            os.environ.get(key) or effective.get(key) for key in keys if key
        ):
            raise BridgeError(
                "autonext_billing_unknown", "Existing subscription route is not confirmed"
            )

    def _queue_note(self, task_id, phase, details):
        key = "autonext-" + digest([self.settings.grant_id, task_id, phase])[:48]
        if phase == "claimed" and getattr(self, "continuation_guard", None):
            key = "autonext-claim-" + digest([self.settings.board_id, task_id])[:40]
        content = canonical(
            {
                "autonext": 1,
                "task_id": task_id,
                "grant_id": self.settings.grant_id,
                "phase": phase,
                **details,
            }
        )
        inserted = self.store.db.execute(
            "INSERT OR IGNORE INTO autonext_outbox(key,grant_id,task_id,phase,content) "
            "VALUES(?,?,?,?,?)",
            (key, self.settings.grant_id, task_id, phase, content),
        )
        if (
            inserted.rowcount != 1
            or phase not in {"completed", "stopped"}
            or not self.settings.coordinator_mode
            or self.settings.completion_target is None
        ):
            return
        # All callers own the source/state transaction. The existing outbox row
        # is the event identity, so replay/restart neither backfills nor executes.
        event_seq = inserted.lastrowid
        evidence = {"autonext_outbox_key": key, "content_sha256": text_sha(content)}
        for name in ("receipt_sha256", "result_sha256"):
            value = details.get(name)
            if isinstance(value, str) and re.fullmatch(SHA, value):
                evidence[name] = value
        completed = phase == "completed"
        payload = {
            "source": "autonext",
            "task_id": task_id,
            "grant_id": self.settings.grant_id,
            "team_id": self.settings.team_id,
            "phase": phase,
            "state": phase,
            "outcome": "success" if completed else "stopped",
            "completion_scope": "accepted_autonext_task"
            if completed
            else "autonext_continuation_stop",
            "agent_work_completion_verified": completed,
            "project_completion_verified": False,
            "chat_completion_verified": False,
            "automatic_retry": False,
            "event_seq": event_seq,
            "evidence_refs": evidence,
        }
        record_notice(
            self.store,
            self.settings.principal,
            valid_target(self.settings.completion_target),
            "autonext",
            task_id,
            event_seq,
            payload,
        )

    def _flush(self):
        # Serialize local append/readback with the durable outbox. A crash after
        # append rolls back this transaction; the exact same external key/body
        # is reconciled by the existing append API, never by a replacement key.
        with self.store.transaction():
            rows = self.store.db.execute(
                "SELECT o.* FROM autonext_outbox o WHERE o.grant_id=? AND o.verified=0 "
                "ORDER BY o.rowid",
                (self.settings.grant_id,),
            ).fetchall()
            for row in rows:
                workspace = self._workspace("threaddesk.manage")
                result = append_whiteboard(
                    workspace,
                    self.settings.board_id,
                    actor="KiraBridge AutoNext",
                    actor_type="system",
                    entry_type="result"
                    if row["phase"] == "completed"
                    else "problem"
                    if row["phase"] == "stopped"
                    else "progress",
                    content=row["content"],
                    external_key=row["key"],
                )
                read = read_whiteboard(workspace, self.settings.board_id, result["id"])["entry"]
                if read["truncated"] or read["content"] != row["content"]:
                    raise BridgeError("autonext_receipt_unknown", "Board receipt readback differs")
                self.store.db.execute(
                    "UPDATE autonext_outbox SET entry_id=?,verified=1 WHERE key=?",
                    (result["id"], row["key"]),
                )
                if row["phase"] == "claimed":
                    self.store.db.execute(
                        "UPDATE autonext_items SET claim_published=1 WHERE task_id=?",
                        (row["task_id"],),
                    )
        self.bridge.teams.wake.set()

    def _stop(self, reason, item=None):
        with self.store.transaction():
            if self._run() and self._run()["state"] == "stopped":
                return
            self.store.db.execute(
                "UPDATE autonext_runs SET state='stopped',reason=? WHERE grant_id=?",
                (reason, self.settings.grant_id),
            )
            self._queue_note(
                item["task_id"] if item else "grant-" + self.settings.grant_id,
                "stopped",
                {"reason": reason, "automatic_retry": False},
            )
        # No provider cancellation, lease stealing, permission grant or retry here.

    def _setup(self):
        with self.store.transaction():
            self.store.db.execute(
                "INSERT OR IGNORE INTO autonext_runs VALUES(?,?,'idle',NULL,?)",
                (self.settings.grant_id, self._configuration_ref(), time.time()),
            )
            if self._run()["config_ref"] != self._configuration_ref():
                raise BridgeError("autonext_grant_changed", "Grant configuration changed; stop")

    def _configuration_ref(self):
        cfg = self.bridge.config
        grant = self.settings.model_dump()
        if grant["completion_target"] is None:
            del grant["completion_target"]  # Preserve existing opt-out grant fingerprints.
        worker, agent = cfg.team.workers.get("codex"), cfg.agents.get("codex")
        executable = (
            shutil.which(
                agent.executable or "codex", path=self.bridge.terminal.environment.get("PATH")
            )
            if agent
            else None
        )
        file_ref = None
        if executable:
            path = Path(executable).resolve(strict=True)
            stat = path.stat()
            file_ref = [str(path), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns]
        policy = cfg.principals.get("codex")
        binding = {
            "grant": grant,
            "worker": worker.model_dump() if worker else None,
            "agent": agent.model_dump() if agent else None,
            "executor_file": file_ref,
            "policy": policy.model_dump() if policy else None,
            "operator_policy": cfg.principals[self.settings.principal].model_dump(),
            "route": cfg.visible_handoffs.model_dump(),
            "team_enabled": cfg.team.enabled,
        }
        if cfg.team.routing is not None:
            binding["routing"] = cfg.team.routing.model_dump()
        return digest(binding)

    async def tick(self):
        if not self.settings.enabled:
            return self.inspect()
        async with self.lock:
            item = None
            try:
                self._setup()
                self._flush()
                if self._run()["state"] in {"stopped", "complete"}:
                    return self.inspect()
                item = self.store.db.execute(
                    "SELECT * FROM autonext_items WHERE grant_id=? AND state='waiting'",
                    (self.settings.grant_id,),
                ).fetchone()
                if item is not None:
                    if not self._reconcile(item):
                        self._flush()
                        return self.inspect()
                    self._flush()
                count = self.store.db.execute(
                    "SELECT count(*) FROM autonext_items WHERE grant_id=?",
                    (self.settings.grant_id,),
                ).fetchone()[0]
                anchor = self.bridge.teams.work_get(
                    self.settings.principal, self.settings.team_id, self.settings.after_work_id
                )
                if (
                    anchor["state"] != "completed"
                    or text_sha(anchor.get("result") or "") != self.settings.after_result_sha256
                ):
                    raise BridgeError(
                        "autonext_predecessor_unconfirmed", "Completion anchor is not confirmed"
                    )
                for approved in self.settings.cards:
                    prior = self.store.db.execute(
                        "SELECT * FROM autonext_items WHERE task_id=?", (approved.task_id,)
                    ).fetchone()
                    if prior:
                        if (
                            prior["grant_id"] != self.settings.grant_id
                            or prior["state"] != "completed"
                        ):
                            raise BridgeError(
                                "autonext_prior_unknown",
                                "Task has an existing claim; never redispatch",
                            )
                        continue
                    card = self._card(approved)
                    if card.state != "READY":
                        continue
                    if count >= self.settings.max_tasks:
                        raise BridgeError(
                            "autonext_turn_budget_reached", "No more approved turns in this budget"
                        )
                    self._budget()
                    await self._route_ready(card)
                    self._claim(approved, card)
                    self._flush()
                    return self.inspect()
                with self.store.transaction():
                    self.store.db.execute(
                        "UPDATE autonext_runs SET state='complete',reason=? WHERE grant_id=?",
                        ("no_authorized_ready_card", self.settings.grant_id),
                    )
            except Exception as exc:
                code = exc.code if isinstance(exc, BridgeError) else "autonext_state_unknown"
                self._stop(code, item)
                try:
                    self._flush()
                except (BridgeError, OSError, ValueError):
                    pass  # Durable local outbox remains unacknowledged, no input retry.
            return self.inspect()

    async def _route_ready(self, card):
        self._identity(card)
        if self.bridge.config.visible_handoffs.enabled:
            binding = self.bridge.config.visible_handoffs.bindings.get("codex")
            if binding is None:
                raise BridgeError("autonext_identity_changed", "Visible target is not bound")
            view = await self.bridge.visible_handoffs.check_target(
                self.settings.principal, "codex", binding, ready=True
            )
            state = await self.bridge.visible_handoffs.binding_readiness(
                self.settings.principal, "codex", binding, view
            )
            if (state.get("protocol") or {}).get("state") != "idle":
                raise BridgeError(
                    "autonext_idle_unknown", "Bound agent work state is not proven idle"
                )
        # Existing executor route is retained. No fallback to queue/API or a new CLI.

    def _claim(self, approved, card):
        with self.store.transaction():
            run = self._run()
            if run is None or run["state"] in {"stopped", "complete"}:
                return
            if run["config_ref"] != self._configuration_ref():
                raise BridgeError("autonext_grant_changed", "Grant changed during preflight")
            count = self.store.db.execute(
                "SELECT count(*) FROM autonext_items WHERE grant_id=?",
                (self.settings.grant_id,),
            ).fetchone()[0]
            if count >= self.settings.max_tasks:
                raise BridgeError("autonext_turn_budget_reached", "Turn budget was already claimed")
            self._budget()
            if self._card(approved) != card:
                raise BridgeError("autonext_source_changed", "Source changed during preflight")
            if guard := getattr(self, "continuation_guard", None):
                guard(card)
            cwd, identity = self._identity(card)
            if self.store.db.execute(
                "SELECT 1 FROM autonext_items WHERE grant_id=? AND state='waiting'",
                (self.settings.grant_id,),
            ).fetchone():
                return
            if self.store.db.execute(
                "SELECT 1 FROM autonext_items WHERE task_id=?", (card.task_id,)
            ).fetchone():
                return
            if any(
                overlaps(row["cwd"], cwd)
                for row in self.store.db.execute("SELECT cwd FROM autonext_leases")
            ):
                raise BridgeError(
                    "autonext_worktree_busy",
                    "Existing worktree lease, including expired leases, is binding",
                )
            self._check_existing_routes(cwd)
            for row in self.store.db.execute(
                "SELECT args FROM tasks WHERE operation='agent.execute' AND state IN "
                "('created','queued','accepted','running','unknown')"
            ):
                other_cwd = json.loads(row["args"]).get("cwd")
                if isinstance(other_cwd, str) and overlaps(other_cwd, cwd):
                    raise BridgeError(
                        "autonext_worktree_busy", "Another agent task owns the worktree"
                    )
            review_scope = bool(getattr(self, "supports_coordinator_checks", False))
            for row in self.store.db.execute(
                "SELECT w.assignee,"
                + ("coalesce(i.cwd,p.cwd)" if review_scope else "i.cwd")
                + " AS pinned_cwd,t.args AS core_args FROM team_work w "
                "LEFT JOIN autonext_items i ON i.work_id=w.id "
                + (
                    "LEFT JOIN autonext_coordinator r ON w.id IN (r.grok_work_id,r.verify_work_id) "
                    "LEFT JOIN autonext_items p ON p.task_id=r.task_id "
                    if review_scope
                    else ""
                )
                + "LEFT JOIN tasks t ON t.id=w.core_task_id WHERE w.state NOT IN "
                "('completed','failed','blocked','cancelled')"
            ):
                worker = self.bridge.config.team.workers.get(row["assignee"])
                other_cwd = row["pinned_cwd"]
                if not other_cwd and row["core_args"]:
                    other_cwd = json.loads(row["core_args"]).get("cwd")
                if not other_cwd:
                    other_cwd = worker.cwd if worker else None
                if other_cwd and overlaps(other_cwd, cwd):
                    raise BridgeError(
                        "autonext_worktree_busy", "Existing or unknown team work owns the worktree"
                    )
            worker = self.bridge.config.team.workers["codex"]
            if self.settings.lease_seconds < worker.timeout + 5:
                raise BridgeError(
                    "autonext_lease_invalid", "Lease must cover the bounded executor turn"
                )
            expires = min(
                time.time() + self.settings.lease_seconds, self.settings.budget_valid_until
            )
            if expires - time.time() < worker.timeout + 5:
                raise BridgeError("autonext_budget_stop", "Remaining lease cannot cover this turn")
            work = self.bridge.teams.delegate(
                self.settings.principal,
                TeamWorkCreate(
                    team_id=self.settings.team_id,
                    assignee="codex",
                    title=card.title,
                    body=card.instruction,
                    idempotency_key="autonext-"
                    + digest([self.settings.grant_id, card.task_id])[:48],
                ),
            )
            self.store.db.execute(
                "INSERT INTO autonext_items(task_id,grant_id,source_ref,card,work_id,cwd,"
                "cwd_ref,state,lease_until) "
                "VALUES(?,?,?,?,?,?,?,'waiting',?)",
                (
                    card.task_id,
                    self.settings.grant_id,
                    approved.content_sha256,
                    canonical(card.model_dump()),
                    work["id"],
                    cwd,
                    identity,
                    expires,
                ),
            )
            self.store.db.execute(
                "INSERT INTO autonext_leases VALUES(?,?,?,?)",
                (cwd, card.task_id, self.owner, expires),
            )
            self.store.db.execute(
                "UPDATE autonext_runs SET state='waiting',reason=NULL WHERE grant_id=?",
                (self.settings.grant_id,),
            )
            self._queue_note(
                card.task_id,
                "claimed",
                {"work_id": work["id"], "source_sha256": approved.content_sha256},
            )

    def _check_existing_routes(self, cwd):
        # Called under the claim's write transaction. Each existing route persists
        # its reservation before AgentManager's shared guard; later starts see
        # our lease. Unknown reservations remain binding, including after restart.
        for row in self.store.db.execute("SELECT metadata FROM handoff_bindings"):
            metadata = json.loads(row["metadata"])
            if self.bridge.handoffs.phase(metadata) in {"accepted", "rejected"}:
                continue
            other_cwd = metadata.get("cwd")
            if not isinstance(other_cwd, str) or not Path(other_cwd).is_absolute():
                raise BridgeError("autonext_scope_unknown", "Handoff worktree is unconfirmed")
            if overlaps(other_cwd, cwd):
                raise BridgeError("autonext_worktree_busy", "Existing handoff owns the worktree")
        for row in self.store.db.execute(
            "SELECT j.message_id,j.run_id,j.state,j.error,j.evidence,j.execution_cwd,m.recipient "
            "FROM message_jobs j "
            "JOIN messages m ON m.id=j.message_id "
            "WHERE j.state IN ('queued','running','unknown') "
            "AND (j.state='running' OR NOT EXISTS (SELECT 1 FROM queue_holds h "
            "WHERE h.queue_id='messages' AND h.item_id=j.message_id))"
        ):
            other_cwd = row["execution_cwd"]
            if row["state"] == "queued":
                receiver = self.bridge.config.messaging.receivers.get(row["recipient"])
                other_cwd = receiver.cwd if receiver else None
            elif row["state"] == "unknown" and other_cwd is None:
                from kirabridge.autonext.legacy_scope import legacy_scope_for_job

                other_cwd = legacy_scope_for_job(self.settings, row, self.store.db)
            if not isinstance(other_cwd, str) or not Path(other_cwd).is_absolute():
                raise BridgeError("autonext_scope_unknown", "Message worktree is unconfirmed")
            if overlaps(other_cwd, cwd):
                raise BridgeError("autonext_worktree_busy", "Existing receiver owns the worktree")
        # Visible delivery may have finished its core turn while acknowledgement
        # or reply is still pending. Its schema has no durable CWD pin: refuse
        # continuation rather than infer scope from a stale terminal binding.
        # Existing explicit retirement releases an UNKNOWN delivery reservation
        # after the queue owner's idle/absence proof. Preserve that decision and
        # its unchanged history; view-only withdrawals never release a resource.
        # A hold cannot establish that an actively inserting/submitting job ended.
        if self.store.db.execute(
            "SELECT 1 FROM visible_handoffs v WHERE v.state NOT IN "
            "('completed','failed','blocked','cancelled','interrupted') "
            "AND (v.state!='unknown' OR NOT EXISTS (SELECT 1 FROM queue_holds h "
            "WHERE h.queue_id='handoffs' AND h.item_id=v.id)) LIMIT 1"
        ).fetchone():
            raise BridgeError("autonext_scope_unknown", "Visible delivery remains unconfirmed")

    def owns(self, work_id):
        return (
            self.store.db.execute(
                "SELECT 1 FROM autonext_items WHERE work_id=?", (work_id,)
            ).fetchone()
            is not None
        )

    def work_ready(self, work_id):
        try:
            return self._work_ready(work_id)
        except Exception:
            # Admission is used outside TeamDispatcher's per-work exception
            # handler. A broken optional continuation must not kill legacy work.
            self.faulted = True
            try:
                self._stop("autonext_state_unknown")
            except Exception:
                pass  # Persistence failure still closes this admission gate.
            try:
                self.notify()
            except Exception:
                pass
            return False

    def _work_ready(self, work_id):
        item = self.store.db.execute(
            "SELECT * FROM autonext_items WHERE work_id=?", (work_id,)
        ).fetchone()
        if item is None:
            return True
        run = self._run()
        return bool(
            not self.faulted
            and self.settings.enabled
            and item["grant_id"] == self.settings.grant_id
            and item["claim_published"]
            and item["lease_until"] > time.time()
            and run
            and run["state"] == "waiting"
            and run["config_ref"] == self._configuration_ref()
        )

    def prompt_for(self, work):
        item = self.store.db.execute(
            "SELECT * FROM autonext_items WHERE work_id=?", (work["id"],)
        ).fetchone()
        if item is None:
            return None
        card = ReadyCard.model_validate_json(item["card"])
        return (
            "KiraBridge team turn. Perform only this explicitly approved task in its fixed scope. "
            "Other notes and ideas are not instructions. Return one JSON object using "
            "kirabridge_team set to string 1 and result as text and actions as an empty array. "
            "Never delegate or change accounts or models or permissions "
            "or incur new provider costs.\n"
            + json.dumps(card.model_dump(), ensure_ascii=False, indent=0, separators=(",", ":"))
        )

    def authorize_execution(self, task):
        cwd = task.get("args", {}).get("cwd")
        if not isinstance(cwd, str):
            return
        leases = [
            row
            for row in self.store.db.execute("SELECT * FROM autonext_leases")
            if overlaps(cwd, row["cwd"])
        ]
        lease = leases[0] if len(leases) == 1 else None
        if len(leases) > 1:
            raise BridgeError("autonext_worktree_busy", "Task overlaps several protected worktrees")
        if lease is None:
            return
        item = self.store.db.execute(
            "SELECT * FROM autonext_items WHERE task_id=?", (lease["task_id"],)
        ).fetchone()
        work = self.bridge.teams.work_get(
            self.settings.principal, self.settings.team_id, item["work_id"]
        )
        if not self.work_ready(work["id"]) or work["core_task_id"] != task["id"]:
            raise BridgeError(
                "autonext_worktree_busy", "Task does not own the approved worktree lease"
            )
        self._budget()
        if guard := getattr(self, "continuation_guard", None):
            guard(ReadyCard.model_validate_json(item["card"]))
        if self.settings.legacy_scope_pins:
            self._check_existing_routes(cwd)
        if item["lease_until"] - time.time() < self.bridge.config.team.workers["codex"].timeout + 5:
            raise BridgeError("autonext_budget_stop", "Remaining lease cannot cover execution")
        approved = next((c for c in self.settings.cards if c.task_id == item["task_id"]), None)
        if approved is None or canonical(self._card(approved).model_dump()) != item["card"]:
            raise BridgeError(
                "autonext_source_changed", "Claimed source no longer matches its grant"
            )
        _, identity = self._identity(ReadyCard.model_validate_json(item["card"]))
        if identity != item["cwd_ref"]:
            raise BridgeError("autonext_identity_changed", "Worktree directory generation changed")

    def _core_proof(self, item, work):
        self.bridge.teams._check_sealed(work)
        core = self.store.get(work["core_task_id"], "codex")
        if (
            core["state"] != "completed"
            or not (core.get("result") or {}).get("success")
            or not work["evidence"].get("model_turn_completed")
            or core["finished"] > item["lease_until"]
        ):
            raise BridgeError("autonext_completion_unknown", "No bounded successful core receipt")
        return core

    def _reconcile(self, item):
        work = self.bridge.teams.work_get(
            self.settings.principal, self.settings.team_id, item["work_id"]
        )
        if work["state"] in TERMINAL:
            self._stop("autonext_work_" + work["state"], item)
            return False
        if work["state"] != "completed":
            if time.time() >= item["lease_until"]:
                self._stop("autonext_timeout_unknown", item)
            return False
        core = self._core_proof(item, work)
        card = ReadyCard.model_validate_json(item["card"])
        result_sha = text_sha(work["result"])
        if card.acceptance.kind == "result_sha256":
            if result_sha != card.acceptance.expected_sha256:
                self._stop("autonext_acceptance_mismatch", item)
                return False
        elif card.acceptance.kind == "coordinator_checks":
            if not self.coordinator_accept(item, work, card):
                return False
        else:
            confirmed = self.store.db.execute(
                "SELECT * FROM autonext_confirmations WHERE task_id=?", (item["task_id"],)
            ).fetchone()
            if confirmed is None:
                if time.time() >= item["lease_until"]:
                    self._stop("autonext_completion_unconfirmed", item)
                return False  # A finished agent turn is not project completion.
            if confirmed["result_sha256"] != result_sha:
                raise BridgeError("autonext_completion_unknown", "Operator receipt result changed")
        receipt = {
            "task_id": item["task_id"],
            "work_id": work["id"],
            "core_task_id": core["id"],
            "source_sha256": item["source_ref"],
            "result_sha256": result_sha,
            "acceptance": card.acceptance.kind,
            "accepted_at": time.time(),
            "scope": "approved task acceptance contract, not blanket product acceptance",
        }
        if card.acceptance.kind == "coordinator_checks":
            receipt["coordinator"] = self.coordinator_receipt(item)
        with self.store.transaction():
            current = self.store.db.execute(
                "SELECT state FROM autonext_items WHERE task_id=?", (item["task_id"],)
            ).fetchone()
            if current["state"] == "completed":
                return True
            self.store.db.execute(
                "UPDATE autonext_items SET state='completed',receipt=? WHERE task_id=?",
                (canonical(receipt), item["task_id"]),
            )
            self.store.db.execute("DELETE FROM autonext_leases WHERE task_id=?", (item["task_id"],))
            self._queue_note(
                item["task_id"],
                "completed",
                {"receipt_sha256": digest(receipt), "result_sha256": result_sha},
            )
        return True

    def coordinator_accept(self, item, work, card):
        raise BridgeError("autonext_coordinator_required", "Explicit coordinator adapter required")

    def coordinator_receipt(self, item):
        raise BridgeError("autonext_coordinator_required", "Explicit coordinator receipt required")

    def receipt(self, principal, task_id):
        if principal != self.settings.principal:
            raise BridgeError(
                "autonext_operator_required", "Only the configured operator may read this receipt"
            )
        self.bridge.security.principal(principal, "team.read")
        row = self.store.db.execute(
            "SELECT receipt FROM autonext_items WHERE task_id=? AND grant_id=?",
            (task_id, self.settings.grant_id),
        ).fetchone()
        return json.loads(row["receipt"]) if row and row["receipt"] else None

    def validate_control(self, principal, args):
        return self.control(principal, args, validate_only=True)

    def control(self, principal, args, *, validate_only=False):
        self.bridge.security.principal(principal, "team.manage")
        if principal != self.settings.principal or args.grant_id != self.settings.grant_id:
            raise BridgeError(
                "autonext_operator_required", "Only the bound operator controls this grant"
            )
        self.bridge.teams.get(principal, self.settings.team_id)
        if args.action == "confirm" and principal == "codex":
            raise BridgeError("autonext_operator_required", "Codex cannot issue operator receipts")
        if args.action == "confirm":
            item = self.store.db.execute(
                "SELECT * FROM autonext_items WHERE task_id=? AND grant_id=?",
                (args.task_id, args.grant_id),
            ).fetchone()
            if (
                item is None
                or ReadyCard.model_validate_json(item["card"]).acceptance.kind != "operator_receipt"
            ):
                raise BridgeError(
                    "autonext_confirmation_invalid", "No matching operator acceptance contract"
                )
            work = self.bridge.teams.work_get(principal, self.settings.team_id, item["work_id"])
            if work["state"] != "completed" or text_sha(work["result"]) != args.result_sha256:
                raise BridgeError("autonext_completion_unknown", "Completed result hash differs")
            self._core_proof(item, work)
            value = (args.task_id, args.result_sha256, principal, text_sha(args.evidence_ref))
            with self.store.transaction():
                old = self.store.db.execute(
                    "SELECT * FROM autonext_confirmations WHERE task_id=?", (args.task_id,)
                ).fetchone()
                if (
                    old
                    and tuple(
                        old[k] for k in ("task_id", "result_sha256", "actor", "evidence_sha256")
                    )
                    != value
                ):
                    raise BridgeError("conflict", "Completion receipt is immutable")
                if not validate_only:
                    self.store.db.execute(
                        "INSERT OR IGNORE INTO autonext_confirmations VALUES(?,?,?,?,?)",
                        (*value, time.time()),
                    )
        if not validate_only:
            self.notify()
        return self.inspect()
