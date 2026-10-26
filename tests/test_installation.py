import hashlib
import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import request

from kirabridge.bridge_core.config import load_config
from kirabridge.bridge_core.models import BridgeError
from kirabridge.chatgpt_setup import configure_tunnel, wizard
from kirabridge.install_ui import SetupUI
from kirabridge.installation import activate_managed, guided_install, idle_queue, linux_service
from kirabridge.local_runtime import setup
from kirabridge.task_manager.store import Store


def configured(tmp_path, monkeypatch, *, wrapper=False):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    result = setup(str(tmp_path / "workspace"), install_wrapper=wrapper)
    return Path(result["config"])


async def test_guided_check_is_read_only_and_has_no_account_claim(tmp_path):
    target = tmp_path / "not-created/config.toml"
    result = await guided_install(target, None, check=True)
    assert not target.parent.exists() and not result["changes"]
    assert result["chatgpt_call"] == "unverified"
    assert "unknown" in result["prerequisites"]["account_access"]


async def test_new_guided_setup_uses_existing_scoped_setup_and_stops_without_service(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda: "")
    answers = iter([True, False])
    monkeypatch.setattr(SetupUI, "confirm", lambda *a, **kw: next(answers))
    path = tmp_path / ".config/kirabridge/config.toml"
    result = await guided_install(path, tmp_path / "release", "en")
    config = load_config(str(path))
    assert result["status"] == "local_service_pending"
    assert all(p.approval_mode == "manual" for p in config.principals.values())
    assert config.principals["local"].roots == [str(tmp_path / "workspace/KiraBridge")]
    assert not (tmp_path / ".local/bin/kirabridge").exists()
    output = capsys.readouterr()
    assert output.out == "" and "KiraBridge" in output.err
    assert "Tunnels" not in output.err
    assert Path(config.credentials_file).stat().st_mode & 0o077 == 0


async def test_rerun_preserves_custom_healthy_installation(tmp_path, monkeypatch):
    path = configured(tmp_path, monkeypatch, wrapper=True)
    before = {
        p: p.read_bytes()
        for p in [path, path.parent / "credentials.json", tmp_path / ".local/bin/kirabridge"]
    }
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr(SetupUI, "confirm", lambda *a, **kw: False)

    async def health(*args):
        return {"dispatcher_active": True, "version": "0.5.2"}

    monkeypatch.setattr("kirabridge.installation.daemon_health", health)
    result = await guided_install(path, tmp_path / "new-release")
    assert result["status"] == "local_ready" and result["local_version"] == "0.5.2"
    assert all(p.read_bytes() == data for p, data in before.items())


def test_managed_install_upgrade_and_busy_gate_preserve_data(tmp_path, monkeypatch):
    path = configured(tmp_path, monkeypatch)
    config = load_config(str(path))
    before = [p.read_bytes() for p in [path, path.parent / "credentials.json"]]
    first, second = tmp_path / "release-1", tmp_path / "release-2"
    for folder in [first, second]:
        (folder / ".venv/bin").mkdir(parents=True)
        (folder / ".venv/bin/python3").write_text("test launcher target")
    activate_managed(path, first, service=False)
    launcher = tmp_path / ".local/bin/kirabridge"
    old = launcher.read_bytes()
    store = Store(config.state_path / "bridge.sqlite3")
    value = request(
        task_id="pending-update", arguments={"path": config.principals["local"].roots[0]}
    )
    from kirabridge.bridge_core.bridge import Bridge

    bridge = Bridge(config)
    bridge.prepare("local", value)
    bridge.store.close()
    with pytest.raises(BridgeError, match="Pending/active"):
        activate_managed(path, second, service=False)
    assert launcher.read_bytes() == old
    store.transition(value.task_id, "cancelled", {"source": "isolated_test_cleanup"})
    snapshot = dict(store.db.execute("select * from tasks where id=?", (value.task_id,)).fetchone())
    activate_managed(path, second, service=False)
    assert launcher.read_bytes() != old and str(second) in launcher.read_text()
    assert json.loads((path.parent / "installation.json").read_text())["previous_root"] == str(
        first
    )
    assert [p.read_bytes() for p in [path, path.parent / "credentials.json"]] == before
    assert (
        dict(store.db.execute("select * from tasks where id=?", (value.task_id,)).fetchone())
        == snapshot
    )
    store.close()


