"""Actual private Core OS restarts; TD stays in-process, CLI/grants are synthetic."""

import asyncio
import json
import os
import signal
import socket
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from test_handoff import configure
from test_remote_relay import certificate, final, intent, relay, tls_server

from kirabridge.mcp_gateway.client import Peer
from kirabridge.remote_handoff_peer import HttpHandoffPeer
from kirabridge.remote_relay import DeviceBinding
from kirabridge.security_manager import SecurityManager
from kirabridge.task_manager.store import Store
from kirabridge.tls_identity import certificate_identity, pinned_context

pytestmark = pytest.mark.skipif(
    os.name != "posix" or not os.environ.get("KIRABRIDGE_TEST_REMOTE_THREADDESK_SOURCE"),
    reason="Explicit paired TD source and POSIX child-process signals required",
)


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def durable_tasks(config):
    with sqlite3.connect(f"file:{config.state_path / 'bridge.sqlite3'}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        return [
            dict(row)
            for row in db.execute(
                "SELECT id,state,receipt,request_hash,finished FROM tasks ORDER BY created"
            )
        ]


class OwnedCore:
    def __init__(self, root, config, source, cert, key):
        self.config = config
        self.trace = root / "core-lifecycle.jsonl"
        self.log = root / "core-child.log"
        self.settings = root / "core-child.json"
        serialized = config.model_dump(mode="json")
        # Product parser remains strict; the child reconstructs the same explicit
        # test-only in-memory fixture used by R2 after validating legal config.
        serialized["visible_handoffs"]["enabled"] = True
        self.settings.write_text(
            json.dumps(
                {
                    "config": serialized,
                    "source": source,
                    "trace": str(self.trace),
                    "fixture_profile": "r2-owned-python-agent",
                }
            )
        )
        self.settings.chmod(0o600)
        self.cert, self.key = cert, key
        self.process = None
        self.identities = []
        self.exits = []

    async def start(self):
        assert self.process is None or self.process.returncode is not None
        before = len(lines(self.trace))
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        sock.listen(32)
        port = sock.getsockname()[1]
        try:
            with self.log.open("ab") as output:
                self.process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    str(Path(__file__).with_name("remote_core_child.py")),
                    str(self.settings),
                    str(sock.fileno()),
                    pass_fds=(sock.fileno(),),
                    start_new_session=True,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=output,
                    stderr=output,
                    env={
                        **os.environ,
                        "PYTHONDONTWRITEBYTECODE": "1",
                        # Reuse the parent's explicit test dependency/source path.
                        # This also carries R2's existing FastAPI installation;
                        # installing extra packages is not part of this test.
                        "PYTHONPATH": os.pathsep.join(str(p) for p in sys.path if p),
                    },
                )
        finally:
            sock.close()
        async with asyncio.timeout(15):
            while True:
                ready = [r for r in lines(self.trace)[before:] if r["event"] == "ready"]
                if ready:
                    identity = ready[-1]
                    assert identity["pid"] == identity["runtime_pid"] == self.process.pid
                    assert Path(identity["source_package_path"]).resolve() == (
                        Path(__file__).resolve().parents[1] / "src" / "kirabridge"
                    )
                    self.identities.append(identity)
                    break
                if self.process.returncode is not None:
                    raise RuntimeError("Owned Core failed to start; see private core-child.log")
                await asyncio.sleep(0.01)
        identity = certificate_identity(self.cert)
        return Peer(
            "device",
            url=f"https://127.0.0.1:{port}/mcp",
            token="k" * 40,
            ca_file=str(self.cert),
            certificate_sha256=identity.certificate_sha256,
        )

    async def stop(self, *, hard=False):
        child = self.process
        assert child is not None and child.returncode is None
        assert self.identities[-1]["pid"] == child.pid
        # This handle came from our own create_subprocess_exec; no PID lookup or
        # operator process is targeted. The tested kill point is completed below.
        child.send_signal(signal.SIGKILL if hard else signal.SIGTERM)
        code = await asyncio.wait_for(child.wait(), 15)
        self.exits.append({"pid": child.pid, "returncode": code, "hard": hard})
        assert code == (-signal.SIGKILL if hard else 0)
        if not hard:
            assert any(
                r["event"] == "core_closed" and r["pid"] == child.pid for r in lines(self.trace)
            )

    async def close(self):
        child = self.process
        if child is not None and child.returncode is None:
            child.terminate()
            try:
                await asyncio.wait_for(child.wait(), 15)
            except TimeoutError:
                child.kill()
                await child.wait()
                raise AssertionError("Owned Core needed forced cleanup") from None


