"""Real file/transaction tests with synthetic runtimes; no native Windows claim."""

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "windows_installer_lifecycle",
    Path(__file__).parents[1] / "installer/windows/windows_lifecycle.py",
)
lifecycle = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = lifecycle
spec.loader.exec_module(lifecycle)


def make_runtime(parent, release, version="0.8.0rc33"):
    runtime = parent / release
    runtime.mkdir(parents=True)
    files = {
        "python.exe": b"Synthetic runtime: never execute this fixture",
        "Lib/site-packages/kirabridge/__init__.py": version.encode(),
        "windows_lifecycle.py": b"Synthetic lifecycle payload",
    }
    for name, body in files.items():
        path = runtime / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    info = {
        "schema_version": 1,
        "release_id": release,
        "version": version,
        "files": {name: hashlib.sha256(body).hexdigest() for name, body in files.items()},
    }
    (runtime / "runtime-manifest.json").write_text(json.dumps(info))
    return runtime


@pytest.fixture
def installation(tmp_path, monkeypatch):
    root = tmp_path / "application"
    data = tmp_path / "private-data"
    source = make_runtime(tmp_path / "packages", "a" * 32)
    transaction = tmp_path / "transaction.json"
    smoked = []
    # Native imports execute only in Windows acceptance; all filesystem behavior
    # and private POSIX configuration I/O below use the real implementation.
    monkeypatch.setattr(lifecycle, "smoke", lambda runtime: smoked.append(runtime))

    def call(action, *arguments):
        return lifecycle.main([action, "--install-dir", str(root), *map(str, arguments)])

    def prepare(runtime=source):
        return call(
            "prepare", "--runtime-dir", runtime, "--transaction", transaction, "--data-dir", data
        )

    def install(runtime=source):
        assert prepare(runtime) == 0
        assert call("commit", "--transaction", transaction) == 0
        assert call("finalize", "--transaction", transaction) == 0

    return root, data, source, transaction, smoked, call, prepare, install


def test_fresh_prepare_commit_finalize_and_idempotent_reinstall(installation):
    root, data, source, tx, smoked, call, prepare, install = installation
    assert prepare() == 0
    assert not (root / "current.json").exists()
    assert (root / "pending.json").exists()
    assert smoked == [root / "releases" / ("a" * 32) / "Runtime"]
    assert json.loads((data / "installer-config.json").read_text())["port"] == 8768
    assert not (data / "preview-credentials.json").exists()
    assert call("run") == 1  # A prepared but unfinished installer cannot launch.
    assert call("commit", "--transaction", tx) == 0
    assert lifecycle.pointer(root)["release"] == "a" * 32
    assert call("status") == 1  # Commit is still pending until installer finalizes.
    assert call("finalize", "--transaction", tx) == 0
    assert not (root / "pending.json").exists()
    before = (root / "current.json").read_bytes()
    install()
    assert (root / "current.json").read_bytes() == before
    assert lifecycle.manifest(source)["version"] == "0.8.0rc33"


def test_upgrade_retains_user_data_and_explicit_rollback_restores_previous(installation, tmp_path):
    root, data, _, tx, _, call, prepare, install = installation
    install()
    old_pointer = (root / "current.json").read_bytes()
    user_files = {
        "preview-credentials.json": b"original credentials, not inspected by the installer",
        "tasks.sqlite": b"original database including unknown task history",
        "tasks.sqlite-wal": b"original pending WAL bytes",
        "notes.txt": b"user data",
    }
    for name, body in user_files.items():
        (data / name).write_bytes(body)
    upgrade = make_runtime(tmp_path / "packages", "b" * 32, "0.8.0rc34")
    assert prepare(upgrade) == 0
    assert call("commit", "--transaction", tx) == 0
    assert lifecycle.pointer(root)["release"] == "b" * 32
    assert call("rollback", "--transaction", tx) == 0
    assert (root / "current.json").read_bytes() == old_pointer
    assert not (root / "releases" / ("b" * 32)).exists()
    assert (root / "releases" / ("a" * 32)).is_dir()
    assert {name: (data / name).read_bytes() for name in user_files} == user_files


def test_recovery_after_committed_interruption_restores_previous_before_new_prepare(
    installation, tmp_path
):
    root, _, source, tx, _, call, prepare, install = installation
    install()
    old = lifecycle.pointer(root)
    upgrade = make_runtime(tmp_path / "packages", "b" * 32, "0.8.0rc34")
    assert prepare(upgrade) == 0
    assert call("commit", "--transaction", tx) == 0
    assert call("recover") == 0
    assert lifecycle.pointer(root) == old
    assert not (root / "releases" / ("b" * 32)).exists()
    assert prepare(source) == 0
    assert call("rollback", "--transaction", tx) == 0
    assert lifecycle.pointer(root) == old


