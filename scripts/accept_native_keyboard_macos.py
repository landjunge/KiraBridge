"""Opt-in, one-primary-task MCP keyboard acceptance using a UUID-owned receiver.

Run with the reviewed checkout's Python. No production configuration, services,
clipboard operation, permission request or task retry. Root supplies both apps;
only a fresh copy of the dedicated KeyboardFixture template is modified.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import plistlib
import re
import shutil
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from unittest.mock import patch

import uvicorn

import kirabridge
from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import Config, PrincipalConfig
from kirabridge.bridge_core.models import BridgeError, TaskRequest
from kirabridge.keyboard_models import KeyboardTextInput
from kirabridge.mcp_gateway.client import MCPClientPool, Peer
from kirabridge.mcp_gateway.http import create_http_app
from kirabridge.operations_service import installed_source_sha
from kirabridge.private_files import private_json, write_private

FIXTURE_ID = "de.netzwerkpunkt.kirabridge.keyboard-fixture"
FINAL_STATES = {"completed", "failed", "unknown", "cancelled", "blocked"}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def redacted(value):
    """Keep task/runtime evidence, never input text or credentials/opaque tokens."""
    if isinstance(value, dict):
        return {
            key: (
                {"redacted_sha256": digest(str(item).encode()), "characters": len(str(item))}
                if key in {"text", "value", "terminal_output", "approval", "authorization"}
                or "token" in key.lower()
                else redacted(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redacted(item) for item in value]
    return value


async def wait_json(path, *, timeout=15):
    async with asyncio.timeout(timeout):
        while not path.exists():  # noqa: ASYNC110 -- bounded owned-receipt observation
            await asyncio.sleep(0.05)
        return private_json(path)


async def run(args):
    require(sys.platform == "darwin" and os.getuid() == os.geteuid() != 0, "Nonroot macOS required")
    require(
        re.fullmatch(r"[a-f0-9]{40}", args.expected_commit)
        and re.fullmatch(r"[a-f0-9]{64}", args.expected_binary_sha256),
        "Exact native pins required",
    )
    native, template, root = (
        p.absolute() for p in (args.native_app, args.fixture_app, args.evidence_dir)
    )
    require(
        native.resolve(strict=True) == native and template.resolve(strict=True) == template,
        "App paths must not resolve through symlinks",
    )
    info = plistlib.loads((template / "Contents/Info.plist").read_bytes())
    require(
        info.get("CFBundleIdentifier") == FIXTURE_ID, "Dedicated KeyboardFixture template required"
    )
    executable = info.get("CFBundleExecutable", "")
    require(executable and Path(executable).name == executable, "Invalid fixture executable")
    require(
        not any(p.is_symlink() for p in template.rglob("*")), "Fixture template symlink refused"
    )
    require(not root.exists() and not root.is_symlink(), "Fresh evidence directory required")
    os.umask(0o077)
    root.mkdir(mode=0o700)
    nonce = uuid.uuid4().hex
    receiver, owned = root / "receiver", root / "OwnedKeyboardFixture.app"
    receiver.mkdir(mode=0o700)
    shutil.copytree(template, owned)
    info.update(
        FixtureRoot=str(receiver), FixtureUUID=nonce, CFBundleIdentifier=FIXTURE_ID + "." + nonce
    )
    (owned / "Contents/Info.plist").write_bytes(plistlib.dumps(info))
    for command in (["--force", "--sign", "-"], ["--verify", "--strict"]):
        await asyncio.to_thread(
            subprocess.run,
            ["/usr/bin/codesign", *command, str(owned)],
            check=True,
            capture_output=True,
            timeout=30,
        )
    token_env, token = (
        "KIRABRIDGE_KEYBOARD_ACCEPT_" + nonce.upper(),
        uuid.uuid4().hex + uuid.uuid4().hex,
    )
    require(token_env not in os.environ, "Private token environment collision")
    os.environ[token_env] = token
    evidence = {
        "passed": False,
        "cleanup_complete": False,
        "nonce": nonce,
        "scenario": args.scenario,
        "records": [],
        "package": str(Path(kirabridge.__file__).parent),
        "python": sys.executable,
        "source_sha256": installed_source_sha(),
        "native_commit": args.expected_commit,
        "native_binary_sha256": args.expected_binary_sha256,
        "template_binary_sha256": digest((template / "Contents/MacOS" / executable).read_bytes()),
    }

    def record(kind, value):
        entry = {"kind": kind, "at": time.time(), "value": redacted(value)}
        write_private(
            root / f"record-{len(evidence['records']):03d}.json", json.dumps(entry, indent=2)
        )
        evidence["records"].append(entry)

    policy = PrincipalConfig(
        approval_mode="automatic",
        permission_level="full",
        token_env=token_env,
        capabilities=["keyboard.inspect", "keyboard.execute", "task.read", "bridge.health"],
        roots=[str(root)],
    )
    if args.scenario == "profile-action":
        policy.capabilities += ["keyboard.profiles.read", "keyboard.profiles.manage"]
    config = Config(
        data_dir=str(root / "state"), concurrency=1, principals={"acceptance": policy}, agents={}
    )
    contract = {
        "app_path": native,
        "expected_commit": args.expected_commit,
        "expected_binary_sha256": args.expected_binary_sha256,
    }
    with patch("kirabridge.bridge_core.bridge.installed_native_contract", return_value=contract):
        bridge = Bridge(config)
    transport, worker_pids = bridge.system_modules.transport, set()
    sock = server = server_task = launched = shell_identity = clients = None
    launch_attempted = False
    task_id, submitted, fixture_closed = "keyboard-accept-" + nonce, False, False
    submit_response_received = False

    async def native_call(operation, arguments):
        result = await transport.request(operation, arguments, principal="acceptance")
        helper = result["native_helper"]
        worker_pids.add(helper["pid"])
        record(
            "native_setup_read" if operation == "apps.inspect" else "native_setup",
            {"operation": operation, "result": result},
        )
        return result

    def receiver_identity(value):
        require(
            value.get("nonce") == nonce
            and value.get("app_path") == str(owned)
            and type(value.get("pid")) is int
            and value["pid"] > 0,
            "Foreign fixture receipt",
        )
        if launched is not None:
            require(
                value["pid"] == launched["pid"] and value["started_at"] == launched["started_at"],
                "Fixture receipt process generation changed",
            )
        return value

    async def fixture_command(operation):
        identifier = str(uuid.uuid4())
        write_private(
            receiver / "command.json",
            json.dumps({"id": identifier, "nonce": nonce, "operation": operation}),
        )
        return receiver_identity(await wait_json(receiver / f"receipt-{identifier}.json"))

    try:
        async with bridge:
            try:
                metadata = transport.snapshot_metadata()
                require(
                    metadata.get("available") is True and metadata.get("keyboard_protocol") == 1,
                    "Pinned private native app has no keyboard protocol",
                )
                record("native_metadata", metadata)
                launch_attempted = True
                record("single_launch_reserved", {"app_path": str(owned), "nonce": nonce})
                launched = (await native_call("apps.launch", {"app_path": str(owned)}))[
                    "application"
                ]
                require(
                    launched["app_path"] == str(owned)
                    and launched["bundle_id"] == info["CFBundleIdentifier"],
                    "Launch returned another app",
                )
                ready = receiver_identity(await wait_json(receiver / "ready.json"))
                shell_identity = await bridge.sessions.terminal_app.process_identity(
                    launched["pid"], detailed=True
                )
                require(
                    shell_identity.split(None, 8)[8] == str(owned / "Contents/MacOS" / executable),
                    "Fixture process image differs",
                )
                await native_call(
                    "app.focus",
                    {
                        "expected_pid": launched["pid"],
                        "expected_start": f"{launched['started_at']:.6f}",
                    },
                )
                before = await fixture_command("snapshot")
                require(
                    before["utf8_bytes"] == before["return_count"] == 0
                    and before["window_key"]
                    and before["editor_first_responder"],
                    "Fixture not empty and focused",
                )
                record("receiver_before", before)
                sock = socket.socket()
                sock.bind(("127.0.0.1", 0))
                sock.listen(64)
                config.port = sock.getsockname()[1]
                server = uvicorn.Server(
                    uvicorn.Config(create_http_app(bridge), log_level="critical", access_log=False)
                )
                server_task = asyncio.create_task(server.serve(sockets=[sock]))
                async with asyncio.timeout(10):
                    while not server.started:  # noqa: ASYNC110 -- bounded private-server startup
                        if server_task.done():
                            await server_task
                        await asyncio.sleep(0.01)
                clients = MCPClientPool()
                await clients.__aenter__()
                await clients.connect(
                    Peer("owned", url=f"http://127.0.0.1:{config.port}/mcp", token=token)
                )

                async def call(tool, arguments):
                    nonlocal submit_response_received
                    result = (await clients.call("owned", tool, arguments)).structuredContent
                    if tool == "task_submit" and isinstance(result, dict):
                        submit_response_received = True
                    record("mcp_response", {"tool": tool, "result": result})
                    require(
                        isinstance(result, dict) and result.get("error") is None,
                        "MCP call failed; no replay",
                    )
                    return result

                await call("bridge_health", {})

                async def setup_task(label, operation, arguments):
                    identifier = f"keyboard-{label}-{nonce}"
                    request = TaskRequest(
                        task_id=identifier,
                        idempotency_key=identifier,
                        operation=operation,
                        arguments=arguments,
                    )
                    await call("task_request", {"request": request.model_dump()})
                    async with asyncio.timeout(15):
                        while True:  # noqa: ASYNC110 -- one setup task, same ID
                            observed = await call("task_get", {"task_id": identifier})
                            if observed["state"] in FINAL_STATES:
                                break
                            await asyncio.sleep(0.1)
                    require(observed["state"] == "completed", "Public setup task failed")
                    return observed["result"]

                async def inspect(label):
                    return await setup_task(
                        label,
                        "keyboard.inspect",
                        {"pid": launched["pid"], "expected_started_at": launched["started_at"]},
                    )

                inspected = await inspect("inspect")
                target = inspected["target"]
                require(
                    target["pid"] == launched["pid"]
                    and target["expected_started_at"] == launched["started_at"],
                    "Wrong MCP keyboard target",
                )
                worker_pids.add(target["helper_pid"])
                text = (
                    "Profiltest ä e\u0301 😀"
                    if args.scenario == "profile-action"
                    else "\ufeff" + "x" * 100000 + " ä e\u0301 👩‍💻\r\n"
                )
                operation, arguments = (
                    "keyboard.text",
                    {"target": target, "text": text, "submit": True},
                )
                if args.scenario == "profile-action":

                    async def noop(_):
                        pass

                    seed = await bridge.keyboard.execute(
                        {
                            "principal": "acceptance",
                            "operation": "keyboard.text",
                            "id": "seed-" + nonce,
                        },
                        KeyboardTextInput(target=target, text=text, submit=False),
                        noop,
                    )
                    record("owned_receiver_seed", seed)
                    inspected = await inspect("inspect-seeded")
                    target = inspected["target"]
                    require(
                        target["pid"] == launched["pid"]
                        and target["expected_started_at"] == launched["started_at"],
                        "Seeded target changed",
                    )
                    require(
                        inspected["field"]["role"] == "AXTextArea", "Owned receiver role changed"
                    )
                    worker_pids.add(target["helper_pid"])
                    action = dict(key={"character": "a"}, modifiers=["command"], provenance="user")
                    profile = {
                        "id": "accept-" + nonce,
                        "app": {
                            "bundle_id": info["CFBundleIdentifier"],
                            "layout_id": inspected["layout"]["layout_id"],
                            "keyboard_type": inspected["layout"]["keyboard_type"],
                            "field_roles": ["AXTextArea"],
                        },
                        "actions": {"select_all": action},
                    }
                    stored = await setup_task(
                        "profile-put", "keyboard.profiles.put", {"profile": profile}
                    )
                    binding = dict(
                        id=profile["id"], revision=stored["revision"], action="select_all"
                    )
                    operation = "keyboard.action"
                    arguments = {
                        "target": target,
                        "profile_id": binding["id"],
                        "expected_revision": binding["revision"],
                        "action": binding["action"],
                    }
                expected_hash, units = digest(text.encode()), len(text.encode("utf-16-le")) // 2
                location, length = (0, units) if args.scenario == "profile-action" else (units, 0)
                expected_selection = dict(location=location, length=length)
                expected_returns = 0 if args.scenario == "profile-action" else 1
                request = TaskRequest(
                    task_id=task_id,
                    idempotency_key=task_id,
                    operation=operation,
                    arguments=arguments,
                )
                record(
                    "single_task_reserved",
                    {
                        "id": task_id,
                        "operation": request.operation,
                        "utf8_bytes": len(text.encode()),
                        "utf16_units": units,
                        "text_sha256": expected_hash,
                    },
                )
                submitted = True  # Reserved before the single primary keyboard task_submit.
                await call("task_submit", {"request": request.model_dump()})
                async with asyncio.timeout(25):
                    while True:  # noqa: ASYNC110 -- same task ID; no mutation retry
                        final = await call("task_get", {"task_id": task_id})
                        if final["state"] in FINAL_STATES:
                            break
                        await asyncio.sleep(0.1)
                require(final["state"] == "completed", "Public keyboard task did not complete")
                result = final["result"]
                if args.scenario == "profile-action":
                    require(
                        result.get("profile_binding_verified") is True
                        and result.get("profile_binding") == binding
                        and type(result.get("post_calls_returned")) is int
                        and result["post_calls_returned"] == 2,
                        "Public profile binding/key-pair receipt incomplete",
                    )
                else:
                    require(
                        result.get("task_id") == task_id
                        and result.get("text_sha256") == expected_hash
                        and all(
                            result.get(k) is True
                            for k in (
                                "staging_verified",
                                "text_verified",
                                "selection_verified",
                                "return_posted",
                            )
                        ),
                        "Public staging/text/Return receipt incomplete",
                    )
                async with asyncio.timeout(5):
                    while True:  # noqa: ASYNC110 -- only independent receiver readback
                        after = await fixture_command("snapshot")
                        record("receiver_after", after)
                        if (
                            after["text_sha256"] == expected_hash
                            and after["utf8_bytes"] == len(text.encode())
                            and after["utf16_units"] == units
                            and after["selection_utf16"] == expected_selection
                            and after["return_count"] == expected_returns
                        ):
                            break
                        await asyncio.sleep(0.05)
                require(
                    after["clipboard_generation"] == before["clipboard_generation"],
                    "Independent receiver text/caret/Return/clipboard differs",
                )
                events = bridge.events("acceptance", task_id)
                record("durable_events", events)
                if args.scenario == "profile-action":
                    snapshots = [
                        event["evidence"]
                        for event in events["events"]
                        if event["evidence"].get("evidence_type")
                        == "keyboard_profile_snapshot_bound"
                    ]
                    require(
                        len(snapshots) == 1
                        and snapshots[0]["profile_binding"] == binding
                        and snapshots[0]["profile_snapshot"] == stored["profile"],
                        "Durable full profile snapshot differs",
                    )
                evidence["tests_passed"] = True
            except BaseException as error:
                record(
                    "failure", {"type": type(error).__name__, "code": getattr(error, "code", None)}
                )
            finally:
                try:
                    if submitted:
                        try:
                            settled = await bridge.tasks.wait("acceptance", task_id, timeout=20)
                        except BridgeError as error:
                            if error.code != "not_found":
                                raise
                            require(
                                submit_response_received
                                and bridge.store.db.execute(
                                    "SELECT 1 FROM tasks WHERE id=?", (task_id,)
                                ).fetchone()
                                is None,
                                "Submission outcome uncertain or task exists; preserve receiver",
                            )
                            record(
                                "definitive_task_absent",
                                {
                                    "id": task_id,
                                    "scope": "private authoritative store after MCP response",
                                },
                            )
                        else:
                            require(
                                settled["state"] in FINAL_STATES,
                                "Task still active; preserve receiver",
                            )
                    if launch_attempted and not (receiver / "ready.json").exists():
                        await wait_json(receiver / "ready.json", timeout=5)
                    if (receiver / "ready.json").exists():
                        ready = receiver_identity(private_json(receiver / "ready.json"))
                        current = await native_call(
                            "apps.inspect",
                            {"pid": ready["pid"], "expected_started_at": ready["started_at"]},
                        )
                        require(
                            current["application"]["app_path"] == str(owned)
                            and current["application"]["bundle_id"] == info["CFBundleIdentifier"],
                            "Own fixture application changed before close",
                        )
                        if shell_identity is None:
                            shell_identity = await bridge.sessions.terminal_app.process_identity(
                                ready["pid"], detailed=True
                            )
                        require(
                            shell_identity.split(None, 8)[8]
                            == str(owned / "Contents/MacOS" / executable)
                            and await bridge.sessions.terminal_app.process_identity(
                                ready["pid"], detailed=True
                            )
                            == shell_identity,
                            "Owned fixture generation changed before close",
                        )
                        record("owned_close_receipt", await fixture_command("close"))
                        async with asyncio.timeout(10):
                            while ready["pid"] in await bridge.sessions.terminal_app.process_ids():  # noqa: ASYNC110 -- bounded independent OS absence
                                await asyncio.sleep(0.05)
                        require(
                            ready["pid"] not in await bridge.sessions.terminal_app.process_ids(),
                            "Fixture absence changed",
                        )
                        fixture_closed = True
                    else:
                        require(
                            launched is None,
                            "Launch occurred without owned ready receipt; preserve",
                        )
                except BaseException as error:
                    record(
                        "cleanup_failure",
                        {"type": type(error).__name__, "code": getattr(error, "code", None)},
                    )
                try:
                    if clients is not None:
                        await clients.__aexit__(None, None, None)
                finally:
                    if transport.process is not None:
                        worker_pids.add(transport.process.pid)
                    if server is not None:
                        server.should_exit = True
                    if server_task is not None:
                        await asyncio.wait_for(server_task, 10)
        pids = await bridge.sessions.terminal_app.process_ids()
        require(not worker_pids.intersection(pids), "Own native worker still present")
        await asyncio.sleep(0.1)
        require(
            not worker_pids.intersection(await bridge.sessions.terminal_app.process_ids()),
            "Worker absence changed",
        )
        evidence["native_worker_absent_twice"] = True
        evidence["fixture_absent_twice"] = fixture_closed
        evidence["cleanup_complete"] = fixture_closed
    finally:
        if sock is not None:
            sock.close()
        os.environ.pop(token_env, None)
        if config.port and server_task is not None and server_task.done():

            def endpoint_absent():
                with socket.socket() as probe:
                    probe.settimeout(0.5)
                    return probe.connect_ex(("127.0.0.1", config.port)) != 0

            evidence["private_endpoint_absent"] = await asyncio.to_thread(endpoint_absent)
        evidence["passed"] = bool(
            evidence.get("tests_passed")
            and evidence["cleanup_complete"]
            and evidence.get("native_worker_absent_twice")
            and evidence.get("private_endpoint_absent")
        )
        write_private(root / "evidence.json", json.dumps(evidence, indent=2, sort_keys=True))
    require(evidence["passed"], f"Acceptance failed; inspect private evidence in {root}")
    print(json.dumps({"passed": True, "evidence_dir": str(root)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--scenario", choices=["keyboard-text", "profile-action"], default="keyboard-text"
    )
    parser.add_argument("--native-app", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-binary-sha256", required=True)
    parser.add_argument("--fixture-app", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    options = parser.parse_args()
    if options.execute:
        asyncio.run(run(options))
    else:
        print("INACTIVE: --execute is required; no work performed.")
