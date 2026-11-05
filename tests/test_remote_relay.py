"""Real isolated TLS/TD/Core integration; the CLI and human approval are synthetic."""

import asyncio
import datetime
import ipaddress
import json
import os
import socket
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import uvicorn

from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.models import BridgeError, TaskRequest, UncertainExecution, digest
from kirabridge.mcp_gateway.client import Peer
from kirabridge.mcp_gateway.http import create_http_app
from kirabridge.remote_handoff_peer import HttpHandoffPeer
from kirabridge.remote_relay import DeviceBinding, NativeGrant, RemoteRelay, grant_binding_sha256
from kirabridge.tls_identity import certificate_identity, pinned_context

pytestmark = pytest.mark.skipif(
    not os.environ.get("KIRABRIDGE_TEST_REMOTE_THREADDESK_SOURCE"),
    reason="Explicit paired remote ThreadDesk source required; legacy MCP source is separate",
)


def certificate(tmp_path, name, *, ca=False):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(hours=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / f"{name}.pem", tmp_path / f"{name}.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    key_path.chmod(0o600)
    return cert_path, key_path


@asynccontextmanager
async def tls_server(app_factory, cert, key):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(32)
    origin = f"https://127.0.0.1:{sock.getsockname()[1]}"
    server = uvicorn.Server(
        uvicorn.Config(
            app_factory(origin),
            log_level="critical",
            access_log=False,
            ssl_certfile=str(cert),
            ssl_keyfile=str(key),
        )
    )
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(10):
            while not server.started:
                if task.done():
                    await task
                await asyncio.sleep(0.01)
        yield origin
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 10)
        sock.close()


@pytest.fixture
async def remote(config, tmp_path, monkeypatch):
    source_root = os.environ["KIRABRIDGE_TEST_REMOTE_THREADDESK_SOURCE"]
    monkeypatch.syspath_prepend(source_root)
    monkeypatch.setenv("KIRABRIDGE_TEST_THREADDESK_SOURCE", source_root)
    from test_handoff import configure
    from threaddesk.server_sync.app import create_app
    from threaddesk.server_sync.auth import provision
    from threaddesk.server_sync.handoffs import subject_ref

    # Explicitly selected isolated managed-agent profile, never a visible-route fallback.
    counter = configure(config, tmp_path, question=False)
    for policy in config.principals.values():
        policy.approval_mode = "manual"
    monkeypatch.setenv("REMOTE_FIXTURE_TOKEN", "k" * 40)
    config.principals["local"].token_env = "REMOTE_FIXTURE_TOKEN"
    td_cert, td_key = certificate(tmp_path, "source")
    kb_cert, kb_key = certificate(tmp_path, "device")
    config.tls_cert, config.tls_key = str(kb_cert), str(kb_key)
    data = tmp_path / "remote-source"
    token = provision(data, "alice")
    td_identity, kb_identity = certificate_identity(td_cert), certificate_identity(kb_cert)
    async with tls_server(
        lambda origin: create_app(data, public_origin=origin, handoff_rpc=True), td_cert, td_key
    ) as td_origin:
        async with httpx.AsyncClient(
            base_url=td_origin,
            headers={"Authorization": "Bearer " + token},
            verify=pinned_context(str(td_cert), td_identity.certificate_sha256),
            trust_env=False,
        ) as http:
            response = await http.post("/api/projects", json={"title": "Owned synthetic remote"})
            assert response.status_code == 200, response.text
            pid = response.json()["id"]
            async with HttpHandoffPeer(
                td_origin,
                pid,
                subject_ref("alice", pid),
                service_ref="owned-source",
                tenant_ref="owned-tenant",
                device_ref="owned-device",
                device_key_sha256=kb_identity.public_key_sha256,
                token=token,
                certificate_file=str(td_cert),
                certificate_sha256=td_identity.certificate_sha256,
            ) as source:
                bridge = Bridge(config, handoff_peer=source)
                async with bridge:
                    async with tls_server(lambda _: create_http_app(bridge), kb_cert, kb_key) as kb:
                        peer = Peer(
                            "device",
                            url=kb + "/mcp",
                            token="k" * 40,
                            ca_file=str(kb_cert),
                            certificate_sha256=kb_identity.certificate_sha256,
                        )
                        binding = DeviceBinding(
                            "owned-device",
                            kb_identity.public_key_sha256,
                            1,
                            "owned-workspace",
                            config.principals["local"].roots[0],
                        )
                        grants = {}
                        yield SimpleNamespace(
                            source=source,
                            bridge=bridge,
                            peer=peer,
                            binding=binding,
                            grants=grants,
                            resolve=grants.get,
                            http=http,
                            pid=pid,
                            counter=counter,
                            token=token,
                            config=config,
                            td_cert=td_cert,
                            td_origin=td_origin,
                        )
                bridge.store.close()


