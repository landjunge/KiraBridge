"""RC13 macOS entrypoint: source-level regression checks only."""
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "install-rc13.sh"


def test_entrypoint_pins_checkout_and_fails_fast():
    source = SCRIPT.read_text()
    assert "set -euo pipefail" in source
    assert 'ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"' in source
    assert 'REF="$(git rev-parse HEAD)"' in source
    assert "git status --porcelain --untracked-files=no" in source


def test_prepare_keeps_active_service():
    source = SCRIPT.read_text()
    assert '"$mode" == "--prepare"' in source
    assert 'installer/install.py prepare --repo "$ROOT" --ref "$REF"' in source
    assert 'installer/install.py install --repo "$ROOT" --ref "$REF"' in source
    assert 'exec "$PYTHON" installer/install.py prepare' in source


def test_python_bootstrap_is_opt_in():
    source = SCRIPT.read_text()
    assert "uv python install 3.11" in source
    assert "brew install uv" in source
    assert 'read -r answer' in source
    assert 'uv python find' in source


def test_banner_and_errors_are_clear():
    source = SCRIPT.read_text()
    assert "K I R A   B R I D G E" in source
    assert "RC13" in source
    assert "WARNING: This step attempts to switch" in source
