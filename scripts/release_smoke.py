"""Bounded package installation in temp paths; no real user setup/service/tunnel."""

from __future__ import annotations

import argparse
import email
import hashlib
import json
import platform
import shutil
import socket
import subprocess
import tarfile
import tempfile
import time
import zipfile
from pathlib import Path


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
            detail["codes"] = [x.get("code") for x in payload.get("read_path_checks", [])]
        except ValueError:
            detail = {"output": "not structured"}
        raise RuntimeError(
            f"Isolated release command failed ({result.returncode}): "
            + json.dumps(detail)
            + result.stderr[-1000:]
        )
    return result


def smoke(artifacts: Path):
    target = platform.system() + "-" + platform.machine()
    bundle = next(artifacts.glob("KiraBridge-*-" + target + ".tar.gz"))
    with tempfile.TemporaryDirectory(prefix="kirabridge-release-") as tmp:
        folder = Path(tmp).resolve()
        with tarfile.open(bundle) as archive:
            # Own freshly built archive; reject links/path escapes as an additional check.
            if any(
                not m.isfile() or ".." in Path(m.name).parts or m.name.startswith("/")
                for m in archive.getmembers()
            ):
                raise RuntimeError("Unexpected release archive member")
            archive.extractall(folder)
        extracted = next(folder.glob("KiraBridge-*"))
        pin = json.loads((extracted / "release.json").read_text())
        license_bytes = (artifacts / "LICENSE").read_bytes()
        assert (extracted / "LICENSE").read_bytes() == license_bytes
        assert (extracted / "payload/LICENSE").read_bytes() == license_bytes
        assert hashlib.sha256(license_bytes).hexdigest() == pin["license_sha256"]
        with zipfile.ZipFile(next(artifacts.glob("*.whl"))) as wheel:
            names = wheel.namelist()
            metadata = email.message_from_bytes(
                wheel.read(next(n for n in names if n.endswith("/METADATA")))
            )
            assert metadata["License-Expression"] == pin["license"]
            assert (
                wheel.read(next(n for n in names if n.endswith("/licenses/LICENSE")))
                == license_bytes
            )
        installed = folder / "isolated-runtime"
        command = [
            "sh",
            str(extracted / "install.sh"),
            "--language",
            "en",
            "--prepare-only",
            "--install-dir",
            str(installed),
        ]
        run(command, input="yes\n")
        python = str(installed / ".venv/bin/python3")
        config = folder / "isolated-config/config.toml"
        workspace = folder / "project"
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        script = (
            "import sys;from pathlib import Path;from kirabridge.local_runtime import setup;"
            "p=Path(sys.argv[1]);setup(sys.argv[2],p,install_wrapper=False);"
            "p.write_text(p.read_text().replace('port = 8765','port = '+sys.argv[3]))"
        )
        run([python, "-c", script, str(config), str(workspace), str(port)])
        probe = workspace / "release-probe.txt"
        probe.write_text("Synthetic isolated release prerequisite\n")
        config_before = hashlib.sha256(config.read_bytes()).hexdigest()
        credentials_before = hashlib.sha256(
            (config.parent / "credentials.json").read_bytes()
        ).hexdigest()
        base = [python, "-m", "kirabridge.cli", "--config", str(config)]
        check = json.loads(run([*base, "install", "--check"]).stdout)
        assert check["changes"] is False and check["chatgpt_call"] == "unverified"
        process = subprocess.Popen(
            [*base, "serve", "--transport", "http"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            health = None
            for _ in range(30):
                if process.poll() is not None:
                    raise RuntimeError("Isolated dispatcher exited before readiness")
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
        denied = subprocess.run(
            [
                "sh",
                str(bad / "install.sh"),
                "--prepare-only",
                "--install-dir",
                str(folder / "must-not-exist"),
            ],
            input="yes\n",
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert denied.returncode != 0 and not (folder / "must-not-exist").exists()
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
            "packaged_start_command": "passed --prepare-only in isolated path",
            "installed_authenticated_dispatcher": True,
            "concrete_preflight_and_loaded_source_match": True,
            "corrupt_package_rejected_before_install": True,
            "config_and_credentials_preserved": True,
            "license_in_bundle_payload_wheel_and_separate_asset": True,
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
