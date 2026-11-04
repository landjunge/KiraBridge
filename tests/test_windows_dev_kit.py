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
        for name in kit.REQUIRED_HARNESSES:
            output.writestr(name, "# Synthetic guard fixture, never a native proof\n")
        for name in kit.BOOTSTRAP_FILES.values():
            output.writestr(name, "# Synthetic bootstrap fixture, never executed\n")
    files = {
        "source.zip": source.getvalue(),
        "python-installer.exe": b"NOT A REAL INSTALLER: unit guard fixture",
        "guest_runner.ps1": b"# Fake fixture, never executed",
        kit.CLIENT_ARCHIVE: b"NOT A REAL TUNNEL CLIENT: unit guard fixture",
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
            if phase == "setup":
                report["artifact"].update(
                    gui_native_smoke=True,
                    authenticated_roundtrip_simulated=True,
                    cloud_attested=False,
                    keyboard_events_requested=0,
                )
        (reports / f"report-{RUN_ID}-{phase}.json").write_text(json.dumps(report))
    # Unit fixtures deliberately override the vendor reference. Production CLI
    # has only the real Python.org digest and cannot accept this fake installer.
    monkeypatch.setitem(kit.PYTHON_INSTALLERS, "3.14.10", kit.digest(files["python-installer.exe"]))
    monkeypatch.setitem(
        kit.CLIENT_ARCHIVES, kit.CLIENT_ARCHIVE, kit.digest(files[kit.CLIENT_ARCHIVE])
    )
    return stage, reports


def modify_report(fixture, phase, fn):
    path = fixture[1] / f"report-{RUN_ID}-{phase}.json"
    report = json.loads(path.read_text())
    fn(report)
    path.write_text(json.dumps(report))


@pytest.mark.parametrize("phase", kit.PHASES)
def test_missing_native_phase_blocks_before_any_archive(fixture, tmp_path, phase):
    (fixture[1] / f"report-{RUN_ID}-{phase}.json").unlink()
    with pytest.raises(ValueError, match="seven phases"):
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


@pytest.mark.parametrize("phase", ["shortcuts", "windows"])
@pytest.mark.parametrize(
    "change",
    [
        lambda r: r.update(exit_code=1),
        lambda r: r.update(status="unknown_or_failed_no_retry"),
        lambda r: r.update(manifest_sha256="f" * 64),
        lambda r: r["artifact"].pop("passed"),
        lambda r: r["artifact"].update(passed=False),
        lambda r: r["artifact"].update(passed=1),
        lambda r: r["artifact"].update(unknown=True),
        lambda r: r["artifact"].update(state="unknown"),
        lambda r: r["artifact"].update(state="cancelled"),
        lambda r: r["artifact"].update(error_type="UncertainExecution"),
    ],
)
def test_new_phase_needs_explicit_true_and_no_failed_or_uncertain_report(fixture, phase, change):
    modify_report(fixture, phase, change)
    with pytest.raises(ValueError):
        kit.prepare(*fixture, PIN)


def test_previous_four_phase_proof_cannot_authorize_new_shortcuts_or_windows(fixture):
    for phase in ("shortcuts", "windows"):
        (fixture[1] / f"report-{RUN_ID}-{phase}.json").unlink()
    with pytest.raises(ValueError, match="seven phases"):
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
    assert package["version"] == "0.8.0rc37.dev1"
    assert package["native_guest_phases"] == list(kit.PHASES)
    assert len(package["native_guest_phases"]) == 7
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
    assert len(calls) == len(kit.DOCS) and set(result) == {"LICENSE", *kit.DOCS}


def replace_source(stage, commit, changes):
    manifest = json.loads((stage / "manifest.json").read_bytes())
    source = stage / "source.zip"
    with zipfile.ZipFile(source) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    for name, body in changes.items():
        if body is None:
            files.pop(name, None)
        else:
            files[name] = body
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.comment = commit.encode()
        for name, body in files.items():
            archive.writestr(name, body)
    source.write_bytes(output.getvalue())
    manifest["source_commit"] = commit
    for entry in manifest["files"]:
        body = (stage / entry["path"]).read_bytes()
        entry.update(bytes=len(body), sha256=kit.digest(body))
    raw = json.dumps(manifest).encode()
    (stage / "manifest.json").write_bytes(raw)
    return kit.digest(raw)


@pytest.mark.parametrize("harness", kit.REQUIRED_HARNESSES)
def test_source_archive_must_include_each_required_native_harness(fixture, harness):
    replace_source(fixture[0], PIN, {harness: None})
    with pytest.raises(ValueError, match="required native acceptance harness"):
        kit.prepare(*fixture, PIN)


@pytest.fixture
def reuse_fixture(fixture, tmp_path):
    import shutil

    current, original_reports = fixture
    runtime = {
        f"src/kirabridge/module{i}.py": f"VALUE = {i}\n".encode()
        for i in range(kit.RUNTIME_MODULE_COUNT)
    }
    harnesses = {name: ("# synthetic " + name).encode() for name in kit.REUSED_HARNESSES}
    harnesses["scripts/windows_guest_runner.ps1"] = (current / "guest_runner.ps1").read_bytes()
    # A wheel/source comparison fixture is not an executable Windows package.
    wheel = next((current / "wheels").glob("kirabridge-*.whl"))
    with zipfile.ZipFile(wheel, "a") as archive:
        for name, data in runtime.items():
            archive.writestr(name[4:], data)
    replace_source(current, PIN, {**runtime, **harnesses})
    previous = tmp_path / "previous-stage"
    shutil.copytree(current, previous)
    old_pin = "c" * 40
    old_hash = replace_source(previous, old_pin, {})
    old_reports = tmp_path / "previous-reports"
    shutil.copytree(original_reports, old_reports)
    for path in old_reports.glob("report-*.json"):
        report = json.loads(path.read_bytes())
        if report["phase"] in ("shortcuts", "windows", "setup"):
            # This synthetic original run stopped at preview; the later phases
            # did not run and cannot supply either fresh required proof.
            path.unlink()
            continue
        report["manifest_sha256"] = old_hash
        if report["phase"] != "core":
            report["artifact_sha256"] = "a" * 64
        if report["phase"] == "preview":
            report["exit_code"] = 1
            report["artifact"].update(passed=False, error_type="BridgeError")
        path.write_text(json.dumps(report))
    new_hash = kit.digest((current / "manifest.json").read_bytes())
    for path in original_reports.glob("report-*.json"):
        report = json.loads(path.read_bytes())
        if report["phase"] not in kit.FRESH_PHASES:
            path.unlink()
        else:
            report["manifest_sha256"] = new_hash
            if report["phase"] == "preview":
                report["artifact"].update(keyboard_events_requested=0)
            path.unlink()
            # Different actual run IDs are explicitly recorded, never merged.
            (original_reports / f"report-{'b' * 32}-{report['phase']}.json").write_text(
                json.dumps(report)
            )
    return current, original_reports, previous, old_reports


def test_component_reuse_records_each_original_source_manifest_and_run(reuse_fixture):
    current, new_reports, previous, old_reports = reuse_fixture
    contents, package = kit.prepare(current, new_reports, PIN, previous, old_reports)
    proof = json.loads(contents["native-acceptance.json"])
    assert package["component_provenance_reuse"] is True
    assert proof["run_ids"] == ["a" * 32, "b" * 32]
    assert [phase["reused"] for phase in proof["phases"]] == [True] * 3 + [False] * len(
        kit.FRESH_PHASES
    )
    assert [phase["source_commit"] for phase in proof["phases"]] == ["c" * 40] * 3 + [PIN] * len(
        kit.FRESH_PHASES
    )
    assert proof["reuse_basis"]["runtime_module_count"] == kit.RUNTIME_MODULE_COUNT == 179
    ignored = proof["reuse_basis"]["ignored_previous_preview"]
    assert ignored["accepted_as_passing_phase"] is False
    assert len(ignored["raw_report_sha256"]) == 64
    assert all(len(phase["raw_report_sha256"]) == 64 for phase in proof["phases"])
    assert proof["phases"][3]["artifact"]["independent_original_process_absent"] is True
    assert [phase["phase"] for phase in proof["phases"]] == list(kit.PHASES)


@pytest.mark.parametrize("component", ["runtime", "reused_harness"])
def test_component_reuse_refuses_changed_runtime_or_reused_harness(reuse_fixture, component):
    current, new_reports, previous, old_reports = reuse_fixture
    change = "src/kirabridge/module0.py" if component == "runtime" else kit.REUSED_HARNESSES[0]
    replace_source(current, PIN, {change: b"# changed after native acceptance"})
    with pytest.raises(ValueError, match="runtime bytes differ|harness bytes differ"):
        kit.prepare(current, new_reports, PIN, previous, old_reports)


def test_component_reuse_refuses_failed_original_phase(reuse_fixture):
    current, new_reports, previous, old_reports = reuse_fixture
    path = old_reports / f"report-{RUN_ID}-keyboard.json"
    report = json.loads(path.read_bytes())
    report["exit_code"] = 1
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="Native report failed"):
        kit.prepare(current, new_reports, PIN, previous, old_reports)


@pytest.mark.parametrize("phase", kit.FRESH_PHASES)
def test_component_reuse_requires_paired_arguments_and_all_fresh_phases(reuse_fixture, phase):
    current, new_reports, previous, old_reports = reuse_fixture
    with pytest.raises(ValueError, match="provided together"):
        kit.prepare(current, new_reports, PIN, previous, None)
    (new_reports / f"report-{'b' * 32}-{phase}.json").unlink()
    with pytest.raises(ValueError, match="selected phases"):
        kit.prepare(current, new_reports, PIN, previous, old_reports)


def test_component_reuse_refuses_preview_without_positive_pid_or_cleanup(reuse_fixture):
    current, new_reports, previous, old_reports = reuse_fixture
    path = new_reports / f"report-{'b' * 32}-preview.json"
    report = json.loads(path.read_bytes())
    report["process_id"] = 0
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="Native report failed"):
        kit.prepare(current, new_reports, PIN, previous, old_reports)
    report["process_id"] = 1234
    report["artifact"]["independent_original_process_absent"] = False
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="cleanup"):
        kit.prepare(current, new_reports, PIN, previous, old_reports)
