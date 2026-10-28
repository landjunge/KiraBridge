import json
from pathlib import Path

import pytest

from kirabridge.bridge_core.models import BridgeError
from kirabridge.whiteboard_read import read_whiteboard

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


def test_rejects_path_escape(tmp_path):
    root = _workspace(tmp_path)
    with pytest.raises(BridgeError, match="invalid"):
        read_whiteboard(str(root), "../secrets", None)


@pytest.mark.skipif(not (OPERATOR / "threads" / f"{REPAIR}.json").is_file(), reason="no operator board")
def test_reads_existing_repair_entry_without_writing():
    stamp = (OPERATOR / "state.json").stat().st_mtime_ns
    result = read_whiteboard(str(OPERATOR), REPAIR, ENTRY)
    assert result["title"] == "KiraBridge – Reparatur 2026"
    assert result["is_active_thread"] is False
    assert result["active_thread_id"] != REPAIR
    assert result["entry"]["ordinal"] == 28
    assert result["entry"]["content"].startswith("Schritt 7")
    assert (OPERATOR / "state.json").stat().st_mtime_ns == stamp
