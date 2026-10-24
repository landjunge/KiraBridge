"""Real isolated install/upgrade/rollback; never touches the production install.

Pass an exact candidate Git commit. Test daemons use private paths and random ports.
No provider, agent, subscription, native tunnel or real launchd service is invoked.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import socket
import sys
from pathlib import Path

from kirabridge.mcp_gateway.client import MCPClientPool, Peer

REPO = Path(__file__).resolve().parents[1]
INSTALLER = REPO / "installer/install.py"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--previous", default="a3b854daa33b4b5ec0da24f39308d2d929aa0f1e")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.output.absolute()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    prefix = root / "install"
    config = root / "config/config.toml"
    launcher = root / "bin/kirabridge"
    common = [
        "--prefix",
        str(prefix),
        "--config",
        str(config),
        "--launcher",
        str(launcher),
        "--plist",
        str(root / "service.plist"),
        "--service",
        "none",
    ]
    evidence = {
        "scope": "ISOLATED REAL INSTALL/HTTP; NOT PRODUCTION LAUNCHD OR CHATGPT HOST",
        "candidate": args.candidate,
        "previous": args.previous,
        "checks": [],
        "production_modified": False,
        "paid_calls": 0,
        "event_test_started": False,
    }

    async def install(action, ref=None, expect=0):
        argv = [sys.executable, str(INSTALLER), action, *common]
        if ref:
            argv += ["--repo", str(REPO), "--ref", ref, "--full-access"]
        child = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        async with asyncio.timeout(180):
            while True:
                line = await child.stdout.readline()
                if not line:
                    break
                print("ISOLIERTER INSTALLER:", line.decode().rstrip(), flush=True)
            code = await child.wait()
        assert code == expect, (action, code, expect)

    async def launch():
        data = json.loads((prefix / "current.json").read_text())
        python = Path(data["release"]) / "source/.venv/bin/python"
        log = (root / ("daemon-" + data["version"] + ".log")).open("ab")
        child = await asyncio.create_subprocess_exec(
            str(python),
            "-m",
            "kirabridge.cli",
            "--config",
            str(config),
            "serve",
            "--transport",
            "http",
            stdout=log,
            stderr=log,
        )
        log.close()
        return child, data

    async def stop(child):
        if child.returncode is None:
            child.terminate()
            await asyncio.wait_for(child.wait(), 10)

    async def connect(data):
        cfg = __import__("tomllib").loads(config.read_text())
        token = json.loads(Path(cfg["credentials_file"]).read_text())["chatgpt"]
        pool = MCPClientPool(call_timeout=5)
        await pool.__aenter__()
        try:
            async with asyncio.timeout(15):
                while True:
                    try:
                        await pool.connect(
                            Peer("test", url=f"http://127.0.0.1:{cfg['port']}/mcp", token=token)
                        )
                        break
                    except Exception:
                        await asyncio.sleep(0.1)
            health = (await pool.call("test", "bridge_health", {})).structuredContent
            assert health["version"] == data["version"] and health["dispatcher_active"]
            return pool, health
        except BaseException:
            await pool.__aexit__(None, None, None)
            raise

    async def task(pool, task_id, operation, arguments):
        receipt = (
            await pool.call(
                "test",
                "action_request",
                {
                    "request": {
                        "task_id": task_id,
                        "idempotency_key": task_id,
                        "operation": operation,
                        "arguments": arguments,
                    }
                },
            )
        ).structuredContent
        assert not receipt.get("error"), receipt
        async with asyncio.timeout(10):
            while True:
                result = (
                    await pool.call("test", "task_get", {"task_id": task_id})
                ).structuredContent
                if result["state"] not in ("created", "queued", "accepted", "running"):
                    return result
                await asyncio.sleep(0.03)

    try:
        print("TESTBEREICH:", root, flush=True)
        await install("install", args.previous)
        cfg = config.read_text()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        config.write_text(cfg.replace("port = 8765", f"port = {port}"))
        config_hash = digest(config)
        credential = Path(__import__("tomllib").loads(config.read_text())["credentials_file"])
        credential_hash = digest(credential)
        old_wrapper = launcher.read_bytes()
        old_daemon, old = await launch()
        try:
            pool, health = await connect(old)
            async with pool:
                write = await task(
                    pool,
                    "install-fixture-write",
                    "file.write",
                    {"path": str(root / "proof.txt"), "text": "INSTALL_PRESERVED\n"},
                )
                assert write["state"] == "completed"
                term = await task(
                    pool,
                    "install-fixture-terminal",
                    "terminal.execute",
                    {
                        "argv": ["/usr/bin/printf", "INSTALL_TERMINAL_OK\n"],
                        "cwd": str(root),
                        "timeout": 5,
                    },
                )
                assert (
                    term["state"] == "completed"
                    and term["result"]["stdout"] == "INSTALL_TERMINAL_OK\n"
                )
                evidence["checks"].append(
                    "old wheel starts; real file/terminal operations without Events"
                )
                await install("prepare", args.candidate)
                request = {
                    "task_id": "install-busy-fixture",
                    "idempotency_key": "install-busy-fixture",
                    "operation": "terminal.execute",
                    "arguments": {
                        "argv": [sys.executable, "-c", "import time;time.sleep(20)"],
                        "cwd": str(root),
                        "timeout": 25,
                    },
                }
                await pool.call("test", "action_request", {"request": request})
                async with asyncio.timeout(5):
                    while (  # noqa: ASYNC110 - bounded integration polling
                        await pool.call("test", "task_get", {"task_id": request["task_id"]})
                    ).structuredContent["state"] != "running":
                        await asyncio.sleep(0.03)
                await install("install", args.candidate, expect=1)
                assert launcher.read_bytes() == old_wrapper and old_daemon.returncode is None
                terminated = await task(
                    pool,
                    "stop-own-install-fixture",
                    "process.terminate",
                    {"task_id": request["task_id"]},
                )
                assert terminated["state"] == "completed"
                async with asyncio.timeout(5):
                    while (  # noqa: ASYNC110 - bounded integration polling
                        await pool.call("test", "task_get", {"task_id": request["task_id"]})
                    ).structuredContent["state"] in ("running", "accepted", "queued"):
                        await asyncio.sleep(0.03)
                evidence["checks"].append(
                    "busy upgrade refused; process/launcher preserved; own fixture stopped"
                )
        finally:
            await stop(old_daemon)
        await install("install", args.candidate)
        assert digest(config) == config_hash and digest(credential) == credential_hash
        new_daemon, new = await launch()
        try:
            pool, health = await connect(new)
            async with pool:
                schemas = {
                    t.name: t.inputSchema for t in (await pool.sessions["test"].list_tools()).tools
                }
                for name in ("task_request", "task_submit", "action_request", "action_submit"):
                    assert (
                        schemas[name]["required"] == ["request"]
                        and "completion_subscription" not in schemas[name]["properties"]
                    )
                read = await task(
                    pool,
                    "install-upgrade-read",
                    "file.read",
                    {"path": str(root / "proof.txt"), "max_bytes": 64},
                )
                assert (
                    read["state"] == "completed" and read["result"]["text"] == "INSTALL_PRESERVED\n"
                )
                old_task = (
                    await pool.call("test", "task_get", {"task_id": "install-fixture-terminal"})
                ).structuredContent
                assert old_task["result"]["stdout"] == "INSTALL_TERMINAL_OK\n"
                policy = (await pool.call("test", "policy_inspect", {})).structuredContent
                assert (
                    policy["approval_mode"] == "automatic"
                    and policy["roots"] == ["/"]
                    and policy["terminal_roots"] == ["/"]
                    and policy["allow_any_executable"]
                )
                evidence["upgraded_version"] = health["version"]
                evidence["checks"].append(
                    "new wheel starts; full rights/results preserved; no subscription"
                )
        finally:
            await stop(new_daemon)
        await install("status")
        await install("rollback")
        assert (
            launcher.read_bytes() == old_wrapper
            and digest(config) == config_hash
            and digest(credential) == credential_hash
        )
        rolled_daemon, rolled = await launch()
        try:
            pool, health = await connect(rolled)
            async with pool:
                saved = (
                    await pool.call("test", "task_get", {"task_id": "install-upgrade-read"})
                ).structuredContent
                assert saved["result"]["text"] == "INSTALL_PRESERVED\n"
                evidence["rolled_back_version"] = health["version"]
                evidence["checks"].append(
                    "rollback starts old package; config/credentials/new results preserved"
                )
        finally:
            await stop(rolled_daemon)
        await install("install", "0" * 40, expect=1)
        assert launcher.read_bytes() == old_wrapper
        evidence["checks"].append("invalid Git ref refused without activation")
        # A separate clean prefix exercises fresh 0.6.0, rather than only upgrade.
        fresh = root / "fresh"
        old_common = common[:]
        common[:] = [
            "--prefix",
            str(fresh / "install"),
            "--config",
            str(fresh / "config/config.toml"),
            "--launcher",
            str(fresh / "bin/kirabridge"),
            "--plist",
            str(fresh / "service.plist"),
            "--service",
            "none",
        ]
        await install("install", args.candidate)
        fresh_cfg = __import__("tomllib").loads((fresh / "config/config.toml").read_text())
        assert (
            fresh_cfg["principals"]["chatgpt"]["roots"] == ["/"]
            and fresh_cfg["principals"]["chatgpt"]["allow_any_executable"]
        )
        prefix, config, launcher = (
            fresh / "install",
            fresh / "config/config.toml",
            fresh / "bin/kirabridge",
        )
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            fresh_port = sock.getsockname()[1]
        config.write_text(config.read_text().replace("port = 8765", f"port = {fresh_port}"))
        fresh_daemon, fresh_release = await launch()
        try:
            pool, fresh_health = await connect(fresh_release)
            async with pool:
                actual = await task(
                    pool,
                    "fresh-file-proof",
                    "file.write",
                    {"path": str(fresh / "proof.txt"), "text": "FRESH_060_OK"},
                )
                assert actual["state"] == "completed"
                actual = await task(
                    pool,
                    "fresh-terminal-proof",
                    "terminal.execute",
                    {
                        "argv": ["/usr/bin/printf", "FRESH_TERMINAL_OK"],
                        "cwd": str(fresh),
                        "timeout": 5,
                    },
                )
                assert actual["result"]["stdout"] == "FRESH_TERMINAL_OK"
                evidence["fresh_started_version"] = fresh_health["version"]
        finally:
            await stop(fresh_daemon)
        common[:] = old_common
        evidence["checks"].append("fresh 0.6.0 starts; file/terminal/result path verified")
        evidence["checks"].append("separate fresh 0.6.0 install with explicit full access succeeds")
        evidence["passed"] = True
    finally:
        (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence, indent=2), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
