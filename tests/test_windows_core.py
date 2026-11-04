"""Windows policy/ABI/routing checks on any host; native acceptance is separate."""

import ctypes
from types import SimpleNamespace

import pytest

from kirabridge.bridge_core.models import BridgeError
from kirabridge.platform_adapters.windows.filesystem_security import (
    ACE_HEADER,
    ACL,
    DIRECTORY,
    DWORD,
    FILE_INFORMATION,
    REPARSE_POINT,
    WindowsFiles,
    validate_local_path,
    validate_security,
)
from kirabridge.platform_adapters.windows.locking import WindowsRuntimeLock

USER = "S-1-5-21-100-200-300-1001"


def test_windows_structures_keep_windows_abi_on_non_windows_host():
    assert ctypes.sizeof(DWORD) == 4
    assert ctypes.sizeof(FILE_INFORMATION) == 52
    assert ctypes.sizeof(ACL) == 8
    assert ctypes.sizeof(ACE_HEADER) == 4


@pytest.mark.parametrize("trustees", [[USER], [USER, "S-1-5-18"], [USER, "S-1-5-32-544"]])
def test_private_acl_accepts_user_and_privileged_trustees(trustees):
    validate_security(USER, trustees, USER)


@pytest.mark.parametrize(
    ("owner", "trustees"),
    [
        ("S-1-5-18", [USER]),
        (USER, []),
        (USER, ["S-1-1-0"]),
        (USER, [USER, "S-1-5-32-545"]),
        (USER, [USER, "S-1-5-21-999"]),
    ],
)
def test_private_acl_refuses_null_world_other_user_or_nonuser_owner(owner, trustees):
    with pytest.raises(BridgeError, match="Windows state") as caught:
        validate_security(owner, trustees, USER)
    assert caught.value.code == "unsafe_state"


@pytest.mark.parametrize(
    "path",
    [
        "state",
        "C:state",
        r"\\server\state",
        r"\\?\C:\state",
        r"C:\data\..\state",
        r"C:\state\db:stream",
        "C:\\state\x00bad",
    ],
)
def test_private_paths_refuse_unc_device_ads_traversal_and_relative_paths(path):
    with pytest.raises(BridgeError) as caught:
        validate_local_path(path)
    assert caught.value.code == "unsafe_state"


def test_private_path_preserves_unicode_and_local_drive():
    assert validate_local_path(r"C:\Users\Daniel\Kira Übung\state") == (
        r"C:\Users\Daniel\Kira Übung\state"
    )


def metadata_api(*, attributes=0, links=1, resolved=r"\\?\C:\state\lock"):
    observed = []

    def info(_handle, pointer):
        pointer._obj.attributes = attributes
        pointer._obj.links = links
        return 1

    def final(_handle, buffer, _size, _flags):
        buffer.value = resolved
        return len(resolved)

    api = object.__new__(WindowsFiles)
    api.kernel = SimpleNamespace(GetFileInformationByHandle=info, GetFinalPathNameByHandleW=final)
    api._inspect_security = lambda handle: observed.append(handle)
    return api, observed


@pytest.mark.parametrize(
    "settings",
    [
        {"attributes": REPARSE_POINT},
        {"attributes": DIRECTORY},
        {"links": 2},
        {"resolved": r"\\?\C:\elsewhere\lock"},
    ],
)
def test_opened_handle_identity_rejects_reparse_wrong_type_hardlinks_or_redirect(settings):
    api, observed = metadata_api(**settings)
    with pytest.raises(BridgeError):
        api._inspect(44, r"C:\state\lock", directory=False)
    assert observed == []


def test_acl_is_checked_on_resolved_open_handle():
    api, observed = metadata_api()
    api._inspect(44, r"C:\state\lock", directory=False)
    assert observed == [44]


class ExclusiveHandles:
    def __init__(self):
        self.active, self.closed = set(), []

    def open(self, path, **options):
        assert options == {"create": True, "exclusive": True, "write": True}
        if path in self.active:
            error = OSError("shared handle refused")
            error.winerror = 32
            raise error
        self.active.add(path)
        return path

    def close(self, handle):
        self.closed.append(handle)
        self.active.remove(handle)


def test_exclusive_native_lock_has_no_pid_fallback_and_releases_only_owned_handle():
    api = ExclusiveHandles()
    one = WindowsRuntimeLock("one", api=api)
    two = WindowsRuntimeLock("one", api=api)
    one.acquire()
    one.acquire()
    with pytest.raises(BridgeError) as caught:
        two.acquire()
    assert caught.value.code == "already_running" and two.handle is None
    one.release()
    one.release()
    two.acquire()
    two.release()
    assert api.closed == ["one", "one"] and not api.active


def test_native_lock_does_not_convert_security_failure_into_contention():
    def refused(*_args, **_kwargs):
        raise BridgeError("unsafe_state", "ACL refused")

    lock = WindowsRuntimeLock("one", api=SimpleNamespace(open=refused))
    with pytest.raises(BridgeError) as caught:
        lock.acquire()
    assert caught.value.code == "unsafe_state" and lock.handle is None


