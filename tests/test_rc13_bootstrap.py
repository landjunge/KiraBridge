"""Bootstrap safety checks for RC13 release staging."""

from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "bootstrap-rc13.sh"


def test_bootstrap_defaults_to_safe_prepare():
    source = SCRIPT.read_text()
    assert 'ACTION="${1:---prepare}"' in source
    assert 'exec bash "$DEST/scripts/install-rc13.sh" "$ACTION"' in source
    assert "git clone --depth 1 --single-branch" in source


def test_bootstrap_does_not_destroy_local_changes_or_unrelated_repo():
    source = SCRIPT.read_text()
    assert "status --porcelain" in source
    assert "remote get-url origin" in source
    assert "Refusing to replace non-repository" in source
    assert "rm -rf" not in source
    assert "sudo " not in source
