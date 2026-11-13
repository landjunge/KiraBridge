"""Native, isolated systemd package acceptance. Never targets the standard user unit."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shlex
import socket
import sqlite3
import subprocess
import sys
import tarfile
import time
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path


def acceptance_environment(environ=None):
    """Copy the child environment without credentials for another installation."""
    # Keep this script standalone: native acceptance hosts copy it on its own.
    legacy = {"CHATGPT_TOKEN", "LOCAL_TOKEN", "CODEX_TOKEN", "GROK_TOKEN"}
    return {
        key: value
        for key, value in (os.environ if environ is None else environ).items()
        if key not in legacy and not (key.startswith("KIRABRIDGE_") and key.endswith("_TOKEN"))
    }


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# Runs in the package interpreter, with no token in arguments or output.
PROBE = r"""
import asyncio, json, sys
import httpx
from kirabridge.bridge_core.config import load_config
from kirabridge.local_runtime import peer
from kirabridge.mcp_gateway.client import MCPClientPool

async def main():
    config = load_config(sys.argv[1])
    endpoint = peer(config, "local").url
    async with httpx.AsyncClient(trust_env=False) as client:
        missing = await client.get(endpoint)
        wrong = await client.get(endpoint, headers={"Authorization": "Bearer " + "x"*48})
    assert missing.status_code == wrong.status_code == 401
    async with MCPClientPool() as pool:
        await pool.connect(peer(config, "local"))
        health = (await pool.call("daemon", "bridge_health", {})).structuredContent
    assert health["dispatcher_active"] and health["server"]["gui_parity"] is False
    print(json.dumps({"version": health["version"], "runtime": health["runtime"],
                      "server": health["server"], "missing_bearer": 401, "wrong_bearer": 401}))
asyncio.run(main())
"""

MARKER = r"""
import json, sys
from pathlib import Path
from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import load_config
from kirabridge.bridge_core.models import TaskRequest, State
bridge = Bridge(load_config(sys.argv[1]))
name = sys.argv[2]
req = TaskRequest(task_id=name, idempotency_key=name, operation="file.list",
                  arguments={"path": sys.argv[3]})
bridge.prepare("local", req)
for state in (State.QUEUED, State.ACCEPTED, State.UNKNOWN):
    bridge.store.transition(name, state, {"synthetic_native_acceptance": True})
assert bridge.store.get(name, "local")["state"] == "unknown"
try:
    bridge.store.get(name, "chatgpt")
except Exception as exc:
    assert getattr(exc, "code", None) == "not_found"
else:
    raise AssertionError("Foreign principal read a task")
