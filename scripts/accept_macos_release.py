"""Actual bundle/wheel/launchd acceptance in explicit isolated paths; macOS only."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import shlex
import shutil
import socket
import sqlite3
import subprocess
import tarfile
import time
from pathlib import Path
from types import SimpleNamespace


def run(argv, **kwargs):
    result = subprocess.run(argv, text=True, capture_output=True, timeout=240, **kwargs)
    if result.returncode:
        raise RuntimeError(
            f"{argv[0]} exited {result.returncode}: {result.stdout[-2000:]}{result.stderr[-2000:]}"
        )
    return result.stdout


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def accept(artifacts, root, previous_wheel, release_download=False):
    if platform.system() != "Darwin":
        raise SystemExit("Actual macOS is required")
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
    # The previous runtime runs the actual published RC14 wheel with locked compatible deps.
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
    assert installer.cli_version(previous) == "0.8.0rc14"
    installer.jwrite(
        previous / "release.json",
        {"version": "0.8.0rc14", "commit": "c21d37ebdd42f03c85df1e89cd3c6969a6362e4c"},
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

    try:
        installer.activate(args, previous)
        health("0.8.0rc14")
        database = installer.state_file(args.config)
        with sqlite3.connect(database) as db:
            db.execute("create table release_acceptance_probe(value text)")
            db.execute("insert into release_acceptance_probe values ('PRESERVE_DATABASE')")
        evidence["checks"].append("actual published RC14 wheel starts under isolated launchd")
        print(run(command, cwd=extracted, env=test_env), flush=True)
        current = health(version)
        evidence["checks"].append("built package upgrades RC14; authenticated version/status/start")
        assert (digest(args.config), digest(credentials)) == before
        assert user_file.read_text() == "PRESERVE_USER_FILE\n"
        with sqlite3.connect(database) as db:
            assert db.execute("select value from release_acceptance_probe").fetchone()[0] == (
                "PRESERVE_DATABASE"
            )
        evidence["checks"].append("config/credentials hashes, database row and user file preserved")
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
        health("0.8.0rc14")
        assert (digest(args.config), digest(credentials)) == before
        evidence["checks"].append(
            "real rollback restarts previous RC14 wheel and preserves secrets"
        )
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
        subprocess.run(["launchctl", "bootout", service], capture_output=True, timeout=20)
        (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", type=Path)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--previous-wheel", required=True, type=Path)
    parser.add_argument("--release-download", action="store_true")
    opts = parser.parse_args()
    accept(
        opts.artifacts.resolve(),
        opts.root.resolve(),
        opts.previous_wheel.resolve(),
        opts.release_download,
    )
