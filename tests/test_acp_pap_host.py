"""Optional local-wheel host parity; CI never fetches the private library."""

import asyncio
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from conftest import request, submit
from test_mcp import http_bridge  # noqa: F401

pytest.importorskip("acp_pap", reason="Opt-in tests require the reviewed local private wheel")

from kirabridge.agent_manager.acp_pap_host import ACPHostAdapter, ACPHostProfile  # noqa: E402
from kirabridge.bridge_core.config import AgentConfig, TeamConfig, TeamWorkerConfig  # noqa: E402
from kirabridge.mcp_gateway.client import MCPClientPool, Peer  # noqa: E402
from kirabridge.mcp_gateway.proxy import DaemonConnection  # noqa: E402
from kirabridge.team_manager.models import TeamCreate, TeamWorkCreate  # noqa: E402

FIXTURE = Path(__file__).with_name("fixtures") / "acp_pap_host_peer.py"


@pytest_asyncio.fixture
async def host(http_bridge, config, tmp_path):  # noqa: F811
    bridge, endpoint = http_bridge
    for policy in config.principals.values():
        policy.approval_mode = "automatic"
        policy.agents = [*policy.agents, "pap"]
    config.agents["pap"] = AgentConfig(
        kind="acp_pap_host", executable=sys.executable, bridge_tools=True
    )
    trace = tmp_path / "synthetic-trace"
    async with MCPClientPool() as pool:
        connection = DaemonConnection(
            pool, Peer("host-local", url=endpoint, token="local-test-" + "a" * 40)
        )
        adapter = ACPHostAdapter(
            bridge,
            lambda owner: connection,
            profile=ACPHostProfile(argv=(str(FIXTURE), str(trace))),
        )
        bridge.agents.register("acp_pap_host", adapter)
        yield bridge, config, adapter, trace, connection


def owned_task(config, text, task_id="pap-owned"):
    return request(
        "agent.execute",
        {
            "agent": "pap",
            "prompt": text,
            "cwd": config.principals["local"].roots[0],
            "timeout": 10,
            "mcp_operations": ["file.read"],
        },
        task_id=task_id,
    )


async def run_task(host, text, task_id="pap-owned"):
    bridge, config, _, _, _ = host
    value = owned_task(config, text, task_id)
    submit(bridge, value)
    return await bridge.tasks.wait("local", value.task_id, timeout=12)


async def test_real_core_grant_read_receipt_and_consumer_ack(host):
    bridge, config, _, trace, _ = host
    path = Path(config.principals["local"].roots[0]) / "source.txt"
    path.write_text("SYNTHETIC_FILE_ä\n")
    final = await run_task(host, "read:" + str(path))
    assert final["state"] == "completed", final
    assert final["result"]["text"] == path.read_text()
    assert final["result"]["request_sha256"] == final["request_sha256"]
    assert final["result"]["grant_ref"] and final["receipt"]
    assert trace.read_text().splitlines() == ["spawn", "prompt"]
    (notice,) = bridge.completions.receive("local", source_id=final["id"])["notices"]
    row = bridge.store.db.execute(
        "SELECT acknowledged FROM completion_notices WHERE id=?", (notice["id"],)
    ).fetchone()
    assert row[0] is None
    assert notice["payload"]["outcome"] == "success"
    ack = bridge.completions.ack("local", notice["id"], notice["receipt"])
    assert ack["ack_scope"] == "consumer_processed"
    assert not bridge.completions.receive("local", source_id=final["id"])["notices"]


@pytest.mark.parametrize("mode", ["outside", "symlink", "foreign", "terminal"])
async def test_existing_path_and_unsupported_terminal_policy_have_no_foreign_effect(
    host, tmp_path, mode
):
    bridge, config, _, _, _ = host
    outside = tmp_path / "outside.txt"
    outside.write_text("MUST_NOT_BE_READ")
    root = Path(config.principals["local"].roots[0])
    if mode == "symlink":
        path = root / "link.txt"
        path.symlink_to(outside)
    else:
        path = outside
    text = (
        "terminal"
        if mode == "terminal"
        else (("foreign:" if mode == "foreign" else "read:") + str(path))
    )
    final = await run_task(host, text)
    assert final["state"] == "completed", final
    assert final["result"]["text"] == (
        "terminal-rejected" if mode == "terminal" else "read-rejected"
    )
    assert final["result"]["ingress_rejection_count"] == (1 if mode == "foreign" else 0)
    assert outside.read_text() == "MUST_NOT_BE_READ"
    assert not bridge.terminal.sessions


async def test_delivery_error_persists_beside_confirmed_core_result(host):
    bridge, _, adapter, _, _ = host

    async def failed_sink(event):
        raise RuntimeError("synthetic sink failure")

    adapter.events = failed_sink
    final = await run_task(host, "confirmed despite delivery error")
    assert final["state"] == "completed", final
    assert final["result"]["text"] == "confirmed despite delivery error"
    assert final["result"]["delivery_failures"] == [
        {"target": "events", "count": 1, "error_type": "RuntimeError"}
    ]
    assert (
        bridge.completions.receive("local", source_id=final["id"])["notices"][0]["payload"][
            "outcome"
        ]
        == "success"
    )


