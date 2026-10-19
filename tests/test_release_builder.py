"""Release output guards preserve existing artifacts before running build tools."""

import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def builder(monkeypatch):
    source = Path(__file__).resolve().parents[1] / "scripts/build_release.py"
    spec = importlib.util.spec_from_file_location("kirabridge_release_builder_tests", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def unexpected(*args, **kwargs):
        pytest.fail("An invalid output destination must be rejected before Git or uv is invoked")

    monkeypatch.setattr(module, "git", unexpected)
    monkeypatch.setattr(module.subprocess, "run", unexpected)
    monkeypatch.setattr(module.subprocess, "check_output", unexpected)
    return module


def test_release_refuses_nonempty_output_without_changing_existing_artifacts(tmp_path, builder):
    destination = tmp_path / "frozen-release"
    destination.mkdir()
    previous = {
        "old-release.tar.gz": b"frozen archive\x00\x80\xff",
        "SHA256SUMS": b"original historical checksum manifest\n",
        "LICENSE": b"original license\n",
    }
    for name, contents in previous.items():
        (destination / name).write_bytes(contents)
    with pytest.raises(SystemExit, match="empty output directory"):
        builder.build(destination)
    assert {path.name: path.read_bytes() for path in destination.iterdir()} == previous


@pytest.mark.parametrize("target_exists", [True, False])
def test_release_refuses_symlink_output_before_following_or_creating_target(
    tmp_path, builder, target_exists
):
    target = tmp_path / "outside-output"
    if target_exists:
        target.mkdir()
    destination = tmp_path / "release-link"
    destination.symlink_to(target, target_is_directory=True)
    with pytest.raises(SystemExit, match="empty output directory"):
        builder.build(destination)
    assert destination.is_symlink() and destination.readlink() == target
    if target_exists:
        assert list(target.iterdir()) == []
    else:
        assert not target.exists()
