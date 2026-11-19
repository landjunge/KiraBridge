"""Bounded package installation in temp paths; no real user setup/service/tunnel."""

from __future__ import annotations

import argparse
import email
import hashlib
import json
import platform
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
import zipfile
from pathlib import Path

ISOLATED_SETUP = r"""
import re
import sys
from pathlib import Path
from kirabridge.local_runtime import setup

path = Path(sys.argv[1])
setup(sys.argv[2], path, install_wrapper=False)
content = path.read_text().replace("port = 8765", "port = " + sys.argv[3])
content, matches = re.subn(
    r"(?m)^\[principals\.local\]\ncapabilities = [^\n]+",
    '[principals.local]\napproval_mode = "automatic"\n'
    'capabilities = ["bridge.health", "file.read"]',
    content,
    count=1,
)
if matches != 1:
    raise RuntimeError("Synthetic local policy could not be configured")
path.write_text(content)
"""


def run(argv, **kwargs):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=240, **kwargs)
    if result.returncode:
        try:
            payload = json.loads(result.stdout)
            detail = {
                k: payload.get(k)
                for k in (
                    "error",
                    "requested_prerequisites_ready",
                    "service_matches_local_config_and_source",
                    "audit_recorded",
                )
            }
            detail["codes"] = [
                check.get("code")
                for group in ("read_path_checks", "operation_checks")
                for check in payload.get(group, [])
            ]
        except ValueError:
            detail = {"output": "not structured"}
        raise RuntimeError(
            f"Isolated release command failed ({result.returncode}): "
            + json.dumps(detail)
            + result.stderr[-1000:]
        )
    return result


def _checksums(root, entries):
    if not isinstance(entries, dict):
        raise RuntimeError("Invalid package checksum declaration")
    for name, expected in entries.items():
        if not isinstance(name, str):
            raise RuntimeError("Invalid package checksum member")
        path = Path(name)
        if (
            not isinstance(expected, str)
            or not re.fullmatch(r"[a-f0-9]{64}", expected)
            or path.is_absolute()
            or ".." in path.parts
            or (root / path).is_symlink()
        ):
            raise RuntimeError("Unsafe package checksum declaration")
        if hashlib.sha256((root / path).read_bytes()).hexdigest() != expected:
            raise RuntimeError("Package checksum mismatch")


