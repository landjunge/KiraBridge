"""Outer receipt/runtime guards only; synthetic data is not native acceptance."""

import importlib.util
import json
from pathlib import Path

import pytest

SOURCE = Path(__file__).parents[1] / "scripts/accept_windows_setup.py"
SPEC = importlib.util.spec_from_file_location("native_setup_acceptance_guard", SOURCE)
HARNESS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HARNESS)


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
