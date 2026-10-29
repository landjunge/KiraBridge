"""One bounded admission attempt for a newly created addressed message.

The durable message is an idempotency receipt, never a backlog selector. Existing
handoff identity, input guards and reply recovery remain owned by the receiver.
"""

from __future__ import annotations

import asyncio
import json
import re

from kirabridge.bridge_core.models import BridgeError, UncertainExecution
from kirabridge.local_runtime import peer
from kirabridge.mcp_gateway.client import MCPClientPool


class DirectDelivery:
    delivery_timeout = 30.0
    PREINPUT_CODES = {
        "session_selection_changed",
        "session_busy",
        "visible_target_busy",
        "visible_target_changed",
        "visible_target_ambiguous",
        "visible_target_missing",
        "visible_target_not_ready",
        "visible_target_working",
        "visible_target_unknown",
        "visible_input_not_empty",
        "visible_target_scrolled",
        "visible_selection_required",
        "desktop_locked",
        "desktop_session_inactive",
        "forbidden",
        "agent_denied",
        "agent_unavailable",
        "approval_required",
        "payload_limit",
        "invalid_arguments",
    }

    def __init__(self, receiver):
        self.receiver = receiver
        self.accepting = False
        self.active = {}
        self.ready = {}
        self.targets = set()
        self._submitted = set()
        self._watchdogs = {}
        self._expired = set()
        self._stop_task = None
        self._claimed = {}

    def submit(self, principal, message_id):
        """Only the new-record send hook calls this; reads never re-admit a job."""
        if message_id in self._submitted:
            return False
        bridge = self.receiver.bridge
        row = bridge.store.db.execute(
            "SELECT j.*,m.sender,m.delivered,m.receipt,m.acknowledged "
            "FROM message_jobs j JOIN messages m ON m.id=j.message_id "
            "WHERE j.message_id=?",
            (message_id,),
        ).fetchone()
        if row is None or row["sender"] != principal or not self._pristine(message_id, row):
            return False
        self._submitted.add(message_id)
        event = self.ready[message_id] = asyncio.Event()
        deadline = asyncio.get_running_loop().time() + self.delivery_timeout
        task = asyncio.create_task(self._deliver(principal, message_id, event))
        self.active[message_id] = task
        watchdog = asyncio.create_task(self._watch(message_id, task, event, deadline))
        self._watchdogs[message_id] = watchdog
        watchdog.add_done_callback(self._consume)

        def finished(result):
            self.active.pop(message_id, None)
            self.ready.pop(message_id, None)
            current_watchdog = self._watchdogs.pop(message_id, None)
            if current_watchdog:
                current_watchdog.cancel()
            self._expired.discard(message_id)
            self._claimed.pop(message_id, None)
            event.set()
            if not result.cancelled():
                result.exception()  # Consume a persistence fault; never retry it.

        task.add_done_callback(finished)
        return True

    @staticmethod
    def _consume(task):
        if not task.cancelled():
            task.exception()

    @staticmethod
    def _empty_evidence(value):
        try:
            return json.loads(value) == {}
        except (ValueError, TypeError):
            return False

    def _pristine(self, message_id, row):
        """A different claim/receipt/hold since submit does not belong to this driver."""
        db = self.receiver.bridge.store.db
        return (
            row is not None
            and row["state"] == "queued"
            and all(
                row[key] is None
                for key in (
                    "run_id",
                    "claimed",
                    "started",
                    "finished",
                    "error",
                    "reply_id",
                    "delivered",
                    "receipt",
                    "acknowledged",
                )
            )
            and self._empty_evidence(row["evidence"])
            and not db.execute(
                "SELECT 1 FROM visible_handoffs WHERE message_id=?", (message_id,)
            ).fetchone()
            and not db.execute(
                "SELECT 1 FROM queue_holds WHERE queue_id='messages' AND item_id=?",
                (message_id,),
            ).fetchone()
            and not db.execute(
                "SELECT 1 FROM queue_withdrawals WHERE queue_id='messages' AND item_id=?",
                (message_id,),
            ).fetchone()
        )

    def _unclaimed(self, message_id):
        row = self.receiver.bridge.store.db.execute(
            "SELECT j.*,m.delivered,m.receipt,m.acknowledged "
            "FROM message_jobs j JOIN messages m ON m.id=j.message_id WHERE j.message_id=?",
            (message_id,),
        ).fetchone()
        return self._pristine(message_id, row)

    async def wait_delivery(self, message_id):
        """Caller cancellation cancels its observation, never the delivery task."""
        event = self.ready.get(message_id)
        if event:
            await event.wait()

    async def _watch(self, message_id, task, event, deadline):
        try:
            async with asyncio.timeout_at(deadline):
                await event.wait()
        except TimeoutError:
            if not event.is_set() and not task.done():
                self._expired.add(message_id)
                task.cancel()
                # Settle synchronously before signalling the bounded observer. Native
                # cleanup may continue, but an ambiguous attempt is never retried.
                self._settle(message_id, "delivery_timeout", uncertain=False)
                event.set()

    @staticmethod
    def _observation(error):
        value = getattr(error, "observation", None)
        if not isinstance(value, dict):
            return None
        result = {}
        for key in ("state", "reason", "target", "handoff_id", "handoff_state", "message_id"):
            item = value.get(key)
            if isinstance(item, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", item):
                result[key] = item
        for key in ("ready", "input_empty"):
            if type(value.get(key)) is bool:
                result[key] = value[key]
        return result or None

    def fail(self, message_id, error):
        """The receiver uses the same classification for an admission/input race."""
        self._settle(
            message_id,
            error.code if isinstance(error, BridgeError) else "delivery_failed",
            uncertain=isinstance(error, UncertainExecution)
            or isinstance(error, BridgeError)
            and error.code == "peer_unknown",
            observation=self._observation(error),
        )

    def _settle(self, message_id, code, *, uncertain, observation=None, preserve_delivered=False):
        bridge = self.receiver.bridge
        with bridge.store.transaction():
            row = bridge.store.db.execute(
                "SELECT j.*,m.sender,m.delivered,m.receipt,m.acknowledged "
                "FROM message_jobs j JOIN messages m ON m.id=j.message_id "
                "WHERE j.message_id=?",
                (message_id,),
            ).fetchone()
            if row is None or row["state"] not in {"queued", "running"}:
                return
            owned_run = self._claimed.get(message_id)
            if owned_run is not None:
                if row["state"] != "running" or row["run_id"] != owned_run:
                    return
            elif not self._pristine(message_id, row):
                return  # A concurrent owner changed this record, not this driver.
            if preserve_delivered and row["state"] == "running":
                if self.receiver._reply_can_finish(row):
                    return  # The normal receiver recovers the delivered reply waiter.
            possible = uncertain or row["started"] is not None or row["acknowledged"] is not None
            # Internal message_receive records a transport receipt before checking
            # the target. Known pre-input guards plus the absence of input evidence
            # prove no paste; a receipt itself must not be called execution.
            if code not in self.PREINPUT_CODES and any(
                row[key] is not None for key in ("claimed", "delivered", "receipt")
            ):
                possible = True
            try:
                evidence = json.loads(row["evidence"])
            except (ValueError, TypeError):
                possible = True
            else:
                if not isinstance(evidence, dict) or evidence.get("terminal_input_attempted"):
                    possible = True
            handoffs = bridge.store.db.execute(
                "SELECT id,state,evidence FROM visible_handoffs WHERE message_id=?", (message_id,)
            ).fetchall()
            for handoff in handoffs:
                try:
                    saved = json.loads(handoff["evidence"])
                except (ValueError, TypeError):
                    saved = None
                safe_abort = (
                    handoff["state"] == "interrupted"
                    and isinstance(saved, dict)
                    and saved.get("preinput_abort") is True
                    and saved.get("terminal_input_attempted") is False
                    and not bridge.store.db.execute(
                        "SELECT 1 FROM visible_handoff_events WHERE id=? "
                        "AND state NOT IN ('planned','interrupted') LIMIT 1",
                        (handoff["id"],),
                    ).fetchone()
                )
                possible = possible or not safe_abort
            evidence = {
                "reason": code,
                "phase": "direct_admission",
                "terminal_input_attempted": "unconfirmed" if possible else False,
                "automatic_retry": False,
            }
            if observation:
                evidence["observation"] = observation
            if (
                not possible
                and not bridge.store.db.execute(
                    "SELECT 1 FROM queue_holds WHERE queue_id='messages' AND item_id=?",
                    (message_id,),
                ).fetchone()
            ):
                # The owned, proven pre-input rejection must not remain in the
                # recipient inbox as apparently fresh work. Reuse delivery holds;
                # keep the immutable body, job/error and idempotency receipt.
                bridge.queues._place_hold(
                    row["sender"], "messages", message_id, "direct_admission_rejected"
                )
                bridge.store.audit(
                    "queue.admission_rejected",
                    row["sender"],
                    None,
                    {
                        "queue": "messages",
                        "item_id": message_id,
                        "source": "direct_admission_rejected",
                        "terminal_input_attempted": False,
                        "history_preserved": True,
                    },
                )
            self.receiver._finish(message_id, "unknown" if possible else "failed", evidence, code)

    async def _deliver(self, principal, message_id, event):
        bridge = self.receiver.bridge
        leases = set()
        try:
            message = bridge.messages.get(principal, message_id)
            if not self._unclaimed(message_id):
                return
            recipient = message["recipient"]
            if not self.accepting:
                raise BridgeError("receiver_unavailable", "Direct receiver is not running")
            recipient_key = ("recipient", recipient)
            if (
                recipient_key in self.targets
                or bridge.store.db.execute(
                    "SELECT 1 FROM message_jobs j JOIN messages m ON m.id=j.message_id "
                    "WHERE m.recipient=? AND j.state='running' AND j.message_id<>? LIMIT 1",
                    (recipient, message_id),
                ).fetchone()
            ):
                raise BridgeError("execution_busy", "Recipient already owns an active turn")
            self.targets.add(recipient_key)
            leases.add(recipient_key)
            binding = None
            if bridge.config.visible_handoffs.enabled:
                await bridge.visible_handoffs.dispatch_ready(principal, recipient)
                binding = bridge.config.visible_handoffs.bindings.get(recipient)
                if binding is None:
                    raise BridgeError("visible_target_missing", "No assigned visible terminal")
                binding = binding.model_copy(deep=True)
                pane_key = ("pane", binding.pane_id)
                if pane_key in self.targets:
                    raise BridgeError(
                        "visible_target_busy", "This pane already owns an active turn"
                    )
                self.targets.add(pane_key)
                leases.add(pane_key)
            if not self._unclaimed(message_id):
                return
            async with MCPClientPool(call_timeout=15) as pool:
                await pool.connect(peer(bridge.config, recipient))
                if not self._unclaimed(message_id):
                    return
                claimed = self.receiver._claim(message_id, direct=True)
                if claimed is None:
                    raise BridgeError("delivery_not_admitted", "Message was not admitted")
                self._claimed[message_id] = claimed[1]
                await self.receiver._process(
                    pool, *claimed, delivery_event=event, delivery_binding=binding
                )
        except asyncio.CancelledError:
            self._settle(
                message_id,
                "delivery_timeout" if message_id in self._expired else "receiver_interrupted",
                uncertain=False,
                preserve_delivered=event.is_set(),
            )
            raise
        except Exception as error:
            self.fail(message_id, error)
        finally:
            self.targets.difference_update(leases)
            event.set()

    async def stop(self):
        """Cancel only this instance's attempts; preserve delivered reply waiters."""
        self.accepting = False
        if self._stop_task is None or self._stop_task.done():
            active = dict(self.active)
            events = {identifier: self.ready[identifier] for identifier in active}
            watchdogs = tuple(self._watchdogs.values())
            for watchdog in watchdogs:
                watchdog.cancel()
            for task in active.values():
                task.cancel()
            self._stop_task = asyncio.create_task(self._stop_owned(active, events, watchdogs))
        try:
            await asyncio.shield(self._stop_task)
        except asyncio.CancelledError:
            # A cancelled HTTP/shutdown observer does not abandon owned cleanup
            # or release reservations while the old coroutine still runs.
            await asyncio.shield(self._stop_task)
            raise

    async def _stop_owned(self, active, events, watchdogs):
        await asyncio.gather(*active.values(), *watchdogs, return_exceptions=True)
        # A task cancelled before its coroutine entered has no finally block.
        for identifier, event in events.items():
            self._settle(
                identifier,
                "receiver_interrupted",
                uncertain=False,
                preserve_delivered=event.is_set(),
            )
            event.set()
