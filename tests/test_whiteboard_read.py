import json
from contextlib import contextmanager
from pathlib import Path

import pytest

from kirabridge.bridge_core.models import BridgeError
from kirabridge.whiteboard_read import append_whiteboard, read_whiteboard

OPERATOR = Path.home() / ".local/share/threaddesk/kirabridge-operator"
REPAIR = "1b7530de7c5f"
ENTRY = "1faa9811f695"


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "desk"
    board = root / "whiteboard" / "thread-a"
    board.mkdir(parents=True)
    (root / "threads").mkdir()
    (root / "threads" / "thread-a.json").write_text(
        json.dumps({"id": "thread-a", "title": "Beispiel"})
    )
    (root / "state.json").write_text(json.dumps({"current_id": "thread-a"}))
    (board / "entry-1.json").write_text(
        json.dumps(
            {
                "id": "entry-1",
                "ordinal": 1,
                "entry_type": "note",
                "actor": "Grok",
                "created_at": "2026-10-28T00:00:00Z",
                "content": "sichtbarer Eintrag",
            }
        )
    )
    return root


def test_reads_one_entry_without_changing_files(tmp_path):
    root = _workspace(tmp_path)
    before = sorted(path.name for path in root.rglob("*"))
    result = read_whiteboard(str(root), "thread-a", "entry-1")
    assert result["title"] == "Beispiel"
    assert result["is_active_thread"] is True
    assert result["entry"]["content"] == "sichtbarer Eintrag"
    assert result["entry"]["untrusted"] is True
    assert sorted(path.name for path in root.rglob("*")) == before


def test_active_thread_is_not_another_board(tmp_path):
    root = _workspace(tmp_path)
    other = root / "threads" / "other-board.json"
    other.write_text(json.dumps({"id": "other-board", "title": "Andere"}))
    (root / "whiteboard" / "other-board").mkdir()
    listed = read_whiteboard(str(root))
    assert listed["thread_id"] == "thread-a"
    assert listed["entries"][0]["id"] == "entry-1"
    assert "content" not in listed["entries"][0]


def test_append_is_readable_and_does_not_rewrite(tmp_path):
    root = _workspace(tmp_path)
    state = (root / "state.json").read_text()
    first = append_whiteboard(
        str(root),
        "thread-a",
        actor="ChatGPT",
        actor_type="chatgpt",
        entry_type="note",
        content="Neue Notiz",
        external_key="once-key",
    )
    assert first["appended"] is True and first["duplicate"] is False
    assert first["ordinal"] == 2
    again = append_whiteboard(
        str(root),
        "thread-a",
        actor="ChatGPT",
        actor_type="chatgpt",
        entry_type="note",
        content="Neue Notiz",
        external_key="once-key",
    )
    assert again["duplicate"] is True and again["id"] == first["id"]
    stored = (root / "whiteboard" / "thread-a" / f"{first['id']}.json").read_bytes()
    third = append_whiteboard(
        str(root),
        "thread-a",
        actor="ChatGPT",
        actor_type="chatgpt",
        entry_type="note",
        content="Neue Notiz",
        external_key="once-key",
    )
    assert third["id"] == first["id"]
    assert (root / "whiteboard" / "thread-a" / f"{first['id']}.json").read_bytes() == stored
    read = read_whiteboard(str(root), "thread-a", first["id"])
    assert read["entry"]["content"] == "Neue Notiz"
    assert read["entry"]["ordinal"] == 2
    listed = read_whiteboard(str(root), "thread-a")
    assert [item["ordinal"] for item in listed["entries"]] == [1, 2]
    assert (root / "state.json").read_text() == state
    with pytest.raises(BridgeError, match="different content"):
        append_whiteboard(
            str(root),
            "thread-a",
            actor="ChatGPT",
            actor_type="chatgpt",
            entry_type="note",
            content="Anderer Text",
            external_key="once-key",
        )


def test_rejects_path_escape(tmp_path):
    root = _workspace(tmp_path)
    with pytest.raises(BridgeError, match="invalid"):
        read_whiteboard(str(root), "../secrets", None)


@pytest.mark.skipif(
    not (OPERATOR / "threads" / f"{REPAIR}.json").is_file(), reason="no operator board"
)
def test_reads_existing_repair_entry_without_writing():
    stamp = (OPERATOR / "state.json").stat().st_mtime_ns
    result = read_whiteboard(str(OPERATOR), REPAIR, ENTRY)
    assert result["title"] == "KiraBridge – Reparatur 2026"
    assert result["is_active_thread"] is False
    assert result["active_thread_id"] != REPAIR
    assert result["entry"]["ordinal"] == 28
    assert result["entry"]["content"].startswith("Schritt 7")
    assert (OPERATOR / "state.json").stat().st_mtime_ns == stamp


async def test_whiteboard_tools_are_in_the_catalog(bridge):
    from kirabridge.mcp_gateway.server import create_server

    server = create_server(bridge)
    tools = await server.list_tools()
    names = {tool.name for tool in tools}
    assert {"whiteboard_read", "whiteboard_append"} <= names


def test_append_touches_thread_under_workspace_lock_not_inside_append_lock(tmp_path, monkeypatch):
    import kirabridge.whiteboard_read as module

    for folder in ("threads", "whiteboard"):
        (tmp_path / folder).mkdir()
    (tmp_path / "threads" / "t1.json").write_text(json.dumps({"id": "t1", "title": "T"}))
    held, events = [], []
    original = module._exclusive

    @contextmanager
    def tracked(path):
        with original(path):
            held.append(path.name)
            try:
                yield
            finally:
                held.remove(path.name)

    def touch(path):
        events.append(list(held))

    monkeypatch.setattr(module, "_exclusive", tracked)
    monkeypatch.setattr(module, "_touch_thread", touch)
    first = append_whiteboard(
        str(tmp_path),
        "t1",
        actor="a",
        actor_type="claude",
        entry_type="note",
        content="one",
        external_key="k1",
    )
    again = append_whiteboard(
        str(tmp_path),
        "t1",
        actor="a",
        actor_type="claude",
        entry_type="note",
        content="one",
        external_key="k1",
    )
    assert first["appended"] and again["duplicate"] and again["id"] == first["id"]
    # Same lock order as ThreadDesk; a duplicate never rewrites the thread.
    assert events == [[".management.lock"]]
