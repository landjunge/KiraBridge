"""Build deterministic macOS source/wheel bundle from a clean exact Git commit."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import subprocess
import tarfile
import tomllib
from pathlib import Path


def git(*args):
    return subprocess.check_output(["git", *args], text=True).strip()


def build(output):
    if output.exists():
        raise SystemExit("Output must not exist; previous artifacts are preserved")
    if git("status", "--porcelain"):
        raise SystemExit("Commit all source changes before building")
    commit = git("rev-parse", "HEAD")
    version = tomllib.loads(Path("pyproject.toml").read_text())["project"]["version"]
    output.mkdir(parents=True)
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(output)],
        check=True,
        env=dict(os.environ, SOURCE_DATE_EPOCH=git("show", "-s", "--format=%ct", commit)),
    )
    wheel = next(output.glob("*.whl"))
    files = {"wheel/" + wheel.name: wheel.read_bytes()}
    for name in git("ls-files").splitlines():
        if name.startswith("src/") or name in {"pyproject.toml", "uv.lock", "LICENSE"}:
            files["payload/" + name] = subprocess.check_output(["git", "show", f"{commit}:{name}"])
    files["installer/install.py"] = Path("installer/install.py").read_bytes()
    files["INSTALL.md"] = Path("docs/INSTALL-MACOS.md").read_bytes()
    files["RELEASE-NOTES.md"] = Path("docs/RELEASE-0.8.0rc15.md").read_bytes()
    files["LICENSE"] = Path("LICENSE").read_bytes()
    files["install.sh"] = b"""#!/bin/sh
set -eu
[ "$(uname -s)" = Darwin ] || { echo 'macOS required' >&2; exit 1; }
case "$(uname -m)" in x86_64|arm64) ;; *) echo 'Unsupported CPU' >&2; exit 1;; esac
case "$(sw_vers -productVersion)" in
  15.*|26.*) ;;
  *) echo 'Requires macOS 15 or 26; older versions unverified' >&2; exit 1;;
esac
command -v uv >/dev/null || { echo 'Install uv 0.11.6 first; see INSTALL.md' >&2; exit 1; }
command -v python3.11 >/dev/null || {
  echo 'Install Python 3.11 first; see INSTALL.md' >&2; exit 1;
}
bundle=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
exec python3.11 "$bundle/installer/install.py" install --bundle "$bundle" "$@"
"""
    manifest = {
        "version": version,
        "commit": commit,
        "platforms": ["Darwin-x86_64", "Darwin-arm64"],
        "wheel": "wheel/" + wheel.name,
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())},
        "runtime": "Python 3.11, uv 0.11.6; dependencies from hash-locked uv.lock",
        "apple_signed": False,
    }
    files["release.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    bundle = output / "KiraBridge-macos.tar.gz"
    with (
        bundle.open("xb") as raw,
        gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as gz,
    ):
        with tarfile.open(fileobj=gz, mode="w") as archive:
            for name, data in sorted(files.items()):
                item = tarfile.TarInfo("KiraBridge/" + name)
                item.size, item.mode, item.mtime = len(data), 0o644, 0
                archive.addfile(item, io.BytesIO(data))
    for artifact in [bundle, wheel]:
        (output / (artifact.name + ".sha256")).write_text(
            hashlib.sha256(artifact.read_bytes()).hexdigest() + "  " + artifact.name + "\n"
        )
    (output / "SHA256SUMS").write_text(
        "".join(
            hashlib.sha256(p.read_bytes()).hexdigest() + "  " + p.name + "\n"
            for p in [bundle, wheel]
        )
    )
    print(json.dumps({"version": version, "commit": commit, "bundle": str(bundle)}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    build(parser.parse_args().out.resolve())
