import importlib.util
import plistlib
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def installer():
    path = Path(__file__).parents[1] / "installer/install.py"
    spec = importlib.util.spec_from_file_location("install_aux_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeLaunchctl:
    def __init__(self, agents):
        self.agents = agents
        self.calls = []
        self.loaded = set()
        self.fail_bootstrap = set()
        self.raise_for = set()

    def __call__(self, *argv, timeout=20):
        self.calls.append(argv)
        label = argv[-1].rsplit("/", 1)[-1].removesuffix(".plist")
        if (argv[0], label) in self.raise_for:
            raise subprocess.TimeoutExpired(argv, timeout)
        code, out = 0, ""
        if argv[0] == "print":
            if label in self.loaded:
                out = f"\tpath = {self.agents / (label + '.plist')}\n"
            else:
                code = 113
        elif argv[0] == "bootstrap" and label in self.fail_bootstrap:
            code = 1
        return subprocess.CompletedProcess(argv, code, out, "")


@pytest.fixture
def world(installer, tmp_path, monkeypatch):
    prefix = tmp_path / "install"
    old = prefix / "releases/0.8.0rc51-aaaaaaaaaaaa"
    new = prefix / "releases/0.8.0rc52-bbbbbbbbbbbb"
    for release in (old, new):
        (release / "source/.venv/bin").mkdir(parents=True)
        (release / "source/.venv/bin/python").write_text("")
        (release / "source/integrations/chat-events").mkdir(parents=True)
        (release / "source/integrations/chat-events/serve.py").write_text("")
    (old / "source/only-old.py").write_text("")
    agents = tmp_path / "LaunchAgents"
    agents.mkdir()
    py = str(old / "source/.venv/bin/python")

    def plist(label, argv):
        path = agents / f"{label}.plist"
        path.write_bytes(plistlib.dumps({"Label": label, "ProgramArguments": argv}))
        path.chmod(0o644)
        return path

    files = {
        "bridge": plist("com.kirabridge.bridge", [py, "-m", "kirabridge.cli"]),
        "approvals": plist("com.kirabridge.approvals", [py, "-m", "kirabridge.console"]),
        "chat": plist(
            "com.kirabridge.chat-events",
            [py, str(old / "source/integrations/chat-events/serve.py")],
        ),
        "grok": plist("com.kirabridge.grok-app", [py, str(old / "source/only-old.py")]),
        "chatgpt": plist("com.kirabridge.chatgpt", ["/bin/sh", str(tmp_path / "tunnel.sh")]),
    }
    fake = FakeLaunchctl(agents)
    fake.loaded = {p.stem for p in files.values()}
    monkeypatch.setattr(installer, "_launchctl", fake)
    monkeypatch.setattr(installer.time, "sleep", lambda _: None)
    backup = prefix / "backups/b1"
    backup.mkdir(parents=True)
    args = SimpleNamespace(service="launchd", prefix=prefix, plist=files["bridge"])
    return SimpleNamespace(
        args=args, new=new, old=old, files=files, fake=fake, backup=backup, agents=agents
    )


def argv(path):
    return plistlib.loads(path.read_bytes())["ProgramArguments"]


def test_sync_rewrites_backs_up_and_restarts(installer, world):
    before = {k: p.read_bytes() for k, p in world.files.items()}
    records, problems = installer.sync_aux_services(world.args, world.new, world.backup)
    assert argv(world.files["approvals"])[0] == str(world.new / "source/.venv/bin/python")
    assert argv(world.files["chat"])[1] == str(
        world.new / "source/integrations/chat-events/serve.py"
    )
    assert world.files["approvals"].stat().st_mode & 0o777 == 0o644
    assert (world.backup / "aux.com.kirabridge.approvals.plist").read_bytes() == before["approvals"]
    # Missing file in new release: untouched and reported.
    assert world.files["grok"].read_bytes() == before["grok"]
    assert [label for label, _ in problems] == ["com.kirabridge.grok-app"]
    # Bridge and unrelated tunnel plist untouched.
    assert world.files["bridge"].read_bytes() == before["bridge"]
    assert world.files["chatgpt"].read_bytes() == before["chatgpt"]
    assert {Path(r["plist"]).stem for r in records} == {
        "com.kirabridge.approvals",
        "com.kirabridge.chat-events",
    }
    ops = [c[:2] for c in world.fake.calls if c[0] != "print"]
    assert ops.count(("bootout", f"gui/{installer.os.getuid()}/com.kirabridge.approvals")) == 1
    assert sum(c[0] == "bootstrap" for c in world.fake.calls) == 2
    assert ("kickstart", "-k") in ops
    assert not any("com.kirabridge.bridge" in " ".join(c) for c in world.fake.calls)


def test_sync_is_idempotent(installer, world):
    installer.sync_aux_services(world.args, world.new, world.backup)
    after = {k: p.read_bytes() for k, p in world.files.items()}
    world.fake.calls.clear()
    records, _ = installer.sync_aux_services(
        world.args, world.new, world.backup, restart_tunnel=False
    )
    assert records == []
    assert {k: p.read_bytes() for k, p in world.files.items()} == after
    assert not [c for c in world.fake.calls if c[0] != "print"]


def test_one_failure_does_not_stop_others(installer, world):
    original = world.files["approvals"].read_bytes()
    world.fake.fail_bootstrap = {"com.kirabridge.approvals"}
    records, problems = installer.sync_aux_services(world.args, world.new, world.backup)
    assert world.files["approvals"].read_bytes() == original
    assert "com.kirabridge.approvals" in {label for label, _ in problems}
    assert [Path(r["plist"]).stem for r in records] == ["com.kirabridge.chat-events"]


@pytest.mark.parametrize("raising_action", ["print", "kickstart"])
def test_tunnel_raise_keeps_aux_records_and_returns_warning(installer, world, raising_action):
    world.fake.raise_for = {(raising_action, installer.TUNNEL_LABEL)}

    records, problems = installer.sync_aux_services(world.args, world.new, world.backup)

    assert {Path(record["plist"]).stem for record in records} == {
        "com.kirabridge.approvals",
        "com.kirabridge.chat-events",
    }
    assert any(
        label == installer.TUNNEL_LABEL and "Neustart fehlgeschlagen" in message
        for label, message in problems
    )


def test_rollback_restores_aux_plists(installer, world):
    before = world.files["chat"].read_bytes()
    records, _ = installer.sync_aux_services(world.args, world.new, world.backup)
    world.fake.calls.clear()
    installer.restore_aux_services({"backup": str(world.backup), "aux_services": records})
    assert world.files["chat"].read_bytes() == before
    assert sum(c[0] == "bootstrap" for c in world.fake.calls) == 2


def test_service_none_skips(installer, world):
    world.args.service = "none"
    before = world.files["approvals"].read_bytes()
    assert installer.sync_aux_services(world.args, world.new, world.backup) == ([], [])
    assert world.files["approvals"].read_bytes() == before
    assert world.fake.calls == []
