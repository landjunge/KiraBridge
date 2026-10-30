"""Manual Intel acceptance through private authenticated MCP and one owned shell.

No installed configuration, production endpoint, agent input or second test window.
Every execution case runs in the newly created visible Terminal.app window.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import re
import secrets
import shlex
import socket
import sys
from pathlib import Path

import httpx
import uvicorn

import kirabridge
from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import Config, PrincipalConfig
from kirabridge.bridge_core.models import TaskRequest
from kirabridge.mcp_gateway.client import MCPClientPool, Peer
from kirabridge.mcp_gateway.http import create_http_app
from kirabridge.platform_adapters.shell_prompt import empty_shell_prompt

PAYLOAD = """import json,os,sys,time
from pathlib import Path
identifier, status, directory = sys.argv[1:]
root = Path(directory)
record = {"id":identifier,"pid":os.getpid(),"tty":os.ttyname(1)}
with (root/(identifier+".jsonl")).open("a") as stream:
    stream.write(json.dumps(record)+"\\n"); stream.flush()
print("KB_ACCEPT_OUTPUT_"+identifier, flush=True)
if identifier == "busy":
    deadline=time.monotonic()+35
    while not (root/"release-busy").exists():
        if time.monotonic()>deadline: sys.exit(99)
        time.sleep(.05)
