"""Finite operator polling, real synthetic sources; no native registrations."""

import os
import sqlite3
from argparse import ArgumentParser
from pathlib import Path
from threading import Event

import pytest

from kirabridge.bridge_core.config import FileIndexConfig
from kirabridge.bridge_core.models import BridgeError


@pytest.fixture
def observed(bridge, config, monkeypatch):
    from kirabridge.file_index import service

    monkeypatch.setattr(service, "monotonic", lambda: 1000.0)
    root = Path(config.principals["local"].roots[0])
    config.file_index = FileIndexConfig(enabled=True, projects={"project": str(root)})
    for n in range(3):
        (root / f"note-{n}.md").write_text("orchid initial")
    index = bridge.file_index
    reconcile(index)
    yield index, root
    bridge.close_file_index()


def reconcile(index, *, observational=False):
    for _ in range(20):
        result = (
            index.scan("local", "project", observational=True)
            if observational
            else index.scan("local", "project")
        )
        if result["status"] != "building" and result["status"] != "observing":
            return result
    pytest.fail("synthetic observation did not finish")


def test_unchanged_observation_preserves_live_cursor_even_mid_pass(observed, monkeypatch):
    from kirabridge.file_index import service

    index, _ = observed
    first = index.query("local", "project", "orchid", limit=1)
    monkeypatch.setattr(service, "ENTRIES", 1)
    assert index.scan("local", "project", observational=True)["status"] == "observing"
    second = index.query("local", "project", "orchid", limit=1, cursor=first["next_cursor"])
    assert second["generation"] == first["generation"] and second["hits"]
    reconcile(index, observational=True)
    assert index.status("local", "project")["binding"] == first["generation"]


@pytest.mark.parametrize("changed", [False, True])
def test_separate_operator_connection_preserves_only_unchanged_cursor(observed, changed):
    from kirabridge.file_index import FileIndex

    index, root = observed
    first = index.query("local", "project", "orchid", limit=1)
    if changed:
        (root / "note-0.md").write_text("replacement tulip")
    other = FileIndex(index.config, index.security)
    try:
        reconcile(other, observational=True)
        if changed:
            with pytest.raises(BridgeError) as expired:
                index.query("local", "project", "orchid", limit=1, cursor=first["next_cursor"])
            assert expired.value.code == "generation_changed"
        else:
            assert index.query("local", "project", "orchid", limit=1, cursor=first["next_cursor"])[
                "hits"
            ]
    finally:
        other.close()


@pytest.mark.parametrize("change", ["content", "metadata", "delete", "rename", "create"])
def test_actual_observed_change_invalidates_cursor(observed, change):
    index, root = observed
    first = index.query("local", "project", "orchid", limit=1)
    path = root / "note-0.md"
    if change == "content":
        path.write_text("replacement tulip")
    elif change == "metadata":
        info = path.stat()
        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1000000))
    elif change == "delete":
        path.unlink()
    elif change == "rename":
        path.rename(root / "renamed.md")
    else:
        (root / "new.md").write_text("orchid new")
    assert reconcile(index, observational=True)["status"] == "reconciled_observation"
    with pytest.raises(BridgeError) as expired:
        index.query("local", "project", "orchid", limit=1, cursor=first["next_cursor"])
    assert expired.value.code == "generation_changed"


def test_content_change_with_colliding_metadata_stamp_still_updates_index(observed, monkeypatch):
    from dataclasses import replace

    from kirabridge.file_index.source import Source

    index, root = observed
    original = Source.capture
    monkeypatch.setattr(
        Source,
        "capture",
        lambda self, *a, **kw: replace(original(self, *a, **kw), stamp="coarse-metadata-fixture"),
    )
    reconcile(index, observational=True)
    first = index.query("local", "project", "orchid", limit=1)
    (root / "note-0.md").write_text("replacement tulip")
    reconcile(index, observational=True)
    assert index.query("local", "project", "tulip")["hits"]
    with pytest.raises(BridgeError):
        index.query("local", "project", "orchid", limit=1, cursor=first["next_cursor"])