def package_contract(artifacts, folder, target):
    candidates = list(artifacts.glob("KiraBridge-*-" + target + ".tar.gz"))
    if target.startswith("Darwin-") and (artifacts / "KiraBridge-macos.tar.gz").exists():
        candidates.append(artifacts / "KiraBridge-macos.tar.gz")
    if len(candidates) != 1:
        raise RuntimeError("Expected exactly one package for this platform")
    bundle = candidates[0]
    with tarfile.open(bundle) as archive:
        members = archive.getmembers()
        names = [m.name for m in members]
        roots = {Path(name).parts[0] for name in names if Path(name).parts}
        if (
            not members
            or len(names) != len(set(names))
            or len(roots) != 1
            or any(
                not m.isfile() or ".." in Path(m.name).parts or Path(m.name).is_absolute()
                for m in members
            )
        ):
            raise RuntimeError("Unexpected release archive member")
        root = next(iter(roots))
        if root != "KiraBridge" and not root.startswith("KiraBridge-"):
            raise RuntimeError("Unexpected release archive root")
        archive.extractall(folder, filter="data")
    extracted = folder / root
    pin = json.loads((extracted / "release.json").read_text())
    commit = pin.get("source_commit", pin.get("commit"))
    if (
        not isinstance(commit, str)
        or not re.fullmatch(r"[a-f0-9]{40}", commit)
        or pin.get("commit", commit) != commit
        or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:(?:a|b|rc)[0-9]+)?", pin["version"])
    ):
        raise RuntimeError("Invalid release pin")
    if pin.get("platform", target) != target or target not in pin.get("platforms", [target]):
        raise RuntimeError("Package platform does not match this host")
    pin["source_commit"] = commit
    checksums = pin.get("files", {})
    if (extracted / "SHA256SUMS").exists():
        rows = [
            line.split(maxsplit=1) for line in (extracted / "SHA256SUMS").read_text().splitlines()
        ]
        if any(len(row) != 2 for row in rows) or len({row[1] for row in rows}) != len(rows):
            raise RuntimeError("Invalid package checksum manifest")
        sums = {name: expected for expected, name in rows}
        if any(name in checksums and checksums[name] != value for name, value in sums.items()):
            raise RuntimeError("Conflicting package checksums")
        checksums = {**checksums, **sums}
    _checksums(extracted, checksums)
    license_bytes = (extracted / "LICENSE").read_bytes()
    license_hash = hashlib.sha256(license_bytes).hexdigest()
    # Legacy manifests must still bind both license copies and the project metadata.
    legacy_license = "license" not in pin and "license_sha256" not in pin
    if ("license" in pin) != ("license_sha256" in pin):
        raise RuntimeError("Incomplete license pin")
    if legacy_license:
        if not {"LICENSE", "payload/LICENSE", "payload/pyproject.toml"}.issubset(checksums):
            raise RuntimeError("Legacy package does not pin its license")
        project = tomllib.loads((extracted / "payload/pyproject.toml").read_text())["project"]
        pin.setdefault("license", project["license"])
        pin.setdefault("license_sha256", checksums["LICENSE"])
    assert isinstance(pin["license"], str) and pin["license"]
    assert license_hash == pin["license_sha256"]
    assert (extracted / "payload/LICENSE").read_bytes() == license_bytes
    separate_license = (artifacts / "LICENSE").exists()
    if not separate_license and not legacy_license:
        raise RuntimeError("Missing separate release license asset")
    if separate_license:
        assert (artifacts / "LICENSE").read_bytes() == license_bytes
    wheels = list(artifacts.glob("*.whl"))
    if len(wheels) != 1:
        raise RuntimeError("Expected one release wheel")
    with zipfile.ZipFile(wheels[0]) as wheel:
        names = wheel.namelist()
        metadata_names = [name for name in names if name.endswith("/METADATA")]
        license_names = [name for name in names if name.endswith("/licenses/LICENSE")]
        assert len(metadata_names) == len(license_names) == 1
        metadata = email.message_from_bytes(wheel.read(metadata_names[0]))
        assert metadata["Name"].lower() == "kirabridge" and metadata["Version"] == pin["version"]
        assert metadata["License-Expression"] == pin["license"]
        assert wheel.read(license_names[0]) == license_bytes
        if "wheel" in pin:
            bundled = extracted / pin["wheel"]
            assert pin["wheel"] in checksums
            assert bundled.read_bytes() == wheels[0].read_bytes()
    return bundle, extracted, pin, separate_license


def preparation(extracted, installed, folder, pin, target):
    if target.startswith("Darwin-") and (extracted / "installer/install.py").exists():
        command = [
            sys.executable,
            str(extracted / "installer/install.py"),
            "prepare",
            "--bundle",
            str(extracted),
            "--service",
            "none",
            "--prefix",
            str(installed),
            "--config",
            str(folder / "isolated-config/config.toml"),
            "--workspace",
            str(folder / "project"),
            "--launcher",
            str(folder / "bin/kirabridge"),
            "--plist",
            str(folder / "unused.plist"),
            "--cache-dir",
            str(folder / "cache"),
        ]
        runtime = installed / "releases" / (pin["version"] + "-" + pin["source_commit"][:12])
        return command, str(runtime / "source/.venv/bin/python"), installed / "releases"
    return (
        [
            "sh",
            str(extracted / "install.sh"),
            "--language",
            "en",
            "--prepare-only",
            "--install-dir",
            str(installed),
        ],
        str(installed / ".venv/bin/python3"),
        installed,
    )


