"""Standalone entry point lifecycle, launcher switching and immutable payload checks."""

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts/windows_standalone.py"
spec = importlib.util.spec_from_file_location("windows_standalone", SCRIPT)
manager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manager)


def payload(path, version):
    (path / "runtime").mkdir(parents=True)
    (path / "runtime/python.exe").write_bytes(b"MZ-python")
    (path / "runtime/python314.dll").write_bytes(b"MZ-dll")
    (path / "src").mkdir()
    (path / "src/source.py").write_text(version)
    files = {
        p.relative_to(path).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in path.rglob("*")
        if p.is_file()
    }
    (path / "provenance.json").write_text(
        json.dumps({"version": version, "commit": "a" * 40, "files": files})
    )
    return path


def invoke(monkeypatch, root, source, action):
    monkeypatch.setattr(manager, "PAYLOAD", source)
    monkeypatch.setattr(sys, "argv", ["manager", "--root", str(root), action])
    return manager.main()


def test_installed_launcher_tracks_update_rollback_and_data(tmp_path, monkeypatch):
    root = tmp_path / "installation with spaces"
    first = payload(tmp_path / "first", "1.0")
    second = payload(tmp_path / "second", "2.0")
    invoke(monkeypatch, root, first, "install")
    data = root / "data/user.db"
    data.write_bytes(b"original")
    initial = (root / "KiraBridge.cmd").read_bytes()
    assert initial.endswith(b"%* & exit /b\r\n")
    invoke(monkeypatch, root, second, "update")
    assert initial != (root / "KiraBridge.cmd").read_bytes()
    data.write_bytes(b"newer user data")
    invoke(monkeypatch, root, second, "rollback")
    assert initial == (root / "KiraBridge.cmd").read_bytes()
    assert data.read_bytes() == b"newer user data"
    invoke(monkeypatch, root, second, "uninstall")
    assert data.read_bytes() == b"newer user data"
    assert not (root / "current.json").exists()
    assert not (root / "KiraBridge.cmd").exists()
    assert list((root / "releases").iterdir()) == []


def test_modified_payload_never_installs(tmp_path, monkeypatch):
    source = payload(tmp_path / "source", "1.0")
    (source / "src/source.py").write_text("tampered")
    root = tmp_path / "install"
    with pytest.raises(manager.PackageError, match="provenance"):
        invoke(monkeypatch, root, source, "install")
    assert not (root / "current.json").exists()


def test_installed_runtime_cannot_delete_itself(tmp_path, monkeypatch):
    root = tmp_path / "install"
    source = payload(tmp_path / "source", "1.0")
    invoke(monkeypatch, root, source, "install")
    current = manager.status(root)["current"]["release"]
    installed = root / "releases" / current
    with pytest.raises(manager.PackageError, match="extracted package"):
        invoke(monkeypatch, root, installed, "uninstall")
    assert (installed / "runtime/python.exe").exists()
    assert manager.status(root)["installed"]


@pytest.mark.parametrize("application_args", [["--help"], ["setup", "--help"]])
def test_run_forwards_application_help_and_propagates_no_bytecode(
    tmp_path, monkeypatch, application_args
):
    root = tmp_path / "install"
    source = payload(tmp_path / "source", "1.0")
    invoke(monkeypatch, root, source, "install")
    calls = []
    monkeypatch.setattr(manager.subprocess, "call", lambda argv: calls.append(argv) or 0)
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "")
    monkeypatch.setattr(manager, "PAYLOAD", source)
    monkeypatch.setattr(sys, "argv", ["manager", "--root", str(root), "run", *application_args])
    assert manager.main() == 0
    assert calls[0][-len(application_args) :] == application_args
    assert manager.os.environ["PYTHONDONTWRITEBYTECODE"] == "1"
