"""Home relay script (scripts/remote_handoff_relay.py): the opt-in team route.

The relay is installed outside the package, so these tests load the versioned script
by path and replace ThreadDesk and KiraBridge with in-memory fakes. Nothing here
connects to a server or starts an agent.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "remote_handoff_relay.py"
PROJECT = "d0c0cb9edc3d"
TEAM = {"team_id": "kirabridge-team", "cwd": "/work/claude"}


@pytest.fixture(scope="module")
def relay_module():
    spec = importlib.util.spec_from_file_location("remote_handoff_relay_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


class FakeThreadDesk:
    def __init__(self, issued: dict):
        self.issued = issued
        self.calls: list[tuple[str, dict]] = []
        self.board: list[tuple[str, str, str]] = []

    async def handoff(self, project, tool, arguments):
        assert project == PROJECT
        self.calls.append((tool, arguments))
        if tool == "get_issued_handoff":
            return {"found": True, "issued": self.issued}
        if tool == "reserve_handoff_delivery":
            self.issued["remote_delivery"] = arguments
            return {"reserved": True}
        raise AssertionError(tool)

    async def whiteboard(self, project, entry_type, key, content):
        self.board.append((entry_type, key, content))


class FakeKiraBridge:
    def __init__(self, work: dict | None = None):
        self.work = work or {}
        self.calls: list[tuple[str, dict]] = []

    async def call(self, tool, arguments):
        self.calls.append((tool, arguments))
        if tool == "team_work_create":
            key = arguments["request"]["idempotency_key"]
            # Same idempotency key -> same work, like TeamManager.delegate.
            return self.work.setdefault(key, {"id": "tw-" + "a" * 32, "state": "queued"})
        if tool == "team_work_get":
            return self.work.get("get", {"error": {"code": "not_found"}})
        raise AssertionError(f"unexpected tool {tool}")

    async def task(self, task_id):
        raise AssertionError("team handoffs must not use task_get")


def make_relay(module, tmp_path, td, kb, *, team=True):
    relay = object.__new__(module.Relay)
    project = {"cwd": "/work/project", "agent": "codex"}
    if team:
        project["team_agents"] = {"claude": dict(TEAM)}
    relay.config = {
        "server": "https://td.example",
        "device_ref": "mac-relay",
        "principal": "remote",
        "projects": {PROJECT: project},
    }
    relay.state_path = tmp_path / "state.json"
    relay.state = {}
    relay.td, relay.kb = td, kb
    return relay


def issued(target="claude"):
    return {
        "content_hash": "c" * 64,
        "handoff": {
            "target_system": target,
            "task": "Datei anlegen",
            "context": {"description": "Nur im Testordner."},
            "acceptance_criteria": ["Datei existiert"],
        },
    }


def item(remote_delivery=None):
    return {
        "handoff_id": "83d6b38e97ea",
        "content_hash": "c" * 64,
        "remote_delivery": remote_delivery,
    }


async def test_team_route_reserves_creates_one_work_and_reports_progress(relay_module, tmp_path):
    td, kb = FakeThreadDesk(issued()), FakeKiraBridge()
    relay = make_relay(relay_module, tmp_path, td, kb)

    await relay.deliver(PROJECT, item())

    assert [tool for tool, _ in td.calls] == [
        "get_issued_handoff",
        "reserve_handoff_delivery",
        "get_issued_handoff",
    ]
    ((tool, arguments),) = kb.calls
    request = arguments["request"]
    assert tool == "team_work_create"
    assert request["team_id"] == "kirabridge-team"
    assert request["assignee"] == "claude"
    assert request["idempotency_key"] == "remote-83d6b38e97ea"
    # The worker's own folder is used, never the project folder.
    assert "/work/claude" in request["body"] and "/work/project" not in request["body"]
    entry = json.loads(relay.state_path.read_text())["83d6b38e97ea"]
    assert entry["kind"] == "team" and entry["task_id"].startswith("tw-")
    assert entry["status"] == "submitted"
    assert [(kind, key) for kind, key, _ in td.board] == [
        ("progress", "remote-accepted-83d6b38e97ea")
    ]


async def test_team_route_retry_after_own_reservation_does_not_reserve_again(
    relay_module, tmp_path
):
    td, kb = FakeThreadDesk(issued()), FakeKiraBridge()
    first = make_relay(relay_module, tmp_path, td, kb)
    await first.deliver(PROJECT, item())
    marker = td.issued["remote_delivery"]

    # Crash before the local state was kept: the next round sees its own reservation.
    td.calls.clear()
    again = make_relay(relay_module, tmp_path / "second", td, kb)
    await again.deliver(PROJECT, item(remote_delivery=marker))

    assert [tool for tool, _ in td.calls] == ["get_issued_handoff"]
    assert len({call[1]["request"]["idempotency_key"] for call in kb.calls}) == 1
    assert again.state["83d6b38e97ea"]["task_id"] == first.state["83d6b38e97ea"]["task_id"]


async def test_team_route_skips_handoff_reserved_by_another_device(relay_module, tmp_path):
    td, kb = FakeThreadDesk(issued()), FakeKiraBridge()
    relay = make_relay(relay_module, tmp_path, td, kb)

    await relay.deliver(PROJECT, item(remote_delivery={"device_ref": "other"}))

    assert kb.calls == [] and relay.state == {} and td.board == []


async def test_projects_without_team_route_keep_the_approval_task(
    relay_module, tmp_path, monkeypatch
):
    td = FakeThreadDesk(issued(target="claude"))

    class ApprovalKiraBridge(FakeKiraBridge):
        async def task(self, task_id):
            return None

        async def call(self, tool, arguments):
            self.calls.append((tool, arguments))
            assert tool == "task_request"
            return {"id": arguments["request"]["task_id"]}

    kb = ApprovalKiraBridge()
    relay = make_relay(relay_module, tmp_path, td, kb, team=False)
    monkeypatch.setattr(relay_module, "notify", lambda *args: None)

    await relay.deliver(PROJECT, item())

    ((tool, arguments),) = kb.calls
    assert arguments["request"]["operation"] == "agent.execute"
    assert "kind" not in relay.state["83d6b38e97ea"]


@pytest.mark.parametrize(
    ("work", "state", "text"),
    [
        (
            {"id": "tw-1", "state": "completed", "result": "Datei angelegt."},
            "completed",
            "Datei angelegt.",
        ),
        (
            {
                "id": "tw-1",
                "state": "failed",
                "result": None,
                "evidence": {"core_state": "failed", "core_task_id": "t-9"},
            },
            "failed",
            "core_task_failed",
        ),
        ({"error": {"code": "not_found"}}, "unknown", "missing_local_team_work"),
    ],
)
async def test_team_result_is_reported_once_to_the_whiteboard(
    relay_module, tmp_path, work, state, text
):
    td, kb = FakeThreadDesk(issued()), FakeKiraBridge({"get": work})
    relay = make_relay(relay_module, tmp_path, td, kb)
    entry = {
        "project": PROJECT,
        "kind": "team",
        "team_id": "kirabridge-team",
        "task_id": "tw-1",
        "agent": "claude",
        "status": "submitted",
    }
    relay.state["83d6b38e97ea"] = entry

    await relay.report("83d6b38e97ea", entry)

    ((kind, key, content),) = td.board
    assert key == "remote-result-83d6b38e97ea"
    assert kind == ("result" if state == "completed" else "problem")
    assert text in content
    assert entry["status"] == "reported" and entry["final_state"] == state
    assert kb.calls == [("team_work_get", {"team_id": "kirabridge-team", "work_id": "tw-1"})]


async def test_running_team_work_is_not_reported_yet(relay_module, tmp_path):
    td = FakeThreadDesk(issued())
    kb = FakeKiraBridge({"get": {"id": "tw-1", "state": "running", "result": None}})
    relay = make_relay(relay_module, tmp_path, td, kb)
    entry = {
        "project": PROJECT,
        "kind": "team",
        "team_id": "kirabridge-team",
        "task_id": "tw-1",
        "agent": "claude",
        "status": "submitted",
    }

    await relay.report("83d6b38e97ea", entry)

    assert td.board == [] and entry["status"] == "submitted"