@pytest.mark.parametrize("after_manifest", [False, True])
def test_failed_copy_is_recoverable_even_without_destination_manifest(
    installation, monkeypatch, after_manifest
):
    root, _, _, _, _, _, prepare, _ = installation
    original_atomic = lifecycle.atomic
    original_copy = lifecycle.shutil.copyfileobj

    def atomic(path, value, **kwargs):
        if not after_manifest and path.name == "runtime-manifest.json":
            raise OSError("Simulated interruption before manifest copy")
        return original_atomic(path, value, **kwargs)

    copied = []

    def copy(source, target):
        original_copy(source, target)
        copied.append(target.name)
        raise OSError("Simulated interruption during payload copy")

    monkeypatch.setattr(lifecycle, "atomic", atomic)
    monkeypatch.setattr(lifecycle.shutil, "copyfileobj", copy)
    assert prepare() == 1
    assert bool(copied) is after_manifest
    assert not (root / "pending.json").exists()
    assert not (root / "current.json").exists()
    assert not (root / "releases").exists()


def test_runtime_smoke_failure_keeps_previous_current_pointer(installation, monkeypatch, tmp_path):
    root, _, _, _, _, _, prepare, install = installation
    install()
    old = (root / "current.json").read_bytes()
    upgrade = make_runtime(tmp_path / "packages", "b" * 32)

    def reject(_):
        raise lifecycle.SetupError("Synthetic native smoke failure")

    monkeypatch.setattr(lifecycle, "smoke", reject)
    assert prepare(upgrade) == 1
    assert (root / "current.json").read_bytes() == old
    assert not (root / "pending.json").exists()
    assert not (root / "releases" / ("b" * 32)).exists()


def test_busy_application_lock_refuses_setup_uninstall_and_configuration(installation):
    root, _, _, _, _, call, prepare, install = installation
    install()
    before = (root / "current.json").read_bytes()
    with lifecycle.locked(root):
        assert prepare() == 1
        assert call("preflight-uninstall") == 1
        assert call("configure", "--port", 18868) == 1
    assert (root / "current.json").read_bytes() == before
    assert not (root / "pending.json").exists()


def test_wrong_transaction_and_finalize_before_commit_cannot_modify_installation(installation):
    root, _, _, tx, _, call, prepare, _ = installation
    assert prepare() == 0
    assert call("finalize", "--transaction", tx) == 1
    wrong = tx.with_name("wrong-transaction.json")
    wrong.write_text(json.dumps({"id": "f" * 32}))
    assert call("commit", "--transaction", wrong) == 1
    assert call("rollback", "--transaction", wrong) == 1
    assert (root / "pending.json").exists()
    assert not (root / "current.json").exists()
    assert call("recover") == 0


def test_downgrade_refused_before_transaction_or_current_changes(installation, tmp_path):
    root, _, _, _, _, _, prepare, install = installation
    install()
    before = (root / "current.json").read_bytes()
    older = make_runtime(tmp_path / "packages", "c" * 32, "0.8.0rc32")
    assert prepare(older) == 1
    assert (root / "current.json").read_bytes() == before
    assert not (root / "pending.json").exists()
    assert not (root / "releases" / ("c" * 32)).exists()


@pytest.mark.parametrize("damage", ["bytes", "extra", "invalid-version", "schema-bool"])
def test_invalid_offline_package_refused_before_staging(installation, damage):
    root, _, source, _, _, _, prepare, _ = installation
    if damage == "bytes":
        (source / "python.exe").write_bytes(b"corrupted")
    elif damage == "extra":
        (source / "unknown.exe").write_bytes(b"unexpected")
    else:
        path = source / "runtime-manifest.json"
        info = json.loads(path.read_text())
        info["version" if damage == "invalid-version" else "schema_version"] = (
            "invalid" if damage == "invalid-version" else True
        )
        path.write_text(json.dumps(info))
    assert prepare() == 1
    assert not (root / "pending.json").exists()
    assert not (root / "releases").exists()


@pytest.mark.parametrize(
    "name", ["../outside", "/absolute", "a\\b", "a/../b", "a//b", "a:b", "NUL.txt", "a./b", "a /b"]
)
def test_windows_alias_and_traversal_payloads_are_refused(installation, name):
    root, _, source, _, _, _, prepare, _ = installation
    path = source / "runtime-manifest.json"
    info = json.loads(path.read_text())
    info["files"][name] = "0" * 64
    path.write_text(json.dumps(info))
    assert prepare() == 1
    assert not (root / "releases").exists()


def test_directory_link_cannot_hide_unmanifested_payload(installation, tmp_path):
    root, _, source, _, _, _, prepare, _ = installation
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "hidden.exe").write_bytes(b"must never copy")
    (source / "linked-directory").symlink_to(outside, target_is_directory=True)
    assert prepare() == 1
    assert not (root / "releases").exists()
    assert (outside / "hidden.exe").read_bytes() == b"must never copy"


