import base64
import json
from contextlib import contextmanager

import pytest
from pydantic import ValidationError

from kirabridge.bridge_core.models import BridgeError
from kirabridge.directory_ranges import DirectoryInput, list_directory
from kirabridge.filesystem_manager import PathScope
from kirabridge.read_query import ReadQuery, read_query


def test_ordered_directory_traversal_has_no_entry_cap_or_gaps(tmp_path):
    names = [f"entry-{i:04}" for i in range(1127)] + ["é", "你好", "Ω"]
    for name in reversed(names):
        (tmp_path / name).touch()
    scope, cursor, seen, identity = PathScope([str(tmp_path)]), "", [], None
    while True:
        page = list_directory(
            scope, str(tmp_path), limit=97, cursor=cursor, expected_identity=identity
        )
        assert page["returned_count"] <= 97
        identity = identity or page["identity"]
        assert page["identity"] == identity
        seen += [entry["name"] for entry in page["entries"]]
        cursor = page["next_cursor"]
        assert bool(cursor) == page["truncated"] == (not page["eof"])
        if not cursor:
            break
    assert seen == sorted(names)


def test_directory_continuation_rejects_mutation_and_cross_path(tmp_path):
    for name in ("a", "b", "c"):
        (tmp_path / name).touch()
    scope = PathScope([str(tmp_path)])
    page = list_directory(scope, str(tmp_path), limit=1)
    with pytest.raises(BridgeError) as exc:
        list_directory(scope, str(tmp_path / "other"), cursor=page["next_cursor"])
    assert exc.value.code == "invalid_arguments"
    (tmp_path / "d").touch()
    for selectors in ({"cursor": page["next_cursor"]}, {"expected_identity": page["identity"]}):
        with pytest.raises(BridgeError) as exc:
            list_directory(scope, str(tmp_path), **selectors)
        assert exc.value.code == "directory_changed"


@pytest.mark.parametrize(
    "cursor", ["garbage!", "e30=", base64.b64encode(b"[" * 1100 + b"0" + b"]" * 1100).decode()]
)
def test_untrusted_directory_cursors_fail_closed(tmp_path, cursor):
    with pytest.raises(BridgeError) as exc:
        list_directory(PathScope([str(tmp_path)]), str(tmp_path), cursor=cursor)
    assert exc.value.code == "invalid_arguments"


def test_directory_cursor_is_position_not_authorization(tmp_path):
    allowed, denied = tmp_path / "allowed", tmp_path / "denied"
    allowed.mkdir()
    denied.mkdir()
    for name in ("a", "b"):
        (denied / name).touch()
    token = list_directory(PathScope([str(denied)]), str(denied), limit=1)["next_cursor"]
    with pytest.raises(BridgeError):
        list_directory(PathScope([str(allowed)]), str(denied), cursor=token)
    (allowed / "link").symlink_to(denied, target_is_directory=True)
    with pytest.raises(BridgeError):
        list_directory(PathScope([str(allowed)]), str(allowed / "link"))


def test_cached_query_exposes_complete_directory_paging(bridge, config):
    from pathlib import Path

    root = Path(config.principals["local"].roots[0])
    for i in range(103):
        (root / f"{i:03}").touch()
    first = read_query(bridge, "local", ReadQuery(operation="file.list", path=str(root)))
    assert first["returned_count"] == 100 and first["truncated"]
    second = read_query(
        bridge,
        "local",
        ReadQuery(operation="file.list", path=str(root), cursor=first["next_cursor"]),
    )
    assert [x["name"] for x in second["entries"]] == ["100", "101", "102"]
    assert second["eof"] and not second["next_cursor"]
    assert bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0


def test_directory_selectors_are_strict():
    for value in (0, 1001, True, "2"):
        with pytest.raises(ValidationError):
            DirectoryInput(path="/tmp", limit=value)
    with pytest.raises(ValidationError):
        ReadQuery(operation="terminal.output", task_id="x", cursor="anything")
    with pytest.raises(ValidationError):
        ReadQuery(operation="file.read", path="/tmp", limit=10)