@pytest.mark.parametrize(
    "fault",
    [
        "write_abort",
        "epoch_abort",
        "engine_rollback",
        "content_delete_denied",
        "start_denied",
        "all_writes_denied",
    ],
)
def test_poll_transaction_fault_never_keeps_local_fts_ready(observed, fault):
    index, root = observed
    (root / "note-0.md").write_text("replacement tulip")
    db = index.cache.db
    if fault in {"write_abort", "epoch_abort", "engine_rollback"}:
        table = "files" if fault == "write_abort" else "scopes"
        severity = "ROLLBACK" if fault == "engine_rollback" else "ABORT"
        db.execute(
            f"CREATE TRIGGER abort_file_update BEFORE UPDATE ON {table} "
            f"BEGIN SELECT RAISE({severity},'synthetic fault'); END"
        )
    else:

        def authorizer(action, table, *_):
            if (
                fault == "content_delete_denied"
                and table == "content"
                and action == sqlite3.SQLITE_DELETE
            ):
                return sqlite3.SQLITE_DENY
            if (
                fault in {"start_denied", "all_writes_denied"}
                and table == "scopes"
                and action
                in (
                    {sqlite3.SQLITE_INSERT}
                    if fault == "start_denied"
                    else {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE}
                )
            ):
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        db.set_authorizer(authorizer)
    try:
        result = index.scan("local", "project", observational=True)
        assert result["status"] == "index_unavailable" and result["complete"] is False
        state = index.status("local", "project")
        assert state["mode"] == "bounded_scan" and state["status"] == "index_unavailable"
        page = index.query("local", "project", "tulip")
        assert page["hits"] and page["complete"] is False
    finally:
        db.set_authorizer(None)
        db.execute("DROP TRIGGER IF EXISTS abort_file_update")
    reconcile(index)
    assert index.status("local", "project")["mode"] == "fts5"


def test_missing_derived_fts_body_is_repaired_and_invalidates_cursor(observed):
    index, _ = observed
    first = index.query("local", "project", "orchid", limit=1)
    index.cache.db.execute("DELETE FROM content")
    index.cache.db.commit()
    assert reconcile(index, observational=True)["status"] == "reconciled_observation"
    assert len(index.query("local", "project", "orchid")["hits"]) == 3
    with pytest.raises(BridgeError):
        index.query("local", "project", "orchid", limit=1, cursor=first["next_cursor"])


def test_commit_denial_rolls_back_changes_without_claiming_local_fts_ready(observed, monkeypatch):
    index, root = observed
    (root / "note-0.md").write_text("changed tulip")
    db, original = index.cache.db, index.cache.start

    def start(*args, **kwargs):
        scan = original(*args, **kwargs)
        db.set_authorizer(
            lambda action, name, *_: (
                sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_TRANSACTION and name == "COMMIT"
                else sqlite3.SQLITE_OK
            )
        )
        return scan

    monkeypatch.setattr(index.cache, "start", start)
    try:
        assert index.scan("local", "project", observational=True)["status"] == "index_unavailable"
        page = index.query("local", "project", "tulip")
        assert page["mode"] == "bounded_scan" and page["hits"] and not page["complete"]
        assert not db.in_transaction
    finally:
        db.set_authorizer(None)


def test_observation_marker_and_preserved_epoch_are_read_under_writer_lock(observed, monkeypatch):
    index, _ = observed
    other = sqlite3.connect(index.cache.path, timeout=0.001)
    original = index.cache.state
    blocked = []

    def state(scope):
        value = original(scope)
        if not blocked and index.cache.db.in_transaction:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                other.execute("UPDATE scopes SET epoch='concurrent-writer'")
            blocked.append(True)
        return value

    monkeypatch.setattr(index.cache, "state", state)
    try:
        reconcile(index, observational=True)
        assert blocked
    finally:
        other.close()


def test_poll_time_budget_stop_during_wait_and_coalesced_partial_progress(observed, monkeypatch):
    from kirabridge.file_index import service
    from kirabridge.file_index.polling import poll

    index, _ = observed
    now = [0.0]

    def wait(_):
        now[0] += 2
        return False

    values = list(
        poll(
            index,
            "local",
            "project",
            cycles=3,
            batches=1,
            max_seconds=1,
            clock=lambda: now[0],
            wait=wait,
        )
    )
    assert values[-1]["poll_status"] == "budget" and values[-1]["batches"] == 1
    assert "poll_time_budget" in values[-1]["reasons"] and not index.scans
    values = list(poll(index, "local", "project", wait=lambda _: True))
    assert values[-1]["poll_status"] == "stopped" and not index.scans
    monkeypatch.setattr(service, "ENTRIES", 1)
    values = list(poll(index, "local", "project", cycles=4, batches=1, wait=lambda _: False))
    assert values[-1]["status"] == "reconciled_observation"
    assert values[-1]["batches"] == 4 and not index.scans


def test_poll_cannot_capture_excluded_or_linked_private_text(observed, tmp_path):
    from kirabridge.file_index.polling import poll

    index, root = observed
    private = tmp_path / "outside"
    private.mkdir()
    path = private / "ordinary.md"
    path.write_text("private-marker-only")
    (root / "link").symlink_to(private, target_is_directory=True)
    (root / "alias.md").hardlink_to(path)
    (root / "vault").mkdir()
    (root / "vault/note.md").write_text("private-marker-only")
    list(poll(index, "local", "project", cycles=1, batches=20))
    assert not index.query("local", "project", "private-marker-only")["hits"]
    assert path.read_text() == "private-marker-only"


