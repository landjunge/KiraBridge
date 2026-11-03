"""The native installer cannot wrap a wrong, incomplete or escaping release."""

import hashlib
import importlib.util
import io
import json
import plistlib
import tarfile
from pathlib import Path

import pytest

COMMIT = "a" * 40
VERSION = "0.8.0rc25"


@pytest.fixture
def builder():
    path = Path(__file__).parents[1] / "scripts/build_installer_app.py"
    spec = importlib.util.spec_from_file_location("installer_app_test", path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def package(path, *, extra=None, mutate=None):
    binary = "native/KiraBridge.app/Contents/MacOS/KiraBridge"
    files = {
        "installer/install.py": b"existing installer",
        "installer/visible_terminal.py": b"existing visibility guard",
        "install.sh": b"#!/bin/sh\nexit 0\n",
        binary: b"exact native executable",
        "native/KiraBridge.app/Contents/Info.plist": plistlib.dumps(
            {
                "KiraBridgeSourceCommit": COMMIT,
                "KiraBridgeVersion": VERSION,
                "CFBundleExecutable": "KiraBridge",
                "CFBundleIdentifier": "de.netzwerkpunkt.kirabridge",
            }
        ),
    }
    manifest = {
        "commit": COMMIT,
        "source_commit": COMMIT,
        "version": VERSION,
        "platforms": ["Darwin-x86_64"],
        "native_app_required": True,
        "native_app": {
            "source_commit": COMMIT,
            "architecture": "x86_64",
            "binary_sha256": hashlib.sha256(files[binary]).hexdigest(),
        },
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
    }
    files["release.json"] = json.dumps(manifest).encode()
    if mutate:
        mutate(files)
    with tarfile.open(path, "w:gz") as archive:
        for name, data in files.items():
            member = tarfile.TarInfo("KiraBridge/" + name)
            member.mode = 0o755 if name == binary else 0o644
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
        if extra:
            archive.addfile(extra, io.BytesIO(b"x") if extra.isfile() else None)
    return files


def test_exact_complete_release_is_accepted_without_installing(tmp_path, builder):
    archive = tmp_path / "runtime.tar.gz"
    expected = package(archive)
    files, modes = builder.release_files(archive, COMMIT, VERSION, "x86_64")
    assert files == expected
    assert modes["native/KiraBridge.app/Contents/MacOS/KiraBridge"] == 0o755
    assert list(tmp_path.iterdir()) == [archive]


def test_corrupt_member_is_refused_before_creation(tmp_path, builder):
    archive = tmp_path / "runtime.tar.gz"
    package(archive, mutate=lambda files: files.update({"installer/install.py": b"altered"}))
    with pytest.raises(RuntimeError, match="checksum"):
        builder.release_files(archive, COMMIT, VERSION, "x86_64")


@pytest.mark.parametrize(
    "commit,version,architecture",
    [
        ("b" * 40, VERSION, "x86_64"),
        (COMMIT, "0.8.0rc24", "x86_64"),
        (COMMIT, VERSION, "arm64"),
    ],
)
def test_wrong_source_version_or_cpu_is_refused(tmp_path, builder, commit, version, architecture):
    archive = tmp_path / "runtime.tar.gz"
    package(archive)
    with pytest.raises(RuntimeError, match="identity"):
        builder.release_files(archive, commit, version, architecture)


@pytest.mark.parametrize("kind", ["escape", "symlink", "duplicate", "extra", "directory"])
def test_unlisted_unsafe_or_duplicate_members_are_refused(tmp_path, builder, kind):
    archive = tmp_path / "runtime.tar.gz"
    name = {
        "escape": "KiraBridge/../escaped",
        "symlink": "KiraBridge/link",
        "duplicate": "KiraBridge/install.sh",
        "extra": "KiraBridge/unlisted",
        "directory": "KiraBridge/directory",
    }[kind]
    member = tarfile.TarInfo(name)
    member.mode = 0o644
    member.size = 1
    if kind == "symlink":
        member.type, member.linkname, member.size = tarfile.SYMTYPE, "/outside", 0
    elif kind == "directory":
        member.type, member.size = tarfile.DIRTYPE, 0
    package(archive, extra=member)
    with pytest.raises(RuntimeError, match="Unsafe|unsafe|Duplicate|inventory"):
        builder.release_files(archive, COMMIT, VERSION, "x86_64")
    assert not (tmp_path / "escaped").exists()


def test_existing_destination_preserved_without_running_tools(tmp_path, builder, monkeypatch):
    destination = tmp_path / "installer.app"
    destination.mkdir()
    keep = destination / "keep"
    keep.write_bytes(b"previous installer")
    monkeypatch.setattr(builder.subprocess, "check_output", lambda *a, **k: pytest.fail("tool ran"))
    with pytest.raises(RuntimeError, match="preserved"):
        builder.build(destination, tmp_path / "missing.tar.gz")
    assert keep.read_bytes() == b"previous installer"


def test_native_companion_metadata_must_match_signed_release(tmp_path, builder):
    archive = tmp_path / "runtime.tar.gz"

    def mutate(files):
        name = "native/KiraBridge.app/Contents/Info.plist"
        metadata = plistlib.loads(files[name])
        metadata["KiraBridgeSourceCommit"] = "b" * 40
        files[name] = plistlib.dumps(metadata)
        manifest = json.loads(files["release.json"])
        manifest["files"][name] = hashlib.sha256(files[name]).hexdigest()
        files["release.json"] = json.dumps(manifest).encode()

    package(archive, mutate=mutate)
    with pytest.raises(RuntimeError, match="Native app identity"):
        builder.release_files(archive, COMMIT, VERSION, "x86_64")