@pytest.fixture
async def remote_os(config, tmp_path, monkeypatch):
    source_root = os.environ["KIRABRIDGE_TEST_REMOTE_THREADDESK_SOURCE"]
    monkeypatch.syspath_prepend(source_root)
    monkeypatch.setenv("KIRABRIDGE_TEST_THREADDESK_SOURCE", source_root)
    from threaddesk.server_sync.app import create_app
    from threaddesk.server_sync.auth import provision
    from threaddesk.server_sync.handoffs import subject_ref

    counter = configure(config, tmp_path, question=False)
    for policy in config.principals.values():
        policy.approval_mode = "manual"
    monkeypatch.setenv("REMOTE_FIXTURE_TOKEN", "k" * 40)
    config.principals["local"].token_env = "REMOTE_FIXTURE_TOKEN"
    td_cert, td_key = certificate(tmp_path, "source")
    kb_cert, kb_key = certificate(tmp_path, "device")
    config.tls_cert, config.tls_key = str(kb_cert), str(kb_key)
    data = tmp_path / "owned-td"
    token = provision(data, "alice")
    td_identity, kb_identity = certificate_identity(td_cert), certificate_identity(kb_cert)
    async with tls_server(
        lambda origin: create_app(data, public_origin=origin, handoff_rpc=True), td_cert, td_key
    ) as origin:
        async with httpx.AsyncClient(
            base_url=origin,
            headers={"Authorization": "Bearer " + token},
            verify=pinned_context(str(td_cert), td_identity.certificate_sha256),
            trust_env=False,
        ) as http:
            response = await http.post("/api/projects", json={"title": "Owned R3 process restart"})
            assert response.status_code == 200
            project = response.json()["id"]
            source_config = {
                "origin": origin,
                "project_id": project,
                "subject_ref": subject_ref("alice", project),
                "service_ref": "owned-source",
                "tenant_ref": "owned-tenant",
                "device_ref": "owned-device",
                "device_key_sha256": kb_identity.public_key_sha256,
                "token": token,
                "certificate_file": str(td_cert),
                "certificate_sha256": td_identity.certificate_sha256,
            }
            async with HttpHandoffPeer(**source_config) as source:
                core = OwnedCore(tmp_path, config, source_config, kb_cert, kb_key)

                def grant(principal, request):
                    # Same trusted local grant API as R2, restricted to the private
                    # test database; no parent Bridge/dispatcher is started.
                    store = Store(config.state_path / "bridge.sqlite3")
                    try:
                        return SecurityManager(config, store).grant(principal, request)
                    finally:
                        store.close()

                grants = {}
                remote = SimpleNamespace(
                    source=source,
                    bridge=SimpleNamespace(security=SimpleNamespace(grant=grant)),
                    binding=DeviceBinding(
                        "owned-device",
                        kb_identity.public_key_sha256,
                        1,
                        "owned-workspace",
                        config.principals["local"].roots[0],
                    ),
                    grants=grants,
                    resolve=grants.get,
                    http=http,
                    pid=project,
                    config=config,
                    counter=counter,
                    core=core,
                )
                try:
                    yield remote
                finally:
                    await core.close()
                    assert core.process is None or core.process.returncode is not None


@pytest.mark.parametrize("hard", [False, True], ids=["sigterm-completed", "sigkill-completed"])
async def test_completed_receipt_survives_real_core_process_restart_once(remote_os, tmp_path, hard):
    remote = remote_os
    envelope = await intent(remote, "os-restart")
    remote.peer = await remote.core.start()
    submits = []

    def observe(coordinator):
        original = coordinator.pool.call

        async def call(peer, tool, arguments, **context):
            if tool == "task_submit":
                submits.append(arguments["request"]["task_id"])
            return await original(peer, tool, arguments, **context)

        coordinator.pool.call = call

    async with relay(remote) as coordinator:
        observe(coordinator)
        await coordinator.deliver(envelope)
        before = await final(remote, coordinator, envelope)
        assert before["state"] == "completed", before
        value = before["result"]["value"]
        assert value["phase"] == "delivered_unverified"
        returned = await remote.source.call("get_return", {"return_id": value["return_id"]})
        assert returned["item"]["binding_status"] == "issued_bound"
        assert returned["item"]["decision"] is None
    checkpoint = durable_tasks(remote.config)
    assert len(checkpoint) == 1 and checkpoint[0]["state"] == "completed"
    assert checkpoint[0]["receipt"] == before["receipt"] and checkpoint[0]["finished"] is not None
    assert len(lines(remote.counter)) == 1
    # Both signal cases use an explicitly observed durable completed point.
    # No in-flight CLI child is deliberately orphaned by this test.
    await remote.core.stop(hard=hard)
    remote.peer = await remote.core.start()
    old, new = remote.core.identities
    assert old["pid"] != new["pid"] and old["generation"] != new["generation"]
    async with relay(remote, clock=lambda: envelope["expires_at"] + 1) as restarted:
        observe(restarted)
        after = await restarted.deliver(envelope)
        readback = await restarted.reconcile(envelope)
    assert after["id"] == readback["id"] == before["id"]
    assert after["receipt"] == readback["receipt"] == before["receipt"]
    assert after["result"] == before["result"]
    assert durable_tasks(remote.config) == checkpoint
    assert submits == [envelope["request"]["task_id"]]
    trace = lines(remote.core.trace)
    server_submits = [r for r in trace if r["event"] == "task_submit"]
    assert len(server_submits) == 1
    assert server_submits[0]["task_id"] == before["id"]
    assert len(lines(remote.counter)) == 1
    returned_after = await remote.source.call("get_return", {"return_id": value["return_id"]})
    assert returned_after == returned
    await remote.core.stop()
    evidence = {
        "case": "sigkill-completed" if hard else "sigterm-completed",
        "kill_point": "Core completed receipt and TD issued-bound unverified return durably read",
        "task_id": before["id"],
        "receipt": before["receipt"],
        "state": after["state"],
        "request_sha256": checkpoint[0]["request_hash"],
        "client_task_submit_calls": len(submits),
        "server_submit_calls": len(server_submits),
        "core_task_count": len(checkpoint),
        "fixture_runs": len(lines(remote.counter)),
        "identities": remote.core.identities,
        "exits": remote.core.exits,
        "same_result": True,
        "same_td_return": True,
        "all_owned_children_reaped": True,
        "limits": [
            "No in-flight kill, TD restart, OS reboot, service manager, mobile or production test"
        ],
    }
    (tmp_path / "r3-evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
