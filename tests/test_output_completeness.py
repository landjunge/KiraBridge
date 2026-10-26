"""Completeness describes retained bytes; it never reconstructs discarded output."""

from types import SimpleNamespace

import pytest

from kirabridge.bridge_core.models import BridgeError
from kirabridge.read_query import ReadQuery, read_query


def output(source, *, limit=64, live=False):
    def inspect(*_):
        if not live:
            raise BridgeError("not_found", "No live buffer")
        return source

    bridge = SimpleNamespace(
        security=SimpleNamespace(principal=lambda *_: None),
        task=lambda *_: {"operation": "terminal.execute", "state": "completed", "result": source},
        terminal=SimpleNamespace(inspect=inspect),
    )
    return read_query(
        bridge, "local", ReadQuery(operation="terminal.output", task_id="owned", max_bytes=limit)
    )


def test_previously_discarded_output_stays_truncated_in_short_response():
    result = output({"stdout": "kept", "stderr": "", "truncated": True, "output_bytes": 999})
    assert result["truncated"] is True
    assert result["output_completeness"] == {
        "capture": "truncated",
        "scope": "managed_process_capture",
        "retained_text_bytes": 4,
        "returned_text_bytes": 4,
        "response_truncated": False,
        "protocol_history": "not_established",
    }
    assert result["output_bytes_observed"] == 999


def test_live_buffer_total_reveals_discarded_bytes_without_saved_result():
    result = output({"stdout": "kept", "stderr": "", "output_bytes": 999}, live=True)
    assert result["truncated"] is True
    assert result["output_completeness"]["capture"] == "truncated"


@pytest.mark.parametrize("declared,capture", [(False, "complete"), (None, "unknown")])
def test_response_clipping_is_separate_from_capture_completeness(declared, capture):
    source = {"stdout": "a😀z", "stderr": "err"}
    if declared is not None:
        source["truncated"] = declared
    result = output(source, limit=3)
    assert result["stdout"] == "a"
    assert result["truncated"] is True
    assert result["output_completeness"]["capture"] == capture
    assert result["output_completeness"]["response_truncated"] is True
    assert result["output_completeness"]["returned_text_bytes"] == 1


def test_visible_capture_does_not_claim_complete_protocol():
    result = output({"terminal_output": "view", "truncated": False})
    assert result["output_completeness"]["scope"] == "visible_terminal_view"
    assert result["output_completeness"]["protocol_history"] == "visible_view_only"
    assert result["output_completeness"]["capture"] == "complete"