async def intent(remote, suffix="one", *, ttl=120, timeout=10.0):
    thread = (await remote.http.get(f"/api/projects/{remote.pid}/thread")).json()
    packet = await remote.source.call(
        "issue_handoff",
        {
            "operation_id": "issue-" + suffix,
            "id": remote.pid,
            "expected_revision": thread["revision"],
            "target": "codex",
        },
    )
    issued = (await remote.source.call("get_issued_handoff", {"handoff_id": packet["handoff_id"]}))[
        "issued"
    ]
    request = TaskRequest(
        task_id="remote-" + suffix,
        idempotency_key="remote-" + suffix,
        operation="handoff.start",
        arguments={
            "handoff_id": packet["handoff_id"],
            "revision": packet["revision"],
            "agent": "codex",
            "cwd": remote.binding.workspace_path,
            "timeout": timeout,
        },
    )
    now = int(datetime.datetime.now(datetime.UTC).timestamp())
    envelope = {
        "format": "kirabridge.remote-task.v1",
        "kind": "intent",
        "route": "separate_managed_session",
        "request": request.model_dump(),
        "request_sha256": digest(request.model_dump()),
        "source": {
            "kind": "issued_handoff",
            "service_ref": remote.source.service_ref,
            "tenant_ref": remote.source.tenant_ref,
            "actor_ref": remote.source.subject_ref,
            "thread_id": remote.pid,
            "thread_revision": issued["source"]["thread_revision"],
            "content_sha256": issued["content_hash"],
            "handoff_id": packet["handoff_id"],
            "handoff_revision": packet["revision"],
            "original_task_id": packet["task_id"],
        },
        "target": {
            "device_ref": remote.binding.device_ref,
            "device_key_sha256": remote.binding.public_key_sha256,
            "authority_revision": 1,
            "workspace_ref": remote.binding.workspace_ref,
        },
        "authorization": {"grant_ref": "grant-" + suffix, "grant_sha256": "0" * 64},
        "issued_at": now - 1,
        "expires_at": now + ttl,
    }
    envelope["authorization"]["grant_sha256"] = grant_binding_sha256(envelope)
    remote.grants["grant-" + suffix] = NativeGrant(
        grant_binding_sha256(envelope), "local", remote.bridge.security.grant("local", request)
    )
    return envelope


def relay(remote, **kwargs):
    return RemoteRelay(remote.source, remote.peer, remote.binding, remote.resolve, **kwargs)


async def final(remote, coordinator, envelope):
    async with asyncio.timeout(10):
        while True:
            task = await coordinator.reconcile(envelope)
            if task["state"] in {"completed", "failed", "unknown", "blocked"}:
                return task
            await asyncio.sleep(0.01)


