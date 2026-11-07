"""Pinned exports replace a development runtime's stale application imports."""

import hashlib
import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts/build_windows_standalone.py"
spec = importlib.util.spec_from_file_location("standalone_builder", SCRIPT)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def test_export_build_replaces_old_source_and_records_every_byte(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    site = runtime / "Lib/site-packages"
    (site / "kirabridge").mkdir(parents=True)
    (site / "kirabridge/__init__.py").write_text("OLD_APPLICATION")
    (site / "kirabridge-old.dist-info").mkdir()
    (site / "kirabridge-old.dist-info/METADATA").write_text("old")
    (site / "dependency.py").write_text("retained")
    (runtime / "python.exe").write_bytes(b"MZ-python")
    (runtime / "python314.dll").write_bytes(b"MZ-dll")
    export = tmp_path / "source.zip"
    with zipfile.ZipFile(export, "w") as archive:
        archive.writestr("src/kirabridge/__init__.py", "CURRENT_APPLICATION")
        archive.writestr("scripts/windows_standalone.py", "CURRENT_ENTRY")
    expected = hashlib.sha256(export.read_bytes()).hexdigest()

    def no_git(*args, **kwargs):
        pytest.fail("A validated native export must not call git")

    monkeypatch.setattr(builder.subprocess, "check_output", no_git)
    output = tmp_path / "standalone.zip"
    result = builder.build(runtime, output, "1.0", export, expected, "a" * 40)
    assert result["sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        assert "runtime/Lib/site-packages/kirabridge/__init__.py" not in names
        assert "runtime/Lib/site-packages/kirabridge-old.dist-info/METADATA" not in names
        assert archive.read("runtime/Lib/site-packages/dependency.py") == b"retained"
        assert archive.read("runtime/Lib/site-packages/kirabridge-source.pth") == b"../../../src\n"
        assert b"%LOCALAPPDATA%\\KiraBridge" in archive.read("Install.cmd")
        assert b"pause" not in archive.read("Install.cmd")
        document = json.loads(archive.read("provenance.json"))
        assert document["source_archive_sha256"] == expected
        assert document["files"] == {
            name: hashlib.sha256(archive.read(name)).hexdigest()
            for name in names
            if name != "provenance.json"
        }
    assert (site / "kirabridge/__init__.py").read_text() == "OLD_APPLICATION"


def test_native_export_hash_mismatch_produces_no_package(tmp_path):
    export = tmp_path / "source.zip"
    export.write_bytes(b"not the pinned source")
    output = tmp_path / "standalone.zip"
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        builder.build(tmp_path / "runtime", output, "1.0", export, "0" * 64, "a" * 40)
    assert not output.exists()


@pytest.mark.parametrize("from_export,override", [(True, None), (False, None), (True, "explicit")])
def test_default_version_comes_from_selected_source_not_checkout(
    tmp_path, monkeypatch, from_export, override
):
    runtime = tmp_path / "runtime"
    (runtime / "Lib/site-packages").mkdir(parents=True)
    (runtime / "python.exe").write_bytes(b"MZ-python")
    (runtime / "python314.dll").write_bytes(b"MZ-dll")
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "pyproject.toml").write_text('[project]\nversion = "dirty-checkout-version"\n')
    monkeypatch.setattr(builder, "ROOT", checkout)
    source = tmp_path / "selected.zip"
    metadata = b'[project]\nversion = "0.7.0.export"\n'
    with zipfile.ZipFile(source, "w") as zipped:
        zipped.writestr("pyproject.toml", metadata)
    raw = source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()

    def selected_git(args, **kwargs):
        assert not from_export, "A verified export must not consult the builder checkout"
        if args == ["git", "rev-parse", "HEAD"]:
            return "a" * 40
        assert args[:3] == ["git", "archive", "--format=zip"]
        return raw

    monkeypatch.setattr(builder.subprocess, "check_output", selected_git)
    output = tmp_path / "package.zip"
    result = builder.build(
        runtime,
        output,
        override,
        source if from_export else None,
        digest if from_export else None,
        "a" * 40 if from_export else None,
    )
    expected = override or "0.7.0.export"
    assert result["version"] == expected
    with zipfile.ZipFile(output) as zipped:
        provenance = json.loads(zipped.read("provenance.json"))
        assert provenance["version"] == expected
        assert provenance["source_archive_sha256"] == digest
        assert zipped.read("pyproject.toml") == metadata