bridge.store.close()
print(json.dumps({"marker": name, "state": "unknown", "foreign_principal": "not_found"}))
"""


def record_step(evidence, suite, name, action):
    started = time.monotonic()
    case = ET.SubElement(suite, "testcase", name=name)
    try:
        detail = action()
        evidence["steps"].append({"name": name, "result": "passed", "detail": detail})
        print(name + ": PASS", flush=True)
        return detail
    except BaseException as exc:
        evidence["result"] = "failed"
        ET.SubElement(case, "failure", message=str(exc) or type(exc).__name__)
        evidence["steps"].append({"name": name, "result": "failed", "error": str(exc)})
        raise
    finally:
        case.set("time", str(round(time.monotonic() - started, 3)))


def validate_update_resume(prior):
    """Resume only the failed baseline after confirmed successful cleanup."""
    cleanup = prior.get("cleanup", {})
    steps = [step for step in prior.get("steps", []) if step.get("name") != "cleanup"]
    cleanup_steps = [step for step in prior.get("steps", []) if step.get("name") == "cleanup"]
    if not (
        prior.get("result") == "failed"
        and cleanup.get("unit_absent")
        and cleanup.get("port_unbound")
        and steps
        and steps[-1].get("name") == "previous-runtime-baseline"
        and steps[-1].get("result") == "failed"
        and all(step.get("result") == "passed" for step in cleanup_steps)
    ):
        raise RuntimeError("Only a failed baseline with confirmed cleanup can resume")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=18765)
    parser.add_argument("--resume-update", action="store_true")
    args = parser.parse_args()
    root = args.root.absolute()
    unit = "kirabridge-debian-dirktest-20261107.service"
    unit_path = Path.home() / ".config/systemd/user" / unit
    assert sys.platform == "linux" and platform.machine() == "x86_64"
    assert os.getuid() != 0 and not unit_path.exists()
    if args.resume_update:
        prior = json.loads((root / "evidence.json").read_text())
        validate_update_resume(prior)
    else:
        assert not root.exists()
    assert root.is_relative_to(Path.home()) and root.name.startswith("kb-debian-dirktest-")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", args.port))
    root.mkdir(mode=0o700, exist_ok=args.resume_update)
    os.umask(0o077)
    evidence = {
        "schema": "kirabridge.native-linux-acceptance.v1",
        "steps": [],
        "identity": {
            "os_release": Path("/etc/os-release").read_text(),
            "machine": platform.machine(),
            "kernel": platform.release(),
            "uid": os.getuid(),
            "harness_python": sys.version,
            "harness_sha256": sha(Path(__file__)),
            "root": str(root),
        },
        "artifacts": {},
        "result": "running",
    }
    suite = ET.Element("testsuite", name="native-debian-package")
    suffix = "-resume" if args.resume_update else ""
    log_path = root / ("acceptance" + suffix + ".log")
    log = log_path.open("x")
    if args.resume_update:
        evidence["previous_attempt"] = prior
        evidence["previous_evidence_sha256"] = sha(root / "evidence.json")
        evidence["identity"]["harness_sha256"] = sha(Path(__file__))

    def run(argv, *, timeout=180):
        log.write("$ " + shlex.join(map(str, argv)) + "\n")
        log.flush()
        result = subprocess.run(
            list(map(str, argv)),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            env={
                k: v
                for k, v in acceptance_environment().items()
                if k not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"}
            },
        )
        log.write(result.stdout + result.stderr)
        log.flush()
        if result.returncode:
            raise RuntimeError(f"{Path(str(argv[0])).name}: exit {result.returncode}; see log")
        return result.stdout

    def step(name, action):
        return record_step(evidence, suite, name, action)

    config = root / "config/config.toml"
    prefix = root / "install"
    launcher = root / "bin/kirabridge"
    workspace = root / "workspace"
    runtime = root / "candidate-runtime"
    credentials = config.parent / "credentials.json"
    common = [
        "--prefix",
        prefix,
        "--config",
        config,
        "--launcher",
        launcher,
        "--workspace",
        workspace,
        "--port",
        str(args.port),
    ]

    def unpack(archive, name):
        destination = root / name
        destination.mkdir(exist_ok=args.resume_update)
        with tarfile.open(archive) as tar:
            for member in tar.getmembers():
                assert member.isfile() and not Path(member.name).is_absolute()
                assert ".." not in Path(member.name).parts
            if not args.resume_update:
                tar.extractall(destination, filter="data")
        bundle = next(destination.iterdir())
        manifest = json.loads((bundle / "release.json").read_text())
        for name, digest in manifest["files"].items():
            assert sha(bundle / name) == digest, name
        # Relative checksum entries must be resolved within their extracted root.
        subprocess.run(
            ["sha256sum", "-c", "SHA256SUMS"], cwd=bundle, stdout=subprocess.DEVNULL, check=True
        )
        evidence["artifacts"][archive.name] = {
            "sha256": sha(archive),
            "source_commit": manifest["source_commit"],
            "version": manifest["version"],
            "manifest_files": len(manifest["files"]),
        }
        if args.resume_update:
            assert evidence["artifacts"][archive.name] == prior["artifacts"][archive.name]
        return bundle

    def bootstrap(bundle):
        return run(
            [
                "sh",
                bundle / "install.sh",
                "--yes",
                "--language",
                "en",
                "--install-dir",
                runtime,
                "--unit",
                unit_path,
                *common,
            ],
            timeout=420,
        )

    def probe(release):
        value = json.loads(run([release / ".venv/bin/python3", "-I", "-c", PROBE, config]))
        assert Path(value["runtime"]["source_package_path"]).is_relative_to(release)
        assert value["runtime"]["config_sha256"] == sha(config)
        reference = candidate if release == runtime else previous
        expected = json.loads((reference / "release.json").read_text())
        package = Path(value["runtime"]["source_package_path"])
        for name, digest in expected["files"].items():
            if name.startswith("payload/src/kirabridge/"):
                assert sha(package / name.removeprefix("payload/src/kirabridge/")) == digest
        value["verified_package_source_files"] = True
        value["source_commit"] = expected["source_commit"]
        return value

    def installer(bundle, release, action):
        return run(
            [
                sys.executable,
                bundle / "installer/install.py",
                action,
                "--release-root",
                release,
                "--service",
                "systemd-user",
                "--plist",
                unit_path,
                "--cache-dir",
                root / "installer-cache",
                *common[:-2],
            ],
            timeout=120,
        )

    def preserve(expected, markers):
        assert (sha(config), sha(credentials), sha(workspace / "dirk-note.txt")) == expected
        database = Path(tomllib.loads(config.read_text())["data_dir"]) / "bridge.sqlite3"
        with sqlite3.connect(database) as db:
            rows = dict(db.execute("select id,state from tasks"))
            assert db.execute("pragma integrity_check").fetchone()[0] == "ok"
        assert all(rows.get(name) == "unknown" for name in markers)
        assert config.stat().st_mode & 0o777 == credentials.stat().st_mode & 0o777 == 0o600
        return {
            "config_credentials_note_unchanged": True,
            "unknowns": markers,
            "sqlite_integrity": "ok",
            "private_modes": "0600",
        }

    try:
        evidence["identity"]["systemd"] = run(["systemctl", "--version"]).splitlines()[0]
        run(["systemctl", "--user", "is-system-running"])
        candidate = unpack(args.candidate.absolute(), "candidate")
        previous = unpack(args.previous.absolute(), "previous")
        if not args.resume_update:
            step("fresh-package-install", lambda: {"output": bootstrap(candidate)})
            first = step("authenticated-mcp-health-and-401", lambda: probe(runtime))
            step("repeat-install-cleans-bootstrap-lock", lambda: {"output": bootstrap(candidate)})
            run(["systemctl", "--user", "restart", unit])
            time.sleep(1)
            restarted = step("native-systemd-restart", lambda: probe(runtime))
            assert restarted["runtime"]["pid"] != first["runtime"]["pid"]
            listeners = run(["ss", "-ltn"])
            matches = [line for line in listeners.splitlines() if f":{args.port} " in line]
            assert len(matches) == 1 and f"127.0.0.1:{args.port}" in matches[0]
            evidence["loopback_listener"] = matches
            step(
                "fresh-install-rollback",
                lambda: {"output": installer(candidate, runtime, "rollback")},
            )
            assert not unit_path.exists() and not launcher.exists()
            run(["systemctl", "--user", "daemon-reload"])
        # The previous Grok archive rejects Debian at its shell guard. Prepare its
        # verified payload explicitly, without claiming that bootstrap as accepted.
        old = previous / "payload"
        uv = root / "uv"
        if not args.resume_update:
            prepare_previous(run, root, uv, old)
        (old / ".kirabridge-source").write_text(
            evidence["artifacts"][args.previous.name]["source_commit"]
        )
        # Use the fixed installer to activate the unchanged, verified RC40
        # runtime. The original RC40 installer rejects uv interpreter links.
        step(
            "previous-runtime-baseline",
            lambda: {"output": installer(candidate, old, "install"), "health": probe(old)},
        )
        run(["systemctl", "--user", "disable", unit])
        (workspace / "dirk-note.txt").write_text(
            "synthetic Dirk data, preserve across update/rollback\n"
        )
        run([old / ".venv/bin/python3", "-I", "-c", MARKER, config, "dirk-before", workspace])
        expected = sha(config), sha(credentials), sha(workspace / "dirk-note.txt")
        step(
            "update-rc40-to-rc41",
            lambda: {
                "output": bootstrap(candidate),
                "health": probe(runtime),
                "data": preserve(expected, ["dirk-before"]),
            },
        )
        run([runtime / ".venv/bin/python3", "-I", "-c", MARKER, config, "dirk-after", workspace])
        step(
            "rollback-with-post-update-data",
            lambda: {
                "output": installer(candidate, runtime, "rollback"),
                "health": probe(old),
                "data": preserve(expected, ["dirk-before", "dirk-after"]),
            },
        )
        enablement = subprocess.run(
            ["systemctl", "--user", "is-enabled", unit],
            capture_output=True,
            text=True,
        )
        assert enablement.returncode == 1 and enablement.stdout.strip() == "disabled"
        evidence["rollback_preserves_disabled_unit"] = True
        step(
            "reapply-update",
            lambda: {
                "output": bootstrap(candidate),
                "health": probe(runtime),
                "data": preserve(expected, ["dirk-before", "dirk-after"]),
            },
        )
        evidence["result"] = "passed"
    except BaseException as exc:
        evidence["result"] = "failed"
        if not suite.findall(".//failure"):
            case = ET.SubElement(suite, "testcase", name="acceptance-invariant")
            ET.SubElement(case, "failure", message=str(exc) or type(exc).__name__)
        raise
    finally:
        try:
            step("cleanup", lambda: cleanup(run, unit_path, config, unit, args.port, evidence))
        finally:
            log.close()
            evidence["log_sha256"] = sha(log_path)
            suite.set("tests", str(len(suite)))
            suite.set("failures", str(len(suite.findall(".//failure"))))
            ET.ElementTree(suite).write(root / ("junit" + suffix + ".xml"), encoding="unicode")
            (root / ("evidence" + suffix + ".json")).write_text(
                json.dumps(evidence, indent=2) + "\n"
            )
    print(json.dumps({"result": evidence["result"], "root": str(root)}, indent=2))


def prepare_previous(run, root, uv, old):
    run(
        [
            "curl",
            "--fail",
            "--location",
            "--proto",
            "=https",
            "--tlsv1.2",
            "--max-time",
            "120",
            "https://github.com/astral-sh/uv/releases/download/0.11.6/uv-x86_64-unknown-linux-gnu.tar.gz",
            "-o",
            root / "uv.tar.gz",
        ]
    )
    assert sha(root / "uv.tar.gz") == (
        "0c6bab77a67a445dc849ed5e8ee8d3cb333b6e2eba863643ce1e228075f27943"
    )
    with tarfile.open(root / "uv.tar.gz") as tar:
        tar.extractall(uv, filter="data")
    uv_bin = uv / "uv-x86_64-unknown-linux-gnu/uv"
    run(
        [uv_bin, "sync", "--project", old, "--locked", "--no-dev", "--python", "3.11.15"],
        timeout=420,
    )


def cleanup(run, unit_path, config, unit, port, evidence):
    # Only this exact owned test unit; leave all test data/evidence for review.
    if unit_path.exists():
        escaped = (
            str(config)
            .replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("%", "%%")
            .replace("$", "$$")
        )
        assert '"' + escaped + '"' in unit_path.read_text()
        run(["systemctl", "--user", "disable", "--now", unit])
        unit_path.unlink()
    run(["systemctl", "--user", "daemon-reload"])
    state = run(
        [
            "systemctl",
            "--user",
            "show",
            unit,
            "-p",
            "LoadState",
            "-p",
            "ActiveState",
            "-p",
            "MainPID",
        ]
    )
    if "ActiveState=failed" in state:
        run(["systemctl", "--user", "reset-failed", unit])
        state = run(
            [
                "systemctl",
                "--user",
                "show",
                unit,
                "-p",
                "LoadState",
                "-p",
                "ActiveState",
                "-p",
                "MainPID",
            ]
        )
    assert (
        "MainPID=0" in state and "ActiveState=inactive" in state and "LoadState=not-found" in state
    )
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", port))
    evidence["cleanup"] = {
        "unit_absent": not unit_path.exists(),
        "systemd": state,
        "port_unbound": True,
    }


if __name__ == "__main__":
    main()
