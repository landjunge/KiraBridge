import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def visible(monkeypatch):
    path = Path(__file__).parents[1] / "installer/visible_terminal.py"
    spec = importlib.util.spec_from_file_location("visible_installer_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    stream = SimpleNamespace(isatty=lambda: True, fileno=lambda: 7)
    module.sys = SimpleNamespace(platform="darwin", stdin=stream, stderr=stream)
    module.os = SimpleNamespace(
        ttyname=lambda _: "/dev/ttys010", getpid=lambda: 111, getuid=lambda: 501
    )
    identities = {
        111: ("111", "110", "501", "ttys010", "Mon", "Oct", "26", "16:00:00", "2026", "python"),
        110: ("110", "1", "501", "ttys010", "Mon", "Oct", "26", "15:00:00", "2026", "zsh"),
    }
    monkeypatch.setattr(module, "process_identity", identities.__getitem__)
    windows = [
        {
            "window_id": 700,
            "visible": True,
            "frontmost_window": True,
            "tabs": [{"tab_index": 0, "tty": "/dev/ttys010", "selected": True}],
        }
    ]
    monkeypatch.setattr(module, "inventory", lambda: windows)
    return module, identities, windows


def test_visible_install_requires_same_fresh_window_tab_tty_and_processes(visible):
    module, _, _ = visible
    proof = module.confirm_visible_terminal()
    assert proof == {"window_id": 700, "tab_index": 0, "tty": "/dev/ttys010"}
    assert module.confirm_visible_terminal(proof) == proof


@pytest.mark.parametrize(
    "case",
    [
        "no_tty",
        "hidden",
        "background_window",
        "background_tab",
        "duplicate",
        "different_tty",
        "target_changed",
    ],
)
def test_visibility_uncertainty_never_permits_activation(visible, monkeypatch, case):
    module, _, windows = visible
    expected = None
    if case == "no_tty":
        monkeypatch.setattr(module.sys.stdin, "isatty", lambda: False)
    elif case == "hidden":
        windows[0]["visible"] = False
    elif case == "background_window":
        windows[0]["frontmost_window"] = False
    elif case == "background_tab":
        windows[0]["tabs"][0]["selected"] = False
    elif case == "duplicate":
        windows.append(dict(windows[0]))
    elif case == "different_tty":
        windows[0]["tabs"][0]["tty"] = "/dev/ttys011"
    else:
        expected = {"window_id": 701, "tab_index": 0, "tty": "/dev/ttys010"}
    with pytest.raises(module.VisibilityError):
        module.confirm_visible_terminal(expected)


def test_pid_reuse_or_exec_during_inventory_is_rejected(visible):
    module, identities, windows = visible

    def changed():
        identities[110] = (*identities[110][:-1], "unconfirmed-process")
        return windows

    module.inventory = changed
    with pytest.raises(module.VisibilityError, match="geändert"):
        module.confirm_visible_terminal()


def test_visibility_probe_transport_failure_is_not_absence(visible, monkeypatch):
    module, _, _ = visible

    def unavailable():
        raise OSError("synthetic failure")

    monkeypatch.setattr(module, "inventory", unavailable)
    with pytest.raises(module.VisibilityError, match="nicht nachgewiesen"):
        module.confirm_visible_terminal()


def test_native_inventory_rejects_background_and_malformed_responses(monkeypatch):
    path = Path(__file__).parents[1] / "installer/visible_terminal.py"
    spec = importlib.util.spec_from_file_location("visible_inventory_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for output in ('{"frontmost":false,"windows":[]}', "not json"):
        monkeypatch.setattr(
            module.subprocess,
            "run",
            lambda *a, _output=output, **kw: SimpleNamespace(
                returncode=0, stdout=_output, stderr=""
            ),
        )
        with pytest.raises(module.VisibilityError):
            module.inventory()


def test_installer_refuses_missing_verifier_hash_before_import(tmp_path):
    import json

    path = Path(__file__).parents[1] / "installer/install.py"
    spec = importlib.util.spec_from_file_location("visible_hook_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / "release.json").write_text(json.dumps({"files": {}}))
    with pytest.raises(RuntimeError, match="checksum"):
        module.require_visible_terminal(
            SimpleNamespace(require_visible_terminal=True, bundle=tmp_path)
        )


def test_headless_test_mode_never_invokes_native_verifier(monkeypatch):
    path = Path(__file__).parents[1] / "installer/install.py"
    spec = importlib.util.spec_from_file_location("headless_visible_hook_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def forbidden(*a, **kw):
        pytest.fail("Headless test/status must not load native visibility code")

    monkeypatch.setattr(module, "Path", forbidden)
    module.require_visible_terminal(SimpleNamespace(require_visible_terminal=False))


def test_internal_recovery_preserves_owner_guard_after_visibility_lost(tmp_path, monkeypatch):
    import json

    path = Path(__file__).parents[1] / "installer/install.py"
    spec = importlib.util.spec_from_file_location("recovery_visible_hook_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    args = SimpleNamespace(
        prefix=tmp_path,
        config=tmp_path / "config",
        launcher=tmp_path / "launcher",
        plist=tmp_path / "plist",
        service="launchd",
    )
    (tmp_path / "current.json").write_text(
        json.dumps(
            {key: str(getattr(args, key)) for key in ("config", "launcher", "plist", "service")}
        )
    )

    def lost(*a):
        raise RuntimeError("visibility lost")

    def owner(*a):
        raise RuntimeError("owner guard retained")

    monkeypatch.setattr(module, "require_visible_terminal", lost)
    monkeypatch.setattr(module, "validate_service_owner", owner)
    with pytest.raises(RuntimeError, match="visibility lost"):
        module.rollback(args)
    with pytest.raises(RuntimeError, match="owner guard retained"):
        module.rollback(args, _compensating=True)


def test_verifier_executes_only_the_bytes_already_hashed(tmp_path, monkeypatch):
    import hashlib
    import json

    path = Path(__file__).parents[1] / "installer/install.py"
    spec = importlib.util.spec_from_file_location("verified_bytes_visible_hook_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    verifier = tmp_path / "visible_terminal.py"
    verified = b'def confirm_visible_terminal(expected): return {"verified": True}\n'
    verifier.write_bytes(verified)
    (tmp_path / "release.json").write_text(
        json.dumps(
            {"files": {"installer/visible_terminal.py": hashlib.sha256(verified).hexdigest()}}
        )
    )
    monkeypatch.setattr(module, "__file__", str(tmp_path / "install.py"))
    original = module.hashlib.sha256

    def replace_after_read(data):
        verifier.write_text('raise RuntimeError("unverified replacement executed")')
        return original(data)

    monkeypatch.setattr(module.hashlib, "sha256", replace_after_read)
    args = SimpleNamespace(require_visible_terminal=True, bundle=tmp_path)
    module.require_visible_terminal(args)
    assert args.visible_terminal_proof == {"verified": True}
