"""`team coordinator` switches the coordinator without a hand-typed revision."""

import sys
from types import SimpleNamespace

import pytest

from kirabridge import cli


@pytest.fixture
def calls(monkeypatch, tmp_path):
    made, output = [], []

    class FakePool:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def connect(self, _peer):
            return None

        async def call(self, _server, tool, arguments):
            made.append((tool, arguments))
            if tool == "team_get":
                return SimpleNamespace(structuredContent={"id": "t1", "revision": 7})
            return SimpleNamespace(structuredContent={"coordinator": "local", "revision": 8})

    monkeypatch.setattr(cli, "load_config", lambda _: SimpleNamespace())
    monkeypatch.setattr("kirabridge.local_runtime.peer", lambda config, principal: "peer")
    monkeypatch.setattr("kirabridge.mcp_gateway.client.MCPClientPool", FakePool)
    monkeypatch.setattr(cli, "emit", lambda value, **_: output.append(value))

    def run(*arguments):
        monkeypatch.setattr(
            sys,
            "argv",
            ["kirabridge", "--config", str(tmp_path / "x.toml"), "team", *arguments],
        )
        cli.main()
        return output[-1]

    return run, made


def test_coordinator_shortcut_reads_the_current_revision_then_sets_the_role(calls):
    run, made = calls
    result = run("coordinator", "t1", "local", "--key", "k-1")
    assert result == {"coordinator": "local", "revision": 8}
    assert [tool for tool, _ in made] == ["team_get", "team_set_role"]
    request = made[1][1]["request"]
    assert request == {
        "team_id": "t1",
        "member": "local",
        "role": "coordinator",
        "active": True,
        "expected_revision": 7,
        "idempotency_key": "k-1",
    }


def test_role_with_explicit_revision_does_not_read_the_team_first(calls):
    run, made = calls
    run("role", "t1", "codex", "worker", "--revision", "3", "--key", "k-2")
    assert [tool for tool, _ in made] == ["team_set_role"]
    assert made[0][1]["request"]["expected_revision"] == 3


def test_coordinator_without_a_name_means_the_calling_identity(calls):
    run, made = calls
    run("coordinator", "t1", "--key", "k-3")
    assert made[1][1]["request"]["member"] == "local"  # the default --principal
