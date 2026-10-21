"""RC13 verification must not mutate the service."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_preflight_checks_credentials_before_switch():
    source = (ROOT / "installer/install.py").read_text()
    block = source.split("def preflight(args, release):", 1)[1].split("\ndef activate(", 1)[0]
    assert "load_service_credentials(config)" in block
    assert "config.validate_network()" in block
    assert 'if not loaded(args):' in block
    assert 'run([args.launcher, "status"]' in block
    assert "stop_service(args)" not in block
    assert "start_service(args)" not in block
    assert "atomic(args.launcher" not in block

def test_install_requires_preflight():
    source = (ROOT / "installer/install.py").read_text()
    assert "preflight(args, release)\n                activate(args, release)" in source

def test_shell_exposes_read_only_check():
    source = (ROOT / "scripts/install-rc13.sh").read_text()
    assert '"$mode" == "--check"' in source
    assert 'installer/install.py preflight --repo "$ROOT" --ref "$REF"' in source
