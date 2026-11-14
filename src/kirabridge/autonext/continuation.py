"""Select existing board work under a standing mandate, using the AutoNext ledger.

The local policy is the authority. Board entries supply task data only. There is
no second work queue: reservations, failed attempts and receipts stay in Core.
"""

import json
import os
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from kirabridge.autonext.manager import digest, overlaps, text_sha
from kirabridge.autonext.models import ID, ApprovedCard, CoordinatorCheck, ReadyCard
from kirabridge.bridge_core.models import BridgeError
from kirabridge.capability_routing.router import WorkerRouting
from kirabridge.whiteboard_read import read_whiteboard


class DiscoverySnapshot(BaseModel):
    """Offline inputs for the read-only selection preview; never a work grant."""

    model_config = ConfigDict(extra="forbid", strict=True)
    entries: list[dict[str, Any]]
    prior: dict[str, str] = Field(default_factory=dict)
    attempts: dict[str, str] = Field(default_factory=dict)
    leases: list[str] = Field(default_factory=list)


class ContinuationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    authority_ref: str = Field(min_length=1, max_length=2000)
    allowed_cwds: list[str] = Field(min_length=1, max_length=32)
    products: list[
        Literal["KiraBridge", "ThreadDesk", "4AllPass", "TollGate", "AgentAuthority"]
    ] = Field(min_length=1, max_length=5)
    checks: list[CoordinatorCheck] = Field(min_length=1, max_length=32)
    sources: list[ApprovedCard] = Field(default_factory=list, max_length=4096)
    task_routing: dict[str, WorkerRouting] = Field(default_factory=dict, max_length=4096)

    @field_validator("task_routing")
    @classmethod
    def exact_task_ids(cls, values):
        if any(re.fullmatch(ID, task_id) is None for task_id in values):
            raise ValueError("Task routing requires exact ReadyCard task IDs")
        return values

    @field_validator("allowed_cwds")
    @classmethod
    def exact_worktrees(cls, values):
        for value in values:
            path = Path(value)
            if not path.is_absolute() or os.path.normpath(value) != value or "\x00" in value:
                raise ValueError("Continuation requires absolute canonical worktree paths")
        if len(set(values)) != len(values):
            raise ValueError("Continuation worktrees must be unique")
        return values


def board_entries(workspace, board_id):
    """Use the existing bounded reader, including all pages, without switching UI."""
    entries, offset = [], 0
    while True:
        page = read_whiteboard(workspace, board_id, offset=offset, include_content=True)
        entries.extend(page["entries"])
        if page["next_offset"] is None:
            return entries
        offset = page["next_offset"]


def grant_id(policy, board_id, task_id):
    # Bind the logical task, not the spelling of an entry or approval generation.
    # Replacing an entry or restarting a controller cannot retry a stopped task.
    return "continue-" + digest([policy.authority_ref, board_id, task_id])[:40]


def mentions(entry, identities):
    if any(entry.get(key) in identities for key in ("task_id", "handoff_id", "run_id")):
        return True
    content = entry.get("content", "")
    return any(
        re.search(r"(?<![A-Za-z0-9_.-])" + re.escape(value) + r"(?![A-Za-z0-9_.-])", content)
        for value in identities
    )


def checks_allowed(policy, card):
    return all(
        any(
            check.argv == template.argv and check.timeout_seconds <= template.timeout_seconds
            for template in policy.checks
        )
        for check in card.acceptance.checks
    )


def scope_available(cwd):
    path = Path(cwd)
    try:
        return (
            not path.is_symlink()
            and str(path.resolve(strict=True)) == cwd
            and (path / ".git").exists()
        )
    except OSError:
        return False


def resolve_worker_routing(profile, task_id):
    """Resolve trusted Codex policy for one task without changing global defaults."""
    base = profile.get("worker_routing", {}).get("codex")
    continuation = profile.get("continuation")
    if continuation:
        policy = ContinuationPolicy.model_validate(continuation)
        override = policy.task_routing.get(task_id)
        if override is not None:
            if base is None or profile.get("routing") is None:
                raise ValueError("Task routing requires an existing routed Codex worker")
            if not any(source.task_id == task_id for source in policy.sources):
                raise ValueError("Task routing requires an assigned source pin")
            return override.model_copy(deep=True)
    return WorkerRouting.model_validate(base) if base is not None else None


