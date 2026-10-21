"""Synthetic project roots only; no live policy, credentials, tasks or services."""

from pathlib import Path

import pytest

from kirabridge.bridge_core.config import FileIndexConfig
from kirabridge.bridge_core.models import BridgeError
from kirabridge.read_query import ReadQuery, read_query


@pytest.fixture
def indexed(bridge, config, monkeypatch):
    from kirabridge.file_index import service

    monkeypatch.setattr(service, "monotonic", lambda: 1000.0)
    root = Path(config.principals["local"].roots[0])
    config.file_index = FileIndexConfig(enabled=True, projects={"project": str(root)})
    yield bridge.file_index, root
    bridge.close_file_index()


def build(index):
    for _ in range(100):
        result = index.scan("local", "project")
        if result["status"] != "building":
            return result
    pytest.fail("bounded synthetic scan did not finish")


def pages(index, text, **kwargs):
    hits, cursor = [], None
    for _ in range(100):
        page = index.query("local", "project", text, cursor=cursor, **kwargs)
        assert not page["complete"] and "filesystem_snapshot_unverified" in page["reasons"]
        hits.extend(page["hits"])
        cursor = page["next_cursor"]
        if cursor is None:
            return hits
    pytest.fail("bounded synthetic query did not finish")


def test_disabled_and_empty_explicit_roots_never_scan_broad_grants(bridge, config):
    config.principals["local"].roots = ["/"]
    value = read_query(
        bridge, "local", ReadQuery(operation="file.search", project="project", text="needle")
    )
    assert value["mode"] == "disabled" and not (config.state_path / "file-index").exists()
    config.file_index.enabled = True
    with pytest.raises(BridgeError, match="scope"):
        bridge.file_index.query("local", "project", "needle")
    assert not (config.state_path / "file-index").exists()
    bridge.close_file_index()


def test_initial_scan_current_plaintext_rename_delete_and_reconcile(indexed, bridge):
    index, root = indexed
    path = root / "note.md"
    path.write_text("<script> orchid current text")
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    assert build(index)["status"] == "reconciled_observation"
    page = index.query("local", "project", "orchid")
    assert page["mode"] == "fts5" and page["hits"][0]["path"] == str(path)
    assert "<script>" in page["hits"][0]["snippet"]
    assert before == (path.read_bytes(), path.stat().st_mtime_ns)
    path.write_text("replacement lavender")
    assert not index.query("local", "project", "orchid")["hits"]
    assert build(index)["status"] == "reconciled_observation"
    assert index.query("local", "project", "lavender")["hits"]
    renamed = root / "renamed.md"
    path.rename(renamed)
    assert not index.query("local", "project", "lavender")["hits"]
    build(index)
    assert index.query("local", "project", "lavender")["hits"][0]["path"] == str(renamed)
    renamed.unlink()
    build(index)
    assert not index.query("local", "project", "lavender")["hits"]
    assert bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0


@pytest.mark.parametrize("capability", ["file.read", "file.list"])
def test_both_existing_capabilities_are_required(indexed, config, capability):
    index, root = indexed
    (root / "note.md").write_text("orchid")
    config.principals["local"].capabilities.remove(capability)
    with pytest.raises(BridgeError, match="Capability"):
        index.query("local", "project", "orchid")


def test_symlinks_hardlinks_secret_names_and_binary_are_not_indexed(indexed, tmp_path):
    index, root = indexed
    outside = tmp_path / "outside.md"
    outside.write_text("private orchid")
    (root / "symlink.md").symlink_to(outside)
    (root / "hardlink.md").hardlink_to(outside)
    (root / ".env").write_text("private orchid")
    (root / "credentials.toml").write_text("private orchid")
    (root / "binary.md").write_bytes(b"private orchid\0")
    (root / "key.pem").write_text("private orchid")
    assert not pages(index, "orchid")
    build(index)
    assert not pages(index, "orchid")


def test_project_scope_is_not_an_authorization_grant(indexed, config):
    index, root = indexed
    (root / "note.md").write_text("orchid")
    build(index)
    config.principals["other"].roots = []
    with pytest.raises(BridgeError, match="allowed"):
        index.query("other", "project", "orchid")
