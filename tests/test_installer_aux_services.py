import importlib.util
import json
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
        self.crash_for = set()
        self.source_paths = {}

    def __call__(self, *argv, timeout=20):
        self.calls.append(argv)
        label = argv[-1].rsplit("/", 1)[-1].removesuffix(".plist")
        if (argv[0], label) in self.crash_for:
            self.crash_for.remove((argv[0], label))
            raise KeyboardInterrupt("simulated process interruption")
        if (argv[0], label) in self.raise_for:
            raise subprocess.TimeoutExpired(argv, timeout)
        code, out = 0, ""
        if argv[0] == "print":
            if label in self.loaded:
                loaded_path = self.source_paths.get(label, self.agents / (label + ".plist"))
                out = f"\tpath = {loaded_path}\n"
            else:
                code = 113
        elif argv[0] == "bootstrap" and label in self.fail_bootstrap:
            code = 1
        if argv[0] == "bootout" and code == 0:
            self.loaded.discard(label)
        elif argv[0] == "bootstrap" and code == 0:
            self.loaded.add(label)
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


def test_backup_preserves_aux_plist_mode(installer, world):
    world.files["approvals"].chmod(0o640)

    installer.sync_aux_services(world.args, world.new, world.backup, restart_tunnel=False)

    saved = world.backup / "aux.com.kirabridge.approvals.plist"
    assert saved.stat().st_mode & 0o777 == 0o640


def test_sync_persists_recovery_before_rewrite_and_recovers_interruption(
    installer, world, monkeypatch
):
    current = world.args.prefix / "current.json"
    transaction = {"backup": str(world.backup), "aux_services": []}
    installer.jwrite(current, transaction)
    original = {key: world.files[key].read_bytes() for key in ("approvals", "chat")}
    real_atomic = installer.atomic
    interrupted = False

    def interrupt_after_aux_replace(path, data, mode=0o600, *, exact_mode=False):
        nonlocal interrupted
        if Path(path) == world.files["approvals"] and not interrupted:
            checkpoint = json.loads(current.read_text())
            record = next(
                item
                for item in checkpoint["aux_services"]
                if item["plist"] == str(world.files["approvals"])
            )
            assert record["original_sha256"]
            assert record["installed_sha256"]
            interrupted = True
            real_atomic(path, data, mode, exact_mode=exact_mode)
            raise OSError("simulated interruption after atomic replacement")
        return real_atomic(path, data, mode, exact_mode=exact_mode)

    monkeypatch.setattr(installer, "atomic", interrupt_after_aux_replace)
    installer.sync_aux_services(world.args, world.new, world.backup, transaction=transaction)

    assert interrupted
    recovery = json.loads(current.read_text())
    installer.restore_aux_services(recovery)
    assert {key: world.files[key].read_bytes() for key in original} == original
    # A repeated recovery safely recognizes that the original definitions are back.
    installer.restore_aux_services(recovery)
    assert {key: world.files[key].read_bytes() for key in original} == original


def test_recovery_reloads_owned_service_interrupted_after_bootout(installer, world):
    current = world.args.prefix / "current.json"
    transaction = {"backup": str(world.backup), "aux_services": []}
    installer.jwrite(current, transaction)
    original = world.files["approvals"].read_bytes()
    world.fake.crash_for = {("bootstrap", "com.kirabridge.approvals")}

    with pytest.raises(KeyboardInterrupt, match="simulated process interruption"):
        installer.sync_aux_services(world.args, world.new, world.backup, transaction=transaction)

    assert world.files["approvals"].read_bytes() != original
    assert "com.kirabridge.approvals" not in world.fake.loaded
    recovery = json.loads(current.read_text())
    record = next(
        item for item in recovery["aux_services"] if item["plist"] == str(world.files["approvals"])
    )
    assert record["was_loaded"] is True

    installer.restore_aux_services(recovery, current)

    assert world.files["approvals"].read_bytes() == original
    assert "com.kirabridge.approvals" in world.fake.loaded
    bootstrap_count = sum(call[0] == "bootstrap" for call in world.fake.calls)
    installer.restore_aux_services(json.loads(current.read_text()), current)
    assert sum(call[0] == "bootstrap" for call in world.fake.calls) == bootstrap_count


def test_recovery_preserves_foreign_loaded_binding(installer, world, monkeypatch):
    current = world.args.prefix / "current.json"
    transaction = {"backup": str(world.backup), "aux_services": []}
    installer.jwrite(current, transaction)
    original = world.files["approvals"].read_bytes()
    installer.sync_aux_services(world.args, world.new, world.backup, transaction=transaction)
    recovery = json.loads(current.read_text())
    world.fake.source_paths["com.kirabridge.approvals"] = world.agents / "foreign.plist"
    world.fake.calls.clear()
    warnings = []
    monkeypatch.setattr(installer, "report", lambda *args, **kwargs: warnings.append(args))

    assert installer.restore_aux_services(recovery, current) is False

    assert world.files["approvals"].read_bytes() == original
    assert "com.kirabridge.approvals" in world.fake.loaded
    assert not any(
        call[0] in {"bootout", "bootstrap"} and "com.kirabridge.approvals" in " ".join(call)
        for call in world.fake.calls
    )
    assert any("fremder plist" in " ".join(map(str, warning)) for warning in warnings)


def test_recovery_reloads_owned_service_that_became_loaded(installer, world):
    current = world.args.prefix / "current.json"
    transaction = {"backup": str(world.backup), "aux_services": []}
    installer.jwrite(current, transaction)
    original = world.files["approvals"].read_bytes()
    world.fake.loaded.remove("com.kirabridge.approvals")

    installer.sync_aux_services(world.args, world.new, world.backup, transaction=transaction)

    recovery = json.loads(current.read_text())
    record = next(
        item for item in recovery["aux_services"] if item["plist"] == str(world.files["approvals"])
    )
    assert record["was_loaded"] is False
    world.fake.loaded.add("com.kirabridge.approvals")
    world.fake.calls.clear()

    assert installer.restore_aux_services(recovery, current) is True

    assert world.files["approvals"].read_bytes() == original
    assert "com.kirabridge.approvals" in world.fake.loaded
    assert [
        call[0]
        for call in world.fake.calls
        if call[0] in {"bootout", "bootstrap"} and "com.kirabridge.approvals" in call[-1]
    ] == ["bootout", "bootstrap"]


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