def discover(bridge, profile, *, snapshot=None, route_candidate=None):
    """Project actionable/held work; reading alone never grants, claims or starts.

    ``snapshot`` replaces all board/Core reads with strict caller-supplied fixture data.
    ``route_candidate`` is used only by the offline preview and must be a pure router.
    """
    policy = ContinuationPolicy.model_validate(profile["continuation"])
    snapshot = DiscoverySnapshot.model_validate(snapshot) if snapshot is not None else None
    entries = (
        snapshot.entries
        if snapshot is not None
        else board_entries(profile["workspace"], profile["board_id"])
    )
    groups, held = {}, []
    for entry in entries:
        if entry["entry_type"] != "task":
            continue
        try:
            card = ReadyCard.model_validate_json(entry["content"])
        except ValueError:
            continue  # Prose, ideas and historic handoffs require coordinator assessment.
        groups.setdefault(card.task_id, []).append((entry, card))
    selected = None
    for task_id, versions in groups.items():
        entry, card = versions[0]
        reason = None
        if snapshot is None:
            prior = bridge.store.db.execute(
                "SELECT state FROM autonext_items WHERE task_id=?", (task_id,)
            ).fetchone()
            attempt = bridge.store.db.execute(
                "SELECT state FROM autonext_runs WHERE grant_id=?",
                (grant_id(policy, profile["board_id"], task_id),),
            ).fetchone()
            leases = None
        else:
            prior = snapshot.prior.get(task_id)
            attempt = snapshot.attempts.get(grant_id(policy, profile["board_id"], task_id))
            leases = snapshot.leases
        identities = [task_id, *(item[0]["id"] for item in versions)]
        activity = [
            item
            for item in entries
            if item["entry_type"] in {"claimed", "progress", "result", "problem"}
            and mentions(item, identities)
        ]
        prior_state = prior["state"] if snapshot is None and prior else prior
        attempt_state = attempt["state"] if snapshot is None and attempt else attempt
        if prior_state:
            reason = "completed" if prior_state == "completed" else "existing_claim"
        elif attempt_state:
            reason = "existing_attempt_" + attempt_state
        elif any(item[0].get("truncated") for item in versions):
            reason = "truncated_source"
        elif len({text_sha(item[0]["content"]) for item in versions}) != 1:
            reason = "conflicting_task_id"
        elif card.state != "READY":
            reason = "card_" + card.state.lower()
        elif card.cwd not in policy.allowed_cwds or card.product not in policy.products:
            reason = "outside_mandate"
        elif not scope_available(card.cwd):
            reason = "worktree_unavailable"
        elif card.sandbox == "workspace-write" and profile["sandbox"] != "workspace-write":
            reason = "outside_sandbox"
        elif card.acceptance.kind != "coordinator_checks":
            reason = "coordinator_acceptance_required"
        elif not checks_allowed(policy, card):
            reason = "outside_check_templates"
        elif not any(
            source.task_id == card.task_id
            and source.entry_id == entry["id"]
            and source.content_sha256 == text_sha(entry["content"])
            for source in policy.sources
        ):
            reason = "unassigned_source"
        elif activity:
            # Even a stale/ambiguous external claim remains reserved. Result
            # delivery is not acceptance, nor permission to repeat its work.
            reason = "external_activity"
        elif any(
            overlaps(cwd, card.cwd)
            for cwd in (
                leases
                if leases is not None
                else (
                    row["cwd"] for row in bridge.store.db.execute("SELECT cwd FROM autonext_leases")
                )
            )
        ):
            reason = "worktree_reserved"
        route = None
        route_error = None
        if reason is None:
            try:
                resolve_worker_routing(profile, card.task_id)
                if route_candidate is not None:
                    route = route_candidate(card)
            except ValueError as error:
                reason = "routing_unavailable"
                route_error = str(error)[:200]
        if reason:
            row = {"task_id": task_id, "entry_id": entry["id"], "reason": reason}
            if route_error:
                row["routing_reason"] = route_error
            held.append(row)
        elif selected is None:
            selected = {
                "pin": ApprovedCard(
                    task_id=task_id,
                    entry_id=entry["id"],
                    content_sha256=text_sha(entry["content"]),
                ),
                "card": card,
                "grant_id": grant_id(policy, profile["board_id"], task_id),
            }
            if route is not None:
                selected["routing"] = route
    return {
        "selected": selected,
        "held": held,
        "source_revision": digest([[e["id"], text_sha(e["content"])] for e in entries]),
        "authority_ref": policy.authority_ref,
    }


