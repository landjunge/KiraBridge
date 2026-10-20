"""Build a pinned, self-contained runtime release without touching a running bridge."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import tomllib
from pathlib import Path


def run(*args, cwd=None, env=None):
    return (
        subprocess.check_output([str(arg) for arg in args], cwd=cwd, env=env, timeout=600)
        .decode()
        .strip()
    )


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(repo, ref, output):
    commit = run("git", "rev-parse", ref + "^{commit}", cwd=repo)
    epoch = int(run("git", "show", "-s", "--format=%ct", commit, cwd=repo))
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="kirabridge-release-") as temp:
        root = Path(temp)
        source = root / "source"
        source.mkdir()
        archive = subprocess.check_output(
            ["git", "archive", "--format=tar", commit], cwd=repo, timeout=60
        )
        with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
            stream.extractall(source, filter="data")
        project = tomllib.loads((source / "pyproject.toml").read_text())
        version = project["project"]["version"]
        if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:rc[0-9]+)?", version):
            raise RuntimeError("Unsupported release version")
        if f'__version__ = "{version}"' not in (source / "src/kirabridge/__init__.py").read_text():
            raise RuntimeError("Runtime version differs from project version")
        lock = tomllib.loads((source / "uv.lock").read_text())
        own = [p for p in lock["package"] if p["name"] == "kirabridge"]
        if len(own) != 1 or own[0]["version"] != version:
            raise RuntimeError("Frozen dependency lock version differs")
        package = root / f"KiraBridge-{version}-runtime"
        package.mkdir()

        # Include exactly the committed tree, with no repository history or local files.
        run("git", "init", "-q", "-b", "release", cwd=source)
        run("git", "add", "--force", "--all", cwd=source)
        tree = run("git", "write-tree", cwd=source)
        if tree != run("git", "rev-parse", commit + "^{tree}", cwd=repo):
            raise RuntimeError("Exported source tree differs from pinned commit")
        raw_commit = subprocess.check_output(["git", "cat-file", "commit", commit], cwd=repo)
        imported = (
            subprocess.check_output(
                ["git", "hash-object", "-w", "-t", "commit", "--stdin"],
                cwd=source,
                input=raw_commit,
            )
            .decode()
            .strip()
        )
        if imported != commit:
            raise RuntimeError("Commit identity differs")
        run("git", "update-ref", "refs/heads/release", commit, cwd=source)
        (source / ".git/shallow").write_text(commit + "\n")
        run("git", "bundle", "create", package / "source.bundle", "refs/heads/release", cwd=source)
        env = dict(os.environ, SOURCE_DATE_EPOCH=str(epoch))
        run("uv", "build", "--project", source, "--out-dir", package, env=env)
        shutil.copy2(source / "installer/install-release.py", package / "install.py")
        shutil.copy2(source / "docs/RELEASE-0.8.0rc12.md", package / "README.md")
        shutil.copy2(source / "LICENSE", package / "LICENSE")
        files = {p.name: digest(p) for p in sorted(package.iterdir()) if p.is_file()}
        info = {
            "schema_version": 1,
            "version": version,
            "source_commit": commit,
            "source_tree": tree,
            "source_date_epoch": epoch,
            "dependency_lock_sha256": digest(source / "uv.lock"),
            "files": files,
            "scope": "Python runtime and managed installer; no prebuilt native companion",
        }
        (package / "BUILD-INFO.json").write_text(json.dumps(info, indent=2) + "\n")
        sums = "".join(f"{digest(p)}  {p.name}\n" for p in sorted(package.iterdir()) if p.is_file())
        (package / "SHA256SUMS").write_text(sums)
        target = output / (package.name + ".tar.gz")
        with (
            target.open("wb") as raw,
            gzip.GzipFile(fileobj=raw, mode="wb", mtime=epoch, filename="") as gz,
        ):
            with tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar:
                for path in sorted(package.rglob("*")):
                    entry = tar.gettarinfo(str(path), arcname=package.name + "/" + path.name)
                    entry.uid = entry.gid = 0
                    entry.uname = entry.gname = ""
                    entry.mtime = epoch
                    entry.mode = 0o644
                    with path.open("rb") as data:
                        tar.addfile(entry, data)
        for path in package.iterdir():
            if (
                path.suffix == ".whl"
                or path.name in {"BUILD-INFO.json", "README.md"}
                or path.name.startswith("kirabridge-")
            ):
                shutil.copy2(path, output / path.name)
        assets = [
            target,
            *sorted(output.glob("kirabridge-*")),
            output / "BUILD-INFO.json",
            output / "README.md",
        ]
        (output / "SHA256SUMS").write_text("".join(f"{digest(p)}  {p.name}\n" for p in assets))
        print(
            json.dumps(
                {
                    "version": version,
                    "commit": commit,
                    "archive": str(target),
                    "sha256": digest(target),
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", default="HEAD")
    parser.add_argument("--output", type=Path, default=Path("dist/release"))
    args = parser.parse_args()
    build(Path(__file__).resolve().parents[1], args.ref, args.output.absolute())
