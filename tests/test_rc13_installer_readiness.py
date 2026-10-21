"""Regression checks for RC13 installer readiness.

Tests deliberately never launch or stop a system service.
"""
from pathlib import Path

def test_installer_preserves_previous_service_on_failed_start():
    source = (Path(__file__).resolve().parents[1] / "installer" / "install.py").read_text()
    assert "rollback(args)" in source
    assert "New daemon readiness not proven" in source
    assert "last health:" in source

def test_installer_requires_daemon_identity_and_dispatcher():
    source = (Path(__file__).resolve().parents[1] / "installer" / "install.py").read_text()
    assert 'health.get("version") == version' in source
    assert 'health.get("dispatcher_active")' in source
    assert 'health.get("runtime", {}).get("config_sha256") == sha(args.config)' in source

def test_config_compatibility_checked_before_switch():
    source = (Path(__file__).resolve().parents[1] / "installer" / "install.py").read_text()
    activation = source.split("def activate(args, release):", 1)[1].split("\ndef rollback(", 1)[0]
    assert "load_config(sys.argv[1])" in activation
    assert activation.index("load_config(sys.argv[1])") < activation.index("stop_service(args)")

def test_service_credentials_and_network_checked_before_switch():
    source = (Path(__file__).resolve().parents[1] / "installer" / "install.py").read_text()
    activation = source.split("def activate(args, release):", 1)[1].split("\ndef rollback(", 1)[0]
    for marker in ("load_service_credentials(config)", "config.validate_network()"):
        assert marker in activation
        assert activation.index(marker) < activation.index("stop_service(args)")

def test_rollback_checks_restored_release_not_failed_candidate():
    source = (Path(__file__).resolve().parents[1] / "installer" / "install.py").read_text()
    rollback = source.split("def rollback(args):", 1)[1].split("\ndef status(", 1)[0]
    assert 'wait_health(args, Path(active["previous"]["release"]), active["previous_version"])' in rollback
    assert 'json.loads(run([args.launcher, "status"], capture=True, timeout=8))' in rollback
    assert 'legacy version, dispatcher or launchd registration mismatch' in rollback

def test_existing_legacy_daemon_uses_its_own_launcher_for_status():
    source = (Path(__file__).resolve().parents[1] / "installer" / "install.py").read_text()
    activation = source.split("def activate(args, release):", 1)[1].split("\ndef rollback(", 1)[0]
    assert 'if old else json.loads(run([args.launcher, "status"], capture=True, timeout=8))' in activation

def test_launchd_registration_required_before_ready():
    source = (Path(__file__).resolve().parents[1] / "installer" / "install.py").read_text()
    block = source.split("def wait_health(args, release, version):", 1)[1].split("\ndef validate_service_owner(", 1)[0]
    assert 'if args.service == "none" or loaded(args):' in block
    assert 'expected launchd service is not registered' in block

def test_start_path_reports_launchctl_bootstrap_failure():
    source = (Path(__file__).resolve().parents[1] / "installer" / "install.py").read_text()
    start = source.split("def start_service(args):", 1)[1].split("\ndef wait_health(", 1)[0]
    assert "launchd bootstrap failed" in start
    assert "result.stderr or result.stdout" in start
    assert "if not loaded(args):" in start
    assert "launchd plist missing" in start