def bind_scope(bridge, card, *, restoring_grant=None, profile=None):
    """Set the fixed executor scope between turns, never during a Core effect."""
    for task in bridge.store.db.execute(
        "SELECT id,args FROM tasks WHERE operation='agent.execute' AND state IN "
        "('created','queued','accepted','running')"
    ):
        if not restoring_grant:
            return False
        owned = bridge.store.db.execute(
            "SELECT coalesce(i.grant_id,p.grant_id) AS grant_id FROM team_work w "
            "LEFT JOIN autonext_items i ON i.work_id=w.id "
            "LEFT JOIN autonext_coordinator r ON w.id IN (r.grok_work_id,r.verify_work_id) "
            "LEFT JOIN autonext_items p ON p.task_id=r.task_id WHERE w.core_task_id=?",
            (task["id"],),
        ).fetchone()
        if not owned or owned["grant_id"] != restoring_grant:
            return False
        if json.loads(task["args"]).get("cwd") != card.cwd:
            return False
    routing = resolve_worker_routing(profile, card.task_id) if profile is not None else None
    for name in ("codex", "grok", "codex_verify"):
        bridge.config.team.workers[name].cwd = card.cwd
    bridge.config.agents["codex"].sandbox_mode = card.sandbox
    if profile is not None:
        bridge.config.team.workers["codex"].routing = routing
    return True


def validate_source(bridge, profile, card):
    """Recheck external reservations at claim and immediately before execution."""
    if not profile["enabled"]:
        raise BridgeError("continuation_disabled", "Continuation is disabled")
    policy = ContinuationPolicy.model_validate(profile["continuation"])
    if (
        card.cwd not in policy.allowed_cwds
        or card.product not in policy.products
        or not checks_allowed(policy, card)
        or not scope_available(card.cwd)
        or bridge.config.team.workers["codex"].routing
        != resolve_worker_routing(profile, card.task_id)
    ):
        raise BridgeError("continuation_scope_changed", "Task is outside the standing mandate")
    entries = board_entries(profile["workspace"], profile["board_id"])
    pins = [pin for pin in bridge.config.autonext.cards if pin.task_id == card.task_id]
    if len(pins) != 1:
        raise BridgeError("continuation_source_changed", "One immutable source pin required")
    if pins[0] not in policy.sources:
        raise BridgeError(
            "continuation_source_changed", "Source is not assigned by the coordinator"
        )
    identities = [card.task_id, pins[0].entry_id]
    for entry in entries:
        if entry["entry_type"] == "task" and mentions(entry, [card.task_id]):
            try:
                other = ReadyCard.model_validate_json(entry["content"])
            except ValueError:
                continue
            if other.task_id == card.task_id:
                identities.append(entry["id"])
                if text_sha(entry["content"]) != pins[0].content_sha256:
                    raise BridgeError("continuation_source_changed", "Conflicting logical task")
    own_notes = {
        row["entry_id"]
        for row in bridge.store.db.execute(
            "SELECT entry_id FROM autonext_outbox WHERE grant_id=? AND verified=1",
            (bridge.config.autonext.grant_id,),
        )
    }
    if any(
        entry["id"] not in own_notes
        and entry["entry_type"] in {"claimed", "progress", "result", "problem"}
        and mentions(entry, identities)
        for entry in entries
    ):
        raise BridgeError(
            "continuation_external_claim", "Another task binding needs reconciliation"
        )


def restore(bridge, profile):
    """Attach the original grant after restart; never generate a replacement turn."""
    from kirabridge.autonext.models import AutoNextConfig

    rows = bridge.store.db.execute(
        "SELECT grant_id FROM autonext_runs WHERE grant_id LIKE 'continue-%' "
        "AND state NOT IN ('complete','stopped')"
    ).fetchall()
    if not rows:
        return None
    if len(rows) != 1:
        raise BridgeError("continuation_state_unknown", "Multiple unfinished grants")
    identifier = rows[0]["grant_id"]
    grant = AutoNextConfig.model_validate_json(
        (bridge.config.state_path / ("grant-" + identifier + ".json")).read_text()
    )
    policy = ContinuationPolicy.model_validate(profile["continuation"])
    if len(grant.cards) != 1:
        raise BridgeError("continuation_state_unknown", "One task per continuation grant required")
    pin = grant.cards[0]
    entry = read_whiteboard(profile["workspace"], profile["board_id"], pin.entry_id)["entry"]
    card = ReadyCard.model_validate_json(entry["content"])
    if (
        grant.grant_id != identifier
        or identifier != grant_id(policy, profile["board_id"], card.task_id)
        or pin.task_id != card.task_id
        or pin.content_sha256 != text_sha(entry["content"])
        or entry["truncated"]
        or grant.board_id != profile["board_id"]
        or card.cwd not in policy.allowed_cwds
        or card.product not in policy.products
        or not checks_allowed(policy, card)
        or not bind_scope(bridge, card, restoring_grant=identifier, profile=profile)
    ):
        raise BridgeError("continuation_state_unknown", "Original task scope cannot be restored")
    grant.enabled = bool(profile["enabled"] and grant.enabled)
    bridge.config.autonext = grant
    return identifier