async def test_two_authorized_tasks_once_returns_read_back_and_restart(remote):
    for suffix in ("one", "two"):
        envelope = await intent(remote, suffix)
        async with relay(remote) as coordinator:
            task = await coordinator.deliver(envelope)
            assert task["id"] == "remote-" + suffix
            task = await final(remote, coordinator, envelope)
            assert task["state"] == "completed", task
            value = task["result"]["value"]
            assert value["phase"] == "delivered_unverified"
            assert not value["project_completion_verified"]
            stored = await remote.source.call("get_return", {"return_id": value["return_id"]})
            assert stored["item"]["decision"] is None
            assert stored["item"]["binding_status"] == "issued_bound"
            assert stored["item"]["return"]["review_status"] == "unverified"
            # This source has no independent remote operator credential in this slice.
            with pytest.raises(BridgeError, match="interactive TD decision"):
                await remote.source.call(
                    "review_return",
                    {"return_id": value["return_id"], "choice": "accepted", "note": "Worker"},
                )
            async with httpx.AsyncClient(
                base_url=remote.td_origin,
                verify=pinned_context(
                    str(remote.td_cert), certificate_identity(remote.td_cert).certificate_sha256
                ),
                trust_env=False,
            ) as operator:
                login = (await operator.post("/auth/login", json={"token": remote.token})).json()
                response = await operator.post(
                    f"/api/projects/{remote.pid}/handoff",
                    json={
                        "tool": "review_return",
                        "arguments": {
                            "return_id": value["return_id"],
                            "choice": "accepted",
                            "note": "Synthetic operator checks owned fixture artifact",
                        },
                    },
                    headers={"X-ThreadDesk-CSRF": login["csrf"]},
                )
                assert response.status_code == 403
            unreviewed = await remote.source.call("get_return", {"return_id": value["return_id"]})
            assert unreviewed["item"]["decision"] is None
            # A new client context only reads the original task, even after expiry.
        async with relay(
            remote, clock=lambda expiry=envelope["expires_at"]: expiry + 1
        ) as restarted:
            assert (await restarted.deliver(envelope))["receipt"] == task["receipt"]
        if suffix == "one":
            # Honor the existing source's 15s handoff cooldown; do not disable it.
            await asyncio.sleep(15.1)
    assert len(remote.counter.read_text().splitlines()) == 2
    board = (await remote.http.get(f"/api/projects/{remote.pid}/whiteboard")).json()["entries"]
    assert sum("Synthetisches Ergebnis" in entry["content"] for entry in board) == 2
    assert (Path(remote.binding.workspace_path) / "synthetic-result.txt").read_text() == "blue"


@pytest.mark.parametrize("field", ["target", "source", "request", "authorization"])
async def test_changed_binding_never_starts_any_task(remote, field):
    envelope = await intent(remote)
    if field == "target":
        envelope[field]["device_key_sha256"] = "0" * 64
    elif field == "source":
        envelope[field]["tenant_ref"] = "foreign-tenant"
    elif field == "request":
        envelope[field]["arguments"]["cwd"] = "/foreign-workspace"
    else:
        envelope[field]["grant_ref"] = "missing-grant"
    async with relay(remote) as coordinator:
        with pytest.raises(BridgeError):
            await coordinator.deliver(envelope)
    assert remote.bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0
    assert not remote.counter.exists()


async def test_expired_and_ungranted_work_is_not_started(remote):
    envelope = await intent(remote)
    async with relay(remote, clock=lambda: envelope["expires_at"]) as coordinator:
        with pytest.raises(BridgeError, match="admission window"):
            await coordinator.deliver(envelope)
    assert not remote.counter.exists()


async def test_crash_after_durable_reservation_never_replays(remote):
    envelope = await intent(remote)
    assert await remote.source.reserve_attempt(envelope, "local")
    async with relay(remote) as restarted:
        with pytest.raises(UncertainExecution, match="Existing dispatch marker"):
            await restarted.deliver(envelope)
        with pytest.raises(UncertainExecution, match="No Core receipt"):
            await restarted.reconcile(envelope)
    assert not remote.counter.exists()


async def test_lost_submit_reply_only_reconciles_original_core_task(remote, monkeypatch):
    envelope = await intent(remote)
    async with relay(remote) as coordinator:
        original = coordinator.pool.call

        async def lose_reply(peer, tool, arguments, **kwargs):
            result = await original(peer, tool, arguments, **kwargs)
            if tool == "task_submit":
                raise OSError("synthetic lost response after real submission")
            return result

        monkeypatch.setattr(coordinator.pool, "call", lose_reply)
        with pytest.raises(UncertainExecution, match="Original submission outcome unknown"):
            await coordinator.deliver(envelope)
    async with relay(remote) as restarted:
        task = await final(remote, restarted, envelope)
        assert task["state"] == "completed"
        assert (await restarted.deliver(envelope))["receipt"] == task["receipt"]
    assert len(remote.counter.read_text().splitlines()) == 1


async def test_visible_production_profile_gate_is_preserved(remote):
    remote.config.visible_handoffs.enabled = True
    envelope = await intent(remote)
    async with relay(remote) as coordinator:
        await coordinator.deliver(envelope)
        task = await final(remote, coordinator, envelope)
        assert task["state"] == "failed"
        assert "visible" in json.dumps(task["result"])
    assert not remote.counter.exists()


