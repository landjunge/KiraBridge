"""One immediate attempt per message. Persisted records are receipts, never backlogs."""

import asyncio

from kirabridge.bridge_core.models import BridgeError
from kirabridge.local_runtime import peer
from kirabridge.mcp_gateway.client import MCPClientPool


class DirectDelivery:
    def __init__(self, receiver):
        self.receiver = receiver
        self.active = {}
        self.ready = {}
        self.targets = set()
        self.accepting = False

    def submit(self, principal, identifier, reference=None):
        if identifier in self.active:
            return
        event = asyncio.Event()
        self.ready[identifier] = event
        task = asyncio.create_task(self._deliver(principal, identifier, reference, event))
        self.active[identifier] = task

        def finished(result):
            self.active.pop(identifier, None)
            self.ready.pop(identifier, None)
            event.set()
            if not result.cancelled():
                result.exception()

        task.add_done_callback(finished)

    async def wait_delivery(self, identifier):
        event = self.ready.get(identifier)
        if event:
            # Bound the caller's delivery observation, never create a retry.
            async with asyncio.timeout(30):
                await event.wait()

    async def _deliver(self, principal, identifier, reference, event):
        owner = self.receiver
        bridge = owner.bridge
        recipient = bridge.messages.get(principal, identifier)["recipient"]
        target = None
        try:
            if not self.accepting:
                raise BridgeError("receiver_unavailable", "Direct receiver is not running")
            if recipient in self.targets:
                raise BridgeError("execution_busy", "Recipient is busy; message was not queued")
            self.targets.add(recipient)
            target = recipient
            binding = None
            if bridge.config.visible_handoffs.enabled:
                from kirabridge.session_resolution import resolve

                binding = await resolve(
                    bridge.sessions,
                    bridge.config.visible_handoffs.bindings,
                    principal,
                    recipient,
                    reference,
                )
                await bridge.visible_handoffs.check_target(
                    principal, recipient, binding, ready=True
                )
            async with MCPClientPool(call_timeout=15) as pool:
                await pool.connect(peer(bridge.config, recipient))
                claimed = owner._claim(identifier)
                if not claimed:
                    raise BridgeError(
                        "delivery_not_admitted", "Message was not admitted; nothing queued"
                    )
                if claimed:
                    message, run_id = claimed
                    await owner._process(
                        pool, message, run_id, binding=binding, delivery_event=event
                    )
        except asyncio.CancelledError:
            with bridge.store.transaction():
                owner._finish(
                    identifier,
                    "unknown",
                    {"reason": "direct_delivery_interrupted", "automatic_retry": False},
                    "delivery_unknown",
                )
            raise
        except Exception as exc:
            with bridge.store.transaction():
                job = bridge.store.db.execute(
                    "SELECT started FROM message_jobs WHERE message_id=?", (identifier,)
                ).fetchone()
                handoffs = bridge.store.db.execute(
                    "SELECT state,evidence FROM visible_handoffs WHERE message_id=?", (identifier,)
                ).fetchall()
                import json

                possible = bool(job and job["started"] is not None) or any(
                    h["state"] != "interrupted"
                    or json.loads(h["evidence"]).get("preinput_abort") is not True
                    for h in handoffs
                )
                owner._finish(
                    identifier,
                    "unknown" if possible else "failed",
                    {
                        "reason": getattr(exc, "code", "delivery_failed"),
                        "terminal_input_attempted": "unconfirmed" if possible else False,
                        "automatic_retry": False,
                    },
                    getattr(exc, "code", "delivery_failed"),
                )
        finally:
            event.set()
            if target:
                self.targets.discard(target)

    async def stop(self):
        self.accepting = False
        identifiers = list(self.active)
        tasks = list(self.active.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        with self.receiver.bridge.store.transaction():
            for identifier in identifiers:
                self.receiver._finish(
                    identifier,
                    "unknown",
                    {"reason": "receiver_stopped_before_confirmation", "automatic_retry": False},
                    "delivery_unknown",
                )