async def test_cancel_pending_permission_returns_confirmed_cancelled_without_replay(host):
    bridge, config, adapter, trace, _ = host
    entered, cleaned = asyncio.Event(), asyncio.Event()

    async def pending(binding, tool_call, options):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    adapter.permission_decider = pending
    value = owned_task(config, "permission")
    submit(bridge, value)
    await asyncio.wait_for(entered.wait(), 5)
    await adapter.cancel(value.task_id)
    final = await bridge.tasks.wait("local", value.task_id, timeout=5)
    assert final["state"] == "failed", final
    assert final["result"]["stop_reason"] == "cancelled"
    assert cleaned.is_set() and not adapter.active
    notice = bridge.completions.receive("local", source_id=final["id"])["notices"][0]
    assert notice["payload"]["outcome"] == "cancelled"
    assert trace.read_text().splitlines() == ["spawn", "prompt"]


@pytest.mark.parametrize("interruption", ["eof", "slow"])
async def test_eof_keeps_core_unknown_and_same_request_does_not_restart(host, interruption):
    bridge, config, adapter, trace, _ = host
    value = owned_task(config, interruption)
    if interruption == "slow":
        value.arguments["timeout"] = 3
    submit(bridge, value)
    final = await bridge.tasks.wait("local", value.task_id, timeout=5)
    assert final["state"] == "unknown", final
    assert final["attempt"] == 1 and final["receipt"] and not adapter.active
    assert bridge.submit("local", value)["state"] == "unknown"
    assert trace.read_text().splitlines() == ["spawn", "prompt"]
    notice = bridge.completions.receive("local", source_id=final["id"])["notices"][0]
    assert notice["payload"]["execution_outcome_unknown"]
    assert notice["payload"]["session_id"]


@pytest.mark.parametrize("revoked", ["capability", "agent", "lease"])
async def test_permission_reply_rechecks_current_core_principal_grant(host, revoked):
    from acp.schema import AllowedOutcome, RequestPermissionResponse

    bridge, config, adapter, trace, _ = host
    entered, release = asyncio.Event(), asyncio.Event()

    async def pending(binding, tool_call, options):
        entered.set()
        await release.wait()
        return RequestPermissionResponse(outcome=AllowedOutcome(option_id="ok"))

    adapter.permission_decider = pending
    value = owned_task(config, "permission")
    submit(bridge, value)
    await asyncio.wait_for(entered.wait(), 5)
    if revoked == "capability":
        config.principals["local"].capabilities.remove("agent.execute")
    elif revoked == "agent":
        config.principals["local"].agents.remove("pap")
    else:
        bridge.store.db.execute("UPDATE tasks SET lease_until=0 WHERE id=?", (value.task_id,))
    release.set()
    final = await bridge.tasks.wait("local", value.task_id, timeout=5)
    assert final["state"] == "failed", final
    assert final["result"]["terminal_response"] == "rpc_error"
    assert trace.read_text().splitlines() == ["spawn", "prompt"]


async def test_permission_without_host_decider_is_denied(host):
    final = await run_task(host, "permission")
    assert final["state"] == "failed", final
    assert final["result"]["stop_reason"] == "cancelled"


async def test_owned_session_and_read_capability_do_not_replace_task_read_grant(host):
    bridge, config, _, trace, _ = host
    path = Path(config.principals["local"].roots[0]) / "private.txt"
    path.write_text("MUST_NOT_BE_READ")
    value = owned_task(config, "read:" + str(path))
    value.arguments["mcp_operations"] = []
    submit(bridge, value)
    final = await bridge.tasks.wait("local", value.task_id, timeout=12)
    assert final["state"] == "completed", final
    assert final["result"]["text"] == "read-rejected"
    assert trace.read_text().splitlines() == ["spawn", "prompt"]


async def test_actual_team_dispatcher_seals_core_request_and_consumes_result(host):
    bridge, config, _, trace, _ = host
    for policy in config.principals.values():
        policy.capabilities += ["team.manage", "team.read", "team.write"]
    config.team = TeamConfig(
        enabled=True,
        workers={
            "other": TeamWorkerConfig(),
            "local": TeamWorkerConfig(
                agent="pap",
                cwd=config.principals["local"].roots[0],
                execution_scope="separate_managed_session",
                timeout=10,
                mcp_operations=["file.read"],
            ),
        },
    )
    bridge.teams.create(
        "other",
        TeamCreate(
            team_id="pap-team",
            name="Synthetic",
            coordinator="other",
            members={"other": "coordinator", "local": "worker"},
            idempotency_key="create",
        ),
    )
    work = bridge.teams.delegate(
        "other",
        TeamWorkCreate(
            team_id="pap-team",
            assignee="local",
            title="Synthetic host parity",
            body="Return the synthetic team envelope",
            idempotency_key="once",
        ),
    )
    await bridge.team_dispatcher.start()
    async with asyncio.timeout(15):
        while True:
            final = bridge.teams.work_get("other", "pap-team", work["id"])
            if final["state"] in {"completed", "failed", "unknown", "blocked"}:
                break
            await asyncio.sleep(0.02)
    assert final["state"] == "completed", final
    core = bridge.task("local", final["core_task_id"])
    assert core["state"] == "completed" and core["attempt"] == 1
    row = bridge.store.db.execute(
        "SELECT core_request_hash FROM team_work WHERE id=?", (work["id"],)
    ).fetchone()
    assert row[0] == core["request_sha256"]
    assert trace.read_text().splitlines() == ["spawn", "prompt"]


async def test_wrong_library_pin_fails_before_synthetic_spawn(host, monkeypatch):
    _, _, _, trace, _ = host
    monkeypatch.setattr(
        "kirabridge.agent_manager.acp_pap_host._MODULE_HASHES", {"client.py": "0" * 64}
    )
    final = await run_task(host, "must not start")
    assert final["state"] == "failed", final
    assert final["error"]["code"] == "acp_dependency_unavailable"
    assert not trace.exists()