def test_nonposix_output_capture_does_not_touch_files_or_database(monkeypatch, tmp_path):
    import kirabridge.process_output_store as module

    monkeypatch.setattr(module, "os", SimpleNamespace(name="nt"))
    output = module.ProcessOutputStore(tmp_path / "not-created", object())
    assert not (tmp_path / "not-created").exists()
    operations = [
        lambda: output.start("local", "task"),
        lambda: output.append("local", "task", "stdout", b"x"),
        lambda: output.finish("local", "task", complete=True),
        lambda: output.status("local", "task"),
        lambda: output.read("local", "task"),
    ]
    for operation in operations:
        with pytest.raises(BridgeError) as caught:
            operation()
        assert caught.value.code == "unsupported_platform"


def test_config_windows_directory_routes_to_acl_validation(monkeypatch, tmp_path):
    import kirabridge.bridge_core.config as config
    import kirabridge.platform_adapters.windows.filesystem_security as windows

    paths = []
    monkeypatch.setattr(config, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(windows, "private_directory", lambda path: paths.append(path))
    config.private_directory(tmp_path)
    assert paths == [tmp_path]


def test_event_journal_windows_startup_uses_acl_and_native_lock(monkeypatch, tmp_path):
    import kirabridge.event_push as events
    import kirabridge.platform_adapters.windows.filesystem_security as windows
    import kirabridge.platform_adapters.windows.locking as locking

    observed = []

    def directory(path):
        path.mkdir(mode=0o700)
        observed.append("acl-directory")

    def file(path):
        path.touch(mode=0o600)
        observed.append("acl-file")

    class Lock:
        def __init__(self, path):
            assert path == tmp_path / "state" / "initialize.lock"

        def acquire(self):
            observed.append("lock")

        def release(self):
            observed.append("unlock")

    monkeypatch.setattr(events, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(windows, "private_directory", directory)
    monkeypatch.setattr(windows, "ensure_private_file", file)
    monkeypatch.setattr(windows, "WindowsFiles", lambda: object())
    monkeypatch.setattr(locking, "WindowsRuntimeLock", Lock)
    journal = events.EventJournal(tmp_path / "state")
    assert observed == ["acl-directory", "acl-file", "lock", "unlock"]
    assert journal.db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert len(journal.key) == 32
    journal.db.close()


def test_windows_private_credentials_io_cannot_skip_native_acl_check(monkeypatch, tmp_path):
    import json
    import os

    import kirabridge.platform_adapters.windows.filesystem_security as windows
    import kirabridge.private_files as files

    observed = []

    def opened(path, *, write=False, create_new=False):
        observed.append((write, create_new))
        flags = os.O_RDWR | os.O_CREAT | os.O_EXCL if create_new else os.O_RDONLY
        return os.open(path, flags, 0o600)

    monkeypatch.setattr(
        files, "os", SimpleNamespace(name="nt", fdopen=os.fdopen, fsync=os.fsync, fstat=os.fstat)
    )
    monkeypatch.setattr(windows, "private_open", opened)
    path = tmp_path / "credentials.json"
    files.write_private(path, json.dumps({"local": "unit-test-value"}))
    assert files.private_json(path) == {"local": "unit-test-value"}
    assert observed == [(True, True), (False, False)]
    with pytest.raises(FileExistsError):
        files.write_private(path, "{}")
    assert files.private_json(path) == {"local": "unit-test-value"}


def test_posix_runtime_lock_still_excludes_second_owner(tmp_path):
    import os

    from kirabridge.platform_adapters import RuntimeLock

    if os.name != "posix":
        pytest.skip("POSIX regression")
    one, two = RuntimeLock(tmp_path / "lock"), RuntimeLock(tmp_path / "lock")
    try:
        one.acquire()
        with pytest.raises(BridgeError) as caught:
            two.acquire()
        assert caught.value.code == "already_running"
        one.release()
        two.acquire()
    finally:
        one.release()
        two.release()


def test_windows_event_journal_lock_contention_has_bounded_failure(monkeypatch, tmp_path):
    import kirabridge.event_push as events
    import kirabridge.platform_adapters.windows.locking as locking

    released = []
    ticks = iter([0, 6])

    class Busy:
        def __init__(self, path):
            assert path == tmp_path / "initialize.lock"

        def acquire(self):
            raise BridgeError("already_running", "Held")

        def release(self):
            released.append(True)

    monkeypatch.setattr(events, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(events, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    monkeypatch.setattr(locking, "WindowsRuntimeLock", Busy)
    with pytest.raises(events.EventError, match="event_journal_initialization_busy"):
        with events.initialization_lock(tmp_path):
            pytest.fail("Busy journal must not enter its schema transaction")
    assert released == [True]


def test_createfile_error_survives_security_descriptor_cleanup(monkeypatch):
    from contextlib import contextmanager

    import kirabridge.platform_adapters.windows.filesystem_security as security

    last_error = [32]

    @contextmanager
    def attributes():
        try:
            yield security.SECURITY_ATTRIBUTES()
        finally:
            last_error[0] = 0  # A successful LocalFree can replace GetLastError.

    def win_error(value):
        error = OSError("native failure")
        error.winerror = value
        return error

    api = object.__new__(security.WindowsFiles)
    api._path = lambda value: value
    api._attributes = attributes
    api.kernel = SimpleNamespace(CreateFileW=lambda *_args: security.HANDLE(-1).value)
    monkeypatch.setattr(security.ctypes, "get_last_error", lambda: last_error[0], raising=False)
    monkeypatch.setattr(security.ctypes, "WinError", win_error, raising=False)
    with pytest.raises(OSError) as caught:
        api.open(r"C:\state\lock", exclusive=True)
    assert caught.value.winerror == 32
