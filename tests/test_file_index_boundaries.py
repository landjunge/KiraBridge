"""Adversarial filesystem changes and live-policy checks, synthetic only."""

import os
from pathlib import Path

import pytest

from kirabridge.bridge_core.config import FileIndexConfig
from kirabridge.bridge_core.models import BridgeError
from kirabridge.file_index.source import Source


@pytest.fixture
def sample(bridge, config, monkeypatch):
    from kirabridge.file_index import service

    monkeypatch.setattr(service, "monotonic", lambda: 1000.0)
    root = Path(config.principals["local"].roots[0])
    config.file_index = FileIndexConfig(enabled=True, projects={"project": str(root)})
    yield bridge.file_index, root
    bridge.close_file_index()


@pytest.mark.parametrize("change", ["root", "parent", "leaf"])
def test_open_source_cannot_emit_text_after_root_parent_or_leaf_exchange(
    sample, tmp_path, monkeypatch, change
):
    index, root = sample
    folder = root / "sub"
    folder.mkdir()
    path = folder / "note.md"
    path.write_text("old orchid must never escape its observed path")
    original, fired = os.open, []

    def exchanged(name, flags, *args, **kwargs):
        fd = original(name, flags, *args, **kwargs)
        if name == "note.md" and "dir_fd" in kwargs and not fired:
            fired.append(True)
            if change == "root":
                root.rename(tmp_path / "moved-root")
                (root / "sub").mkdir(parents=True)
            elif change == "parent":
                folder.rename(tmp_path / "moved-parent")
                folder.mkdir()
            else:
                path.rename(tmp_path / "moved-note.md")
            path.write_text("replacement tulip")
        return fd

    monkeypatch.setattr(os, "open", exchanged)
    if change == "root":
        with pytest.raises(BridgeError, match="observation changed"):
            index.query("local", "project", "orchid")
    else:
        page = index.query("local", "project", "orchid")
        assert not page["hits"] and "source_changed" in page["reasons"]
    assert fired


@pytest.mark.parametrize("change", ["capability", "root", "exclusion"])
def test_revocation_during_a_hit_discards_the_whole_page(sample, config, monkeypatch, change):
    index, root = sample
    for name in ("one.md", "two.md"):
        (root / name).write_text("orchid")
    original, fired = Source.capture, []

    def revoked(source, *args, **kwargs):
        doc = original(source, *args, **kwargs)
        if not fired:
            fired.append(True)
            if change == "capability":
                config.principals["local"].capabilities.remove("file.read")
            elif change == "root":
                config.principals["local"].roots = []
            else:
                config.file_index.exclusions.append("two.md")
        return doc

    monkeypatch.setattr(Source, "capture", revoked)
    with pytest.raises(BridgeError):
        index.query("local", "project", "orchid")
    assert fired


def test_bridge_state_exclusion_survives_explicit_full_grant(sample, config):
    index, _ = sample
    policy = config.principals["local"]
    policy.roots = ["/"]
    policy.permission_level = "full"
    policy.allow_any_executable = True
    config.file_index.projects["state"] = str(config.state_path)
    with pytest.raises(BridgeError):
        index.query("local", "state", "orchid")


def test_loaded_config_and_credential_paths_are_excluded_even_with_ordinary_names(sample, config):
    index, root = sample
    config._source_path = str(root / "ordinary.toml")
    config.credentials_file = str(root / "ordinary.md")
    for name in ("ordinary.toml", "ordinary.md"):
        (root / name).write_text("private orchid")
    assert not index.query("local", "project", "orchid")["hits"]
    assert index.scan("local", "project")["status"] == "reconciled_observation"
    assert index.cache.db.execute("SELECT count(*) FROM files").fetchone()[0] == 0


def test_exclusion_case_aliases_and_symlink_directories_are_never_sources(sample, tmp_path):
    index, root = sample
    config = index.config
    config.file_index.exclusions = ["private"]
    (root / "PRIVATE").mkdir()
    (root / "PRIVATE/note.md").write_text("orchid")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "note.md").write_text("orchid")
    (root / "escape").symlink_to(outside, target_is_directory=True)
    page = index.query("local", "project", "orchid")
    assert not page["hits"] and not page["complete"]


@pytest.mark.parametrize(
    "change", ["query", "limit", "principal", "policy", "restart", "reconcile"]
)
def test_cursor_is_bound_to_query_scope_policy_and_live_instance(sample, config, change):
    index, root = sample
    for name in ("one.md", "two.md"):
        (root / name).write_text("orchid")
    first = index.query("local", "project", "orchid", limit=1)
    assert first["next_cursor"]
    principal, text, limit = "local", "orchid", 1
    if change == "query":
        text = "tulip"
    elif change == "limit":
        limit = 2
    elif change == "principal":
        principal = "other"
    elif change == "policy":
        config.file_index.exclusions = ["unknown.md"]
    elif change == "restart":
        from kirabridge.file_index import FileIndex

        index = FileIndex(index.config, index.security)
    elif change == "reconcile":
        index.scan("local", "project")
    try:
        with pytest.raises(BridgeError, match="changed|unavailable"):
            index.query(principal, "project", text, limit=limit, cursor=first["next_cursor"])
    finally:
        index.close()


def test_cursor_is_once_only_expires_and_has_bounded_open_iterators(sample):
    index, root = sample
    for name in ("one.md", "two.md"):
        (root / name).write_text("orchid")
    first = index.query("local", "project", "orchid", limit=1)["next_cursor"]
    index.query("local", "project", "orchid", limit=1, cursor=first)
    with pytest.raises(BridgeError, match="unavailable"):
        index.query("local", "project", "orchid", limit=1, cursor=first)
    oldest = index.query("local", "project", "orchid", limit=1)["next_cursor"]
    for _ in range(4):
        index.query("local", "project", "orchid", limit=1)
    assert len(index.queries) == 4
    with pytest.raises(BridgeError, match="unavailable"):
        index.query("local", "project", "orchid", limit=1, cursor=oldest)
    latest = next(reversed(index.queries))
    index.queries[latest]["created"] -= 301
    with pytest.raises(BridgeError, match="unavailable"):
        index.query("local", "project", "orchid", limit=1, cursor=latest)