async def test_unknown_cli_turn_never_gets_a_second_execution(remote):
    executable = Path(remote.config.agents["codex"].executable)
    executable.write_text(
        executable.read_text().replace(
            "print(json.dumps({'type':'turn.completed'}),flush=True)", ""
        )
    )
    envelope = await intent(remote)
    async with relay(remote) as coordinator:
        await coordinator.deliver(envelope)
        task = await final(remote, coordinator, envelope)
        assert task["state"] == "unknown"
    async with relay(remote) as restarted:
        assert (await restarted.deliver(envelope))["state"] == "unknown"
        assert (await restarted.reconcile(envelope))["receipt"] == task["receipt"]
    assert len(remote.counter.read_text().splitlines()) == 1
    board = (await remote.http.get(f"/api/projects/{remote.pid}/whiteboard")).json()["entries"]
    assert not any("Synthetisches Ergebnis" in entry["content"] for entry in board)


async def test_cancellation_after_reservation_never_replays(remote, monkeypatch):
    envelope = await intent(remote)
    async with relay(remote) as coordinator:
        original = coordinator.pool.call

        async def cancel_before_submit(peer, tool, arguments, **kwargs):
            if tool == "task_submit":
                raise asyncio.CancelledError()
            return await original(peer, tool, arguments, **kwargs)

        monkeypatch.setattr(coordinator.pool, "call", cancel_before_submit)
        with pytest.raises(asyncio.CancelledError):
            await coordinator.deliver(envelope)
    async with relay(remote) as restarted:
        with pytest.raises(UncertainExecution, match="Existing dispatch marker"):
            await restarted.deliver(envelope)
    assert not remote.counter.exists()


async def test_grant_revocation_after_reservation_stops_before_core_submit(remote, monkeypatch):
    envelope = await intent(remote)
    original = remote.source.reserve_attempt

    async def revoke_after_reservation(value, principal):
        receipt = await original(value, principal)
        remote.grants.clear()
        return receipt

    monkeypatch.setattr(remote.source, "reserve_attempt", revoke_after_reservation)
    async with relay(remote) as coordinator:
        with pytest.raises(BridgeError, match="Grant changed before submission"):
            await coordinator.deliver(envelope)
    assert remote.bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0
    assert not remote.counter.exists()


async def test_native_agent_timeout_stays_unknown_without_retry(remote):
    executable = Path(remote.config.agents["codex"].executable)
    executable.write_text(
        executable.read_text().replace(
            "print(json.dumps({'type':'turn.started'}),flush=True)",
            "print(json.dumps({'type':'turn.started'}),flush=True)\nimport time; time.sleep(8)",
        )
    )
    envelope = await intent(remote, timeout=2.5)
    async with relay(remote) as coordinator:
        await coordinator.deliver(envelope)
        task = await final(remote, coordinator, envelope)
        assert task["state"] == "unknown"
    async with relay(remote) as restarted:
        assert (await restarted.deliver(envelope))["state"] == "unknown"
    assert len(remote.counter.read_text().splitlines()) == 1


async def test_existing_core_task_of_another_principal_is_never_reused(remote):
    envelope = await intent(remote)
    request = TaskRequest(
        task_id="remote-one",
        idempotency_key="remote-one",
        operation="file.list",
        arguments={"path": remote.binding.workspace_path},
    )
    token = remote.bridge.security.grant("other", request)
    remote.bridge.submit("other", request, token)
    async with relay(remote) as coordinator:
        with pytest.raises(UncertainExecution):
            await coordinator.deliver(envelope)
    task = await remote.bridge.tasks.wait("other", request.task_id)
    assert task["principal"] == "other"
    assert not remote.counter.exists()


async def test_caller_mutation_cannot_change_an_admitted_snapshot(remote, monkeypatch):
    envelope = await intent(remote)
    original = remote.source.call

    async def mutate_during_lookup(tool, args, **kwargs):
        result = await original(tool, args, **kwargs)
        envelope["request"]["arguments"]["cwd"] = "/foreign-workspace"
        return result

    monkeypatch.setattr(remote.source, "call", mutate_during_lookup)
    async with relay(remote) as coordinator:
        task = await coordinator.deliver(envelope)
        assert task["args"]["cwd"] == remote.binding.workspace_path
    await remote.bridge.tasks.wait("local", "remote-one")
    assert len(remote.counter.read_text().splitlines()) == 1


