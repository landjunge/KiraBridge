"""Static safety contract for the RC13 one-command macOS entrypoint."""

from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "install-rc13.sh"


def test_entrypoint_is_fail_fast_and_resolves_its_checkout():
    source = SCRIPT.read_text()
    assert "set -euo pipefail" in source
    assert 'ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"' in source
    assert 'REF="$(git rev-parse HEAD)"' in source


def test_prepare_mode_never_calls_install():
    source = SCRIPT.read_text()
    prepare = source.split('if [[ "${1:-}" == "--prepare" ]]; then', 1)[1].split("\nfi", 1)[0]
    assert "installer/install.py prepare" in prepare
    assert "installer/install.py install" not in prepare


def test_install_entrypoint_requires_clean_checkout_and_prerequisites():
    source = SCRIPT.read_text()
    assert "git status --porcelain --untracked-files=no" in source
    assert "Python 3.11 or newer required" in source
    assert 'exec python3 installer/install.py install --repo "$ROOT" --ref "$REF"' in source