def smoke(artifacts: Path):
    target = platform.system() + "-" + platform.machine()
    with tempfile.TemporaryDirectory(prefix="kirabridge-release-") as tmp:
        folder = Path(tmp).resolve()
        bundle, extracted, pin, separate_license = package_contract(artifacts, folder, target)
        installed = folder / "isolated-runtime"
        command, python, _ = preparation(extracted, installed, folder, pin, target)
        run(command, input="yes\n")
        config = folder / "isolated-config/config.toml"
        workspace = folder / "project"
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        # Only this temporary local fixture grants the requested probe operation.
        # Real setup defaults and all other operation approvals remain unchanged.
        run([python, "-c", ISOLATED_SETUP, str(config), str(workspace), str(port)])
        probe = workspace / "release-probe.txt"
        probe.write_text("Synthetic isolated release prerequisite\n")
        config_before = hashlib.sha256(config.read_bytes()).hexdigest()
        credentials_before = hashlib.sha256(
            (config.parent / "credentials.json").read_bytes()
        ).hexdigest()
        base = [python, "-m", "kirabridge.cli", "--config", str(config)]
        check = json.loads(run([*base, "install", "--check"]).stdout)
        assert check["changes"] is False and check["chatgpt_call"] == "unverified"
        # Kept inside the temporary folder so a failed start explains itself.
        dispatcher_log = folder / "dispatcher.stderr.log"
        log_stream = dispatcher_log.open("wb")
        process = subprocess.Popen(
            [*base, "serve", "--transport", "http"],
            stdout=subprocess.DEVNULL,
            stderr=log_stream,
        )
        log_stream.close()
        try:
            health = None
            for _ in range(30):
                if process.poll() is not None:
                    tail = dispatcher_log.read_bytes()[-4000:].decode("utf-8", "replace")
                    raise RuntimeError(
                        f"Isolated dispatcher exited before readiness (exit {process.returncode})"
                        + (":\n" + tail if tail.strip() else "; no error output")
                    )
                reply = subprocess.run([*base, "status"], capture_output=True, text=True, timeout=7)
                if reply.returncode == 0:
                    health = json.loads(reply.stdout)
                    break
                time.sleep(0.2)
            assert health and health["version"] == pin["version"] and health["dispatcher_active"]
            ready = json.loads(
                run(
                    [
                        *base,
                        "readiness",
                        "--workflow-id",
                        "release-package-smoke",
                        "--operation",
                        "file.read",
                        "--read-path",
                        str(probe),
                    ]
                ).stdout
            )
            assert (
                ready["requested_prerequisites_ready"]
                and ready["service_matches_local_config_and_source"]
            )
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        # Corrupt only this temp package. Its installer must stop before preparing another runtime.
        bad = folder / "bad-package"
        shutil.copytree(extracted, bad)
        with (bad / "payload/pyproject.toml").open("a") as f:
            f.write("\n# deliberate isolated checksum failure\n")
        bad_command, _, forbidden = preparation(bad, folder / "must-not-exist", folder, pin, target)
        denied = subprocess.run(
            bad_command,
            input="yes\n",
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert denied.returncode != 0 and not forbidden.exists()
        assert hashlib.sha256(config.read_bytes()).hexdigest() == config_before
        assert (
            hashlib.sha256((config.parent / "credentials.json").read_bytes()).hexdigest()
            == credentials_before
        )
        evidence = {
            "platform": target,
            "version": pin["version"],
            "source_commit": pin["source_commit"],
            "archive_sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
            "packaged_start_command": "passed isolated bundled installer preparation",
            "installed_authenticated_dispatcher": True,
            "concrete_preflight_and_loaded_source_match": True,
            "corrupt_package_rejected_before_install": True,
            "config_and_credentials_preserved": True,
            "license_in_bundle_payload_wheel_and_separate_asset": separate_license,
            "license_sha256": pin["license_sha256"],
            "license_expression": pin["license"],
            "real_user_setup_service_tunnel_changed": False,
            "new_chatgpt_account_call": "not performed",
            "real_user_service_manager": "not exercised",
        }
        (artifacts / ("smoke-" + target + ".json")).write_text(
            json.dumps(evidence, indent=2) + "\n"
        )
        print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("artifacts", type=Path)
    smoke(parser.parse_args().artifacts.absolute())
