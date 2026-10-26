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
    if output.is_symlink() or (output.exists() and any(output.iterdir())):
        raise SystemExit("Use a new empty output directory; existing artifacts are preserved")
    if git("status", "--porcelain"):
        raise SystemExit("Commit all source changes before building")
    commit = git("rev-parse", "HEAD")
    project = tomllib.loads(Path("pyproject.toml").read_text())["project"]
    version = project["version"]
    license_bytes = Path("LICENSE").read_bytes()
    license_fields = {
        "license": project["license"],
        "license_sha256": hashlib.sha256(license_bytes).hexdigest(),
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "LICENSE").write_bytes(license_bytes)
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(output)],
        check=True,
        env=dict(os.environ, SOURCE_DATE_EPOCH=git("show", "-s", "--format=%ct", commit)),
    )
    wheel = next(output.glob("*.whl"))
    files = {"wheel/" + wheel.name: wheel.read_bytes()}
    for name in git("ls-files").splitlines():
        if name.startswith(("src/", "docs/", "examples/")) or name in {
            "pyproject.toml",
            "uv.lock",
            "LICENSE",
        }:
            member = name if name.startswith("docs/") else "payload/" + name
            files[member] = subprocess.check_output(["git", "show", f"{commit}:{name}"])
    for name in (
        "installer/install.py",
        "installer/presentation.py",
        "installer/visible_terminal.py",
    ):
        files[name] = subprocess.check_output(["git", "show", f"{commit}:{name}"])
    presentation_assets = {
        name: hashlib.sha256(files[name]).hexdigest()
        for name in (
            "payload/src/kirabridge/terminal_design.py",
            "payload/src/kirabridge/install_ui.py",
            "installer/presentation.py",
        )
    }
    presentation = {
        "schema": "kirabridge.installer.presentation.v1",
        "assets": presentation_assets,
        "palette": "#F06DB0",
        "output": "human-stderr-only",
    }
    files["INSTALL.md"] = (
        Path("docs/INSTALL-MACOS.md").read_bytes().replace(b"](CHATGPT.md)", b"](docs/CHATGPT.md)")
    )
    files["RELEASE-NOTES.md"] = (
        Path(f"docs/RELEASE-{version}.md")
        .read_bytes()
        .replace(b"](INSTALL-MACOS.md)", b"](docs/INSTALL-MACOS.md)")
        .replace(b"](ACCEPTANCE-MACOS-RC15.md)", b"](docs/ACCEPTANCE-MACOS-RC15.md)")
    )
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
        "source_commit": commit,
        **license_fields,
        "platforms": ["Darwin-x86_64", "Darwin-arm64"],
        "wheel": "wheel/" + wheel.name,
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())},
        "presentation": presentation,
        "runtime": "Python 3.11, uv 0.11.6; dependencies from hash-locked uv.lock",
        "apple_signed": False,
        "maturity": "source-pinned artifact; acceptance and publication recorded separately",
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
    bootstrap = output / "install-macos.sh"
    bootstrap.write_text(
        "#!/bin/sh\nset -eu\numask 077\n"
        'command -v gh >/dev/null || { echo "GitHub CLI/auth required" >&2; exit 1; }\n'
        'scratch=$(mktemp -d "${TMPDIR:-/tmp}/kirabridge-release.XXXXXXXX")\n'
        "trap 'rm -rf \"$scratch\"' EXIT\n"
        f"gh release download v{version} -R landjunge/KiraBridge "
        '-p KiraBridge-macos.tar.gz -D "$scratch"\n'
        f"printf '%s  %s\\n' {hashlib.sha256(bundle.read_bytes()).hexdigest()} "
        'KiraBridge-macos.tar.gz > "$scratch/expected.sha256"\n'
        '(cd "$scratch" && shasum -a 256 -c expected.sha256)\n'
        'tar -xzf "$scratch/KiraBridge-macos.tar.gz" -C "$scratch"\n'
        'sh "$scratch/KiraBridge/install.sh" "$@"\n'
    )
    (output / "install-macos.sh.sha256").write_text(
        hashlib.sha256(bootstrap.read_bytes()).hexdigest() + "  install-macos.sh\n"
    )
    # Preserve main's Linux source-install route. macOS uses the guarded updater
    # above; there is no second macOS installer implementation in this build.
    linux_name = f"KiraBridge-{version}-Linux-x86_64"
    linux_files = {
        "payload/" + name: subprocess.check_output(["git", "show", f"{commit}:{name}"])
        for name in git("ls-files").splitlines()
        if name.startswith(("src/", "docs/", "examples/"))
        or name in {"LICENSE", "pyproject.toml", "uv.lock"}
    }
    linux_files.update(
        {
            name.removeprefix("payload/"): data
            for name, data in list(linux_files.items())
            if name.startswith(("payload/docs/", "payload/examples/"))
        }
    )
    linux_files["install.sh"] = (
        Path("scripts/release-install.sh")
        .read_bytes()
        .replace(b"@PLATFORM@", b"Linux-x86_64")
        .replace(b"@SOURCE_SHORT@", commit[:12].encode())
        .replace(b"@SOURCE@", commit.encode())
        .replace(b"@VERSION@", version.encode())
    )
    linux_files["LICENSE"] = Path("LICENSE").read_bytes()
    linux_files["installer/presentation.py"] = files["installer/presentation.py"]
    for language in ("DE", "EN"):
        command = "sh install.sh" + (" --language en" if language == "EN" else "")
        linux_files[f"INSTALL-{language}.md"] = (
            f"# KiraBridge {version} — unapproved candidate\n\n"
            f"[Installation {language}](docs/INSTALL-{language}.md)\n\n"
            f"```sh\n{command}\n```\n\n"
            "Linux installation acceptance is not established by a macOS build.\n"
        ).encode()
    linux_files["RELEASE-NOTES.md"] = Path(f"docs/RELEASE-{version}.md").read_bytes()
    linux_files["release.json"] = (
        json.dumps(
            {
                "version": version,
                "source_commit": commit,
                "platform": "Linux-x86_64",
                **license_fields,
                "presentation": presentation,
                "maturity": "unpublished candidate; Linux package acceptance not performed",
            },
            indent=2,
        )
        + "\n"
    ).encode()
    linux_files["SHA256SUMS"] = "".join(
        hashlib.sha256(data).hexdigest() + "  " + name + "\n"
        for name, data in sorted(linux_files.items())
    ).encode()
    linux_bundle = output / (linux_name + ".tar.gz")
    with (
        linux_bundle.open("xb") as raw,
        gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as gz,
    ):
        with tarfile.open(fileobj=gz, mode="w") as archive:
            for name, data in sorted(linux_files.items()):
                item = tarfile.TarInfo(linux_name + "/" + name)
                item.size, item.mode, item.mtime = (
                    len(data),
                    0o755 if name == "install.sh" else 0o644,
                    0,
                )
                archive.addfile(item, io.BytesIO(data))
    (output / "SHA256SUMS").write_text(
        "".join(
            hashlib.sha256(p.read_bytes()).hexdigest() + "  " + p.name + "\n"
            for p in [bundle, wheel, bootstrap, linux_bundle, output / "LICENSE"]
        )
    )
    print(json.dumps({"version": version, "commit": commit, "bundle": str(bundle)}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    build(parser.parse_args().out.resolve())
