"""Guest smoke staging policy; no child process, Windows API or desktop is invoked."""

import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from kirabridge.bridge_core.models import BridgeError

spec = importlib.util.spec_from_file_location(
    "windows_preview_harness", Path(__file__).parents[1] / "scripts/accept_windows_preview.py"
)
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)


def test_native_acl_helper_receives_random_path_that_has_never_been_created(monkeypatch, tmp_path):
    import kirabridge.bridge_core.config as config

    observed = []
    snapshots = []
    monkeypatch.setattr(harness.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(harness.secrets, "token_hex", lambda count: "a" * 32)
    report = {"passed": False}

    def native_create(root):
        assert not root.exists()
        assert root.parent == tmp_path
        assert snapshots[-1]["stage"] == "creating_private_smoke_directory"
        assert snapshots[-1]["owned_process_started"] is False
        observed.append(root)
        root.mkdir(mode=0o700)  # Stand-in for atomic native ACL creation, not mkdtemp.

    monkeypatch.setattr(config, "private_directory", native_create)
    state, log = harness.private_smoke_paths(report, persist=lambda: snapshots.append(dict(report)))
    assert observed == [tmp_path / ("kirabridge-preview-smoke-" + "a" * 32)]
    assert state == observed[0] / "state" and log == observed[0] / "owned-preview.log"
    assert not state.exists() and not log.exists()
    assert report["stage"] == "private_smoke_directory_ready"
    assert "independent_original_process_absent" not in report


def test_collision_is_refused_without_reusing_or_changing_existing_directory(monkeypatch, tmp_path):
    import kirabridge.bridge_core.config as config

    monkeypatch.setattr(harness.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(harness.secrets, "token_hex", lambda count: "b" * 32)
    root = tmp_path / ("kirabridge-preview-smoke-" + "b" * 32)
    root.mkdir()
    original = root / "keep.txt"
    original.write_text("original")
    monkeypatch.setattr(config, "private_directory", lambda root: pytest.fail("Must not reuse"))
    with pytest.raises(FileExistsError):
        harness.private_smoke_paths({}, persist=lambda: None)
    assert original.read_text() == "original"


def test_before_child_failure_retains_stage_and_safe_error_code_without_fake_cleanup(
    monkeypatch, tmp_path, capsys
):
    import kirabridge.bridge_core.config as config

    artifact = tmp_path / "preview-result.json"
    monkeypatch.setattr(harness.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(harness, "os", SimpleNamespace(name="nt", path=os.path, fsync=os.fsync))
    monkeypatch.setattr(
        harness.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("No child on ACL failure")
    )

    def refuse(root):
        saved = json.loads(artifact.read_text())
        assert saved["stage"] == "creating_private_smoke_directory"
        assert saved["owned_process_started"] is False
        assert not root.exists()
        raise BridgeError("unsafe_state", "sensitive https://example.invalid/PRIVATE_TOKEN")

    monkeypatch.setattr(config, "private_directory", refuse)
    with pytest.raises(SystemExit) as stopped:
        harness.main(["--output", str(artifact)])
    assert stopped.value.code == 1
    saved = json.loads(artifact.read_text())
    assert saved["stage"] == "creating_private_smoke_directory"
    assert saved["error_code"] == "unsafe_state" and saved["error_type"] == "BridgeError"
    assert saved["owned_process_started"] is False and saved["passed"] is False
    assert "owned_process" not in saved and "independent_original_process_absent" not in saved
    assert "PRIVATE_TOKEN" not in artifact.read_text()
    captured = capsys.readouterr()
    assert "PRIVATE_TOKEN" not in captured.out + captured.err
