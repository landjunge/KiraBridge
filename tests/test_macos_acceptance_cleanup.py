"""Acceptance cannot pass until its own launchd test service is observably absent."""

import ast
import importlib.util
import inspect
import json
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def harness(monkeypatch):
    source = Path(__file__).resolve().parents[1] / "scripts/accept_macos_release.py"
    spec = importlib.util.spec_from_file_location("macos_cleanup_tests", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    elapsed = [0.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: elapsed[0])
    monkeypatch.setattr(
        module.time, "sleep", lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds)
    )
    return module


def finish(harness, root, evidence):
    # Exercise the actual outer finally without installing packages or starting services.
    function = ast.parse(inspect.getsource(harness.accept)).body[0]
    cleanup = next(node for node in reversed(function.body) if isinstance(node, ast.Try)).finalbody
    code = compile(ast.Module(body=cleanup, type_ignores=[]), "<accept cleanup>", "exec")
    context = dict(
        vars(harness), root=root, evidence=evidence, helper=None, service="owned-fixture"
    )
    exec(code, context)


def test_cleanup_failure_cannot_leave_successful_evidence(harness, monkeypatch, tmp_path):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv[1])
        return subprocess.CompletedProcess(argv, 5 if argv[1] == "bootout" else 0)

    monkeypatch.setattr(harness.subprocess, "run", run)
    evidence = {"passed": True}
    with pytest.raises(RuntimeError, match="still present"):
        finish(harness, tmp_path, evidence)
    saved = json.loads((tmp_path / "evidence.json").read_text())
    assert saved["passed"] is False and saved["service_cleanup_error"] == "RuntimeError"
    assert calls.count("bootout") == 1 and calls.count("print") > 1


def test_cleanup_accepts_already_absent_service(harness, monkeypatch, tmp_path):
    def run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 113)

    monkeypatch.setattr(harness.subprocess, "run", run)
    evidence = {"passed": True}
    finish(harness, tmp_path, evidence)
    saved = json.loads((tmp_path / "evidence.json").read_text())
    assert saved["passed"] is True and saved["service_cleanup_absence_verified"] is True


def test_cleanup_waits_for_observed_removal(harness, monkeypatch, tmp_path):
    results = iter([0, 0, 113])
    budgets = []

    def run(argv, **kwargs):
        budgets.append(kwargs["timeout"])
        return subprocess.CompletedProcess(argv, next(results))

    monkeypatch.setattr(harness.subprocess, "run", run)
    evidence = {"passed": True}
    finish(harness, tmp_path, evidence)
    assert evidence["service_cleanup_absence_verified"] is True
    assert len(budgets) == 3 and all(0 < value <= 20 for value in budgets)


def test_cleanup_observation_error_is_not_absence(harness, monkeypatch, tmp_path):
    def run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0 if argv[1] == "bootout" else 13)

    monkeypatch.setattr(harness.subprocess, "run", run)
    evidence = {"passed": True}
    with pytest.raises(RuntimeError, match="observe"):
        finish(harness, tmp_path, evidence)
    assert json.loads((tmp_path / "evidence.json").read_text())["passed"] is False
