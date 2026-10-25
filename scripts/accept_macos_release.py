"""Actual bundle/wheel/launchd acceptance in explicit isolated paths; macOS only."""

from __future__ import annotations

import argparse
import email.parser
import hashlib
import importlib.util
import json
import os
import platform
import re
import shlex
import shutil
import socket
import sqlite3
import subprocess
import tarfile
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

# Fixed helper source: credentials are loaded only from the isolated config and
# never enter argv, stdout, stderr or evidence. This client performs reads only.
HOLD_COMPLETION = r"""
import asyncio
import json
import sys
import time
from pathlib import Path

import anyio
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import McpError
from mcp.types import CONNECTION_CLOSED

from kirabridge.bridge_core.config import load_config
from kirabridge.local_runtime import peer


def exception_tree(exc, *, depth=0, seen=None, budget=None):
    # Only class identity and numeric MCP codes: never exception text/args,
    # request URLs/headers, credentials, response bodies or traceback locals.
    seen = set() if seen is None else seen
    budget = [64] if budget is None else budget
    if id(exc) in seen or depth >= 8 or budget[0] <= 0:
        return None
    seen.add(id(exc))
    budget[0] -= 1
    result = {"type": type(exc).__name__, "module": type(exc).__module__}
    if isinstance(exc, McpError) and type(exc.error.code) is int:
        result["mcp_code"] = exc.error.code
    if isinstance(exc, BaseExceptionGroup):
        children = [
            exception_tree(child, depth=depth + 1, seen=seen, budget=budget)
            for child in exc.exceptions[:64]
        ]
        result["children"] = [child for child in children if child is not None]
    cause = exc.__cause__ if exc.__cause__ is not None else exc.__context__
    if cause is not None:
        cause_tree = exception_tree(cause, depth=depth + 1, seen=seen, budget=budget)
        if cause_tree is not None:
            result["cause"] = cause_tree
    return result


def disconnected(exc):
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return False
    if isinstance(exc, BaseExceptionGroup):
        return bool(exc.exceptions) and all(disconnected(child) for child in exc.exceptions)
    return isinstance(
        exc,
        (
            httpx.TransportError,
            ConnectionError,
            anyio.EndOfStream,
            anyio.BrokenResourceError,
            anyio.ClosedResourceError,
        ),
    ) or (isinstance(exc, McpError) and exc.error.code == CONNECTION_CLOSED)


async def main():
    config_path, ready_path, result_path = map(Path, sys.argv[1:4])
    root = ready_path.parent.resolve()
    assert config_path.resolve().is_relative_to(root)
    config = load_config(str(config_path))
    assert config.state_path.resolve().is_relative_to(root)
    assert config.credentials_file
    assert Path(config.credentials_file).resolve().is_relative_to(root)
    endpoint = peer(config, "local")
    sent = asyncio.Event()
    evidence = {
        "scope": "isolated authenticated completion_receive only",
        "response_received": False,
    }

    async def request_hook(request):
        body = json.loads(await request.aread()) if request.method == "POST" else {}
        if (
            body.get("method") == "tools/call"
            and body.get("params", {}).get("name") == "completion_receive"
        ):

            async def trace(name, info):
                if name in {
                    "http11.send_request_body.complete",
                    "http2.send_request_body.complete",
                }:
                    sent.set()

            request.extensions["trace"] = trace

    try:
        async with asyncio.timeout(35):
            async with httpx.AsyncClient(
                headers={"Authorization": "Bearer " + endpoint.token},
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(30),
                event_hooks={"request": [request_hook]},
            ) as client:
                async with streamable_http_client(endpoint.url, http_client=client) as streams:
                    async with ClientSession(streams[0], streams[1]) as session:
                        await session.initialize()
                        evidence["started_monotonic"] = time.monotonic()
                        call = asyncio.create_task(
                            session.call_tool(
                                "completion_receive",
                                {
                                    "target": "isolated-upgrade-open-read",
                                    "limit": 1,
                                    "wait_seconds": 20,
                                },
                            )
                        )
                        try:
                            await asyncio.wait_for(sent.wait(), 5)
                            await asyncio.sleep(0.25)
                            assert not call.done(), "Completion read returned before blocking proof"
                            evidence.update(body_sent=True, pending_after_seconds=0.25)
                            ready_path.write_text(json.dumps(evidence))
                            result = await call
                            evidence["response_received"] = True
                            assert not result.isError and isinstance(result.structuredContent, dict)
                            assert not result.structuredContent.get("error")
                            assert result.structuredContent.get("notices") == []
                            evidence["settled"] = "empty_response"
                        except BaseException as exc:
                            evidence["inner_exception_type"] = type(exc).__name__
                            evidence["request_error_tree"] = exception_tree(exc)
                            evidence["settled"] = (
                                "connection_ended"
                                if disconnected(exc)
                                else "invalid_or_failed_response"
                            )
                            raise
                        finally:
                            if not call.done():
                                call.cancel()
                            await asyncio.gather(call, return_exceptions=True)
    except BaseException as exc:
        evidence["outcome_type"] = type(exc).__name__
        evidence["outcome_error_tree"] = exception_tree(exc)
        # Transport task groups cancel the awaiting request before surfacing
        # their actual disconnect leaf during async-context unwinding.
        if evidence.get("body_sent") and not evidence["response_received"] and disconnected(exc):
            evidence["settled"] = "connection_ended"
    finally:
        evidence["ended_monotonic"] = time.monotonic()
        result_path.write_text(json.dumps(evidence, indent=2) + "\n")


asyncio.run(main())
"""


