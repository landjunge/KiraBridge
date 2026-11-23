"""Project established TeamWork milestones into the existing ChatGPT team inbox."""

from __future__ import annotations

import json
import re
import uuid

from kirabridge.bridge_core.models import BridgeError, digest
from kirabridge.team_manager.continuation import REVIEW
from kirabridge.team_manager.models import TeamMessageSend

OPERATION = "chatgpt_status"
RECIPIENT = "chatgpt"
END_STATES = {"completed", "failed", "unknown", "blocked", "cancelled"}
START_EVENTS = {"turn.started", "assistant_message", "prompt_response_observed"}
WORK_ID = re.compile(r"tw-[a-f0-9]{32}")
SOURCE_KEY = (
    "(CASE WHEN json_valid(e.metadata) THEN json_extract(e.metadata,'$.chatgpt_status_key') END)"
)


class ChatGPTTeamStatus:
    def __init__(self, teams):
        self.teams = teams
        self.db = teams.store.db

    def _audience(self, team_id):
        """The established team recipient rules remain authoritative."""
        return self.teams._member(team_id, RECIPIENT, writable=True)

    def _authority(self, team_id):
        team = self.teams.coordinator_roles._current(team_id)
        if team is None or not team["coordinator"] or team["coordinator"] == RECIPIENT:
            return None
        try:
            self._audience(team_id)
            self.teams._team(team["coordinator"], team_id, "team.write", write=True, manage=True)
            self.teams._automatic(team["coordinator"])
        except BridgeError:
            return None
        return team

    def _relevant(self, work_id):
        if self.teams.coordinator_roles.linked_work(work_id):
            return False
        return not self.db.execute(
            "SELECT 1 FROM team_coordinator_resumes WHERE resume_work_id=?",
            (work_id,),
        ).fetchone()

    @staticmethod
    def confirmed_start(core, native):
        return (
            core.get("state") == "running"
            and type(core.get("started")) in {float, int}
            and isinstance(core.get("receipt"), str)
            and bool(core["receipt"])
            and isinstance(native.get("session_id"), str)
            and bool(native["session_id"])
            and native.get("event") in START_EVENTS
        )

    def source_fields(self, team_id, kind, work_id, metadata):
        if not isinstance(work_id, str) or not WORK_ID.fullmatch(work_id):
            return {}
        observed = metadata.get("state")
        subject = kind.removeprefix("team.work_")
        if kind == "team.work_observed":
            if observed == "running" and metadata.get("native_start_confirmed") is True:
                subject = "started"
            elif observed in END_STATES - {"completed"}:
                subject = observed
            else:
                return {}
        elif kind not in {"team.work_" + value for value in END_STATES | {"accepted"}}:
            return {}
        if not self._relevant(work_id):
            return {}
        try:
            self._audience(team_id)
        except BridgeError:
            return {}
        team = self.teams.coordinator_roles._current(team_id)
        if team is None or team["coordinator"] == RECIPIENT:
            return {}
        # Only events written under this program version carry a source marker.
        # A restart sees pending new events, never a replay of historical work.
        return {
            "chatgpt_status": (subject if subject in {"started", "accepted"} else "terminal"),
            "chatgpt_status_subject": subject,
            "chatgpt_status_key": "kb-status-" + digest([team_id, work_id, subject]),
        }

    def record_review_acceptance(self, reviewer, result):
        operation = self.teams.continuation.operation(reviewer["id"], REVIEW)
        if operation is None:
            return
        link = self.db.execute(
            "SELECT r.work_id FROM team_coordinator_resumes r "
            "JOIN completion_notices n ON n.id=r.notice_id "
            "WHERE r.notice_id=? AND r.resume_work_id=? AND n.source='team' "
            "AND n.acknowledged IS NOT NULL",
            (operation["idem"], reviewer["id"]),
        ).fetchone()
        if link is None or result != self.teams.continuation.marker(link["work_id"]):
            return
        original = self.teams._work(link["work_id"])
        if original["state"] != "completed" or original["team_id"] != reviewer["team_id"]:
            return
        self.teams._check_sealed(reviewer)
        self.teams._event(
            original["team_id"],
            reviewer["assignee"],
            "team.work_accepted",
            original["id"],
            review_work_id=reviewer["id"],
            completion_notice_id=operation["idem"],
        )

    def _predecessor(self, work):
        if work["parent_id"]:
            return work["parent_id"]
        row = self.db.execute(
            "SELECT json_extract(metadata,'$.predecessor_work_id') AS predecessor "
            "FROM team_events WHERE team_id=? AND object_id=? "
            "AND kind='team.continuation_selected' AND json_valid(metadata) "
            "ORDER BY seq DESC LIMIT 1",
            (work["team_id"], work["id"]),
        ).fetchone()
        return row["predecessor"] if row else None

    def _followup(self, work):
        row = self.db.execute(
            "SELECT w.id,w.state,EXISTS (SELECT 1 FROM team_events s "
            "WHERE s.team_id=w.team_id AND s.object_id=w.id "
            "AND CASE WHEN json_valid(s.metadata) "
            "THEN json_extract(s.metadata,'$.chatgpt_status') END='started') AS start_proven "
            "FROM team_work w WHERE w.team_id=? AND (w.parent_id=? OR EXISTS ("
            "SELECT 1 FROM team_events e WHERE e.team_id=w.team_id AND e.object_id=w.id "
            "AND e.kind='team.continuation_selected' "
            "AND CASE WHEN json_valid(e.metadata) "
            "THEN json_extract(e.metadata,'$.predecessor_work_id') END=?)) "
            "AND w.state IN ('queued','queued_manual','accepted','accepted_manual','running') "
            "ORDER BY w.seq LIMIT 1",
            (work["team_id"], work["id"], work["id"]),
        ).fetchone()
        return row

    def _render(self, work, subject):
        if subject == "started":
            predecessor = self._predecessor(work)
            linked = isinstance(predecessor, str) and WORK_ID.fullmatch(predecessor)
            label = "Folgeauftrag" if linked else "Auftrag"
            previous = f" zu {predecessor}" if linked else ""
            step = {
                "completed": "Die fachliche Prüfung steht aus.",
                "unknown": "Der ursprüngliche Beleg ist ungeklärt.",
                "failed": "Der Ausfall ist zu prüfen.",
                "blocked": "Die Blockade ist zu prüfen.",
                "cancelled": "Die Ausführung wurde beendet.",
            }.get(work["state"], "Ein Ergebnis steht aus.")
            return f"{label} {work['id']}{previous} wurde nachweisbar gestartet. {step}", {
                **({"predecessor_work_id": predecessor} if linked else {})
            }
        if subject == "accepted":
            next_work = self._followup(work)
            next_id = next_work["id"] if next_work else None
            body = f"Auftrag {work['id']} fachlich abgenommen."
            if next_id and WORK_ID.fullmatch(next_id):
                detail = {
                    # A generic Core dispatch signal still awaits a provider start.
                    "running": "in Bearbeitung" if next_work["start_proven"] else "zugeordnet",
                    "accepted": "angenommen",
                    "accepted_manual": "angenommen",
                }.get(next_work["state"], "zugeordnet")
                return f"{body} Folgeauftrag {next_id} ist {detail}.", {"followup_work_id": next_id}
            return (
                f"{body} Bisher ist kein Folgeauftrag zugeordnet. "
                "Nächster Schritt: Teamplan prüfen.",
                {},
            )
        message = {
            "completed": "Ergebnis liegt vor. Fachliche Prüfung steht aus.",
            "unknown": "Ausgang ungeklärt. Prüfung des Originalbelegs steht aus.",
            "failed": "Ausführung fehlgeschlagen. Prüfung des Fehlerbelegs steht aus.",
            "blocked": "Ausführung blockiert. Prüfung der Ursache steht aus.",
            "cancelled": "Ausführung abgebrochen. Kein weiterer Start belegt.",
        }[subject]
        return f"Auftrag {work['id']}: {message}", {}

    def _remember_status(self, team, key, event, message):
        self.db.execute(
            "INSERT INTO team_operations VALUES(?,?,?,?,?,?)",
            (
                team["id"],
                team["owner"],
                OPERATION,
                key,
                digest([event["seq"], event["object_id"], key]),
                message["id"],
            ),
        )

    def _publish_one(self, event):
        metadata = json.loads(event["metadata"])
        key, subject = metadata["chatgpt_status_key"], metadata["chatgpt_status_subject"]
        with self.teams.store.transaction():
            team = self._authority(event["team_id"])
            if (
                team is None
                or self.db.execute(
                    "SELECT 1 FROM team_operations WHERE team_id=? AND operation=? AND idem=?",
                    (event["team_id"], OPERATION, key),
                ).fetchone()
            ):
                return False
            work = self.teams._work(event["object_id"])
            body, binding = self._render(work, subject)
            sender = team["coordinator"]
            message = self.teams._send(
                sender,
                TeamMessageSend(
                    team_id=event["team_id"],
                    recipient=RECIPIENT,
                    body=body,
                    kind="note",
                    # The stable receipt lives in the same transaction. An
                    # agent's public message key cannot occupy that receipt.
                    idempotency_key="kb-status-send-" + uuid.uuid4().hex,
                ),
            )
            self._remember_status({**dict(team), "id": event["team_id"]}, key, event, message)
            self.teams._event(
                event["team_id"],
                sender,
                "team.chatgpt_status_published",
                message["id"],
                work_id=work["id"],
                source_event_seq=event["seq"],
                subject=subject,
                **binding,
            )
        return True

    def publish(self, limit=8):
        if not self.teams.config.team.enabled:
            return 0
        teams = [
            row["id"]
            for row in self.db.execute(
                "SELECT t.id FROM teams t JOIN team_members m ON m.team_id=t.id "
                "WHERE m.principal=? AND m.active=1 AND t.coordinator<>? ORDER BY t.id",
                (RECIPIENT, RECIPIENT),
            ).fetchall()
            if self._authority(row["id"]) is not None
        ]
        if not teams:
            return 0
        marks = ",".join("?" for _ in teams)
        candidates = self.db.execute(
            f"SELECT e.* FROM team_events e WHERE e.team_id IN ({marks}) "
            f"AND {SOURCE_KEY} IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM team_operations o WHERE o.team_id=e.team_id "
            f"AND o.operation=? AND o.idem={SOURCE_KEY}) "
            "ORDER BY e.seq LIMIT ?",
            (*teams, OPERATION, limit),
        ).fetchall()
        sent = 0
        for event in candidates:
            try:
                sent += int(self._publish_one(event))
            except BridgeError:
                # The original remains available for the same authorized scope.
                continue
        return sent
