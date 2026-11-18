"""A returned failure carries one normalized error; nothing is scraped from text."""

from kirabridge.completion_manager import completion_payload
from kirabridge.task_manager.failure import normalize_failure


def test_process_exit_timeout_and_kill_are_distinguished():
    exit_one = {"success": False, "exit_code": 1, "evidence": {"exit_code": 1}}
    assert normalize_failure(exit_one) == {
        "code": "command_exit_nonzero",
        "kind": "command_exit",
        "retry_safe": False,
        "exit_code": 1,
    }
    timeout = {"exit_code": -15, "evidence": {"timed_out": True, "exit_code": -15}}
    assert normalize_failure(timeout)["kind"] == "timeout"
    killed = {"exit_code": -15, "evidence": {"timed_out": False, "terminated": False}}
    assert normalize_failure(killed)["code"] == "command_killed"
    agent = {"exit_code": 1, "evidence": {"agent": "claude", "exit_code": 1}}
    assert normalize_failure(agent)["kind"] == "agent_exit"


def test_peer_error_code_is_kept_and_only_unsent_requests_are_retry_safe():
    rejected = {
        "evidence": {"request_sent": True, "response_received": True},
        "value": {"error": {"code": "tool_error", "message": "ignored text"}},
    }
    assert normalize_failure(rejected) == {
        "code": "tool_error",
        "kind": "tool_rejected",
        "retry_safe": False,
    }
    unsent = {
        "evidence": {"request_sent": False, "validation_failed": True},
        "value": {"error": {"code": "threaddesk_validation"}},
    }
    assert normalize_failure(unsent) == {
        "code": "threaddesk_validation",
        "kind": "validation",
        "retry_safe": True,
    }


def test_unusable_input_never_invents_details():
    assert normalize_failure(None)["code"] == "operation_failed"
    assert normalize_failure({"success": False})["kind"] == "failed"
    assert normalize_failure({"exit_code": True})["code"] == "operation_failed"
    bad = {"value": {"error": {"code": "Not A Code!"}}}
    assert normalize_failure(bad)["code"] == "tool_rejected"


def test_completion_payload_reads_the_normalized_error():
    task = {
        "id": "t",
        "operation": "terminal.execute",
        "state": "failed",
        "error": {"code": "command_timeout", "kind": "timeout", "retry_safe": False},
        "result": {"exit_code": -15},
        "evidence": {},
        "created": 1.0,
        "updated": 2.0,
        "started": 1.0,
        "finished": 2.0,
    }
    payload = completion_payload(task, 1)
    assert payload["error_code"] == "command_timeout" and payload["outcome"] == "timeout"
    assert payload["error_kind"] == "timeout"
