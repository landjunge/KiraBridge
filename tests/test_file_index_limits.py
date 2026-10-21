"""Resource caps, fallback, and actual authenticated/CLI query surfaces."""

import json
import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from kirabridge.bridge_core.config import FileIndexConfig
from kirabridge.bridge_core.models import BridgeError
from kirabridge.file_index.source import BATCH_BYTES, ENTRIES, FILE_BYTES
from kirabridge.filesystem_manager import PathScope
from kirabridge.read_query import ReadQuery, read_query


@pytest.fixture
def sample(bridge, config, monkeypatch):
    from kirabridge.file_index import service

    monkeypatch.setattr(service, "monotonic", lambda: 1000.0)
    root = Path(config.principals["local"].roots[0])
    config.file_index = FileIndexConfig(enabled=True, projects={"project": str(root)})
    yield bridge.file_index, root
    bridge.close_file_index()


def test_more_than1000_real_text_sources_are_not_legacy_listing(sample, bridge, monkeypatch):
    index, root = sample
    for position in range(1050):
        (root / ("file-%04d.md" % position)).write_text("current orchid text")
    monkeypatch.setattr(bridge.filesystem, "list", lambda *a: pytest.fail("legacy1000 listing"))
    for _ in range(20):
        state = index.scan("local", "project")
        assert state["scanned"] <= ENTRIES and state["source_bytes"] <= BATCH_BYTES
        if state["status"] == "reconciled_observation":
            break
    assert state["status"] == "reconciled_observation"
    cursor, paths = None, []
    for _ in range(30):
        page = index.query("local", "project", "orchid", limit=100, cursor=cursor)
        assert page["mode"] == "fts5" and not page["complete"]
        paths.extend(hit["path"] for hit in page["hits"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert len(paths) == len(set(paths)) == 1050


def test_failed_reads_are_budgeted_and_oversize_is_not_materialized(sample):
    index, root = sample
    for position in range(12):
        (root / ("bad-%02d.md" % position)).write_bytes(b"bad\xff")
    page = index.query("local", "project", "orchid")
    assert not page["hits"] and page["next_cursor"] and "byte_budget" in page["reasons"]
    assert index.scan("local", "project")["source_bytes"] <= BATCH_BYTES
    (root / "large.md").write_bytes(b"orchid" + b"x" * FILE_BYTES)
    cursor, seen = None, set()
    for _ in range(10):
        page = index.query("local", "project", "orchid", cursor=cursor)
        seen.update(page["reasons"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert not page["hits"] and "source_over_limit" in seen


@pytest.mark.parametrize(
    "query", ["", "x" * 513, "x\0", "x\x7f", "x\x85", "x\x9f", " ".join(["x"] * 17)]
)
def test_query_bounds_and_no_operator_expansion(sample, query):
    index, _ = sample
    with pytest.raises(BridgeError, match="literal"):
        index.query("local", "project", query)


@pytest.mark.parametrize(
    "values",
    [
        {"operation": "file.search", "project": "project", "path": "/outside"},
        {"operation": "file.read", "path": "/outside", "project": "project"},
        {"operation": "file.search", "project": "project", "limit": 1},
        {"operation": "file.search", "project": "project", "text": "x", "limit": True},
        {"operation": "file.search", "project": "../outside", "text": "x"},
    ],
)
def test_cached_dictionary_tool_rejects_mixed_or_unbounded_selectors(values):
    with pytest.raises(ValidationError):
        ReadQuery.model_validate(values)


def test_corrupt_optional_cache_falls_back_and_core_remains_available(sample, bridge):
    index, root = sample
    (root / "note.md").write_text("orchid")
    assert index.query("local", "project", "orchid")["hits"]
    index.cache.close()
    index.cache.path.write_bytes(b"broken SQLite cache")
    page = index.query("local", "project", "orchid")
    assert page["mode"] == "bounded_scan" and page["index_status"] == "index_unavailable"
    assert page["hits"] and not page["complete"]
    assert (
        bridge.filesystem.read(
            PathScope([str(root)]),
            str(root / "note.md"),
            100,
        )["text"]
        == "orchid"
    )
    assert bridge.store.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_no_fts_available_is_a_named_bounded_fallback(sample, monkeypatch):
    from kirabridge.file_index import cache

    index, root = sample
    (root / "note.md").write_text("orchid")
    monkeypatch.setattr(cache, "FTS_SQL", "CREATE VIRTUAL TABLE content USING missing_fts5(body)")
    page = index.query("local", "project", "orchid")
    assert page["mode"] == "bounded_scan" and page["hits"]
    assert not index.cache.fts


def test_literal_operators_are_not_executed(sample):
    index, root = sample
    (root / "note.md").write_text("alpha only")
    for _ in range(10):
        if index.scan("local", "project")["status"] != "building":
            break
    assert not index.query("local", "project", "alpha OR absent")["hits"]
    assert not index.query("local", "project", '" OR 1=1 --')["hits"]


def test_real_read_query_and_local_operator_scan_cli(sample, bridge, capsys):
    from argparse import ArgumentParser

    from kirabridge.file_index.cli import execute, register

    index, root = sample
    (root / "note.md").write_text("orchid")
    parser = ArgumentParser()
    register(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["file-index", "scan", "project", "--batches", "20"])
    execute(index, "local", args, lambda value: print(json.dumps(value)))
    assert json.loads(capsys.readouterr().out)["status"] == "reconciled_observation"
    result = read_query(
        bridge, "local", ReadQuery(operation="file.search", project="project", text="orchid")
    )
    assert result["hits"][0]["path"] == str(root / "note.md")
    assert read_query(bridge, "local", ReadQuery(operation="file.search", project="project"))[
        "enabled"
    ]


def test_live_cache_query_interruption_preserves_a_continuation(sample, monkeypatch):
    index, root = sample
    (root / "note.md").write_text("orchid")
    for _ in range(10):
        if index.scan("local", "project")["status"] != "building":
            break
    real = index.cache.db

    class OnceInterrupted:
        interrupted = False

        def execute(self, sql, *args):
            if "content MATCH" in sql and not self.interrupted:
                self.interrupted = True
                raise sqlite3.OperationalError("interrupted")
            return real.execute(sql, *args)

        def set_progress_handler(self, *args):
            real.set_progress_handler(*args)

    proxy = OnceInterrupted()
    monkeypatch.setattr(index.cache, "open", lambda: proxy)
    first = index.query("local", "project", "orchid")
    assert not first["hits"] and first["next_cursor"] and "query_budget" in first["reasons"]
    second = index.query("local", "project", "orchid", cursor=first["next_cursor"])
    assert second["hits"]


def test_time_budget_preserves_observed_position(sample, monkeypatch):
    from kirabridge.file_index import service
    from kirabridge.file_index.source import Source

    index, root = sample
    for name in ("one.md", "two.md"):
        (root / name).write_text("orchid")
    clock = [1000.0]
    original = Source.capture
    monkeypatch.setattr(service, "monotonic", lambda: clock[0])

    def elapsed(source, *args):
        result = original(source, *args)
        clock[0] += 0.2
        return result

    monkeypatch.setattr(Source, "capture", elapsed)
    first = index.query("local", "project", "orchid")
    assert len(first["hits"]) == 1 and first["next_cursor"] and "time_budget" in first["reasons"]
    second = index.query("local", "project", "orchid", cursor=first["next_cursor"])
    assert len(second["hits"]) == 1 and first["hits"][0]["path"] != second["hits"][0]["path"]


def test_corrupt_cache_is_explicitly_regenerable_without_touching_source(sample):
    index, root = sample
    path = root / "note.md"
    path.write_text("orchid")
    original = (path.read_bytes(), path.stat().st_mtime_ns)
    index.status("local", "project")
    index.cache.close()
    index.cache.path.write_bytes(b"broken derived index")
    assert index.query("local", "project", "orchid")["index_status"] == "index_unavailable"
    index.close()
    index.cache.discard()
    for _ in range(10):
        if index.scan("local", "project")["status"] != "building":
            break
    assert index.query("local", "project", "orchid")["mode"] == "fts5"
    assert original == (path.read_bytes(), path.stat().st_mtime_ns)


def test_superseded_scan_cannot_publish_or_delete_the_new_scan(sample):
    from kirabridge.file_index import FileIndex

    index, root = sample
    for position in range(510):
        (root / ("note-%04d.md" % position)).write_text("orchid")
    assert index.scan("local", "project")["status"] == "building"
    other = FileIndex(index.config, index.security)
    try:
        assert other.scan("local", "project")["status"] == "building"
        with pytest.raises(BridgeError, match="superseded"):
            index.scan("local", "project")
        for _ in range(10):
            if other.scan("local", "project")["status"] != "building":
                break
        assert other.status("local", "project")["mode"] == "fts5"
        assert other.cache.db.execute("SELECT count(*) FROM files").fetchone()[0] == 510
    finally:
        other.close()


def test_restarted_process_does_not_publish_an_interrupted_scan(sample):
    from kirabridge.file_index import FileIndex

    index, root = sample
    for position in range(510):
        (root / ("note-%04d.md" % position)).write_text("orchid")
    assert index.scan("local", "project")["status"] == "building"
    index.close()
    other = FileIndex(index.config, index.security)
    try:
        assert other.status("local", "project")["mode"] == "bounded_scan"
        assert other.scan("local", "project")["status"] == "building"
        for _ in range(10):
            if other.scan("local", "project")["status"] != "building":
                break
        assert other.status("local", "project")["mode"] == "fts5"
    finally:
        other.close()


def test_depth_budget_stays_partial_and_closes_walks(sample):
    index, root = sample
    folder = root
    for _ in range(13):
        folder = folder / "deep"
        folder.mkdir()
    (folder / "note.md").write_text("orchid")
    result = index.scan("local", "project")
    assert result["status"] == "partial" and "depth_budget" in result["reasons"]
    assert not result["complete"] and not index.scans
    assert index.status("local", "project")["mode"] == "bounded_scan"


@pytest.mark.parametrize("alias", ["ancestor", "directory", "database", "hardlink"])
def test_unsafe_cache_paths_never_open_a_foreign_database(sample, tmp_path, alias):
    from kirabridge.file_index.cache import Cache

    index, root = sample
    (root / "note.md").write_text("orchid")
    foreign = tmp_path / "foreign"
    foreign.mkdir(mode=0o700)
    target = foreign / "other.sqlite3"
    target.write_bytes(b"foreign database must be unchanged")
    target.chmod(0o600)
    if alias == "ancestor":
        linked_state = tmp_path / "state-alias"
        linked_state.symlink_to(foreign, target_is_directory=True)
        index.cache = Cache(linked_state)
    elif alias == "directory":
        index.cache.directory.symlink_to(foreign, target_is_directory=True)
    else:
        index.cache.directory.mkdir(mode=0o700)
        if alias == "database":
            index.cache.path.symlink_to(target)
        else:
            index.cache.path.hardlink_to(target)
    page = index.query("local", "project", "orchid")
    assert page["mode"] == "bounded_scan" and page["index_status"] == "index_unavailable"
    assert page["hits"] and target.read_bytes() == b"foreign database must be unchanged"
    assert not (foreign / "content.sqlite3").exists()
    assert not (foreign / "file-index").exists()
