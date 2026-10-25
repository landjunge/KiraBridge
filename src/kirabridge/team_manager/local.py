"""A separate local console forwards automatic work directly to the authenticated daemon."""

from kirabridge.bridge_core.models import BridgeError
from kirabridge.local_runtime import peer
from kirabridge.mcp_gateway.client import MCPClientPool


async def delegate(manager, principal, request):
    worker = manager.config.team.workers.get(request.assignee)
    receiver = manager.direct_delivery
    if not worker or not worker.agent or (receiver and receiver.accepting):
        return manager.delegate(principal, request)
    async with MCPClientPool(call_timeout=15) as pool:
        await pool.connect(peer(manager.config, principal))
        health = (await pool.call("daemon", "bridge_health", {})).structuredContent
        if not health or health.get("team_dispatch_mode") != "direct":
            raise BridgeError("dispatcher_upgrade_required", "Daemon needs direct team delivery")
        response = await pool.call("daemon", "team_work_create", {"request": request.model_dump()})
        result = response.structuredContent
        if not isinstance(result, dict):
            raise BridgeError("team_delivery_unconfirmed", "Read original work; do not replay")
        if isinstance(result.get("error"), dict) and not result.get("id"):
            code = result["error"].get("code", "team_delivery_failed")
            raise BridgeError(code, "Team work was refused; nothing queued")
        return result
