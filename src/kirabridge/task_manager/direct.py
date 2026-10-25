"""Immediate bounded execution admission. Durable rows are journals, never work queues."""

import asyncio

from kirabridge.bridge_core.models import BridgeError
from kirabridge.operations import OPERATIONS


class DirectAdmission:
    def __init__(self, manager):
        self.manager = manager
        self.active = {}

    def check(self, operation):
        manager = self.manager
        if not manager.started:
            raise BridgeError("dispatcher_unavailable", "Dispatcher is not running; nothing queued")
        lane = OPERATIONS[operation].execution_class
        limit = {
            "normal": manager.config.concurrency,
            "read": manager.config.read_concurrency,
            "stop": 1,
        }[lane]
        if sum(current == lane for current, _ in self.active.values()) >= limit:
            raise BridgeError(
                "execution_busy", "Execution capacity is busy; request was not queued"
            )

    def start(self, identifier):
        manager = self.manager
        task = manager.store.get(identifier)
        lane = OPERATIONS[task["operation"]].execution_class
        work = asyncio.create_task(manager._execute(task))
        self.active[identifier] = (lane, work)

        def finished(result):
            self.active.pop(identifier, None)
            if not result.cancelled():
                result.exception()

        work.add_done_callback(finished)

    async def stop(self):
        identifiers = list(self.active)
        work = [entry[1] for entry in self.active.values()]
        for task in work:
            task.cancel()
        await asyncio.gather(*work, return_exceptions=True)
        from kirabridge.bridge_core.models import State

        for identifier in identifiers:
            if self.manager.store.get(identifier)["state"] in {State.ACCEPTED, State.RUNNING}:
                self.manager.store.transition(
                    identifier,
                    State.UNKNOWN,
                    {"reason": "dispatcher_stopped_before_confirmation", "automatic_retry": False},
                    owner=self.manager.owner,
                )
        self.active.clear()