sys.exit(int(status))
"""


async def accept(root, selection="full"):
    if (platform.system(), platform.machine()) != ("Darwin", "x86_64"):
        raise RuntimeError("This manual acceptance requires the Intel Mac")
    assert (
        Path(kirabridge.__file__)
        .resolve()
        .is_relative_to(Path(__file__).resolve().parents[1] / "src" / "kirabridge")
    ), "Run only the worktree source, never the installed package"
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    receipts = root / "receipts"
    receipts.mkdir()
    payload = root / "payload.py"
    payload.write_text(PAYLOAD)
    token = secrets.token_urlsafe(48)
    token_name = "KB_ISSUE51_ISOLATED_ACCEPT_TOKEN"
    previous_token = os.environ.get(token_name)
    os.environ[token_name] = token
    config = Config(
        data_dir=str(root / "state"),
        concurrency=2,
        principals={
            "chatgpt": PrincipalConfig(
                client_type="chatgpt",
                permission_level="full",
                approval_mode="automatic",
                token_env=token_name,
                roots=[str(root)],
                terminal_roots=[str(root)],
                executables=[sys.executable],
                capabilities=[
                    "session.inspect",
                    "session.input",
                    "terminal.execute",
                    "bridge.health",
                    "task.read",
                    "task.cancel",
                ],
            )
        },
    )
    bridge = Bridge(config)
    transport = bridge.sessions.terminal_app
    original_native, original_catalog = transport.native, transport.catalog
    before = await transport.window_inventory()
    before_ids = {row["window_id"] for row in before["windows"]}
    before_rows = await original_catalog()
    identities = {
        process["pid"]: await transport.process_identity(process["pid"], detailed=True)
        for row in before_rows
        for process in row["processes"]
    }
    evidence = {
        "platform": platform.platform(),
        "architecture": platform.machine(),
        "python": sys.version,
        "package": str(Path(kirabridge.__file__).resolve()),
        "scope": "private authenticated MCP; only one new owned visible shell",
        "selection": selection,
        "checks": [],
        "acceptance": "in_progress",
        "before_windows": sorted(before_ids),
        "before_pids": sorted(identities),
        "native_dispatches": [],
        "production_modified": False,
        "arm_tested": False,
        "hosted_macos_tested": False,
    }
    owned = None
    server = server_task = sock = None
    tasks_started = False
    race = {"armed": False}

    def checkpoint():
        (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")

    def check(name, **detail):
        evidence["checks"].append({"name": name, **detail})
        checkpoint()
        print(json.dumps(evidence["checks"][-1]), flush=True)

    async def wait_idle():
        async with asyncio.timeout(20):
            while True:  # noqa: ASYNC110 -- bounded real UI observation
                rows = [r for r in await original_catalog() if r["pane_id"] == owned["pane_id"]]
                if len(rows) == 1 and rows[0]["expected_pid"] == owned["expected_pid"]:
                    if not rows[0]["busy"]:
                        screen = await transport.read(owned["pane_id"])
                        if empty_shell_prompt(screen):
                            return screen
                await asyncio.sleep(0.15)

    async def owned_comment_return(comment):
        screen = await transport.read(owned["pane_id"])
        assert screen.rstrip("\n").split("\n")[-1].endswith(" " + comment)
        identity = await transport.process_identity(owned["expected_pid"], detailed=True)
        await transport.press_return(
            owned["pane_id"],
            identity_guard={owned["expected_pid"]: identity},
            expected_screen=screen,
        )
        await wait_idle()

    async def traced_native(source, *, mutation=False):
        if mutation and "app.doScript(" in source:
            if race["armed"]:
                race["armed"] = False
                screen = await transport.read(owned["pane_id"])
                assert empty_shell_prompt(screen)
                current = await transport.catalog()
                assert len(current) == 1 and current[0]["pane_id"] == owned["pane_id"]
                context = await transport.prepare_shell_paste(current[0])
                await transport.insert(
                    owned["pane_id"],
                    "# KB_ACCEPT_RACE",
                    identity_guard=context["identities"],
                    expected_screen=context["screen"],
                    shell_snapshot=context["snapshot"],
                )
                async with asyncio.timeout(5):
                    while True:  # noqa: ASYNC110 -- observe fixture input, never repeat it
                        changed_screen = await transport.read(owned["pane_id"])
                        if (
                            changed_screen.rstrip("\n")
                            .split("\n")[-1]
                            .endswith(" # KB_ACCEPT_RACE")
                        ):
                            break
                        await asyncio.sleep(0.05)
                check("race fixture inserted own harmless comment before real native guard")
            trace = {"source_sha256": hashlib.sha256(source.encode()).hexdigest()}
            evidence["native_dispatches"].append(trace)
            try:
                result = await original_native(source, mutation=mutation)
            except Exception as error:
                trace["error"] = getattr(error, "code", type(error).__name__)
                checkpoint()
                raise
            trace["confirmed"] = result
            checkpoint()
            return result
        return await original_native(source, mutation=mutation)

    async def forbidden(*_args, **_kwargs):
        evidence.setdefault("forbidden_fallback_attempts", []).append(True)
        raise AssertionError("No raw send, managed hidden command or additional window allowed")

    def command(identifier, status=0):
        invoke = shlex.join([sys.executable, str(payload), identifier, str(status), str(receipts)])
        label = "KB_ACCEPT_STATUS_" + identifier
        return (
            invoke
            + "; kb_issue51_accept_status=$?; /usr/bin/printf '%s:%s\\n' "
            + shlex.quote(label)
            + ' "$kb_issue51_accept_status"; '
            + "/usr/bin/printf '%s\\n' \"$kb_issue51_accept_status\" > "
            + shlex.quote(str(receipts / (identifier + ".status")))
        )

    def request(identifier, text=None, **changes):
        arguments = {
            "pane_id": owned["pane_id"],
            "expected_pid": owned["expected_pid"],
            "text": text if text is not None else command(identifier),
            "submit": True,
        }
        arguments.update(changes)
        return TaskRequest(
            task_id="intel-" + root.name + "-" + identifier,
            idempotency_key="intel-" + root.name + "-" + identifier,
            operation="session.input",
            arguments=arguments,
        )

    try:
        opened = await transport.open("cd -- " + shlex.quote(str(root)))
        evidence["opened"] = opened
        checkpoint()
        async with asyncio.timeout(20):
            while True:  # noqa: ASYNC110 -- bounded ownership reconciliation
                matches = [
                    r
                    for r in await original_catalog()
                    if r["tty"] == opened["tty"]
                    and int(r["pane_id"].split(":")[1]) not in before_ids
                ]
                if len(matches) == 1:
                    owned = matches[0]
                    break
                await asyncio.sleep(0.15)
        added = {
            r["window_id"] for r in (await transport.window_inventory())["windows"]
        } - before_ids
        assert added == {int(owned["pane_id"].split(":")[1])}
        evidence["owned"] = {k: owned[k] for k in ("pane_id", "expected_pid", "tty")}
        await wait_idle()

        # Narrow real catalogue observations; never fabricate readiness or substitute targets.
        async def owned_catalog():
            return [r for r in await original_catalog() if r["pane_id"] == owned["pane_id"]]

        transport.catalog = owned_catalog
        transport.native = traced_native
        transport.send = transport.open = bridge.sessions.tmux.send = forbidden
        bridge.terminal.execute = forbidden
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        sock.listen(64)
        port = sock.getsockname()[1]
        config.port = port
        server = uvicorn.Server(
            uvicorn.Config(
                create_http_app(bridge),
                log_level="critical",
                access_log=False,
            )
        )
        await bridge.tasks.start()
        tasks_started = True
        server_task = asyncio.create_task(server.serve(sockets=[sock]))
        async with asyncio.timeout(10):
            while not server.started:
                if server_task.done():
                    await server_task
                await asyncio.sleep(0.02)
        evidence["private_port"] = port
        endpoint = f"http://127.0.0.1:{port}/mcp"
        async with httpx.AsyncClient(trust_env=False) as unauthenticated:
            response = await unauthenticated.post(endpoint, json={})
            assert response.status_code == 401
        check("private endpoint rejects unauthenticated requests", status=401)
        async with MCPClientPool(call_timeout=50) as clients:
            await clients.connect(Peer("chatgpt", url=endpoint, token=token))

            async def call(tool, arguments):
                result = await clients.call("chatgpt", tool, arguments)
                data = result.structuredContent
                assert isinstance(data, dict), result
                return data

            async def submit(value):
                return await call("action_request", {"request": value.model_dump()})

            async def finished(value):
                async with asyncio.timeout(45):
                    while True:  # noqa: ASYNC110 -- bounded real task result readback
                        task = await call("task_get", {"task_id": value.task_id})
                        if task.get("state") in {
                            "completed",
                            "failed",
                            "unknown",
                            "cancelled",
                            "blocked",
                        }:
                            evidence.setdefault("tasks", {})[value.task_id] = task
                            checkpoint()
                            return task
                        await asyncio.sleep(0.1)

            async def output(identifier, expected_status):
                status = receipts / (identifier + ".status")
                async with asyncio.timeout(20):
                    while not status.exists():  # noqa: ASYNC110 -- bounded private shell witness
                        await asyncio.sleep(0.1)
                await wait_idle()
                observed = await call(
                    "read_query",
                    {
                        "query": {
                            "operation": "session.read",
                            "pane_id": owned["pane_id"],
                            "expected_pid": owned["expected_pid"],
                        }
                    },
                )
                text = observed["text"]
                assert re.search(r"(?m)^KB_ACCEPT_OUTPUT_" + re.escape(identifier) + r"\r?$", text)
                assert re.search(
                    r"(?m)^KB_ACCEPT_STATUS_"
                    + re.escape(identifier)
                    + ":"
                    + str(expected_status)
                    + r"\r?$",
                    text,
                )
                assert int(status.read_text()) == expected_status
                rows = [
                    json.loads(line)
                    for line in (receipts / (identifier + ".jsonl")).read_text().splitlines()
                ]
                assert len(rows) == 1 and rows[0]["tty"] == owned["tty"]
                (root / (identifier + "-screen.txt")).write_text(text)
                check(
                    "actual shell output, exit status and exactly one TTY-bound execution",
                    identifier=identifier,
                    exit_status=expected_status,
                    receipt=rows[0],
                    screen_sha256=hashlib.sha256(text.encode()).hexdigest(),
                )

            async def refused(identifier, value, expected_code):
                before_count = len(evidence["native_dispatches"])
                await submit(value)
                task = await finished(value)
                assert task["state"] == "failed", task
                assert task["error"]["code"] == expected_code, task
                observation = task["evidence"].get("last_observation", task["evidence"])
                assert observation.get("terminal_input_attempted") is not True, task
                assert len(evidence["native_dispatches"]) == before_count
                assert not (receipts / (identifier + ".jsonl")).exists()
                check("rejected before native mutation", identifier=identifier, code=expected_code)
                return task

            if selection == "full":
                value = request("once")
                results = await asyncio.gather(submit(value), submit(value))
                assert all(r.get("id") == value.task_id for r in results), results
                assert (await finished(value))["state"] == "completed"
                await output("once", 0)
                assert len(evidence["native_dispatches"]) == 1
                await submit(value)
                assert (await finished(value))["state"] == "completed"
                assert len(evidence["native_dispatches"]) == 1
                assert len((receipts / "once.jsonl").read_text().splitlines()) == 1
                changed = value.model_copy(
                    update={"arguments": {**value.arguments, "text": command("conflict")}}
                )
                conflict = await submit(changed)
                assert conflict.get("error", {}).get("code") == "idempotency_conflict", conflict
                assert not (receipts / "conflict.jsonl").exists()
                check("concurrent/late identical delivery deduplicated; changed payload conflicts")

                nonzero = request("nonzero", command("nonzero", 7))
                await submit(nonzero)
                assert (await finished(nonzero))["state"] == "completed"
                await output("nonzero", 7)
                check("session.input task completion distinguished from shell exit 7")

                pending = request("paste-comment", "# KB_ACCEPT_PENDING", submit=False)
                await submit(pending)
                assert (await finished(pending))["state"] == "completed"
                screen = await transport.read(owned["pane_id"])
                assert screen.rstrip("\n").split("\n")[-1].endswith(" # KB_ACCEPT_PENDING")
                await refused("nonempty", request("nonempty"), "visible_input_not_empty")
                assert await transport.read(owned["pane_id"]) == screen
                check("existing owned input preserved byte-for-byte")
                await owned_comment_return("# KB_ACCEPT_PENDING")

                await refused(
                    "wrong-pid",
                    request("wrong-pid", expected_pid=99999999),
                    "session_selection_changed",
                )
                wrong_tty = owned["pane_id"].rsplit(":", 1)[0] + ":ttys99999"
                await refused(
                    "wrong-tty",
                    request("wrong-tty", pane_id=wrong_tty),
                    "session_selection_changed",
                )

                busy = request("busy")
                await submit(busy)
                assert (await finished(busy))["state"] == "completed"
                async with asyncio.timeout(10):
                    while not any(r["busy"] for r in await owned_catalog()):  # noqa: ASYNC110
                        await asyncio.sleep(0.1)
                blocked = request("busy-rejected")
                await refused("busy-rejected", blocked, "session_busy")
                (receipts / "release-busy").write_text("release own bounded fixture\n")
                await output("busy", 0)
                await submit(blocked)
                assert (await finished(blocked))["state"] == "failed"
                assert not (receipts / "busy-rejected.jsonl").exists()
                check("previously rejected task never starts after shell becomes idle")

            race["armed"] = True
            changing = request("race-rejected")
            await submit(changing)
            task = await finished(changing)
            assert task["state"] == "unknown", task
            assert task["error"]["code"] == "visible_input_changed", task
            assert not (receipts / "race-rejected.jsonl").exists()
            assert evidence["native_dispatches"][-1]["error"] == "visible_input_changed"
            await owned_comment_return("# KB_ACCEPT_RACE")
            count = len(evidence["native_dispatches"])
            await submit(changing)
            assert (await finished(changing))["state"] == "unknown"
            assert len(evidence["native_dispatches"]) == count
            check("real pre-native input change refused; conservative unknown never replayed")
            assert not evidence.get("forbidden_fallback_attempts")
            check("no hidden, raw-send or extra-window fallback attempted")
            evidence["acceptance"] = "tests_passed_cleanup_pending"
    except BaseException as error:
        evidence["acceptance"] = "failed"
        evidence["error"] = {"type": type(error).__name__, "message": str(error)}
        raise
    finally:
        # Stop only the private server/workers. Never stop the installed daemon.
        try:
            if server is not None:
                server.should_exit = True
            if server_task is not None:
                await asyncio.wait_for(server_task, 10)
            if tasks_started:
                await bridge.tasks.stop()
            await bridge.threaddesk.close()
            bridge.store.close()
            if owned is not None:
                current = [r for r in await original_catalog() if r["pane_id"] == owned["pane_id"]]
                assert len(current) == 1 and current[0]["expected_pid"] == owned["expected_pid"]
                assert not current[0]["busy"], "Leave busy/uncertain owned fixture untouched"
                evidence["close"] = await transport.close_tab(owned["pane_id"])
            after = await transport.window_inventory()
            evidence["after_windows"] = sorted(r["window_id"] for r in after["windows"])
            assert set(evidence["after_windows"]) == before_ids
            for pid, expected in identities.items():
                assert await transport.process_identity(pid, detailed=True) == expected
            evidence["original_process_identities_preserved"] = True
            if sock is not None:
                sock.close()
                probe = socket.socket()
                try:
                    evidence["private_endpoint_absent"] = (
                        probe.connect_ex(("127.0.0.1", config.port)) != 0
                    )
                    assert evidence["private_endpoint_absent"]
                finally:
                    probe.close()
            evidence["cleanup_complete"] = True
        except BaseException as error:
            evidence["acceptance"] = "failed"
            evidence["cleanup_error"] = {"type": type(error).__name__, "message": str(error)}
            raise
        finally:
            if previous_token is None:
                os.environ.pop(token_name, None)
            else:
                os.environ[token_name] = previous_token
            checkpoint()
    evidence["acceptance"] = "passed"
    checkpoint()
    print(
        json.dumps({"acceptance": evidence["acceptance"], "evidence": str(root / "evidence.json")})
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--allow-one-owned-visible-window", action="store_true", required=True)
    parser.add_argument("--case", choices=["full", "state-change"], default="full")
    options = parser.parse_args()
    asyncio.run(accept(options.root.resolve(), options.case))
