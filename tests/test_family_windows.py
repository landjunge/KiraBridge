"""Narrow native CLI/ABI and real Intel Swift fixture; never move product windows."""

import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from kirabridge import cli
from kirabridge import family_windows as family
from kirabridge.bridge_core.config import load_config
from kirabridge.bridge_core.models import BridgeError, UncertainExecution


@pytest.fixture
def policy(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    apps = tmp_path / "Applications"
    apps.mkdir()
    for product in family.PRODUCTS:
        (apps / (product + ".app")).mkdir()
    path = tmp_path / "policy.toml"
    path.write_text(
        "data_dir = " + json.dumps(str(tmp_path / "never-created")) + "\n"
        '[principals.local]\npermission_level="full"\n'
        "roots=" + json.dumps([str(apps)]) + "\n"
        'capabilities=["windows.focus","accessibility.set","apps.launch"]\n'
    )
    path.chmod(0o600)
    profile = family.registration_template(load_config(str(path)), "local")
    profile["enabled"] = True
    for product, entry in profile["apps"].items():
        entry["path"] = str(apps / (product + ".app"))
    registry = family.registry_path()
    registry.parent.mkdir(parents=True)
    registry.write_text(json.dumps(profile))
    registry.chmod(0o600)
    return path, profile


def args(policy, action="switch", **kw):
    return SimpleNamespace(
        command="family",
        config=str(policy[0]),
        principal="local",
        action=action,
        target="threaddesk",
        source_pid="123",
        source_start=None,
        **kw,
    )


def receipt():
    return {
        "success": True,
        "active_product": "threaddesk",
        "actual_outer_bounds": {"x": -500, "y": 24, "width": 1358, "height": 664},
        "visible_family_windows": 1,
    }


class Transport:
    def __init__(self, value=None, mutate=None):
        self.value = value if value is not None else receipt()
        self.mutate = mutate
        self.calls = []
        self.closed = False

    async def request(self, operation, arguments, *, principal, before_send):
        if self.mutate:
            self.mutate()
        before_send()
        self.calls.append((operation, arguments, principal))
        return self.value

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_exact_abi_no_source_timestamp_needed(policy, monkeypatch):
    monkeypatch.setattr(family.sys, "platform", "darwin")
    native = Transport()
    result = await family.execute_family(args(policy), transport=native)
    assert result == receipt()
    assert native.calls == [
        ("family.window.switch", {"target": "threaddesk", "source_pid": 123}, "local")
    ]
    assert native.closed


@pytest.mark.parametrize(
    "change",
    [
        {"success": False},
        {"active_product": "4allpass"},
        {"visible_family_windows": 2},
        {"visible_family_windows": True},
        {"actual_outer_bounds": {"x": 0, "y": 0, "width": 0, "height": 1}},
        {"actual_outer_bounds": {"x": 0, "y": 0, "width": float("nan"), "height": 1}},
        {"error": {"code": "failed"}},
        {"execution_outcome_unknown": True},
    ],
)
def test_bad_receipt_is_never_success(change):
    with pytest.raises(UncertainExecution):
        family.validate_receipt({**receipt(), **change}, "threaddesk")


@pytest.mark.parametrize(
    "target,pid,start",
    [
        ("shell", 123, None),
        ("threaddesk", True, None),
        ("threaddesk", 0, None),
        ("threaddesk", 2**31, None),
        ("threaddesk", 123, "not-a-start"),
    ],
)
def test_only_fixed_catalog_and_exact_pid(target, pid, start):
    with pytest.raises(ValidationError):
        family.FamilyRequest(target=target, source_pid=pid, source_start=start)


@pytest.mark.asyncio
async def test_denied_policy_and_changed_policy_prevent_dispatch(policy, monkeypatch):
    monkeypatch.setattr(family.sys, "platform", "darwin")

    def revoke():
        policy[0].write_text("[principals.local]\ncapabilities=[]\n")

    native = Transport(mutate=revoke)
    with pytest.raises(BridgeError):
        await family.execute_family(args(policy), transport=native)
    assert native.calls == [] and native.closed


@pytest.mark.parametrize("action", ["switch", "path-check"])
@pytest.mark.parametrize("restriction", ["empty", "unrelated", "state", "read_only"])
@pytest.mark.asyncio
async def test_registration_never_broadens_path_scope(policy, monkeypatch, restriction, action):
    monkeypatch.setattr(family.sys, "platform", "darwin")
    path, profile = policy
    apps = path.parent / "Applications"
    original = path.read_text()
    if restriction == "state":
        original = original.replace(str(path.parent / "never-created"), str(apps))
    else:
        roots = [] if restriction != "unrelated" else [str(path.parent / "elsewhere")]
        original = original.replace(
            "roots=" + json.dumps([str(apps)]), "roots=" + json.dumps(roots)
        )
        if restriction == "read_only":
            original += "read_roots=" + json.dumps([str(apps)]) + "\n"
    path.write_text(original)
    # The registration matches the CURRENT fully automatic capability grants;
    # refusal must be PathScope, rather than a stale policy or disabled profile.
    profile["policy"] = family.policy_snapshot(load_config(str(path)), "local")
    family.registry_path().write_text(json.dumps(profile))
    native = Transport()
    with pytest.raises(BridgeError) as exc:
        await family.execute_family(args(policy, action), transport=native)
    assert exc.value.code == "path_denied"
    assert not native.calls


@pytest.mark.asyncio
async def test_scope_is_rechecked_before_dispatch_without_following_symlinks(policy, monkeypatch):
    monkeypatch.setattr(family.sys, "platform", "darwin")
    target = Path(policy[1]["apps"]["threaddesk"]["path"])

    def replace():
        retained = target.with_suffix(".retained")
        target.rename(retained)
        target.symlink_to(retained, target_is_directory=True)

    native = Transport(mutate=replace)
    with pytest.raises(BridgeError) as exc:
        await family.execute_family(args(policy), transport=native)
    assert exc.value.code == "path_denied"
    assert not native.calls and native.closed


@pytest.mark.asyncio
async def test_path_check_returns_fresh_descriptor_proof_without_store(policy, monkeypatch, capsys):
    def forbidden(*a, **kw):
        pytest.fail("Path proof must not initialize Bridge/Store/native transport")

    monkeypatch.setattr(cli, "Bridge", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(family, "NativeSystemTransport", forbidden)
    await cli.execute(args(policy, "path-check"))
    value = json.loads(capsys.readouterr().out)
    target = Path(policy[1]["apps"]["threaddesk"]["path"])
    assert value == {
        "success": True,
        "target": "threaddesk",
        "app_path": str(target),
        "policy_sha256": policy[1]["policy"]["sha256"],
        "registry_sha256": family.hashlib.sha256(family.registry_path().read_bytes()).hexdigest(),
        "directory_device": str(target.stat().st_dev),
        "directory_inode": str(target.stat().st_ino),
    }
    assert not (policy[0].parent / "never-created").exists()


@pytest.mark.asyncio
async def test_registry_cannot_broaden_paths_bundle_ids_or_principal(policy, monkeypatch):
    monkeypatch.setattr(family.sys, "platform", "darwin")
    profile = policy[1]
    profile["apps"]["threaddesk"]["bundle_id"] = "com.apple.Terminal"
    family.registry_path().write_text(json.dumps(profile))
    native = Transport()
    with pytest.raises(BridgeError):
        await family.execute_family(args(policy), transport=native)
    assert not native.calls


@pytest.mark.asyncio
async def test_missing_pinned_backend_never_uses_source_or_global_app_fallback(policy, monkeypatch):
    monkeypatch.setattr(family.sys, "platform", "darwin")
    monkeypatch.setattr(family, "installed_native_contract", lambda _: {"expected_commit": None})
    with pytest.raises(BridgeError, match="pinned installed"):
        await family.execute_family(args(policy))


@pytest.mark.asyncio
async def test_native_entry_does_not_initialize_bridge_or_sqlite(policy, monkeypatch, capsys):
    def forbidden(*a, **kw):
        pytest.fail("Family adapter must not initialize Bridge/Store/SQLite")

    monkeypatch.setattr(cli, "Bridge", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    await cli.execute(args(policy, "registration"))
    result = json.loads(capsys.readouterr().out)
    assert result["enabled"] is False
    assert set(result["apps"]) == set(family.PRODUCTS)
    assert not (policy[0].parent / "never-created").exists()


@pytest.mark.asyncio
async def test_cli_unknown_is_nonzero_top_level_safe_json(policy, monkeypatch, capsys):
    async def unknown(_):
        raise UncertainExecution("family_focus_unknown", "not an effect receipt")

    monkeypatch.setattr(family, "execute_family", unknown)
    with pytest.raises(SystemExit) as exc:
        await cli.execute(args(policy))
    assert exc.value.code == 3
    value = json.loads(capsys.readouterr().out)
    assert value["success"] is False and value["execution_outcome_unknown"] is True
    assert value["error"]["code"] == "family_focus_unknown" and value["error"]["message"]


@pytest.mark.asyncio
async def test_other_platform_is_honestly_unsupported(policy, monkeypatch):
    monkeypatch.setattr(family.sys, "platform", "linux")
    with pytest.raises(BridgeError, match="macOS"):
        await family.execute_family(args(policy))


@pytest.mark.skipif(
    sys.platform != "darwin" or not shutil.which("xcrun"), reason="macOS native compiler fixture"
)
def test_intel_native_fixture_without_product_window_effects(tmp_path):
    root = Path(__file__).resolve().parents[1]
    binary = tmp_path / "family-fixture"
    names = [
        "FamilyWindowBroker.swift",
        "FamilyWindowNative.swift",
        "SystemBridge.swift",
        "SystemControl.swift",
        "SystemServices.swift",
        "SystemKeyboard.swift",
        "SystemShortcuts.swift",
        "SystemSpecialKeys.swift",
    ]
    command = [
        "xcrun",
        "swiftc",
        "-swift-version",
        "5",
        "-D",
        "FAMILY_WINDOW_BROKER",
        "-parse-as-library",
        "-target",
        f"{platform.machine()}-apple-macosx12.0",
        *[str(root / "integrations/desktop" / n) for n in names],
        str(root / "tests/fixtures/family_windows/main.swift"),
        "-o",
        str(binary),
    ]
    for name in [
        "Cocoa",
        "ApplicationServices",
        "CryptoKit",
        "ScreenCaptureKit",
        "UserNotifications",
        "ImageIO",
        "UniformTypeIdentifiers",
        "SystemConfiguration",
        "Security",
        "CoreAudio",
        "IOKit",
    ]:
        command.extend(["-framework", name])
    compiled = subprocess.run(command, capture_output=True, text=True, timeout=120)
    assert compiled.returncode == 0, compiled.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    value = json.loads(result.stdout.splitlines()[0])
    family.validate_receipt(value, "threaddesk")
    assert "effects_on_real_windows=0" in result.stdout


@pytest.mark.parametrize("action", ["registration", "path-check"])
def test_fresh_cli_process_never_opens_sqlite(policy, action):
    root = Path(__file__).resolve().parents[1]
    code = """import sqlite3,sys

def forbidden(*a,**kw):
    raise RuntimeError('unexpected SQLite initialization')
sqlite3.connect=forbidden
from kirabridge.cli import main
sys.argv=['kirabridge','--config',sys.argv[1],'--principal','local','family',sys.argv[2]]
if sys.argv[-1]=='path-check': sys.argv.append('threaddesk')
main()
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(policy[0]), action],
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(root / "src")},
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    if action == "registration":
        assert value["enabled"] is False
    else:
        assert value["success"] is True and value["target"] == "threaddesk"


@pytest.mark.parametrize("mode", [0o644, 0o620])
def test_registration_must_be_owner_only(policy, mode):
    family.registry_path().chmod(mode)
    with pytest.raises((BridgeError, ValueError)):
        family.read_registry()


def test_registration_does_not_authorize_another_principal(policy):
    with pytest.raises(BridgeError):
        family.policy_snapshot(load_config(str(policy[0])), "chatgpt")
