"""Runtime-owned, one-shot native admission; never a persisted replay queue."""

import asyncio

from kirabridge.bridge_core.models import State, TerminalInput, canonical
from kirabridge.permissions import direct_terminal_required


class NativeAdmission:
    timeout = 30.0

    def __init__(self, manager):
        self.manager = manager
        self.accepting = False
        self.active = {}
        self.events = {}
        self.targets = {}
        self.status = {}
        self.managed_admissions = {}
        self.expired = set()
        self.observer = None
        self.after_event = 0
        self._stop_task = None

    def start(self):
        self.after_event = self.manager.store.db.execute(
            "SELECT COALESCE(max(seq),0) FROM events"
        ).fetchone()[0]
        self.accepting = True
        self.observer = asyncio.create_task(self._observe_fresh_authorizations())

    async def _observe_fresh_authorizations(self):
        """Admit fresh CLI approvals without reviving pre-start queue history."""
        while self.accepting:
            try:
                rows = self.manager.store.db.execute(
                    "SELECT id FROM tasks WHERE state='queued' AND ("
                    "operation='terminal.visible' OR "
                    "(operation IN ('terminal.execute','admin.execute') AND "
                    "principal IN (SELECT value FROM json_each(?))) OR "
                    "(operation='session.input' AND "
                    "json_extract(args,'$.pane_id') LIKE 'terminal:%') OR "
                    "(operation='agent.execute' AND ?)) AND EXISTS ("
                    "SELECT 1 FROM events e WHERE e.task_id=tasks.id AND e.state='queued' "
                    "AND e.seq>? AND (json_extract(e.evidence,'$.local_operator_approved')=1 "
                    "OR EXISTS (SELECT 1 FROM events c WHERE c.task_id=tasks.id "
                    "AND c.state='created' AND c.seq>?))) ORDER BY created,id LIMIT ?",
                    (
                        canonical(self.manager.native_principals()),
                        self.manager.config.visible_handoffs.enabled,
                        self.after_event,
                        self.after_event,
                        self.manager.config.max_queued,
                    ),
                ).fetchall()
                for row in rows:
                    self.submit(row["id"])
            except Exception:
                # Storage uncertainty never authorizes execution or deletes a
                # queue entry. Other dispatcher lanes retain their own handling.
                pass
            await asyncio.sleep(0.1)

    def native(self, task):
        operation, arguments = task["operation"], task.get("args", {})
        return (
            operation == "terminal.visible"
            or operation in {"terminal.execute", "admin.execute"}
            and direct_terminal_required(self.manager.config, task.get("principal"))
            or operation == "session.input"
            and str(arguments.get("pane_id", "")).startswith("terminal:")
            or operation == "agent.execute"
            and self.manager.config.visible_handoffs.enabled
            and not getattr(self.manager, "is_sealed_managed_task", lambda task: False)(task)
        )

    def target(self, task):
        arguments = task.get("args", {})
        pane = arguments.get("pane_id")
        if pane:
            if not isinstance(pane, str):
                return ("invalid-target", task["id"])
            return ("pane", pane)
        if task["operation"] == "agent.execute":
            agent = arguments.get("agent")
            if not isinstance(agent, str):
                return ("invalid-agent", task["id"])
            binding = self.manager.config.visible_handoffs.bindings.get(agent)
            return ("pane", binding.pane_id) if binding else ("agent", agent)
        # The existing executor selects/opens an idle shell. Never select by cwd.
        return ("visible-shell-selection",)

    def submit(self, task_id):
        manager = self.manager
        task = manager.store.get(task_id)
        if not self.native(task) or task["state"] != State.QUEUED or task_id in self.events:
            return
        if not self.accepting:
            return  # Explicitly unadmitted; startup must not select this record.
        task = manager.store.claim_exact(manager.owner, manager.config.lease_seconds, task_id)
        if task is None:
            return
        event = self.events[task_id] = asyncio.Event()
        target = self.target(task)
        if target in self.targets or len(self.active) >= manager.config.max_queued:
            manager.store.transition(
                task_id,
                State.FAILED,
                {
                    "reason": "execution_busy",
                    "phase": "native_admission",
                    "terminal_input_attempted": False,
                    "automatic_retry": False,
                    "safe_to_retry": False,
                },
                error={"code": "execution_busy"},
                owner=manager.owner,
            )
            self.status[task_id] = "rejected"
            event.set()
            self.events.pop(task_id, None)
            self.status.pop(task_id, None)
            return
        self.targets[target] = task_id
        if self._managed_background(task):
            self.managed_admissions[task_id] = self._route_identity(task)
        self.status[task_id] = "admitting"
        running = self.active[task_id] = asyncio.create_task(self._run(task, target, event))

        def observed(done):
            if not done.cancelled():
                done.exception()  # A storage fault must not become an unobserved task exception.

        running.add_done_callback(observed)

    def observe(self, task_id, evidence):
        event = self.events.get(task_id)
        if event is None:
            return
        if self._managed_spawn_observed(task_id, evidence):
            # The trusted executor has durably observed this exact managed
            # process start. Admission ends; execution and its reservation do not.
            self.status[task_id] = "process_started"
            event.set()
        elif evidence.get("state") in {"sent", "confirmed", "completed"} and evidence.get(
            "handoff_id"
        ):
            self.status[task_id] = "confirmed_input"
            event.set()
        elif (
            evidence.get("terminal_input_attempted") is True
            or evidence.get("execution_route") == "visible_terminal"
        ):
            # This callback intentionally precedes native transport. Never call
            # it a confirmed paste/Return; the existing executor owns the result.
            self.status[task_id] = "input_attempted"
            event.set()

    @staticmethod
    def _route_identity(task):
        return task["operation"], task["principal"], canonical(task.get("args", {}))

    @staticmethod
    def _managed_background(task):
        # submit() has already admitted only a configured native principal. The
        # immutable route identity below binds every later spawn observation.
        if task["operation"] != "terminal.execute":
            return False
        try:
            # Match the executor's strict typed route, not arbitrary truthy args.
            return TerminalInput.model_validate(task.get("args", {})).background
        except ValueError:
            return False

    def _managed_spawn_observed(self, task_id, evidence):
        if (
            not self.accepting
            or task_id not in self.active
            or task_id in self.expired
            or self.status.get(task_id) != "admitting"
            or task_id not in self.managed_admissions
            or evidence.get("evidence_type") != "local_process_spawned"
            or type(evidence.get("pid")) is not int
            or not 0 < evidence["pid"] <= 2**31 - 1
        ):
            return False
        # This is an internal executor callback, never a user-supplied PID or
        # historical event. running()/progress() must have persisted the same
        # evidence under this runtime's lease before notifying admission.
        task = self.manager.store.get(task_id)
        return (
            self._managed_background(task)
            and self._route_identity(task) == self.managed_admissions[task_id]
            and task["state"] == State.RUNNING
            and task.get("lease_owner") == self.manager.owner
            and canonical(task.get("evidence")) == canonical(evidence)
        )

    async def _watch(self, task_id, event, execution):
        try:
            await asyncio.wait_for(event.wait(), self.timeout)
        except TimeoutError:
            self.expired.add(task_id)
            self.status[task_id] = "confirmation_unknown"
            execution.cancel()
            event.set()

    async def _run(self, task, target, event):
        task_id = task["id"]
        execution = asyncio.create_task(self.manager._execute(task))
        watchdog = asyncio.create_task(self._watch(task_id, event, execution))
        try:
            await execution
        finally:
            watchdog.cancel()
            await asyncio.gather(watchdog, return_exceptions=True)
            if self.status.get(task_id) == "admitting":
                self.status[task_id] = "finished"
            event.set()
            self.active.pop(task_id, None)
            self.events.pop(task_id, None)
            self.status.pop(task_id, None)
            self.managed_admissions.pop(task_id, None)
            self.expired.discard(task_id)
            if self.targets.get(target) == task_id:
                self.targets.pop(target)

    async def wait(self, task_id):
        event = self.events.get(task_id)
        if event is not None:
            # Cancellation of an HTTP caller never cancels the actual attempt.
            await asyncio.shield(event.wait())
        result = self.manager.store.get(task_id)
        if self.native(result):
            status = self.status.get(task_id)
            if status is None:
                status = (
                    "pending_approval"
                    if result["state"] == State.CREATED
                    else "not_admitted"
                    if result["state"] == State.QUEUED
                    else "execution_unresolved"
                    if result["state"] in {State.ACCEPTED, State.RUNNING}
                    else result["state"]
                )
            result["delivery"] = {
                "status": status,
                "automatic_retry": False,
                "scope": (
                    "managed process admission; process_started is not process completion"
                    if self._managed_background(result)
                    else "native input observation; input_attempted is not confirmed delivery"
                ),
            }
            if result["state"] == State.QUEUED and event is None:
                result["error"] = {
                    "code": "native_delivery_not_admitted",
                    "message": "Historical or unavailable native attempt; inspect without replay",
                }
            elif status in {"confirmation_unknown", "execution_unresolved"}:
                result["error"] = {
                    "code": "native_admission_timeout"
                    if status == "confirmation_unknown"
                    else "native_execution_unresolved",
                    "message": "Native delivery is unconfirmed; inspect this ID without replay",
                }
        return result

    async def stop(self):
        self.accepting = False
        if self._stop_task is None or self._stop_task.done():
            owned = list(self.active.items())
            events = {identifier: self.events.get(identifier) for identifier, _ in owned}
            for _, task in owned:
                task.cancel()
            observer = self.observer
            if observer is not None:
                observer.cancel()
                self.observer = None
            self._stop_task = asyncio.create_task(self._stop_owned(owned, events, observer))
        try:
            await asyncio.shield(self._stop_task)
        except asyncio.CancelledError:
            await asyncio.shield(self._stop_task)
            raise

    async def _stop_owned(self, owned, events, observer):
        await asyncio.gather(
            *(task for _, task in owned),
            *([observer] if observer is not None else []),
            return_exceptions=True,
        )
        # A task cancelled before its coroutine's first instruction has no
        # finally block. Close only these owned observations and reservations.
        for identifier, task in owned:
            current = self.manager.store.get(identifier)
            if current["state"] in {State.ACCEPTED, State.RUNNING}:
                self.manager.store.transition(
                    identifier,
                    State.UNKNOWN,
                    {
                        "reason": "native_dispatcher_stopped",
                        "automatic_retry": False,
                        "execution_stop_claimed": False,
                        "last_observation": current["evidence"],
                    },
                    error={"code": "native_dispatcher_stopped"},
                    owner=self.manager.owner,
                )
            if events[identifier] is not None:
                events[identifier].set()
            if self.active.get(identifier) is task:
                self.active.pop(identifier, None)
            self.events.pop(identifier, None)
            self.status.pop(identifier, None)
            self.managed_admissions.pop(identifier, None)
            self.expired.discard(identifier)
            for target, holder in list(self.targets.items()):
                if holder == identifier:
                    self.targets.pop(target)
