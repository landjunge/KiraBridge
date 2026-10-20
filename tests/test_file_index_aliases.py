"""Synthetic alias countercases; no live paths, data or credentials."""

from pathlib import Path

import pytest

from kirabridge.bridge_core.config import FileIndexConfig
from kirabridge.bridge_core.models import BridgeError

MARKER = "orchid-alias-fixture-only"


def alias(path, style):
    if style == "double-anchor":
        return "//" + str(path).lstrip("/")
    step = path.parent / "alias-step"
    step.mkdir(exist_ok=True)
    return str(step / ".." / path.name)


def no_hits(bridge):
    try:
        try:
            result = bridge.file_index.query("local", "project", MARKER)
        except BridgeError as exc:
            assert exc.code == "search_scope_denied"
            return
        assert not result["hits"], "Known excluded synthetic source escaped through alias"
    finally:
        bridge.close_file_index()


@pytest.mark.parametrize("dynamic", [False, True])
def test_ambiguous_project_anchor_cannot_bypass_policy_exclusion(bridge, config, dynamic):
    root = Path(config.principals["local"].roots[0])
    policy = root / "ordinary.toml"
    policy.write_text(MARKER)
    config._source_path = str(policy)
    double = alias(root, "double-anchor")
    config.principals["local"].roots = [double]
    if dynamic:
        config.file_index = FileIndexConfig(enabled=True, projects={"project": str(root)})
        config.file_index.projects["project"] = double
    else:
        try:
            config.file_index = FileIndexConfig(enabled=True, projects={"project": double})
        except ValueError:
            return
    no_hits(bridge)


@pytest.mark.parametrize("style", ["double-anchor", "parent-component"])
@pytest.mark.parametrize("kind", ["policy", "credential", "state"])
def test_ambiguous_protected_metadata_fails_closed(bridge, config, style, kind):
    root = Path(config.principals["local"].roots[0])
    if kind == "state":
        root = config.state_path
        config.principals["local"].roots = [str(root.parent)]
        (root / "ordinary.md").write_text(MARKER)
        config.data_dir = alias(root, style)
    else:
        protected = root / ("ordinary.toml" if kind == "policy" else "ordinary.md")
        protected.write_text(MARKER)
        if kind == "policy":
            config._source_path = alias(protected, style)
        else:
            config.credentials_file = alias(protected, style)
    config.file_index = FileIndexConfig(enabled=True, projects={"project": str(root)})
    no_hits(bridge)


@pytest.mark.parametrize("style", ["double-anchor", "parent-component"])
def test_ambiguous_home_does_not_weaken_browser_exclusion(bridge, config, monkeypatch, style):
    root = Path(config.principals["local"].roots[0])
    home = root / "synthetic-home"
    browser = home / "Library" / "Safari"
    browser.mkdir(parents=True)
    (browser / "ordinary.md").write_text(MARKER)
    config.file_index = FileIndexConfig(enabled=True, projects={"project": str(browser)})
    ambiguous_home = Path(alias(home, style))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: ambiguous_home))
    no_hits(bridge)


@pytest.mark.parametrize("style", ["inner-separators", "inner-dot"])
def test_unambiguous_normalized_components_keep_source_exclusions(bridge, config, style):
    root = Path(config.principals["local"].roots[0])
    protected = root / "ordinary.toml"
    protected.write_text(MARKER)
    config._source_path = str(protected)
    (root / "public.md").write_text("public-lavender-only")
    value = str(root.parent) + ("//" if style == "inner-separators" else "/./") + root.name
    config.file_index = FileIndexConfig(enabled=True, projects={"project": value})
    try:
        assert not bridge.file_index.query("local", "project", MARKER)["hits"]
        assert bridge.file_index.query("local", "project", "public-lavender-only")["hits"]
    finally:
        bridge.close_file_index()


def test_literal_relative_credentials_path_uses_its_consumers_path_semantics(
    bridge, config, monkeypatch
):
    root = Path(config.principals["local"].roots[0])
    literal_home = root / "~"
    literal_home.mkdir()
    (literal_home / "ordinary.md").write_text(MARKER)
    monkeypatch.chdir(root)
    # local_runtime.private_json consumes Path(credentials_file), without a
    # separate user-home expansion. All content here is synthetic.
    config.credentials_file = "~/ordinary.md"
    config.file_index = FileIndexConfig(enabled=True, projects={"project": str(root)})
    no_hits(bridge)


def test_dynamic_ambiguous_exclusion_does_not_silently_lose_its_deny(bridge, config):
    root = Path(config.principals["local"].roots[0])
    (root / "step").mkdir()
    (root / "ordinary.md").write_text(MARKER)
    config.file_index = FileIndexConfig(enabled=True, projects={"project": str(root)})
    config.file_index.exclusions.append("step/../ordinary.md")
    no_hits(bridge)


def test_disabled_index_and_existing_reads_ignore_optional_metadata_ambiguity(bridge, config):
    from kirabridge.read_query import ReadQuery, read_query

    root = Path(config.principals["local"].roots[0])
    public = root / "ordinary.md"
    public.write_text("ordinary core read")
    state = config.state_path
    config.data_dir = alias(state, "double-anchor")
    config._source_path = alias(root / "policy.toml", "double-anchor")
    config.credentials_file = alias(root / "ordinary.md", "parent-component")
    assert not config.file_index.enabled
    try:
        assert bridge.file_index.query("local", "project", MARKER)["mode"] == "disabled"
        assert not (state / "file-index").exists()
        result = read_query(bridge, "local", ReadQuery(operation="file.read", path=str(public)))
        assert result["text"] == "ordinary core read"
        assert bridge.store.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        bridge.close_file_index()
