"""Deployment guard branches only; mocks do not establish macOS runner acceptance."""

import importlib.util
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest


@pytest.fixture
def host(monkeypatch):
    source = Path(__file__).resolve().parents[1] / "scripts/check_macos_ci_host.py"
    spec = importlib.util.spec_from_file_location("macos_ci_host_tests", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    state = SimpleNamespace(
        system="Darwin",
        machine="x86_64",
        name="kirabridge-ci",
        uid=502,
        home="/Users/kirabridge-ci",
        groups=[20],
        primary_gid=20,
        mode=0o700,
        owner=502,
        production_access=False,
        gui=0,
        calls=[],
    )

    class FakePath(PurePosixPath):
        @classmethod
        def home(cls):
            return cls(state.home)

        def stat(self):
            return SimpleNamespace(st_uid=state.owner, st_mode=state.mode)

        def is_dir(self):
            return True

        def resolve(self):
            return self

    def run(argv, **kwargs):
        state.calls.append(argv)
        assert kwargs["timeout"] == 10
        return SimpleNamespace(returncode=state.gui)

    monkeypatch.setattr(module, "Path", FakePath)
    monkeypatch.setattr(module.platform, "system", lambda: state.system)
    monkeypatch.setattr(module.platform, "machine", lambda: state.machine)
    monkeypatch.setattr(module.os, "getuid", lambda: state.uid)
    monkeypatch.setattr(module.os, "getgroups", lambda: state.groups)
    monkeypatch.setattr(module.os, "getgid", lambda: state.primary_gid)
    monkeypatch.setattr(module.os, "access", lambda *args: state.production_access)
    monkeypatch.setattr(
        module.pwd,
        "getpwuid",
        lambda uid: SimpleNamespace(
            pw_name=state.name, pw_uid=uid, pw_gid=state.primary_gid, pw_dir=state.home
        ),
    )
    monkeypatch.setattr(module.grp, "getgrnam", lambda name: SimpleNamespace(gr_gid=80))
    monkeypatch.setattr(module.subprocess, "run", run)
    monkeypatch.setenv("GITHUB_WORKSPACE", "/Users/kirabridge-ci/actions-runner/_work/repo")
    return module, state


def test_isolated_identity_reaches_only_its_own_readonly_gui_probe(host):
    module, state = host
    module.check_host()
    assert state.calls == [["/bin/launchctl", "print", "gui/502"]]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("machine", "arm64", "Intel macOS"),
        ("uid", 501, "dedicated"),
        ("name", "landjunge", "dedicated"),
        ("groups", [20, 80], "administrator"),
        ("primary_gid", 80, "administrator"),
        ("mode", 0o755, "0700"),
        ("production_access", True, "Production home"),
        ("gui", 113, "GUI login"),
    ],
)
def test_unisolated_or_wrong_architecture_host_is_refused(host, field, value, message):
    module, state = host
    setattr(state, field, value)
    with pytest.raises(RuntimeError, match=message):
        module.check_host()
    if field != "gui":
        assert state.calls == []


def test_workspace_outside_dedicated_home_is_refused(host, monkeypatch):
    module, state = host
    monkeypatch.setenv("GITHUB_WORKSPACE", "/Users/landjunge/KiraBridge")
    with pytest.raises(RuntimeError, match="workspace"):
        module.check_host()
    assert state.calls == []


@pytest.mark.parametrize("access_mode", [4, 2, 1])
def test_partial_production_home_permission_is_also_refused(host, monkeypatch, access_mode):
    module, state = host
    monkeypatch.setattr(module.os, "access", lambda path, mode: mode == access_mode)
    with pytest.raises(RuntimeError, match="Production home"):
        module.check_host()
    assert state.calls == []
