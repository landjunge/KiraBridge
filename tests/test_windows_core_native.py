"""Run inside the Windows guest; skipped policy tests are not native acceptance."""

import os
import subprocess
import sys

import pytest

from kirabridge.bridge_core.models import BridgeError

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Requires a real Windows guest")


def test_real_windows_owner_acl_and_private_io(tmp_path):
    from kirabridge.platform_adapters.windows.filesystem_security import (
        WindowsFiles,
        private_directory,
        private_open,
    )

    root = tmp_path / "private"
    private_directory(root)
    private_directory(root)  # Existing object is validated, never re-ACL'd.
    path = root / "secret.txt"
    fd = private_open(path, write=True, create_new=True)
    with os.fdopen(fd, "wb") as file:
        file.write("Kira Übung".encode())
    fd = private_open(path)
    with os.fdopen(fd, "rb") as file:
        assert file.read() == "Kira Übung".encode()
    with pytest.raises(FileExistsError):
        private_open(path, write=True, create_new=True)
    os.link(path, root / "linked.txt")
    with pytest.raises(BridgeError) as caught:
        WindowsFiles().open(path)
    assert caught.value.code == "unsafe_state"


def test_real_windows_runtime_lock_excludes_second_process_then_releases(tmp_path):
    from kirabridge.platform_adapters import RuntimeLock
    from kirabridge.platform_adapters.windows.filesystem_security import private_directory

    root = tmp_path / "private"
    private_directory(root)
    path = root / "dispatcher.lock"
    lock = RuntimeLock(path)
    source = """
import sys
from pathlib import Path
from kirabridge.bridge_core.models import BridgeError
from kirabridge.platform_adapters import RuntimeLock
lock = RuntimeLock(Path(sys.argv[1]))
try:
    lock.acquire()
except BridgeError as error:
    print(error.code)
else:
    print('acquired')
    lock.release()
"""
    lock.acquire()
    try:
        result = subprocess.run(
            [sys.executable, "-c", source, str(path)],
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        )
        assert result.stdout.strip() == "already_running", result.stderr
    finally:
        lock.release()
    result = subprocess.run(
        [sys.executable, "-c", source, str(path)],
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    )
    assert result.stdout.strip() == "acquired", result.stderr


def test_real_windows_broad_acl_is_refused_without_silent_repair(tmp_path):
    from pathlib import Path

    from kirabridge.platform_adapters.windows.filesystem_security import (
        WindowsFiles,
        private_directory,
        private_open,
    )

    root = tmp_path / "private"
    private_directory(root)
    path = root / "fixture.txt"
    os.close(private_open(path, write=True, create_new=True))
    subprocess.run(
        [
            str(Path(os.environ["SystemRoot"]) / "System32" / "icacls.exe"),
            str(path),
            "/grant",
            "*S-1-1-0:(R)",
        ],
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    )
    with pytest.raises(BridgeError) as caught:
        WindowsFiles().open(path)
    assert caught.value.code == "unsafe_state"


def test_real_windows_sqlite_core_and_event_journal_start(tmp_path):
    from kirabridge.event_push import EventJournal
    from kirabridge.task_manager.store import Store

    store = Store(tmp_path / "core" / "bridge.sqlite3")
    assert store.db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    store.close()
    # Existing sidecar/database checks are repeated on normal restart.
    store = Store(tmp_path / "core" / "bridge.sqlite3")
    store.close()
    journal = EventJournal(tmp_path / "events")
    assert journal.db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert len(journal.key) == 32
    journal.db.close()