@pytest.mark.parametrize("mismatch", ["device", "request", "certificate", "unreserved"])
async def test_direct_core_start_cannot_evade_device_request_reservation(
    remote, mismatch, monkeypatch, tmp_path
):
    envelope = await intent(remote)
    if mismatch != "unreserved":
        assert await remote.source.reserve_attempt(envelope, "local")
    request = TaskRequest.model_validate(envelope["request"])
    if mismatch == "device":
        monkeypatch.setattr(remote.source, "device_ref", "another-device")
    elif mismatch == "request":
        request.arguments["timeout"] = 9.0
    elif mismatch == "certificate":
        other, _ = certificate(tmp_path, "other-core")
        monkeypatch.setattr(remote.config, "tls_cert", str(other))
    token = remote.bridge.security.grant("local", request)
    remote.bridge.submit("local", request, token)
    task = await remote.bridge.tasks.wait("local", request.task_id)
    assert task["state"] == "failed"
    assert task["result"]["value"]["error"]["code"] == "remote_execution_binding"
    assert not remote.counter.exists()


def test_leaf_certificate_parser_rejects_ca_bundle_key_and_oversize(tmp_path):
    cert, key = certificate(tmp_path, "good")
    ca, _ = certificate(tmp_path, "ca", ca=True)
    with pytest.raises(BridgeError, match="Invalid explicit leaf"):
        certificate_identity(ca)
    for name, data in {
        "bundle": cert.read_bytes() * 2,
        "key": key.read_bytes(),
        "oversize": b"x" * 65537,
        "mixed": cert.read_bytes() + key.read_bytes(),
    }.items():
        path = tmp_path / name
        path.write_bytes(data)
        with pytest.raises(BridgeError):
            certificate_identity(path)
    with pytest.raises(BridgeError):
        certificate_identity(tmp_path / "absent")


async def test_consistent_second_device_peer_cannot_take_first_device_reservation(
    remote, tmp_path, monkeypatch
):
    envelope = await intent(remote)
    assert await remote.source.reserve_attempt(envelope, "local")
    second_cert, _ = certificate(tmp_path, "second-device")
    second_identity = certificate_identity(second_cert)
    async with HttpHandoffPeer(
        remote.td_origin,
        remote.pid,
        remote.source.subject_ref,
        service_ref=remote.source.service_ref,
        tenant_ref=remote.source.tenant_ref,
        device_ref="second-device",
        device_key_sha256=second_identity.public_key_sha256,
        token=remote.token,
        certificate_file=str(remote.td_cert),
        certificate_sha256=certificate_identity(remote.td_cert).certificate_sha256,
    ) as second_source:
        assert second_source.operator_ref != remote.source.operator_ref
        # An independently consistent executor profile and source connection;
        # this is a direct Core-admission test, not a second physical Mac.
        monkeypatch.setattr(remote.config, "tls_cert", str(second_cert))
        monkeypatch.setattr(remote.bridge.handoffs, "peer", second_source)
        request = TaskRequest.model_validate(envelope["request"])
        token = remote.bridge.security.grant("local", request)
        remote.bridge.submit("local", request, token)
        task = await remote.bridge.tasks.wait("local", request.task_id)
        assert task["state"] == "failed"
        assert task["result"]["value"]["error"]["code"] == "remote_execution_binding"
    assert not remote.counter.exists()


async def test_wrong_leaf_tls_and_device_identity_are_rejected(remote, tmp_path):
    other_cert, _ = certificate(tmp_path, "other-device")
    other = certificate_identity(other_cert)
    with pytest.raises(BridgeError, match="Device certificate identity"):
        RemoteRelay(
            remote.source,
            remote.peer,
            replace(remote.binding, public_key_sha256=other.public_key_sha256),
            remote.resolve,
        )
    with pytest.raises(BridgeError, match="does not match its pin"):
        pinned_context(str(remote.td_cert), other.certificate_sha256)
    async with httpx.AsyncClient(
        verify=pinned_context(str(other_cert), other.certificate_sha256),
        trust_env=False,
    ) as client:
        with pytest.raises(httpx.ConnectError):
            await client.get(remote.td_origin + "/health")
    assert not remote.counter.exists()


def test_runtime_schema_is_the_reviewed_contract():
    root = Path(__file__).resolve().parents[1]
    assert (root / "src/kirabridge/remote_contract.v1.schema.json").read_bytes() == (
        root / "docs/contracts/remote-task.v1.schema.json"
    ).read_bytes()
