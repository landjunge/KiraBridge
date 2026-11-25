"""Release preflight policy in temp paths, without installers or daemon processes."""

import hashlib
import json
import subprocess
import sys

import pytest
from test_release_package_contract import script

from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import load_config
from kirabridge.local_runtime import setup
from kirabridge.permissions import decision
from kirabridge.readiness import ReadinessInput, readiness


@pytest.mark.parametrize("smoke_fixture", [False, True], ids=["manual-default", "probe-only-grant"])
async def test_release_probe_needs_its_explicit_fixture_grant(tmp_path, monkeypatch, smoke_fixture):
    config_path = tmp_path / "config/config.toml"
    workspace = tmp_path / "project"
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    if smoke_fixture:
        module = script("release_smoke")
        monkeypatch.setattr(
            sys, "argv", ["isolated-setup", str(config_path), str(workspace), "19876"]
        )
        exec(module.ISOLATED_SETUP, {})
    else:
        setup(str(workspace), config_path, install_wrapper=False)
    config = load_config(str(config_path))
    assert config.principals["local"].approval_mode == ("automatic" if smoke_fixture else "manual")
    assert not config.principals["local"].automatic_operations
    if smoke_fixture:
        assert config.principals["local"].capabilities == ["bridge.health", "file.read"]
    assert decision(config, "local", "file.read")["automatic"] is smoke_fixture
    assert not decision(config, "local", "file.write")["automatic"]
    for name in ("codex", "grok"):
        assert config.principals[name].approval_mode == "manual"
        assert not config.principals[name].automatic_operations
        assert not decision(config, name, "file.read")["automatic"]
    if smoke_fixture:
        assert config.port == 19876
    probe = workspace / "release-probe.txt"
    probe.write_text("Synthetic isolated release prerequisite\n")
    files = [config_path, config_path.parent / "credentials.json"]
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    async with Bridge(config) as bridge:
        result = readiness(
            bridge,
            "local",
            ReadinessInput(
                operations=["file.read"],
                read_paths=[str(probe)],
                workflow_id="release-package-smoke",
            ),
        )
        assert result["dispatcher_active"] and result["audit_recorded"]
        assert result["read_path_checks"][0]["code"] == "available"
        assert result["requested_prerequisites_ready"] is smoke_fixture
        assert result["operation_checks"][0]["code"] == (
            "available" if smoke_fixture else "approval_required"
        )
    assert before == {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    assert not (tmp_path / ".local/bin/kirabridge").exists()


def test_smoke_failure_reports_operation_denial_alongside_accessible_path(monkeypatch):
    module = script("release_smoke")
    payload = {
        "error": None,
        "requested_prerequisites_ready": False,
        "service_matches_local_config_and_source": True,
        "audit_recorded": True,
        "read_path_checks": [{"path": "private synthetic path", "code": "available"}],
        "operation_checks": [{"operation": "file.read", "code": "approval_required"}],
    }
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, json.dumps(payload), ""),
    )
    with pytest.raises(RuntimeError) as failed:
        module.run(["synthetic-command"])
    assert '"codes": ["available", "approval_required"]' in str(failed.value)
    assert "private synthetic path" not in str(failed.value)
