"""Many ThreadDesk writes beside large reads: every receipt arrives, nothing is doubled.

Real pinned ThreadDesk peer, private temporary workspace; no operator data.
"""

import argparse
import importlib.util
import os
import sys
from pathlib import Path

import pytest

from kirabridge.whiteboard_read import append_whiteboard

pytestmark = pytest.mark.skipif(
    not os.environ.get("KIRABRIDGE_TEST_THREADDESK_SOURCE"),
    reason="Pinned external ThreadDesk source required for real integration",
)


def benchmark():
    path = Path(__file__).resolve().parents[1] / "scripts/benchmark_threaddesk_writes.py"
    spec = importlib.util.spec_from_file_location("benchmark_threaddesk_writes", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def seeded_workspace(root, source):
    sys.path.insert(0, str(source))
    from threaddesk.api.service import ThreadService
    from threaddesk.storage.json_store import JsonStore

    root.mkdir(mode=0o700)
    service = ThreadService(JsonStore(root))
    notes = [service.create(f"notes {n}").id for n in range(2)]
    big = service.create("large")
    service.set_note("N" * 200_000, big.id)
    board = service.create("board").id
    for number in range(300):
        append_whiteboard(
            str(root),
            board,
            actor="seed",
            actor_type="system",
            entry_type="note",
            content=f"seed {number} " + "x" * 400,
        )
    return notes, board, big.id


async def test_parallel_writes_beside_large_reads_have_receipts_and_no_duplicates(tmp_path):
    source = Path(os.environ["KIRABRIDGE_TEST_THREADDESK_SOURCE"]).resolve()
    workspace = (tmp_path / "workspace").resolve()
    notes, board, big = seeded_workspace(workspace, source)
    args = argparse.Namespace(
        workspace=str(workspace),
        threaddesk_source=str(source),
        note_threads=notes,
        board_threads=[board, notes[0]],
        big_thread=big,
        big_board=board,
        writes=4,
        timeout=15,
        port=18799,
        rows=False,
    )
    summary = await benchmark().run(args)
    print(summary["phases"])
    assert summary["writes"] == 16
    assert summary["states"] == {"completed": 16, "other": 0}
    assert summary["duplicates"] == 0 and summary["missing_after_readback"] == 0
    assert summary["concurrent_large_reads"] > 0