def stop_helper(child):
    if child is not None and child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=3)


def run(argv, **kwargs):
    result = subprocess.run(argv, text=True, capture_output=True, timeout=240, **kwargs)
    if result.returncode:
        raise RuntimeError(
            f"{argv[0]} exited {result.returncode}: {result.stdout[-2000:]}{result.stderr[-2000:]}"
        )
    return result.stdout


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def accept(
    artifacts,
    root,
    previous_wheel,
    release_download=False,
    upgrade_only=False,
    previous_commit=None,
    hold_completion=False,
):
    if platform.system() != "Darwin":
        raise SystemExit("Actual macOS is required")
    with zipfile.ZipFile(previous_wheel) as wheel:
        metadata_paths = [name for name in wheel.namelist() if name.endswith(".dist-info/METADATA")]
        assert len(metadata_paths) == 1, "Previous wheel must have one package metadata record"
        metadata = email.parser.BytesParser().parsebytes(wheel.read(metadata_paths[0]))
        assert metadata["Name"].lower() == "kirabridge"
        previous_version = metadata["Version"]
        assert previous_version
    if previous_commit is None and previous_version == "0.8.0rc14":
        previous_commit = "c21d37ebdd42f03c85df1e89cd3c6969a6362e4c"
    if not previous_commit or not re.fullmatch(r"[0-9a-f]{40}", previous_commit):
        raise SystemExit("Supply the verified 40-character --previous-commit for this wheel")
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    extracted = root / "extracted"
    extracted.mkdir()
    bundle = artifacts / "KiraBridge-macos.tar.gz"
    assert digest(bundle) == (artifacts / (bundle.name + ".sha256")).read_text().split()[0]
    with tarfile.open(bundle) as archive:
        assert all(
            m.isfile() and not Path(m.name).is_absolute() and ".." not in Path(m.name).parts
            for m in archive.getmembers()
        )
        archive.extractall(extracted, filter="data")
    package = extracted / "KiraBridge"
    spec = importlib.util.spec_from_file_location(
        "accept_installer", package / "installer/install.py"
    )
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    label = "com.kirabridge.test." + root.name.lower().replace("_", "-")
    installer.LABEL = label
    service = f"gui/{os.getuid()}/{label}"
    # Guard cleanup: never stop an existing service, even with this unique test name.
    assert subprocess.run(["launchctl", "print", service], capture_output=True).returncode != 0
    args = SimpleNamespace(
        bundle=package,
        prefix=root / "install",
        config=root / "config/config.toml",
        launcher=root / "bin/kirabridge",
        plist=root / "service.plist",
        service="launchd",
        cache_dir=root / "cache",
        full_access=False,
        workspace=root / "workspace",
    )
    installer.private_dir(args.prefix)
    candidate = installer.prepare_bundle(args)
    version = installer.cli_version(candidate)
    assert run([str(installer.python(candidate)), "-m", "kirabridge.cli", "--version"]).strip() == (
        "cli.py " + version
    )
    # Run the explicitly pinned previous wheel with locked compatible dependencies.
    previous = root / "previous"
    shutil.copytree(package / "payload", previous / "source")
    run(
        [
            "uv",
            "sync",
            "--project",
            str(previous / "source"),
            "--locked",
            "--no-dev",
            "--no-install-project",
            "--no-build",
            "--python",
            "3.11",
            "--cache-dir",
            str(args.cache_dir),
        ]
    )
    run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(installer.python(previous)),
            "--no-deps",
            "--cache-dir",
            str(args.cache_dir),
            str(previous_wheel),
        ]
    )
    assert installer.cli_version(previous) == previous_version
    installer.jwrite(
        previous / "release.json",
        {"version": previous_version, "commit": previous_commit},
    )
    installer.fresh_config(args, previous)
    import tomllib

    fresh = tomllib.loads(args.config.read_text())
    assert fresh["principals"]["chatgpt"]["approval_mode"] == "manual"
    assert fresh["principals"]["chatgpt"]["roots"] == [str(args.workspace)]
    assert not fresh["principals"]["chatgpt"]["allow_any_executable"]
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    installer.atomic(args.config, args.config.read_text().replace("port = 8765", f"port = {port}"))
    credentials = args.config.parent / "credentials.json"
    before = (digest(args.config), digest(credentials))
    user_file = args.workspace / "preserve.txt"
    user_file.write_text("PRESERVE_USER_FILE\n")
    common = [
        "--prefix",
        str(args.prefix),
        "--config",
        str(args.config),
        "--launcher",
        str(args.launcher),
        "--plist",
        str(args.plist),
        "--cache-dir",
        str(args.cache_dir),
        "--workspace",
        str(args.workspace),
        "--test-label",
        label,
    ]
    command = ["sh", "KiraBridge/install.sh", *common]
    download_command = Path("scripts/install-command.sh").read_text().strip()
    if release_download:
        command = ["sh", "-c", download_command, "kirabridge-isolated-test", *common]
    evidence = {
        "download_command": download_command if release_download else "not exercised",
        "os": platform.platform(),
        "architecture": platform.machine(),
        "version": version,
        "scope": "isolated real launchd label, config, port, runtime and data; no production paths",
        "tested_command": shlex.join(command),
        "cwd": str(extracted),
        "checks": [],
        "upgrade_only": upgrade_only,
        "hold_completion": hold_completion,
        "previous_version": previous_version,
        "previous_commit": previous_commit,
        "previous_wheel_sha256": digest(previous_wheel),
        "remote_release_command": (
            "authenticated draft download" if release_download else "not exercised in this run"
        ),
    }

    scratch = root / "scratch"
    scratch.mkdir(mode=0o700)
    test_env = dict(os.environ, TMPDIR=str(scratch))

    def health(expected, prior_pid=None):
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            try:
                result = installer.cli(candidate, args.config, "status", timeout=8)
                if (
                    result["version"] == expected
                    and result["dispatcher_active"]
                    and (prior_pid is None or result["runtime"]["pid"] != prior_pid)
                ):
                    return result
            except Exception:
                pass
            time.sleep(0.25)
        raise RuntimeError("Authenticated daemon health timeout")

    helper = None
    try:
        installer.activate(args, previous)
        previous_health = health(previous_version)
        database = installer.state_file(args.config)
        with sqlite3.connect(database) as db:
            db.execute("create table release_acceptance_probe(value text)")
            db.execute("insert into release_acceptance_probe values ('PRESERVE_DATABASE')")
        evidence["checks"].append(
            f"pinned previous {previous_version} wheel starts under isolated launchd"
        )
        if hold_completion:
            ready_path, result_path = (
                root / "completion-read-ready.json",
                root / "completion-read-result.json",
            )
            helper = subprocess.Popen(
                [
                    str(installer.python(previous)),
                    "-c",
                    HOLD_COMPLETION,
                    str(args.config),
                    str(ready_path),
                    str(result_path),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=test_env,
            )
            deadline = time.monotonic() + 12
            while not ready_path.exists():
                if helper.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError(
                        "Isolated completion read did not become demonstrably pending"
                    )
                time.sleep(0.05)
            proof = json.loads(ready_path.read_text())
            assert proof["body_sent"] and proof["pending_after_seconds"] >= 0.25
            assert helper.poll() is None
            evidence["open_completion_read"] = {
                "old_pid": previous_health["runtime"]["pid"],
                "ready": proof,
                "upgrade_started_monotonic": time.monotonic(),
            }
        print(run(command, cwd=extracted, env=test_env), flush=True)
        current = health(version)
        if hold_completion:
            helper.wait(timeout=8)
            completion = json.loads(result_path.read_text())
            assert completion["body_sent"] and completion["pending_after_seconds"] >= 0.25
            assert (
                completion["ended_monotonic"]
                >= evidence["open_completion_read"]["upgrade_started_monotonic"]
            )
            assert completion["settled"] in {"empty_response", "connection_ended"}
            assert current["runtime"]["pid"] != previous_health["runtime"]["pid"]
            evidence["open_completion_read"].update(
                new_pid=current["runtime"]["pid"],
                helper=completion,
                upgraded_monotonic=time.monotonic(),
            )
            evidence["checks"].append(
                "upgrade while authenticated completion_receive HTTP request remained open; "
                "old read settled without replay and new daemon PID healthy"
            )
        evidence["checks"].append(
            f"built package upgrades {previous_version}; authenticated version/status/start"
        )
        assert (digest(args.config), digest(credentials)) == before
        assert user_file.read_text() == "PRESERVE_USER_FILE\n"
        with sqlite3.connect(database) as db:
            assert db.execute("select value from release_acceptance_probe").fetchone()[0] == (
                "PRESERVE_DATABASE"
            )
        evidence["checks"].append("config/credentials hashes, database row and user file preserved")
        if not upgrade_only:
            # Installer subprocess has exited; the daemon remains independently owned by launchd.
            time.sleep(1)
            assert health(version)["runtime"]["pid"] == current["runtime"]["pid"]
            evidence["checks"].append("daemon survives installer/terminal command exit")
            print(run(command, cwd=extracted, env=test_env), flush=True)
            assert health(version)["runtime"]["pid"] == current["runtime"]["pid"]
            evidence["checks"].append("repeat install idempotent; same PID and no config rewrite")
            run(["launchctl", "kickstart", "-k", service])
            restarted = health(version, current["runtime"]["pid"])
            evidence["checks"].append("real launchctl kickstart restart and authenticated status")
            run(["launchctl", "kill", "SIGKILL", service])
            health(version, restarted["runtime"]["pid"])
            evidence["checks"].append("launchd KeepAlive automatically recovers a crashed daemon")
        print(
            run(["python3.11", str(package / "installer/install.py"), "status", *common]),
            flush=True,
        )
        print(
            run(["python3.11", str(package / "installer/install.py"), "rollback", *common]),
            flush=True,
        )
        health(previous_version)
        assert (digest(args.config), digest(credentials)) == before
        evidence["checks"].append(
            f"real rollback restarts previous {previous_version} wheel and preserves secrets"
        )
        if not upgrade_only:
            # Fresh installation, reusing the prepared wheel in a separate config and prefix.
            installer.stop_service(args)
            fresh_args = SimpleNamespace(**vars(args))
            fresh_args.prefix = root / "fresh/install"
            fresh_args.config = root / "fresh/config/config.toml"
            fresh_args.launcher = root / "fresh/bin/kirabridge"
            fresh_args.plist = root / "fresh/service.plist"
            fresh_args.workspace = root / "fresh/workspace"
            installer.private_dir(fresh_args.prefix)
            fresh_release = installer.prepare_bundle(fresh_args)
            installer.fresh_config(fresh_args, fresh_release)
            installer.atomic(
                fresh_args.config,
                fresh_args.config.read_text().replace("port = 8765", f"port = {port}"),
            )
            # Explicitly isolated service arguments; production label cannot be reached.
            args = fresh_args
            installer.activate(args, fresh_release)
            health(version)
            evidence["checks"].append(
                "fresh built-wheel installation starts actual isolated launchd service"
            )
        evidence["passed"] = True
    finally:
        try:
            stop_helper(helper)
        except BaseException as exc:
            evidence["passed"] = False
            evidence["helper_cleanup_error"] = type(exc).__name__
            raise
        finally:
            try:
                subprocess.run(["launchctl", "bootout", service], capture_output=True, timeout=20)
            except BaseException as exc:
                evidence["passed"] = False
                evidence["service_cleanup_error"] = type(exc).__name__
                raise
            finally:
                (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", type=Path)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--previous-wheel", required=True, type=Path)
    parser.add_argument("--release-download", action="store_true")
    parser.add_argument("--previous-commit", help="Verified source commit for the previous wheel")
    parser.add_argument(
        "--upgrade-only",
        action="store_true",
        help="Only new-package upgrade, data preservation and rollback",
    )
    parser.add_argument(
        "--hold-completion",
        action="store_true",
        help="Keep a proven open isolated completion_receive read during the upgrade",
    )
    opts = parser.parse_args()
    accept(
        opts.artifacts.resolve(),
        opts.root.resolve(),
        opts.previous_wheel.resolve(),
        opts.release_download,
        opts.upgrade_only,
        opts.previous_commit,
        opts.hold_completion,
    )
