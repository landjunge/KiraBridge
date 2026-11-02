"""Keep one UUID-owned receiver open for a separate, real Apps-connector check.

Explicit prepare/start create and launch only a fresh KeyboardFixture copy. Snapshot
and close use its existing private receipt protocol. This helper sends no keyboard
input, starts no MCP/native worker, and makes no claim about a ChatGPT client.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import plistlib
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from kirabridge.bridge_core.models import BridgeError
from kirabridge.platform_adapters.terminal_app import TerminalAppTransport
from kirabridge.private_files import private_json, write_private

FIXTURE_ID = "de.netzwerkpunkt.kirabridge.keyboard-fixture"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


async def wait_json(path, *, timeout):
    async with asyncio.timeout(timeout):
        while not path.exists():  # noqa: ASYNC110 -- bounded external receiver-file observation
            await asyncio.sleep(0.05)
        return private_json(path)


def save(path, value):
    write_private(path, json.dumps(value, indent=2, sort_keys=True))


def checked_root(path, *, existing):
    root = path.absolute()
    require(root.parent.resolve(strict=True) == root.parent, "Symlink parent refused")
    require(not root.is_symlink(), "Symlink session refused")
    if existing:
        info = root.stat()
        require(
            root.is_dir() and info.st_uid == os.getuid() and not info.st_mode & 0o077,
            "Session must be an owner-only directory",
        )
    else:
        require(not root.exists(), "Fresh session directory required")
    return root


def prepare(options):
    template = options.fixture_app.absolute()
    require(template.resolve(strict=True) == template, "Symlink fixture path refused")
    require(not any(p.is_symlink() for p in template.rglob("*")), "Fixture symlink refused")
    info = plistlib.loads((template / "Contents/Info.plist").read_bytes())
    require(info.get("CFBundleIdentifier") == FIXTURE_ID, "Dedicated KeyboardFixture required")
    executable = info.get("CFBundleExecutable", "")
    require(
        isinstance(executable, str) and executable and Path(executable).name == executable,
        "Invalid fixture executable",
    )
    template_binary_hash = digest((template / "Contents/MacOS" / executable).read_bytes())
    root = checked_root(options.session_dir, existing=False)
    root.mkdir(mode=0o700)
    receiver, owned, nonce = root / "receiver", root / "OwnedKeyboardFixture.app", uuid.uuid4().hex
    receiver.mkdir(mode=0o700)
    shutil.copytree(template, owned)
    bundle_id = FIXTURE_ID + "." + nonce
    info.update(FixtureRoot=str(receiver), FixtureUUID=nonce, CFBundleIdentifier=bundle_id)
    (owned / "Contents/Info.plist").write_bytes(plistlib.dumps(info))
    for command in (["--force", "--sign", "-"], ["--verify", "--strict"]):
        subprocess.run(
            ["/usr/bin/codesign", *command, str(owned)], check=True, capture_output=True, timeout=30
        )
    state = {
        "root": str(root),
        "nonce": nonce,
        "bundle_id": bundle_id,
        "app_path": str(owned),
        "executable": executable,
        "binary_sha256": digest((owned / "Contents/MacOS" / executable).read_bytes()),
        "template_binary_sha256": template_binary_hash,
    }
    save(root / "session.json", state)
    return {"status": "prepared", **state, "launched": False}


def load(options):
    root = checked_root(options.session_dir, existing=True)
    state = private_json(root / "session.json")
    require(state.get("root") == str(root), "Session root changed")
    nonce = state.get("nonce", "")
    require(
        isinstance(nonce, str) and len(nonce) == 32 and all(c in "0123456789abcdef" for c in nonce),
        "Invalid fixture UUID",
    )
    owned, receiver = root / "OwnedKeyboardFixture.app", root / "receiver"
    require(
        state.get("app_path") == str(owned) and state.get("bundle_id") == FIXTURE_ID + "." + nonce,
        "Owned app binding changed",
    )
    require(
        owned.resolve(strict=True) == owned and receiver.resolve(strict=True) == receiver,
        "Owned path changed",
    )
    require(not any(p.is_symlink() for p in owned.rglob("*")), "Owned app symlink refused")
    info = plistlib.loads((owned / "Contents/Info.plist").read_bytes())
    executable = state.get("executable", "")
    require(
        isinstance(executable, str) and executable and Path(executable).name == executable,
        "Owned executable changed",
    )
    require(
        info.get("CFBundleExecutable") == executable
        and info.get("FixtureUUID") == nonce
        and info.get("FixtureRoot") == str(receiver)
        and info.get("CFBundleIdentifier") == state["bundle_id"]
        and digest((owned / "Contents/MacOS" / executable).read_bytes()) == state["binary_sha256"],
        "Owned application metadata or binary changed",
    )
    return root, state


def receipt(state, value, *, ready=None):
    require(
        value.get("nonce") == state["nonce"]
        and value.get("app_path") == state["app_path"]
        and type(value.get("pid")) is int
        and value["pid"] > 0
        and type(value.get("started_at")) in {int, float}
        and math.isfinite(value["started_at"])
        and value["started_at"] > 0,
        "Foreign or incomplete fixture receipt",
    )
    if ready is not None:
        require(
            value["pid"] == ready["pid"] and value["started_at"] == ready["started_at"],
            "Fixture PID generation changed",
        )
    return value


async def live_identity(transport, state, ready):
    identity = await transport.process_identity(ready["pid"], detailed=True)
    require(
        identity.split(None, 8)[8]
        == str(Path(state["app_path"]) / "Contents/MacOS" / state["executable"]),
        "Fixture process image changed",
    )
    return identity


async def command(root, state, ready, operation, timeout):
    identifier = str(uuid.uuid4())
    payload = {"id": identifier, "nonce": state["nonce"], "operation": operation}
    save(root / f"command-reserved-{identifier}.json", payload)
    save(root / "receiver/command.json", payload)
    result = receipt(
        state,
        await wait_json(root / "receiver" / f"receipt-{identifier}.json", timeout=timeout),
        ready=ready,
    )
    return {"command_id": identifier, "operation": operation, "receiver_receipt": result}


async def session_action(options):
    root, state = load(options)
    transport = TerminalAppTransport(asyncio.Lock())
    if options.action == "start":
        require(not (root / "receiver/ready.json").exists(), "Fixture already has a ready receipt")
        save(root / "start-attempt.json", {"nonce": state["nonce"], "automatic_retry": False})
        await asyncio.to_thread(
            subprocess.run,
            ["/usr/bin/open", "-n", state["app_path"]],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=options.timeout,
        )
        ready = receipt(
            state, await wait_json(root / "receiver/ready.json", timeout=options.timeout)
        )
        identity = await live_identity(transport, state, ready)
        require(
            ready.get("utf8_bytes") == ready.get("return_count") == 0, "New fixture is not empty"
        )
        save(root / "identity.json", {"process_identity": identity, "ready": ready})
        return {"status": "ready", **state, "receiver_receipt": ready}
    ready_path = root / "receiver/ready.json"
    if not ready_path.exists():
        require(options.action == "status", "No ready receipt; launch state must be reconciled")
        return {
            "status": "start_unknown" if (root / "start-attempt.json").exists() else "prepared",
            **state,
            "launched": "not_proven",
        }
    ready = receipt(state, private_json(ready_path))
    try:
        identity = await live_identity(transport, state, ready)
    except BridgeError:
        require(ready["pid"] not in await transport.process_ids(), "Fixture identity is uncertain")
        require(
            options.action == "status" or (root / "closed.json").exists(),
            "Fixture is absent; inspect existing receipts instead of replaying a command",
        )
        return {"status": "absent", **state, "receiver_receipt": ready}
    if (root / "identity.json").exists():
        bound = private_json(root / "identity.json")
        receipt(state, bound["ready"], ready=ready)
        require(identity == bound["process_identity"], "Owned process generation changed")
    else:
        require(options.action == "status", "Launch receipt exists without bound OS identity")
    if options.action == "status":
        return {
            "status": "running",
            **state,
            "receiver_receipt": ready,
            "process_identity": identity,
            "close_attempted": (root / "close-attempt.json").exists(),
        }
    if options.action == "close":
        save(root / "close-attempt.json", {"nonce": state["nonce"], "automatic_retry": False})
    operation = options.action.replace("-", "_")
    observed = await command(root, state, ready, operation, options.timeout)
    if options.action != "close":
        require(
            await live_identity(transport, state, ready) == identity, "Snapshot generation changed"
        )
        return {"status": "observed", **observed}
    async with asyncio.timeout(options.timeout):
        while ready["pid"] in await transport.process_ids():  # noqa: ASYNC110 -- bounded owned PID
            await asyncio.sleep(0.05)
    await asyncio.sleep(0.1)
    require(ready["pid"] not in await transport.process_ids(), "Owned fixture absence changed")
    result = {"status": "closed", "fixture_absent_twice": True, **observed}
    save(root / "closed.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    for name in (
        "prepare",
        "start",
        "status",
        "snapshot",
        "focus-button",
        "focus-editor",
        "clear-events",
        "open-second-window",
        "focus-main",
        "focus-second",
        "reset",
        "close",
    ):
        action = actions.add_parser(name)
        action.add_argument("--session-dir", type=Path, required=True)
        action.add_argument("--timeout", type=float, default=15)
        if name == "prepare":
            action.add_argument("--fixture-app", type=Path, required=True)
    options = parser.parse_args()
    require(sys.platform == "darwin" and os.getuid() == os.geteuid() != 0, "Nonroot macOS required")
    require(
        math.isfinite(options.timeout) and 0 < options.timeout <= 30, "Bounded timeout required"
    )
    os.umask(0o077)
    result = (
        prepare(options) if options.action == "prepare" else asyncio.run(session_action(options))
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
