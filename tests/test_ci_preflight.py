"""Focused emission boundaries; synthetic records do not claim CI acceptance."""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ci_remote_tests.py"
SPEC = importlib.util.spec_from_file_location("ci_preflight_under_test", SCRIPT)
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


@pytest.fixture
def evidence(tmp_path):
    snapshot = gate.filesystem_snapshot(tmp_path)
    source = {
        "root": str(tmp_path),
        "commit": "a" * 40,
        "manifest_sha256": "b" * 64,
        "files": {"fixture.py": "synthetic-file-map-must-not-be-printed"},
    }
    return {
        "run_id": "synthetic-emission-unit-test",
        "lane": "remote",
        "python": "/synthetic/python",
        "version": "synthetic",
        "platform": "synthetic",
        "sources": {"kb": copy.deepcopy(source), "td": copy.deepcopy(source)},
        "imports_before": {"kirabridge": "/synthetic/kb", "threaddesk": "/synthetic/td"},
        "temp_scope": {
            "identity": {"GITHUB_RUN_ID": "42", "GITHUB_RUN_ATTEMPT": "1", "UV_PYTHON": "3.11"},
            "runner_temp": str(tmp_path),
            "effective_python_temp": str(tmp_path),
            "report_dir": str(tmp_path / "report"),
            "pytest_basetemp": str(tmp_path / "report" / "pytest-basetemp"),
            "filesystem_before": snapshot,
            "report_filesystem": snapshot,
            "runner_filesystem": snapshot,
            "workspace_device": tmp_path.stat().st_dev,
            "root_device": Path("/").stat().st_dev,
        },
        "environment": {"GITHUB_RUN_ID": "42", "SECRET": "synthetic-secret-must-not-be-printed"},
        "dependencies": {"synthetic": "dependency-inventory-must-not-be-printed"},
        "authority": "synthetic-authority-must-not-be-printed",
    }


def test_compact_record_preserves_observations_without_acceptance_or_unbounded_maps(
    evidence, capsys
):
    before = copy.deepcopy(evidence)
    gate.emit_preflight(evidence)
    output = capsys.readouterr().out
    record = json.loads(output)
    assert record["schema"] == "kirabridge.ci-preflight.v1"
    assert record["phase"] == "PREFLIGHT"
    assert record["acceptance"] == "not_evaluated"
    assert record["pytest_started"] is False
    assert "gate" not in record and "pytest_exit" not in record
    assert record["imports"] == evidence["imports_before"]
    assert record["temp_scope"] == evidence["temp_scope"]
    assert record["sources"]["kb"]["file_count"] == 1
    assert "files" not in record["sources"]["kb"]
    assert len(output.encode("utf-8")) <= gate.PREFLIGHT_MAX_BYTES
    assert output.count("\n") == 1
    for marker in (
        "file-map-must-not",
        "secret-must-not",
        "inventory-must-not",
        "authority-must-not",
    ):
        assert marker not in output
    assert evidence == before


@pytest.mark.parametrize("key", ["gate", "pytest_exit", "junit", "finished_ns"])
def test_completion_fields_cannot_be_emitted_as_preflight(evidence, capsys, key):
    evidence[key] = "synthetic-completion"
    with pytest.raises(gate.GateError, match="precede pytest completion"):
        gate.emit_preflight(evidence)
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    ("section", "key"),
    [("sources", "td"), ("imports_before", "kirabridge"), ("temp_scope", "filesystem_before")],
)
def test_missing_bound_observation_stops_before_emission(evidence, capsys, section, key):
    del evidence[section][key]
    with pytest.raises(gate.GateError, match="bindings missing"):
        gate.emit_preflight(evidence)
    assert capsys.readouterr().out == ""


def test_utf8_byte_limit_rejects_without_partial_or_truncated_record(evidence, capsys):
    # UTF-8 bytes exceed the limit even though the character count does not.
    evidence["imports_before"]["kirabridge"] = "\u20ac" * (gate.PREFLIGHT_MAX_BYTES // 2)
    with pytest.raises(gate.GateError, match="record too large"):
        gate.emit_preflight(evidence)
    assert capsys.readouterr().out == ""