def test_polling_batches_updates_and_offline_restart(observed):
    from kirabridge.file_index import FileIndex
    from kirabridge.file_index.polling import poll

    index, root = observed
    first = root / "note-0.md"
    waited = []

    def wait(_):
        waited.append(True)
        first.rename(root / "renamed.md")
        (root / "note-1.md").unlink()
        (root / "note-2.md").write_text("new lavender")
        (root / "added.md").write_text("new lavender")
        return False

    values = list(poll(index, "local", "project", cycles=2, batches=20, wait=wait))
    assert len(waited) == 1 and values[-1]["poll_status"] == "finished"
    assert all(v["complete"] is False and v["poll_mode"] == "bounded_poll" for v in values)
    assert len(index.query("local", "project", "lavender")["hits"]) == 2
    assert not index.scans
    index.close()
    (root / "offline.md").write_text("offline hyacinth")
    other = FileIndex(index.config, index.security)
    try:
        list(poll(other, "local", "project", cycles=1, batches=20))
        assert other.query("local", "project", "hyacinth")["hits"]
    finally:
        other.close()


@pytest.mark.parametrize("change", ["capability", "root", "exclusion", "alias"])
def test_operator_session_does_not_follow_changed_authority(observed, config, change):
    from kirabridge.file_index.polling import poll

    index, root = observed

    def wait(_):
        if change == "capability":
            config.principals["local"].capabilities.remove("file.list")
        elif change == "root":
            other = root / "other"
            other.mkdir()
            config.file_index.projects["project"] = str(other)
        elif change == "exclusion":
            config.file_index.exclusions.append("note-0.md")
        else:
            config.file_index.projects["project"] = "//" + str(root).lstrip("/")
        return False

    with pytest.raises(BridgeError):
        list(poll(index, "local", "project", cycles=2, batches=20, wait=wait))
    assert not index.scans


def test_poll_stop_and_partial_budget_close_held_source_iterators(observed, monkeypatch):
    from kirabridge.file_index import service
    from kirabridge.file_index.polling import poll

    index, _ = observed
    monkeypatch.setattr(service, "ENTRIES", 1)
    values = list(poll(index, "local", "project", cycles=1, batches=1))
    assert values[-1]["poll_status"] == "budget" and not index.scans
    assert values[-1]["complete"] is False
    stopped = Event()
    stopped.set()
    values = list(poll(index, "local", "project", stopped=stopped))
    assert values[-1]["poll_status"] == "stopped"


@pytest.mark.parametrize(
    "bad",
    [
        {"cycles": 0},
        {"batches": 0},
        {"cycles": 1000, "batches": 2},
        {"interval_ms": 1},
        {"max_seconds": 301},
    ],
)
def test_poll_hard_work_caps_reject_before_scanning(observed, bad):
    from kirabridge.file_index.polling import poll

    index, _ = observed
    with pytest.raises(BridgeError) as denied:
        list(poll(index, "local", "project", **bad))
    assert denied.value.code == "invalid_search_budget"


def test_disabled_poll_has_no_index_and_real_cli_is_operator_entry(bridge, config):
    from kirabridge.file_index.cli import execute, register
    from kirabridge.file_index.polling import poll

    assert list(poll(bridge.file_index, "local", "unused"))[-1]["poll_status"] == "disabled"
    assert not (config.state_path / "file-index").exists()
    root = Path(config.principals["local"].roots[0])
    config.file_index = FileIndexConfig(enabled=True, projects={"project": str(root)})
    (root / "note.md").write_text("orchid")
    parser = ArgumentParser()
    register(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["file-index", "poll", "project", "--cycles", "1", "--batches", "20"])
    values = []
    execute(bridge.file_index, "local", args, values.append)
    assert values[-1]["poll_mode"] == "bounded_poll" and values[-1]["complete"] is False
    assert bridge.store.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    bridge.close_file_index()


@pytest.mark.parametrize("signal_name", ["SIGINT", "SIGTERM"])
def test_operator_signal_unwinds_only_its_scan_and_restores_host_handler(
    observed, monkeypatch, signal_name
):
    import signal

    from kirabridge.file_index import service
    from kirabridge.file_index.cli import execute, register

    index, _ = observed
    monkeypatch.setattr(service, "ENTRIES", 1)
    sig = getattr(signal, signal_name)
    previous = signal.getsignal(sig)
    parser = ArgumentParser()
    register(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["file-index", "poll", "project", "--cycles", "3", "--batches", "1"])
    values = []

    def emit(value):
        values.append(value)
        if len(values) == 1:
            signal.raise_signal(sig)

    execute(index, "local", args, emit)
    assert values[-1]["poll_status"] == "stopped" and not values[-1]["complete"]
    assert "scanned" not in values[-1] and not index.scans
    assert signal.getsignal(sig) == previous
