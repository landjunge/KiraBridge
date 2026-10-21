"""Interrupted RC13 preparation must not delete or overwrite partial payloads."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_incomplete_version_directory_is_reported_without_deletion(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / "installer" / "install.py"
    spec = importlib.util.spec_from_file_location("rc13_install_partial", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    ref = "a" * 40
    version = "0.8.0rc13"
    releases = tmp_path / "releases"
    destination = releases / (version + "-" + ref[:12])
    destination.mkdir(parents=True)
    sentinel = destination / "important-existing-file"
    sentinel.write_text("retain")

    def fake_run(args, **kwargs):
        if args[-1] == ref + "^{commit}":
            return (ref + "\n").encode()
        if args[-1] == ref + ":pyproject.toml":
            return b'[project]\nversion = "0.8.0rc13"\n'
        pytest.fail("Unexpected subprocess call")

    monkeypatch.setattr(module, "run", fake_run)
    args = SimpleNamespace(ref=ref, repo=tmp_path, prefix=tmp_path)
    with pytest.raises(RuntimeError, match="Incomplete RC13 preparation"):
        module.prepare(args)
    assert sentinel.read_text() == "retain"
