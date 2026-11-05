"""Portable guard tests with fake source data; never native Windows acceptance."""

import hashlib
import importlib.util
import io
import json
import os
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
try:
    spec = importlib.util.spec_from_file_location(
        "candidate_observer", SCRIPTS / "windows_candidate_evidence.py"
    )
    observer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(observer)
finally:
    sys.path.remove(str(SCRIPTS))

PIN, VERSION = "c" * 40, "0.8.0rc39"


@pytest.fixture
def staged(tmp_path):
    import build_windows_dev_kit as kit

    root, payload = tmp_path / "source", tmp_path / "payload"
    root.mkdir()
    payload.mkdir()
    files = {
        name: b"# Synthetic owned guard fixture\n"
        for name in (*kit.REQUIRED_HARNESSES, *kit.CANDIDATE_PRODUCERS)
    }
    files.update(
        {
            "src/kirabridge/__init__.py": f'__version__ = "{VERSION}"\n'.encode(),
            "src/kirabridge/sample.py": b"FIXTURE = True\n",
            "pyproject.toml": f'[project]\nname="kirabridge"\nversion="{VERSION}"\n'.encode(),
        }
    )
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as target:
        target.comment = PIN.encode()
        for name, data in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            target.writestr(name, data)
    zipped = archive.getvalue()
    (payload / "source.zip").write_bytes(zipped)
    runner = files["scripts/windows_guest_runner.ps1"]
    (payload / "guest_runner.ps1").write_bytes(runner)
    raw = json.dumps(
        {
            "schema_version": 1,
            "source_commit": PIN,
            "files": [
                {
                    "path": "source.zip",
                    "bytes": len(zipped),
                    "sha256": hashlib.sha256(zipped).hexdigest(),
                },
                {
                    "path": "guest_runner.ps1",
                    "bytes": len(runner),
                    "sha256": hashlib.sha256(runner).hexdigest(),
                },
            ],
        }
    ).encode()
    manifest = payload / "manifest.json"
    manifest.write_bytes(raw)
    return SimpleNamespace(
        root=root, manifest=manifest, digest=hashlib.sha256(raw).hexdigest(), files=files, kit=kit
    )


def observe(staged):
    return observer.inspect_source(staged.root, staged.manifest, staged.digest, VERSION, PIN)


def test_actual_fixture_bytes_match_shared_builder_inventory_without_claiming_platform(staged):
    result = observe(staged)
    document, digest = staged.kit.candidate_inventory(VERSION, PIN, staged.files)
    assert result == {**document, "inventory_sha256": digest}
    assert "evidence_platform" not in result
    assert set(staged.kit.CANDIDATE_PRODUCERS) <= result["harness_sha256"].keys()
    assert result["runtime_module_count"] == 2


@pytest.mark.parametrize(
    "name",
    [
        "src/kirabridge/sample.py",
        "pyproject.toml",
        "scripts/windows_guest_runner.ps1",
        "scripts/windows_candidate_evidence.py",
        "scripts/build_windows_dev_kit.py",
        "scripts/accept_windows_keyboard.py",
    ],
)
def test_changed_extracted_runtime_version_harness_or_producer_cannot_pass(staged, name):
    (staged.root / name).write_bytes(b"# changed after extraction\n")
    with pytest.raises(ValueError, match="bytes differ"):
        observe(staged)


@pytest.mark.parametrize("change", ["missing", "extra"])
def test_exact_executed_module_set_required(staged, change):
    if change == "missing":
        (staged.root / "src/kirabridge/sample.py").unlink()
    else:
        (staged.root / "src/kirabridge/extra.py").write_text("# undeclared\n")
    with pytest.raises(ValueError, match="module set differs"):
        observe(staged)


def test_changed_archive_and_manifest_are_not_evidence(staged):
    (staged.manifest.parent / "source.zip").write_bytes(b"changed")
    with pytest.raises(ValueError, match="Source archive differs"):
        observe(staged)
    staged.manifest.write_bytes(staged.manifest.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="Manifest differs"):
        observe(staged)


def test_executed_bootstrap_must_match_the_source_inventory(staged):
    (staged.manifest.parent / "guest_runner.ps1").write_bytes(b"# another bootstrap\n")
    with pytest.raises(ValueError, match="Executed bootstrap differs"):
        observe(staged)


def test_wrong_source_version_and_pins_rejected(staged):
    with pytest.raises(ValueError, match="source version differs"):
        observer.inspect_source(staged.root, staged.manifest, staged.digest, "0.8.0rc40", PIN)
    with pytest.raises(ValueError, match="source identity differs"):
        observer.inspect_source(staged.root, staged.manifest, staged.digest, VERSION, "d" * 40)
    with pytest.raises(ValueError, match="Exact source"):
        observer.inspect_source(staged.root, staged.manifest, staged.digest, VERSION, "main")


def test_symlinked_files_are_not_observed_as_owned_candidate(staged, tmp_path):
    if os.name == "nt":
        pytest.skip("Symlink privilege is not assumed by this portable guard test")
    target = tmp_path / "outside.py"
    target.write_bytes(staged.files["src/kirabridge/sample.py"])
    path = staged.root / "src/kirabridge/sample.py"
    path.unlink()
    path.symlink_to(target)
    with pytest.raises(ValueError, match="Linked candidate"):
        observe(staged)


def test_collector_main_refuses_non_windows_before_writing_any_evidence(
    staged, monkeypatch, capsys
):
    monkeypatch.setattr(observer, "os", SimpleNamespace(name="posix"))
    with pytest.raises(SystemExit) as exc:
        observer.main(
            [
                "--source-root",
                str(staged.root),
                "--manifest",
                str(staged.manifest),
                "--manifest-sha256",
                staged.digest,
                "--candidate-version",
                VERSION,
                "--source-commit",
                PIN,
            ]
        )
    assert exc.value.code == 2
    assert not capsys.readouterr().out
    assert not list(staged.root.rglob("*report*"))


def test_producers_must_be_complete_and_change_the_candidate_pin(staged):
    baseline = observe(staged)
    incomplete = dict(staged.files)
    del incomplete[staged.kit.CANDIDATE_PRODUCERS[0]]
    with pytest.raises(ValueError, match="evidence producer"):
        staged.kit.candidate_inventory(VERSION, PIN, incomplete)
    changed = dict(staged.files)
    changed[staged.kit.CANDIDATE_PRODUCERS[0]] = b"# another bootstrap\n"
    _, new_hash = staged.kit.candidate_inventory(VERSION, PIN, changed)
    assert new_hash != baseline["inventory_sha256"]


def test_observed_inventory_is_compatible_with_existing_candidate_report_checker(staged):
    # Constructed format compatibility ONLY, no genuine native process is claimed.
    result = observe(staged)
    synthetic = {**result, "evidence_platform": "win32", "artifact": {"platform": "nt"}}
    document, pin = staged.kit.candidate_inventory(VERSION, PIN, staged.files)
    staged.kit.require_windows_candidate_report(synthetic, document, pin, "keyboard")
    synthetic["harness_sha256"] = dict(synthetic["harness_sha256"])
    del synthetic["harness_sha256"][staged.kit.CANDIDATE_PRODUCERS[1]]
    with pytest.raises(ValueError, match="absent from the native inventory"):
        staged.kit.require_windows_candidate_report(synthetic, document, pin, "keyboard")
