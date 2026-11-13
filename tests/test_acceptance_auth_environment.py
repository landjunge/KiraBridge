"""Synthetic environments only; no installers, services or operator credentials."""

import json
import subprocess
from types import SimpleNamespace

import pytest
from test_release_package_contract import script

from kirabridge import local_runtime


@pytest.mark.parametrize("name", ["accept_macos_release", "accept_linux_server"])
def test_acceptance_environment_is_a_copy_without_ambient_auth(name, monkeypatch):
    module = script(name)
    original = {
        "PATH": "/synthetic/bin",
        "TMPDIR": "/synthetic/scratch",
        "KIRABRIDGE_LOCAL_TOKEN": "synthetic-ambient-local",
        "KIRABRIDGE_CHATGPT_TOKEN": "synthetic-ambient-chatgpt",
        "KIRABRIDGE_GROK_APP_TOKEN": "synthetic-ambient-grok",
        "KIRABRIDGE_TOKEN": "synthetic-legacy-bridge",
        "CHATGPT_TOKEN": "synthetic-legacy-chatgpt",
        "LOCAL_TOKEN": "synthetic-legacy-local",
        "CODEX_TOKEN": "synthetic-legacy-codex",
        "GROK_TOKEN": "synthetic-legacy-grok",
        "GITHUB_TOKEN": "synthetic-artifact-access",
        "KIRABRIDGE_CONFIG": "/synthetic/config.toml",
    }
    before = dict(original)
    monkeypatch.setattr(module, "os", SimpleNamespace(environ=original))
    for cleaned in (module.acceptance_environment(), module.acceptance_environment(original)):
        assert cleaned == {
            key: original[key] for key in ("PATH", "TMPDIR", "GITHUB_TOKEN", "KIRABRIDGE_CONFIG")
        }
        cleaned["PATH"] = "/synthetic/changed-child"
        assert original == before


@pytest.mark.parametrize("name", ["accept_macos_release", "accept_linux_server"])
@pytest.mark.parametrize("token_env", ["KIRABRIDGE_LOCAL_TOKEN", "CHATGPT_TOKEN"])
def test_isolated_client_loads_fresh_credentials_without_changing_caller(
    name, token_env, tmp_path, monkeypatch
):
    module = script(name)
    fresh = "synthetic-fresh-test-credential-" + "f" * 40
    ambient = "synthetic-ambient-credential-" + "a" * 40
    credentials = tmp_path / "credentials.json"
    credentials.write_text(json.dumps({"local": fresh}))
    credentials.chmod(0o600)
    config = SimpleNamespace(
        principals={"local": SimpleNamespace(token_env=token_env)},
        credentials_file=str(credentials),
    )
    caller = {token_env: ambient}
    child = module.acceptance_environment(caller)
    monkeypatch.setattr(local_runtime, "os", SimpleNamespace(environ=caller))
    assert local_runtime.token_for(config, "local") == ambient
    monkeypatch.setattr(local_runtime, "os", SimpleNamespace(environ=child))
    assert local_runtime.token_for(config, "local") == fresh
    assert caller == {token_env: ambient}


@pytest.mark.parametrize("explicit_env", [False, True])
def test_mac_inprocess_installer_and_cli_children_use_isolation(monkeypatch, explicit_env):
    module = script("accept_macos_release")
    caller = {
        "PATH": "/synthetic/bin",
        "KIRABRIDGE_LOCAL_TOKEN": "synthetic-ambient",
        "PYTHONPATH": "/synthetic/python",
    }
    monkeypatch.setattr(module, "os", SimpleNamespace(environ=caller))
    captured = []

    def installer_run(argv, **kwargs):
        captured.append(kwargs)
        return b"synthetic-result"

    installer = SimpleNamespace(run=installer_run)
    module.isolate_installer_environment(installer)
    kwargs = {"env": caller} if explicit_env else {}
    assert installer.run(["synthetic-installer-cli"], capture=True, **kwargs) == b"synthetic-result"
    assert captured[0]["capture"] is True
    assert "KIRABRIDGE_LOCAL_TOKEN" not in captured[0]["env"]
    assert ("PYTHONPATH" in captured[0]["env"]) is explicit_env

    def child_run(argv, **kwargs):
        captured.append(kwargs)
        return subprocess.CompletedProcess(argv, 0, "synthetic-output", "")

    monkeypatch.setattr(module.subprocess, "run", child_run)
    assert module.run(["synthetic-bundle-installer"], **kwargs) == "synthetic-output"
    assert "KIRABRIDGE_LOCAL_TOKEN" not in captured[-1]["env"]
    assert caller["KIRABRIDGE_LOCAL_TOKEN"] == "synthetic-ambient"