def test_directory_cursor_rejects_extra_fields(tmp_path):
    cursor = base64.urlsafe_b64encode(json.dumps({"v": 1, "unexpected": True}).encode()).decode()
    with pytest.raises(BridgeError):
        list_directory(PathScope([str(tmp_path)]), str(tmp_path), cursor=cursor)


def test_directory_mutation_during_enumeration_fails_whole_page(tmp_path, monkeypatch):
    import kirabridge.directory_ranges as ranges

    (tmp_path / "a").touch()
    original = ranges.heapq.nsmallest

    def changed(*args, **kwargs):
        selected = original(*args, **kwargs)
        (tmp_path / "new").touch()
        return selected

    monkeypatch.setattr(ranges.heapq, "nsmallest", changed)
    with pytest.raises(BridgeError) as exc:
        list_directory(PathScope([str(tmp_path)]), str(tmp_path))
    assert exc.value.code == "directory_changed"


def test_directory_generation_detects_mutation_with_frozen_stat_tick(tmp_path, monkeypatch):
    import kirabridge.directory_ranges as ranges

    monkeypatch.setattr(ranges, "_identity", lambda value: "f" * 64)
    for name in ("a", "b"):
        (tmp_path / name).touch()
    scope = PathScope([str(tmp_path)])
    first = list_directory(scope, str(tmp_path), limit=1)
    (tmp_path / "c").touch()
    for selectors in ({"cursor": first["next_cursor"]}, {"expected_identity": first["identity"]}):
        with pytest.raises(BridgeError) as exc:
            list_directory(scope, str(tmp_path), **selectors)
        assert exc.value.code == "directory_changed"


def test_verifying_scan_detects_mutation_even_with_frozen_stat_tick(tmp_path, monkeypatch):
    import kirabridge.directory_ranges as ranges

    monkeypatch.setattr(ranges, "_identity", lambda value: "f" * 64)
    (tmp_path / "a").touch()
    smallest = ranges.heapq.nsmallest

    def changed(*args, **kwargs):
        selected = smallest(*args, **kwargs)
        (tmp_path / "b").touch()
        return selected

    monkeypatch.setattr(ranges.heapq, "nsmallest", changed)
    with pytest.raises(BridgeError) as exc:
        list_directory(PathScope([str(tmp_path)]), str(tmp_path))
    assert exc.value.code == "directory_changed"


@pytest.mark.parametrize("change", ["replacement", "kind"])
def test_same_name_count_binds_entry_inode_and_kind_with_frozen_stat(tmp_path, monkeypatch, change):
    import kirabridge.directory_ranges as ranges

    directory = tmp_path / "directory"
    directory.mkdir()
    for name in ("a", "b"):
        (directory / name).touch()
    replacement = tmp_path / "replacement"
    replacement.touch()
    monkeypatch.setattr(ranges, "_identity", lambda value: "f" * 64)
    scope = PathScope([str(directory)])
    page = list_directory(scope, str(directory), limit=1)
    if change == "replacement":
        replacement.replace(directory / "b")
    else:
        (directory / "b").unlink()
        (directory / "b").mkdir()
    with pytest.raises(BridgeError) as exc:
        list_directory(scope, str(directory), cursor=page["next_cursor"])
    assert exc.value.code == "directory_changed"


def test_directory_checksum_is_independent_of_enumeration_order(tmp_path, monkeypatch):
    import kirabridge.directory_ranges as ranges

    for name in ("a", "b", "c"):
        (tmp_path / name).touch()
    original, calls = ranges.os.scandir, []

    @contextmanager
    def reordered(fd):
        with original(fd) as source:
            entries = list(source)
        calls.append(True)
        yield iter(entries if len(calls) % 2 else list(reversed(entries)))

    monkeypatch.setattr(ranges.os, "scandir", reordered)
    scope = PathScope([str(tmp_path)])
    first = list_directory(scope, str(tmp_path), limit=1)
    second = list_directory(scope, str(tmp_path), limit=1, cursor=first["next_cursor"])
    assert first["identity"] == second["identity"]
    assert [row["name"] for row in first["entries"] + second["entries"]] == ["a", "b"]