def test_private_config_malformed_bytes_preserved_and_no_release_created(installation):
    root, data, _, _, _, _, prepare, _ = installation
    data.mkdir(mode=0o700)
    config = data / "installer-config.json"
    config.write_bytes(b"{malformed local settings")
    config.chmod(0o600)
    assert prepare() == 1
    assert config.read_bytes() == b"{malformed local settings"
    assert not (root / "pending.json").exists()
    assert not (root / "releases").exists()


def test_upgrade_refuses_malformed_settings_without_touching_existing_release(
    installation, tmp_path
):
    root, data, _, _, _, _, prepare, install = installation
    install()
    before = (root / "current.json").read_bytes()
    (data / "installer-config.json").write_bytes(b"{broken existing settings")
    upgrade = make_runtime(tmp_path / "packages", "b" * 32)
    assert prepare(upgrade) == 1
    assert (root / "current.json").read_bytes() == before
    assert (data / "installer-config.json").read_bytes() == b"{broken existing settings"
    assert not (root / "pending.json").exists()
    assert not (root / "releases" / ("b" * 32)).exists()


def test_unsafe_private_data_refused_with_actionable_code(installation, capsys):
    root, data, _, _, _, _, prepare, _ = installation
    data.mkdir(mode=0o755)
    data.chmod(0o755)
    assert prepare() == 1
    assert "unsafe_state" in capsys.readouterr().err
    assert data.stat().st_mode & 0o777 == 0o755
    assert not (data / "installer-config.json").exists()
    assert not (root / "pending.json").exists()


@pytest.mark.parametrize("relationship", ["same", "child", "parent"])
def test_application_data_overlap_refused_before_config_creation(installation, relationship):
    root, _, source, tx, _, call, _, _ = installation
    paths = {"same": root, "child": root / "Data", "parent": root.parent}
    assert (
        call(
            "prepare",
            "--runtime-dir",
            source,
            "--transaction",
            tx,
            "--data-dir",
            paths[relationship],
        )
        == 1
    )
    assert not (paths[relationship] / "installer-config.json").exists()
    assert not (root / "pending.json").exists()


def test_data_directory_link_refused_without_modifying_target(installation, tmp_path):
    root, data, _, _, _, _, prepare, _ = installation
    outside = tmp_path / "outside-data"
    outside.mkdir(mode=0o700)
    data.symlink_to(outside, target_is_directory=True)
    assert prepare() == 1
    assert not list(outside.iterdir())
    assert not (root / "pending.json").exists()


def test_configure_preserves_credentials_and_status_contains_no_secret(installation, capsys):
    _, data, _, _, _, call, _, install = installation
    install()
    secret = b"private-credential-value"
    (data / "preview-credentials.json").write_bytes(secret)
    assert call("configure", "--port", 18868) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["port"] == 18868
    assert output["endpoint"] == "http://127.0.0.1:18868/mcp"
    assert secret.decode() not in json.dumps(output)
    assert (data / "preview-credentials.json").read_bytes() == secret
    before = (data / "installer-config.json").read_bytes()
    assert call("configure", "--port", 80) == 1
    assert (data / "installer-config.json").read_bytes() == before


def test_uninstall_preserves_data_and_untracked_files_and_refuses_missing_preflight(installation):
    root, data, _, _, _, call, _, install = installation
    install()
    runtime = root / "releases" / ("a" * 32) / "Runtime"
    user = runtime / "my-note.txt"
    user.write_bytes(b"untracked note")
    (data / "tasks.sqlite").write_bytes(b"persistent database")
    assert call("uninstall") == 1
    assert (root / "current.json").exists()
    assert call("preflight-uninstall") == 0
    assert call("run") == 1
    assert call("uninstall") == 0
    assert user.read_bytes() == b"untracked note"
    assert not (runtime / "python.exe").exists()
    assert not (root / "current.json").exists()
    assert not (root / "pending.json").exists()
    assert (data / "tasks.sqlite").read_bytes() == b"persistent database"


def test_cancelled_uninstall_leaves_current_and_user_configuration(installation):
    root, data, _, _, _, call, _, install = installation
    install()
    before = (root / "current.json").read_bytes()
    config = (data / "installer-config.json").read_bytes()
    assert call("preflight-uninstall") == 0
    assert call("cancel-uninstall") == 0
    assert (root / "current.json").read_bytes() == before
    assert (data / "installer-config.json").read_bytes() == config
    assert not (root / "pending.json").exists()


def test_corrupt_pending_transaction_does_not_overwrite_current(installation):
    root, _, _, _, _, call, prepare, install = installation
    install()
    before = (root / "current.json").read_bytes()
    assert prepare() == 0
    path = root / "pending.json"
    pending = json.loads(path.read_text())
    pending["previous"] = {"schema": 1, "release": "../../outside"}
    path.write_text(json.dumps(pending))
    assert call("recover") == 1
    assert (root / "current.json").read_bytes() == before
    assert path.exists()
