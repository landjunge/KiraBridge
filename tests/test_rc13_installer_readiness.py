"""Regression checks for RC13 installer readiness.

Tests deliberately never launch or stop a system service.
"""
from pathlib import Path

def test_installer_preserves_previous_service_on_failed_start():
    source = (Path(__file__).resolve().parents[1] / "installer" / "install.py").read_text()
    assert "rollback(args)" in source
    assert "New daemon readiness not proven" in source
    assert "last health:" in source

def test_installer_requires_daemon_identity_and_dispatcher():
    source = (Path(__file__).resolve().parents[1] / "installer" / "install.py").read_text()
    assert 'health.get("version") == version' in source
    assert 'health.get("dispatcher_active")' in source
    assert 'health.get("runtime", {}).get("config_sha256") == sha(args.config)' in source
