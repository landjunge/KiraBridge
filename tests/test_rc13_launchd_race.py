"""Regression for launchd handover race during RC13 activation."""
import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace


def installer():
    path = Path(__file__).resolve().parents[1] / "installer" / "install.py"
    spec = importlib.util.spec_from_file_location("rc13_launchd_race", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_transient_eio_retries_without_touching_other_jobs(monkeypatch, tmp_path):
    mod = installer()
    plist = tmp_path / "bridge.plist"
    plist.write_text("test")
    args = SimpleNamespace(service="launchd", plist=plist)
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if len(calls) == 1:
            return subprocess.CompletedProcess(argv, 5, "", "Input/output error")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(mod, "loaded", lambda args: len(calls) > 1)
    monkeypatch.setattr(mod.time, "sleep", lambda seconds: None)
    mod.start_service(args)
    assert len(calls) == 2
    assert all(cmd[:2] == ["launchctl", "bootstrap"] for cmd in calls)


def test_stop_waits_for_unregistration(monkeypatch):
    mod = installer()
    args = SimpleNamespace(service="launchd")
    responses = iter([True, True, False, False])
    monkeypatch.setattr(mod, "loaded", lambda args: next(responses))
    monkeypatch.setattr(mod, "run", lambda *args, **kwargs: b"")
    monkeypatch.setattr(mod.time, "sleep", lambda seconds: None)
    mod.stop_service(args)
