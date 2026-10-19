"""Build private release-candidate bundles from an exact, clean Git source pin."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import subprocess
import tarfile
from pathlib import Path

PLATFORMS = ("Darwin-x86_64", "Darwin-arm64", "Linux-x86_64")


def git(*args):
    return subprocess.check_output(["git", *args], text=True).strip()


def build(destination: Path):
    if destination.is_symlink() or (destination.exists() and any(destination.iterdir())):
        raise SystemExit(
            "Use a new empty output directory; existing release artifacts are preserved"
        )
    if git("status", "--porcelain", "--untracked-files=normal"):
        raise SystemExit("Commit the source first; release builds require a clean worktree")
    commit, version = git("rev-parse", "HEAD"), __import__("kirabridge").__version__
    destination.mkdir(parents=True, exist_ok=True)
    files = {
        name: subprocess.check_output(["git", "show", f"{commit}:{name}"])
        for name in git("ls-files").splitlines()
        if name.startswith(("src/", "docs/", "examples/"))
        or name in {"LICENSE", "pyproject.toml", "uv.lock"}
    }
    subprocess.run(
        ["uv", "build", "--out-dir", str(destination)],
        check=True,
        env=dict(os.environ, SOURCE_DATE_EPOCH=git("show", "-s", "--format=%ct", commit)),
    )
    for target in PLATFORMS:
        prefix = f"KiraBridge-{version}-{target}"
        contents = {"payload/" + name: data for name, data in files.items()}
        contents.update(
            {name: data for name, data in files.items() if name.startswith(("docs/", "examples/"))}
        )
        contents["LICENSE"] = files["LICENSE"]
        contents["install.sh"] = (
            Path("scripts/release-install.sh")
            .read_bytes()
            .replace(b"@PLATFORM@", target.encode())
            .replace(b"@SOURCE_SHORT@", commit[:12].encode())
            .replace(b"@SOURCE@", commit.encode())
            .replace(b"@VERSION@", version.encode())
        )
        for language in ("DE", "EN"):
            command = "sh install.sh" + (" --language en" if language == "EN" else "")
            contents[f"INSTALL-{language}.md"] = (
                f"# KiraBridge {version}\n\n"
                f"[Installation {language}](docs/INSTALL-{language}.md)\n\n"
                f"```sh\n{command}\n```\n\n[Team](docs/TEAM-ORCHESTRATION.md)\n\n"
                "[Grok App / Eve](docs/GROK-APP-CONNECTOR.md)\n"
            ).encode()
        contents["RELEASE-NOTES.md"] = (
            Path(f"docs/RELEASE-NOTES-{version}.md")
            .read_bytes()
            .replace(b"(providers/README.md)", b"(docs/providers/README.md)")
            .replace(b"(GROK-APP-CONNECTOR.md)", b"(docs/GROK-APP-CONNECTOR.md)")
            .replace(b"(evidence/", b"(docs/evidence/")
        )
        contents["TEAM-ORCHESTRATION.md"] = (
            b"# Team\n\n[Anleitung / Guide](docs/TEAM-ORCHESTRATION.md)\n"
        )
        contents["release.json"] = (
            json.dumps(
                {
                    "name": "KiraBridge",
                    "version": version,
                    "source_commit": commit,
                    "platform": target,
                    "maturity": "release candidate",
                    "license": "LicenseRef-Netzwerkpunkt-Personal-Use-1.0",
                    "license_sha256": hashlib.sha256(files["LICENSE"]).hexdigest(),
                    "distribution": "private preparation; no public release approval",
                    "python": "3.11.15",
                    "uv": "0.11.6",
                    "network_install": True,
                    "reproducibility": "bundle members normalized; dependency hashes in uv.lock; "
                    "remote Python runtime not bundled",
                },
                indent=2,
            )
            + "\n"
        ).encode()
        contents["SHA256SUMS"] = "".join(
            hashlib.sha256(data).hexdigest() + "  " + name + "\n"
            for name, data in sorted(contents.items())
        ).encode()
        path = destination / (prefix + ".tar.gz")
        with (
            path.open("xb") as raw,
            gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as gz,
        ):
            with tarfile.open(fileobj=gz, mode="w") as archive:
                for name, data in sorted(contents.items()):
                    item = tarfile.TarInfo(prefix + "/" + name)
                    item.size, item.mode, item.mtime = (
                        len(data),
                        0o755 if name == "install.sh" else 0o644,
                        0,
                    )
                    archive.addfile(item, io.BytesIO(data))
    (destination / "LICENSE").write_bytes(files["LICENSE"])
    outputs = sorted(
        p
        for p in destination.iterdir()
        if p.is_file() and (p.name == "LICENSE" or p.name.endswith(".tar.gz") or p.suffix == ".whl")
    )
    (destination / "SHA256SUMS").write_text(
        "".join(hashlib.sha256(p.read_bytes()).hexdigest() + "  " + p.name + "\n" for p in outputs)
    )
    print(
        json.dumps(
            {"version": version, "source_commit": commit, "artifacts": [str(p) for p in outputs]},
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    build(parser.parse_args().out.absolute())
