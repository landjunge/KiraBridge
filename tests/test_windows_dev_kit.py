"""Archive/receipt guards only: synthetic fixtures never prove native Windows."""

import importlib.util
import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "build_windows_dev_kit", Path(__file__).parents[1] / "scripts/build_windows_dev_kit.py"
)
kit = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = kit
spec.loader.exec_module(kit)
PIN = "b96f5c79f1df92d6dcba36df6c6fe7fd9712ff61"
RUN_ID = "a" * 32


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    stage, reports = tmp_path / "stage", tmp_path / "reports"
    stage.mkdir()
    reports.mkdir()
    source = io.BytesIO()
    with zipfile.ZipFile(source, "w") as output:
        output.comment = PIN.encode()
        output.writestr("LICENSE", "Fixture license")
        for name in kit.DOCS:
            output.writestr(name, "Fixture public documentation")
    files = {
        "source.zip": source.getvalue(),
        "python-installer.exe": b"NOT A REAL INSTALLER: unit guard fixture",
        "guest_runner.ps1": b"# Fake fixture, never executed",
    }
    requirements = []
    for package in ["kirabridge", *[f"fixture{i}" for i in range(37)]]:
        version = kit.VERSION if package == "kirabridge" else "1.0"
        wheel = io.BytesIO()
        with zipfile.ZipFile(wheel, "w") as output:
            output.writestr(
                f"{package}-{version}.dist-info/METADATA",
                f"Metadata-Version: 2.1\nName: {package}\nVersion: {version}\n",
            )
        files[f"wheels/{package}-{version}-py3-none-any.whl"] = wheel.getvalue()
        requirements.append(f"{package}=={version}")
    entries = []
    for name, body in files.items():
        path = stage / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(body)
        entries.append({"path": name, "sha256": kit.digest(body), "bytes": len(body)})
    manifest = {
        "schema_version": 1,
        "python_version": "3.14.10",
        "source_commit": PIN,
        "requirements": requirements,
        "files": entries,
    }
    raw = json.dumps(manifest).encode()
    (stage / "manifest.json").write_bytes(raw)
    manifest_hash = kit.digest(raw)
    for phase in kit.PHASES:
        report = {
            "phase": phase,
            "manifest_sha256": manifest_hash,
            "exit_code": 0,
            "process_id": 1234,
        }
        if phase == "core":
            report["stdout"] = ".... [100%]\n4 passed in 0.10s\n"
        else:
            report["artifact"] = {
                "passed": True,
                "platform": "nt",
                "independent_original_process_absent": True,
                "owned_process": {
                    "pid": 1234,
                    "created_100ns": 123456789000,
                    "exe": "C:\\Users\\Kiradev\\private\\python.exe",
                },
                "token": "never-package-this-secret",
                "password": "never-package-password",
                "endpoint": "http://10.0.2.2:8123/private-capability",
            }
        (reports / f"report-{RUN_ID}-{phase}.json").write_text(json.dumps(report))
    # Unit fixtures deliberately override the vendor reference. Production CLI
    # has only the real Python.org digest and cannot accept this fake installer.
    monkeypatch.setitem(kit.PYTHON_INSTALLERS, "3.14.10", kit.digest(files["python-installer.exe"]))
    return stage, reports


def modify_report(fixture, phase, fn):
    path = fixture[1] / f"report-{RUN_ID}-{phase}.json"
    report = json.loads(path.read_text())
    fn(report)
    path.write_text(json.dumps(report))


def test_missing_native_phase_blocks_before_any_archive(fixture, tmp_path):
    (fixture[1] / f"report-{RUN_ID}-preview.json").unlink()
    with pytest.raises(ValueError, match="four phases"):
        kit.prepare(*fixture, PIN)
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize(
    "change",
    [
        lambda r: r.update(exit_code=1),
        lambda r: r.update(status="unknown_or_failed_no_retry"),
        lambda r: r.update(manifest_sha256="f" * 64),
        lambda r: r["artifact"].update(passed=False),
        lambda r: r["artifact"].update(platform="posix"),
    ],
)
def test_failed_unknown_foreign_or_nonwindows_reports_block(fixture, change):
    modify_report(fixture, "keyboard", change)
    with pytest.raises(ValueError):
        kit.prepare(*fixture, PIN)


