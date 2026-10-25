"""Owner-only review forwards one exact approval to the running dispatcher, without a queue."""

from kirabridge.bridge_core.models import BridgeError, State, TaskRequest
from kirabridge.local_runtime import peer
from kirabridge.mcp_gateway.client import MCPClientPool


async def approve(manager, identifier, *, expected_hash=None, source="local_cli"):
    if manager.started:
        return manager.approve(identifier, expected_hash=expected_hash, source=source)
    with manager.store.transaction():
        task = manager.store.get(identifier)
        hashed = manager.store.db.execute(
            "SELECT request_hash FROM tasks WHERE id=?", (identifier,)
        ).fetchone()[0]
        if expected_hash is not None and expected_hash != hashed:
            raise BridgeError("review_conflict", "The reviewed request changed")
        if task["state"] != State.CREATED:
            raise BridgeError("state_conflict", "Only an exact pending review can be approved")
        request = TaskRequest(
            task_id=identifier,
            idempotency_key=task["idem"],
            operation=task["operation"],
            arguments=task["args"],
            parent_id=task["parent_id"],
        )
    async with MCPClientPool(call_timeout=15) as pool:
        await pool.connect(peer(manager.config, task["principal"]))
        health = (await pool.call("daemon", "bridge_health", {})).structuredContent
        if not health or health.get("dispatch_mode") != "direct":
            raise BridgeError(
                "dispatcher_upgrade_required", "Dispatcher does not support immediate admission"
            )
        approval = manager.security.grant(task["principal"], request)
        response = await pool.call(
            "daemon", "task_submit", {"request": request.model_dump(), "approval": approval}
        )
        result = response.structuredContent
        if not isinstance(result, dict) or result.get("error"):
            raise BridgeError(
                "approval_delivery_unconfirmed", "Read the original task; do not replay"
            )
        return result
