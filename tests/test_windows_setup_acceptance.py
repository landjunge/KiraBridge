"""Outer receipt/runtime guards only; synthetic data is not native acceptance."""

import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SOURCE = Path(__file__).parents[1] / "scripts/accept_windows_setup.py"
SPEC = importlib.util.spec_from_file_location("native_setup_acceptance_guard", SOURCE)
HARNESS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HARNESS)


def frozen_client(monkeypatch, source, data=b"frozen official-client fixture"):
    from kirabridge import windows_setup_client as client

    monkeypatch.setattr(client, "ARCHIVE_SIZE", len(data))
    monkeypatch.setattr(client, "ARCHIVE_SHA256", hashlib.sha256(data).hexdigest())
    tools = source.parent / "tools"
    tools.mkdir()
    archive = tools / client.ASSET
    archive.write_bytes(data)
    return archive, data


@pytest.mark.parametrize("inner_exit", [0, 1])
def test_outer_uses_new_venv_keeps_base_unchanged_and_requires_actual_inner_exit_zero(
    tmp_path, monkeypatch, inner_exit
):
    root = tmp_path / "payload/source"
    (root / "src/kirabridge").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "src/kirabridge/__init__.py").write_text('__version__ = "fixture"\n')
    wheels = root.parent / "wheels"
    wheels.mkdir()
    (wheels / "kirabridge-fixture-py3-none-any.whl").write_bytes(b"not a real wheel")
    frozen_client(monkeypatch, root)
    monkeypatch.setattr(HARNESS, "__file__", str(root / "scripts/accept_windows_setup.py"))
    commands = []

    def prepare(argv, report, label, **options):
        commands.append((argv, label, options))
        report["preparation_steps"].append(
            {"name": label, "exit_code": inner_exit if label == "inner_acceptance" else 0}
        )
        if label == "inner_acceptance":
            output = Path(argv[argv.index("--output") + 1])
            output.write_text(
                json.dumps({"passed": True, "platform": "nt", "preparation_steps": []})
            )
            return inner_exit
        return 0

    monkeypatch.setattr(HARNESS, "prepare_command", prepare)
    report = {"passed": False, "preparation_steps": []}
    with (tmp_path / "receipt.json").open("x+") as output:
        if inner_exit:
            with pytest.raises(RuntimeError, match="Original inner receipt"):
                HARNESS.outer(output, report)
        else:
            HARNESS.outer(output, report)
    assert "--without-pip" in commands[0][0] and "--system-site-packages" in commands[0][0]
    assert commands[1][0][0] != commands[0][0][0]
    assert {"--no-index", "--no-deps", "--ignore-installed", "--no-compile", "--no-user"} <= set(
        commands[1][0]
    )
    assert len(report["preparation_steps"]) == 3
    assert report["inner_exit_code"] == inner_exit
    assert report["fresh_venv_wheel_installation"] is True


def test_stage_is_durable_before_effect_and_ui_diagnostic_excludes_sensitive_fields():
    report, persisted = {}, []
    HARNESS.stage(
        report, lambda: persisted.append(dict(report)), "presenter_action", "install_client"
    )
    assert persisted == [{"stage": "presenter_action", "operation": "install_client"}]
    state = SimpleNamespace(
        message="Der Download ist fehlgeschlagen.", next_action="Prüfe die Verbindung.",
        operation="", busy=False, client_ready=False, prompt="SECRET PROMPT",
        response_code="SECRET RESPONSE", runtime_key="SECRET KEY", tunnel_id="SECRET ID",
    )
    result = HARNESS.public_ui_status(state)
    assert result == {
        "message": state.message, "next_action": state.next_action, "operation": "",
        "busy": False, "client_ready": False,
    }
    assert "SECRET" not in json.dumps(result)


def test_bundled_client_is_verified_then_written_exclusively_to_own_state(tmp_path, monkeypatch):
    source = tmp_path / "payload/source"
    source.mkdir(parents=True)
    archive, data = frozen_client(monkeypatch, source)
    state = tmp_path / "fresh-test-state"
    state.mkdir()
    protected = tmp_path / "KiraBridgeWindowsSetup"
    protected.mkdir()
    (protected / "bundled-client.zip").write_bytes(b"existing user cache")
    receipt = HARNESS.prepare_client_cache(source, state)
    assert (state / "bundled-client.zip").read_bytes() == data
    assert receipt == {
        "asset": archive.name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
        "private_test_cache_written": True, "network_download_required": False,
    }
    with pytest.raises(FileExistsError):
        HARNESS.prepare_client_cache(source, state)
    assert (protected / "bundled-client.zip").read_bytes() == b"existing user cache"


@pytest.mark.parametrize("alteration", ["short", "same_size_wrong_hash", "oversized"])
def test_bad_bundled_client_refused_before_cache_write(tmp_path, monkeypatch, alteration):
    source = tmp_path / "payload/source"
    source.mkdir(parents=True)
    archive, data = frozen_client(monkeypatch, source)
    archive.write_bytes({
        "short": data[:-1], "same_size_wrong_hash": b"X" * len(data), "oversized": data + b"X",
    }[alteration])
    state = tmp_path / "fresh-test-state"
    state.mkdir()
    with pytest.raises(RuntimeError, match="size/hash guard"):
        HARNESS.prepare_client_cache(source, state)
    assert not list(state.iterdir())


def test_outer_requires_bundled_client_before_preparing_runtime(tmp_path, monkeypatch):
    source = tmp_path / "payload/source"
    (source / "src/kirabridge").mkdir(parents=True)
    (source / "src/kirabridge/__init__.py").write_text('__version__ = "fixture"\n')
    (source.parent / "wheels").mkdir()
    (source.parent / "wheels/kirabridge-fixture-py3-none-any.whl").write_bytes(b"fixture")
    monkeypatch.setattr(HARNESS, "__file__", str(source / "scripts/accept_windows_setup.py"))
    monkeypatch.setattr(
        HARNESS, "prepare_command", lambda *a, **k: pytest.fail("No preparation allowed")
    )
    with (tmp_path / "receipt.json").open("x+") as output:
        with pytest.raises(FileNotFoundError):
            HARNESS.outer(output, {"passed": False})
    assert json.loads((tmp_path / "receipt.json").read_text())["stage"] == "verify_bundled_client"


def test_outer_refuses_missing_frozen_wheel_before_any_preparation(tmp_path, monkeypatch):
    root = tmp_path / "source"
    (root / "src/kirabridge").mkdir(parents=True)
    (root / "src/kirabridge/__init__.py").write_text('__version__ = "missing"\n')
    monkeypatch.setattr(HARNESS, "__file__", str(root / "scripts/accept_windows_setup.py"))
    monkeypatch.setattr(
        HARNESS, "prepare_command", lambda *a, **k: pytest.fail("No preparation allowed")
    )
    with (tmp_path / "receipt.json").open("x+") as output:
        with pytest.raises(RuntimeError, match="Frozen wheel"):
            HARNESS.outer(output, {"passed": False})
