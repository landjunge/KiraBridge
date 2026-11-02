"""Build deterministic macOS source/wheel bundle from a clean exact Git commit."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import io
import json
import os
import platform
import plistlib
import stat
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from pathlib import Path


def git(*args):
    return subprocess.check_output(["git", *args], text=True).strip()


def build_native_app(destination):
    """Use the existing companion builder, never a second compilation/signing path."""
    source = Path(__file__).with_name("build_desktop_app.py")
    spec = importlib.util.spec_from_file_location("_kirabridge_companion_builder", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return Path(module.build(destination))


def native_payload(output, commit, version):
    """Capture exact signed app bytes and modes without retaining a mutable source app."""
    with tempfile.TemporaryDirectory(prefix=".native-build-", dir=output) as temporary:
        requested = Path(temporary) / "KiraBridge.app"
        app = build_native_app(requested)
        if app.is_symlink() or app.resolve() != requested.resolve() or not app.is_dir():
            raise RuntimeError("Companion builder returned an unexpected destination")
        subprocess.run(
            ["/usr/bin/codesign", "--verify", "--strict", str(app)],
            check=True,
            capture_output=True,
            timeout=30,
        )
        architecture = (
            subprocess.check_output(
                ["/usr/bin/lipo", "-archs", str(app / "Contents/MacOS/KiraBridge")], timeout=15
            )
            .decode("ascii")
            .split()
        )
        if architecture != [platform.machine()] or architecture[0] not in {"x86_64", "arm64"}:
            raise RuntimeError("Native app CPU architecture differs from build host")
        metadata = plistlib.loads((app / "Contents/Info.plist").read_bytes())
        if (
            metadata.get("CFBundleIdentifier") != "de.netzwerkpunkt.kirabridge"
            or metadata.get("CFBundleExecutable") != "KiraBridge"
            or metadata.get("KiraBridgeSourceCommit") != commit
            or metadata.get("KiraBridgeVersion") != version
            or type(metadata.get("KiraBridgeSystemProtocol")) is not int
            or metadata.get("KiraBridgeSystemProtocol") != 1
        ):
            raise RuntimeError("Built companion identity differs from release")
        files, modes, total = {}, {}, 0
        for path in sorted(app.rglob("*")):
            if path.is_symlink():
                raise RuntimeError("Native app symlinks are not supported")
            if path.is_dir():
                continue
            info = path.stat()
            mode = stat.S_IMODE(info.st_mode)
            if not stat.S_ISREG(info.st_mode) or mode not in {0o644, 0o755}:
                raise RuntimeError("Unsafe native app file type or mode")
            if info.st_size > 32 * 1024 * 1024 or len(files) >= 1000:
                raise RuntimeError("Native app exceeds package limits")
            data = path.read_bytes()
            total += len(data)
            if total > 64 * 1024 * 1024:
                raise RuntimeError("Native app exceeds package limits")
            member = "native/KiraBridge.app/" + path.relative_to(app).as_posix()
            files[member], modes[member] = data, mode
        binary = "native/KiraBridge.app/Contents/MacOS/KiraBridge"
        required = {
            binary,
            "native/KiraBridge.app/Contents/Info.plist",
            "native/KiraBridge.app/Contents/_CodeSignature/CodeResources",
        }
        if not required.issubset(files) or modes[binary] != 0o755:
            raise RuntimeError("Signed native app files are incomplete")
        return (
            files,
            modes,
            {
                "schema": "kirabridge.native-app.v1",
                "path": "native/KiraBridge.app",
                "protocol": 1,
                "source_commit": commit,
                "binary_sha256": hashlib.sha256(files[binary]).hexdigest(),
                "signing": "ad-hoc",
                "architecture": architecture[0],
            },
        )


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
    file_modes, native_app = {}, None
    if sys.platform == "darwin":
        native_files, file_modes, native_app = native_payload(output, commit, version)
        files.update(native_files)
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
        "installer/desktop.py",
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
        "platforms": ["Darwin-" + platform.machine()],
        "wheel": "wheel/" + wheel.name,
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())},
        "native_app_required": True,
        "presentation": presentation,
        "runtime": "Python 3.11, uv 0.11.6; dependencies from hash-locked uv.lock",
        "apple_signed": False,
        "maturity": "source-pinned artifact; acceptance and publication recorded separately",
    }
    if native_app is not None:
        manifest.update(native_app=native_app, file_modes=file_modes)
    files["release.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    bundle = bootstrap = None
    if sys.platform == "darwin":
        bundle = output / "KiraBridge-macos.tar.gz"
        with (
            bundle.open("xb") as raw,
            gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as gz,
        ):
            with tarfile.open(fileobj=gz, mode="w") as archive:
                for name, data in sorted(files.items()):
                    item = tarfile.TarInfo("KiraBridge/" + name)
                    item.size, item.mode, item.mtime = len(data), file_modes.get(name, 0o644), 0
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
            'tar -xpzf "$scratch/KiraBridge-macos.tar.gz" -C "$scratch"\n'
            'sh "$scratch/KiraBridge/install.sh" "$@"\n'
        )
        (output / "install-macos.sh.sha256").write_text(
            hashlib.sha256(bootstrap.read_bytes()).hexdigest() + "  install-macos.sh\n"
        )
    else:
        (output / (wheel.name + ".sha256")).write_text(
            hashlib.sha256(wheel.read_bytes()).hexdigest() + "  " + wheel.name + "\n"
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
            if p is not None
        )
    )
    print(
        json.dumps(
            {"version": version, "commit": commit, "bundle": str(bundle) if bundle else None},
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    build(parser.parse_args().out.resolve())