def pending_team_upgrade(tmp_path, monkeypatch, state):
    """An installed launcher and real team schema, without starting any workers."""
    from kirabridge.bridge_core.bridge import Bridge

    path = configured(tmp_path, monkeypatch)
    config = load_config(str(path))
    first, second = tmp_path / "release-1", tmp_path / "release-2"
    for folder in (first, second):
        (folder / ".venv/bin").mkdir(parents=True)
        (folder / ".venv/bin/python3").write_text("test launcher target")
    activate_managed(path, first, service=False)
    bridge = Bridge(config)
    try:
        bridge.store.db.execute(
            "INSERT INTO teams(id,name,owner,coordinator,revision,created) "
            "VALUES('update-team','Team','local','local',1,1)"
        )
        bridge.store.db.execute(
            "INSERT INTO team_work(id,team_id,assigned_by,assignee,title,body,root_id,"
            "depth,state,created) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                "update-work",
                "update-team",
                "local",
                "local",
                "Preserve work",
                "An update must preserve this intentional team content.",
                "update-work",
                0,
                state,
                1,
            ),
        )
    finally:
        bridge.store.close()
    return path, config, first, second


@pytest.mark.parametrize(
    "state", ["queued", "dispatching", "created", "accepted", "running", "processing_result"]
)
def test_managed_upgrade_blocks_pending_automatic_team_work_without_modifying_it(
    tmp_path, monkeypatch, state
):
    path, config, first, second = pending_team_upgrade(tmp_path, monkeypatch, state)
    launcher = tmp_path / ".local/bin/kirabridge"
    manifest = path.parent / "installation.json"
    before = {p: p.read_bytes() for p in (launcher, manifest, path)}
    store = Store(config.state_path / "bridge.sqlite3")
    try:
        row = dict(store.db.execute("SELECT * FROM team_work WHERE id='update-work'").fetchone())
        with pytest.raises(BridgeError) as caught:
            activate_managed(path, second, service=False)
        assert caught.value.code == "service_busy"
        assert all(p.read_bytes() == contents for p, contents in before.items())
        assert json.loads(manifest.read_text())["release_root"] == str(first)
        assert (
            dict(store.db.execute("SELECT * FROM team_work WHERE id='update-work'").fetchone())
            == row
        )
        assert store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0
    finally:
        store.close()


@pytest.mark.parametrize("state", ["queued_manual", "accepted_manual", "unknown"])
def test_managed_upgrade_preserves_external_pending_and_unknown_team_work(
    tmp_path, monkeypatch, state
):
    path, config, first, second = pending_team_upgrade(tmp_path, monkeypatch, state)
    store = Store(config.state_path / "bridge.sqlite3")
    try:
        before = dict(store.db.execute("SELECT * FROM team_work WHERE id='update-work'").fetchone())
        activate_managed(path, second, service=False)
        record = json.loads((path.parent / "installation.json").read_text())
        assert record["release_root"] == str(second)
        assert record["previous_root"] == str(first)
        assert (
            dict(store.db.execute("SELECT * FROM team_work WHERE id='update-work'").fetchone())
            == before
        )
        assert store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0
    finally:
        store.close()


def test_idle_gate_accepts_older_database_without_creating_team_tables(tmp_path, monkeypatch):
    path = configured(tmp_path, monkeypatch)
    config = load_config(str(path))
    store = Store(config.state_path / "bridge.sqlite3")
    try:
        before = [tuple(row) for row in store.db.execute("SELECT name,sql FROM sqlite_master")]
        version = store.db.execute("PRAGMA user_version").fetchone()[0]
        assert not any(name == "team_work" for name, _ in before)
        with idle_queue(config):
            pass
        assert [
            tuple(row) for row in store.db.execute("SELECT name,sql FROM sqlite_master")
        ] == before
        assert store.db.execute("PRAGMA user_version").fetchone()[0] == version
        assert store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0
    finally:
        store.close()


def test_foreign_launcher_never_replaced(tmp_path, monkeypatch):
    path = configured(tmp_path, monkeypatch, wrapper=True)
    launcher = tmp_path / ".local/bin/kirabridge"
    before = launcher.read_bytes()
    with pytest.raises(BridgeError, match="Existing launcher preserved"):
        activate_managed(path, tmp_path / "release")
    assert launcher.read_bytes() == before