def test_four_skips_are_not_native_core_acceptance(fixture):
    modify_report(fixture, "core", lambda r: r.update(stdout="4 skipped in 0.01s"))
    with pytest.raises(ValueError, match="actually passed"):
        kit.prepare(*fixture, PIN)


def test_mixed_run_ids_are_not_one_acceptance(fixture):
    path = fixture[1] / f"report-{RUN_ID}-preview.json"
    path.rename(fixture[1] / ("report-" + "b" * 32 + "-preview.json"))
    with pytest.raises(ValueError, match="one native guest run"):
        kit.prepare(*fixture, PIN)


def test_modified_staged_payload_or_symlink_blocks(fixture, tmp_path):
    path = fixture[0] / "guest_runner.ps1"
    path.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="differs"):
        kit.prepare(*fixture, PIN)
    target = tmp_path / "secret"
    target.write_bytes(b"secret")
    path.unlink()
    path.symlink_to(target)
    with pytest.raises(ValueError, match="Symlink"):
        kit.prepare(*fixture, PIN)


def test_archive_is_deterministic_and_contains_only_allowed_payloads_and_public_proof(
    fixture, tmp_path
):
    # Extra staging files are not copied merely because they exist.
    (fixture[0] / "host-token").write_text("do-not-leak")
    (fixture[0] / "Windows.iso").write_bytes(b"not a payload")
    contents, package = kit.prepare(*fixture, PIN)
    assert package["offline_wheels"] == 38
    first = kit.build(contents, package, tmp_path / "out1")
    second = kit.build(contents, package, tmp_path / "out2")
    assert first["asset_sha256"] == second["asset_sha256"]
    with zipfile.ZipFile(first["asset"]) as archive:
        names = archive.namelist()
        assert not any("host-token" in name or name.endswith("Windows.iso") for name in names)
        evidence = archive.read("KiraBridge-Windows-Dev-Kit/native-acceptance.json")
        assert b"never-package" not in evidence and b"C:" not in evidence
        assert b"10.0.2.2" not in evidence
        proof = json.loads(evidence)
        keyboard = next(r for r in proof["phases"] if r["phase"] == "keyboard")
        assert keyboard["artifact"]["owned_process"]["created_100ns"] == 123456789000
        assert keyboard["artifact"]["owned_process"]["pid"] == 1234
        assert b"4 passed" not in evidence  # No raw PowerShell stdout is bundled.
        assert proof["phases"][0]["test_counts"]["passed"] == 4
    original = Path(first["asset"]).read_bytes()
    with pytest.raises(ValueError, match="must be new"):
        kit.build(contents, package, Path(first["asset"]).parent)
    assert Path(first["asset"]).read_bytes() == original


def test_vendor_installer_digest_is_an_independent_required_guard(fixture, monkeypatch):
    monkeypatch.setitem(kit.PYTHON_INSTALLERS, "3.14.10", "f" * 64)
    with pytest.raises(ValueError, match="vendor release"):
        kit.prepare(*fixture, PIN)


def test_filtered_guest_archive_reads_only_fixed_public_docs_at_exact_git_pin(monkeypatch):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("LICENSE", "fixture")
    calls = []

    def run(command, **options):
        calls.append(command)
        assert command[:2] == ["git", "show"]
        assert command[2] in [f"{PIN}:{name}" for name in kit.DOCS]
        assert options["check"] is True and options["timeout"] == 15
        return type("Result", (), {"stdout": b"pinned public documentation"})()

    monkeypatch.setattr(kit.subprocess, "run", run)
    with zipfile.ZipFile(io.BytesIO(data.getvalue())) as archive:
        result = kit.public_documentation(archive, PIN)
    assert len(calls) == 2 and set(result) == {"LICENSE", *kit.DOCS}
