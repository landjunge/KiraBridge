"""The downloadable package must restore its pinned tree without parent history."""

import importlib.util
import subprocess
from pathlib import Path


def git(repo, *args):
    return (
        subprocess.check_output(
            [
                "git",
                "-c",
                "user.name=Release test",
                "-c",
                "user.email=release@example.invalid",
                "-c",
                "commit.gpgsign=false",
                *args,
            ],
            cwd=repo,
        )
        .decode()
        .strip()
    )


def test_packaged_source_restores_shallow_boundary(tmp_path):
    module_path = Path(__file__).resolve().parents[1] / "installer/install-release.py"
    spec = importlib.util.spec_from_file_location("release_installer", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original = tmp_path / "original"
    original.mkdir()
    git(original, "init", "--quiet", "-b", "release")
    (original / "proof.txt").write_text("before\n")
    git(original, "add", ".")
    git(original, "commit", "--quiet", "-m", "before")
    parent = git(original, "rev-parse", "HEAD")
    (original / "proof.txt").write_text("release\n")
    git(original, "add", ".")
    git(original, "commit", "--quiet", "-m", "release")
    ref = git(original, "rev-parse", "HEAD")
    (original / ".git/shallow").write_text(ref + "\n")
    bundle = tmp_path / "source.bundle"
    git(original, "bundle", "create", str(bundle), "refs/heads/release")
    restored = tmp_path / "restored"
    module.restore_source(bundle, ref, restored)
    assert git(restored, "rev-parse", "HEAD") == ref
    assert (restored / "proof.txt").read_text() == "release\n"
    assert git(restored, "rev-parse", "--is-shallow-repository") == "true"
    result = subprocess.run(
        ["git", "cat-file", "-e", parent], cwd=restored, capture_output=True, check=False
    )
    assert result.returncode != 0
    target = tmp_path / "source.tar"
    git(restored, "archive", "--format=tar", ref, "-o", str(target))
    assert target.stat().st_size > 0