@pytest.mark.parametrize("connected", [True, False])
def test_repeat_chatgpt_setup_preserves_key_profile_and_policy(
    tmp_path, monkeypatch, connected, capsys
):
    path = configured(tmp_path, monkeypatch)
    with path.open("a") as f:
        f.write('\n[principals.chatgpt]\ncapabilities=["bridge.health"]\n')
    profile = path.parent / "tunnel/kirabridge.yaml"
    profile.parent.mkdir()
    profile.write_text('{"test":"existing"}')
    key = path.parent / "openai-tunnel-runtime.key"
    key.write_text("DO_NOT_PRINT_SECRET")
    before = [p.read_bytes() for p in [path, profile, key]]
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr(
        "kirabridge.setup_dependencies.shutil.which", lambda n: "/fake/tunnel-client"
    )
    monkeypatch.setattr(
        "kirabridge.chatgpt_setup.runtime_status", lambda b: {"connected": connected}
    )
    monkeypatch.setattr(
        "kirabridge.chatgpt_setup.getpass.getpass", lambda *a: pytest.fail("key requested")
    )
    result = wizard(load_config(str(path)), path, "setup", language="en")
    assert (
        result["chatgpt_tool_call"] == "unverified"
        if connected
        else result["configuration_preserved"]
    )
    assert [p.read_bytes() for p in [path, profile, key]] == before
    assert "DO_NOT_PRINT_SECRET" not in capsys.readouterr().err
    with pytest.raises(BridgeError, match="Existing tunnel/key"):
        configure_tunnel(load_config(str(path)), path, "tunnel_existing123456", "x" * 40, "fake")


def test_account_permission_decline_does_not_request_key(tmp_path, monkeypatch):
    path = configured(tmp_path, monkeypatch)
    before = path.read_bytes()
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr(
        "kirabridge.setup_dependencies.shutil.which", lambda n: "/fake/tunnel-client"
    )
    monkeypatch.setattr(SetupUI, "confirm", lambda *a, **kw: False)
    monkeypatch.setattr(
        "kirabridge.chatgpt_setup.getpass.getpass", lambda *a: pytest.fail("key requested")
    )
    result = wizard(load_config(str(path)), path, "setup", language="en")
    assert result["status"] == "account_access_pending"
    assert path.read_bytes() == before


def test_banner_stderr_narrow_and_no_color(monkeypatch):
    from os import terminal_size

    stream = io.StringIO()
    monkeypatch.setattr(
        "kirabridge.install_ui.shutil.get_terminal_size", lambda *a: terminal_size((32, 24))
    )
    SetupUI("en", stream).banner()
    assert stream.getvalue() == "KiraBridge\n"


def test_linux_unit_is_user_only_quoted_and_conflicts_preserved(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr("kirabridge.installation.shutil.which", lambda n: "/bin/systemctl")
    calls = []
    monkeypatch.setattr(
        "kirabridge.installation.subprocess.run",
        lambda argv, **kw: calls.append(argv) or SimpleNamespace(returncode=0),
    )
    linux_service(tmp_path / "folder with spaces/config.toml", "/private/bin/kirabridge")
    unit = tmp_path / ".config/systemd/user/kirabridge.service"
    assert '"' + str(tmp_path / "folder with spaces/config.toml") + '"' in unit.read_text()
    assert all("--user" in call for call in calls)
    unit.write_text("Existing foreign service")
    with pytest.raises(BridgeError, match="Existing user service differs"):
        linux_service(tmp_path / "config", "/private/bin/kirabridge")
    assert unit.read_text() == "Existing foreign service"


@pytest.mark.parametrize("valid", [True, False])
def test_original_client_download_hash_before_install_and_no_execution(
    tmp_path, monkeypatch, valid
):
    from kirabridge.setup_dependencies import download_client

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        for name in ["tunnel-client", "cloudflared", "cloudflared-manifest.json"]:
            z.writestr(name, "isolated-test-data")
    data = archive.getvalue()
    response = io.BytesIO(data)
    response.url = "https://original.example/test"  # no network in this test
    monkeypatch.setattr(
        "kirabridge.setup_dependencies.urllib.request.urlopen", lambda *a, **k: response
    )
    monkeypatch.setattr("kirabridge.setup_dependencies.platform.system", lambda: "Darwin")
    monkeypatch.setattr("kirabridge.setup_dependencies.platform.machine", lambda: "x86_64")
    monkeypatch.setattr(
        "kirabridge.setup_dependencies.CLIENTS",
        {
            ("Darwin", "x86_64"): (
                "darwin-amd64",
                hashlib.sha256(data).hexdigest() if valid else "0" * 64,
            )
        },
    )
    path = tmp_path / "config.toml"
    if not valid:
        with pytest.raises(BridgeError, match="Checksum mismatch"):
            download_client(path)
        assert not (tmp_path / "tools").exists()
    else:
        binary = Path(download_client(path))
        assert binary.read_text() == "isolated-test-data"
        assert binary.stat().st_mode & 0o777 == 0o700
        with pytest.raises(BridgeError, match="Existing tool folder preserved"):
            download_client(path)
