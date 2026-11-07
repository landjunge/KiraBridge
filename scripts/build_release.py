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


def git_blob(commit, name):
    return subprocess.check_output(["git", "show", f"{commit}:{name}"])


def presentation_for(commit):
    mapping = {
        "payload/src/kirabridge/terminal_design.py": "src/kirabridge/terminal_design.py",
        "payload/src/kirabridge/install_ui.py": "src/kirabridge/install_ui.py",
        "installer/presentation.py": "installer/presentation.py",
    }
    return {
        "schema": "kirabridge.installer.presentation.v1",
        "assets": {
            member: hashlib.sha256(git_blob(commit, source)).hexdigest()
            for member, source in mapping.items()
        },
        "palette": "#F06DB0",
        "output": "human-stderr-only",
    }


def server_install_page(version, language):
    english = language == "EN"
    command = "sh install.sh --yes" + (" --language en" if english else "")
    if english:
        text = f"""# KiraBridge {version} — Linux server

User-level systemd service, without sudo. This is not the macOS desktop build
and it is not ThreadDesk Server&Sync.

Verify with `sha256sum -c SHA256SUMS` in the extracted package.

```sh
{command}
```

Service: `systemctl --user restart kirabridge.service`.
Rollback restores the launcher and unit. Configuration, credentials, tasks and
UNKNOWN states stay in place; a database backup is not written back over them.

HTTP MCP, bearer authentication and `bridge_health` are the server surface.
The macOS GUI, Terminal.app and native keyboard are unavailable. Clipboard
tools are optional and are not required. A macOS run is not Linux acceptance.

Details: [INSTALL-LINUX-SERVER.md](docs/INSTALL-LINUX-SERVER.md).
"""
    else:
        text = f"""# KiraBridge {version} — Linux-Server

Benutzerdienst unter systemd, ohne sudo. Das ist nicht die macOS-Desktopfassung
und nicht ThreadDesk Server&Sync.

Prüfung im entpackten Paket: `sha256sum -c SHA256SUMS`.

```sh
{command}
```

Dienst: `systemctl --user restart kirabridge.service`.
Rollback stellt Launcher und Unit wieder her. Konfiguration, Zugangsdaten,
Tasks und UNKNOWN-Zustände bleiben liegen; ein Datenbankbackup wird nicht
darüber zurückgeschrieben.

HTTP-MCP, Bearer-Authentifizierung und `bridge_health` sind der Serverbetrieb.
macOS-GUI, Terminal.app und native Tastatur sind nicht verfügbar. Zwischenablage
ist optional und nicht erforderlich. Ein macOS-Lauf ist kein Linux-Nachweis.

Ausführlich: [INSTALL-LINUX-SERVER.de.md](docs/INSTALL-LINUX-SERVER.de.md).
"""
    return text.encode()


def write_linux_server_bundle(output, commit, version, license_fields, presentation):
    """Source package for an existing Linux host. No native app and no network."""
    linux_name = f"KiraBridge-{version}-Linux-x86_64"
    linux_files = {
        "payload/" + name: git_blob(commit, name)
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
    linux_files["installer/install.py"] = git_blob(commit, "installer/install.py")
    linux_files["installer/presentation.py"] = git_blob(commit, "installer/presentation.py")
    for language in ("DE", "EN"):
        linux_files[f"INSTALL-{language}.md"] = server_install_page(version, language)
    notes = Path(f"docs/RELEASE-{version}.md")
    if notes.is_file():
        linux_files["RELEASE-NOTES.md"] = notes.read_bytes()
    listed = {
        name: hashlib.sha256(data).hexdigest() for name, data in sorted(linux_files.items())
    }
    linux_files["release.json"] = (
        json.dumps(
            {
                "version": version,
                "commit": commit,
                "source_commit": commit,
                "platform": "Linux-x86_64",
                "role": "linux-server",
                "service": "systemd-user",
                "desktop_gui": "unavailable",
                "gui_parity": False,
                **license_fields,
                "presentation": presentation,
                "files": listed,
                "maturity": (
                    "source-pinned Linux server package; "
                    "native host acceptance is recorded separately"
                ),
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
    digest = hashlib.sha256(linux_bundle.read_bytes()).hexdigest()
    (output / (linux_bundle.name + ".sha256")).write_text(
        digest + "  " + linux_bundle.name + "\n"
    )
    return linux_bundle


def build(output, *, target=None):
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
    if target == "linux-server":
        # Explicit server artifact. The default macOS release still returns
        # before any Linux bytes are written.
        presentation = presentation_for(commit)
        bundle = write_linux_server_bundle(
            output, commit, version, license_fields, presentation
        )
        (output / "SHA256SUMS").write_text(
            hashlib.sha256(bundle.read_bytes()).hexdigest()
            + "  "
            + bundle.name
            + "\n"
            + hashlib.sha256(license_bytes).hexdigest()
            + "  LICENSE\n"
        )
        print(json.dumps({"version": version, "commit": commit, "bundle": str(bundle)}, indent=2))
        return
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
    # Build only the host platform. A local macOS release must not manufacture
    # untested Linux assets as a side effect.
    if sys.platform == "darwin":
        (output / "SHA256SUMS").write_text(
            "".join(
                hashlib.sha256(p.read_bytes()).hexdigest() + "  " + p.name + "\n"
                for p in [bundle, wheel, bootstrap, output / "LICENSE"]
            )
        )
        print(json.dumps({"version": version, "commit": commit, "bundle": str(bundle)}, indent=2))
        return
    # Preserve the existing Linux route for builds performed on Linux.
    linux_bundle = write_linux_server_bundle(
        output, commit, version, license_fields, presentation
    )
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
    parser.add_argument("--target", choices=("host", "linux-server"), default="host")
    args = parser.parse_args()
    build(args.out.resolve(), target=None if args.target == "host" else args.target)
