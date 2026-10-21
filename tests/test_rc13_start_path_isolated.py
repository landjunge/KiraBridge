"""Isolated start-path checks. Never invokes real launchctl or a Mac service."""
import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest


def installer():
    path = Path(__file__).resolve().parents[1] / "installer" / "install.py"
    spec = importlib.util.spec_from_file_location("rc13_install", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def args(tmp_path):
    plist = tmp_path / "com.kirabridge.bridge.plist"
    plist.write_text("fixture")
    return SimpleNamespace(service="launchd", plist=plist)


def test_bootstrap_failure_reports_launchctl_error(monkeypatch, args):
    module = installer()
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a[0], 5, "", "service failed"))
    with pytest.raises(RuntimeError, match=r"bootstrap failed .*service failed"):
        module.start_service(args)


def test_successful_bootstrap_must_register_service(monkeypatch, args):
    module = installer()
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, "", ""))
    monkeypatch.setattr(module, "loaded", lambda a: False)
    with pytest.raises(RuntimeError, match="service is absent"):
        module.start_service(args)


def test_successful_bootstrap_and_registration(monkeypatch, args):
    module = installer()
    calls = []
    def fake_run(argv, **kw):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module, "loaded", lambda a: True)
    module.start_service(args)
    assert calls[0][:2] == ["launchctl", "bootstrap"]


def test_missing_plist_does_not_invoke_launchctl(monkeypatch, args):
    module = installer()
    args.plist.unlink()
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **kw: pytest.fail("launchctl must not run"))
    with pytest.raises(RuntimeError, match="plist missing"):
        module.start_service(args)


def test_failed_subprocess_surfaces_stderr(monkeypatch):
    module = installer()

    class FakeProcess:
        returncode = 12
        pid = 123456

        def communicate(self, timeout=None):
            return b"", b"configuration rejected by daemon"

    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **kw: FakeProcess())
    monkeypatch.setattr(module.os, "killpg", lambda *a: None)
    with pytest.raises(RuntimeError, match="configuration rejected by daemon"):
        module.run(["fake-command"], capture=True)
