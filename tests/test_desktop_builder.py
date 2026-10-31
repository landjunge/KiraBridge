"""Companion builds preserve installed apps and identify the compiled source."""

import hashlib
import importlib.util
import plistlib
from pathlib import Path

import pytest


@pytest.fixture
def builder(monkeypatch):
    source = Path(__file__).resolve().parents[1] / "scripts/build_desktop_app.py"
    spec = importlib.util.spec_from_file_location("kirabridge_desktop_builder_tests", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.sys, "platform", "darwin")
    return module


@pytest.mark.parametrize("symlink", [False, True])
def test_existing_app_never_reaches_build_tools(tmp_path, builder, monkeypatch, symlink):
    old = tmp_path / "old.app"
    old.mkdir()
    (old / "user-file").write_bytes(b"previous signed application")
    destination = tmp_path / "candidate.app" if symlink else old
    if symlink:
        destination.symlink_to(old, target_is_directory=True)

    def unexpected(*args, **kwargs):
        pytest.fail("Existing destination must be rejected before invoking build tools")

    monkeypatch.setattr(builder.subprocess, "check_output", unexpected)
    monkeypatch.setattr(builder.subprocess, "run", unexpected)
    with pytest.raises(RuntimeError, match="existing installations are preserved"):
        builder.build(destination)
    assert (old / "user-file").read_bytes() == b"previous signed application"


def test_dirty_checkout_rejected_before_creating_app(tmp_path, builder, monkeypatch):
    monkeypatch.setattr(builder.subprocess, "check_output", lambda *a, **kw: " M source.py\n")
    destination = tmp_path / "candidate.app"
    with pytest.raises(RuntimeError, match="Commit all source changes"):
        builder.build(destination)
    assert not destination.exists()


def test_companion_metadata_binds_release_and_source(tmp_path, builder, monkeypatch):
    root = tmp_path / "repository"
    (root / "scripts").mkdir(parents=True)
    (root / "integrations/desktop").mkdir(parents=True)
    sources = [
        root / "integrations/desktop" / name
        for name in (
            "main.swift",
            "SystemBridge.swift",
            "SystemControl.swift",
            "SystemServices.swift",
        )
    ]
    for source in sources:
        source.write_text("// isolated fixture: " + source.name + "\n")
    (root / "pyproject.toml").write_text('[project]\nversion = "0.8.0rc18"\n')
    monkeypatch.setattr(builder, "__file__", str(root / "scripts/build_desktop_app.py"))
    commit = "1" * 40
    monkeypatch.setattr(
        builder.subprocess,
        "check_output",
        lambda args, **kw: "" if "status" in args else commit + "\n",
    )
    calls = []

    def compile_or_sign(argv, **kwargs):
        calls.append(argv)
        if "swiftc" in argv:
            Path(argv[-1]).write_bytes(b"compiled-fixture")

    monkeypatch.setattr(builder.subprocess, "run", compile_or_sign)
    destination = tmp_path / "candidate.app"
    assert builder.build(destination) == str(destination)
    info = plistlib.loads((destination / "Contents/Info.plist").read_bytes())
    assert info["CFBundleShortVersionString"] == "0.8.0"
    assert info["KiraBridgeVersion"] == "0.8.0rc18"
    assert info["KiraBridgeSourceCommit"] == commit
    assert (
        info["KiraBridgeCompanionSourceSHA256"]
        == hashlib.sha256(
            b"".join(source.name.encode() + b"\0" + source.read_bytes() for source in sources)
        ).hexdigest()
    )
    assert info["KiraBridgeSystemProtocol"] == 1
    assert calls[0][-6:] == [
        *map(str, sources),
        "-o",
        str(destination / "Contents/MacOS/KiraBridge"),
    ]
    assert calls[1] == ["/usr/bin/codesign", "--force", "--sign", "-", str(destination)]
    assert calls[2] == ["/usr/bin/codesign", "--verify", "--deep", "--strict", str(destination)]
