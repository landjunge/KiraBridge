"""Native construction and real authenticated MCP; provider CLIs are fixtures."""

import json

import pytest
from test_autonext import scenario, until  # noqa: F401
from test_autonext_coordinator import configure
from test_mcp import http_bridge  # noqa: F401

from kirabridge.autonext.coordinator import CoordinatedAutoNext
from kirabridge.autonext.manager import AutoNextManager, text_sha
from kirabridge.autonext.models import ApprovedCard, AutoNextConfig
from kirabridge.autonext.status import coordinator_status
from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.models import BridgeError
from kirabridge.mcp_gateway.client import MCPClientPool, Peer
from kirabridge.read_query import ReadQuery, read_query_async
from kirabridge.whiteboard_read import append_whiteboard


@pytest.fixture
def bridge(config):
    # Select the real native manager before any dispatcher or grant is enabled.
    config.autonext = AutoNextConfig(principal="codex", coordinator_mode=True)
    instance = Bridge(config)
    yield instance
    instance.store.close()


def prepared(s, tmp_path, monkeypatch, **options):
    original = s["bridge"].autonext
    assert isinstance(original, CoordinatedAutoNext)
    card = configure(s, tmp_path, monkeypatch, **options)
    # The legacy test helper replaces the manager. Exercise only the instance
    # that the actual Bridge constructor selected, including its normal wake hook.
    s["bridge"].autonext = original
    return card


def test_native_opt_in_is_selected_while_disabled_and_legacy_remains_default(config, bridge):
    assert isinstance(bridge.autonext, CoordinatedAutoNext)
    assert bridge.autonext.worker is None
    assert not config.autonext.enabled
    legacy = config.model_copy(deep=True)
    legacy.data_dir += "-legacy"
    legacy.autonext = AutoNextConfig()
    instance = Bridge(legacy)
    try:
        assert type(instance.autonext) is AutoNextManager
        assert instance.autonext.worker is None
        assert not instance.config.autonext.enabled
    finally:
        instance.store.close()


async def test_status_is_owner_scoped_bounded_and_does_not_dispatch(
    scenario,  # noqa: F811
    tmp_path,
    monkeypatch,
):
    s, b = scenario, scenario["bridge"]
    prepared(s, tmp_path, monkeypatch)
    count = b.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0]
    status = coordinator_status(b, "codex")
    assert status["native_manager"] and status["read_only"]
    assert status["controller_running"] is False
    assert not status["restart_required"] and status["tasks"] == []
    assert b.autonext.worker is None
    assert b.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == count
    for principal in ("local", "grok"):
        with pytest.raises(BridgeError) as error:
            coordinator_status(b, principal)
        assert error.value.code == "coordinator_owner_required"
    policy = s["config"].principals["codex"]
    policy.capabilities.remove("team.read")
    with pytest.raises(BridgeError):
        coordinator_status(b, "codex")


@pytest.mark.parametrize("selector", [{"task_id": "other"}, {"wait_seconds": 1}, {"path": "/"}])
def test_cached_status_rejects_unrelated_selectors(selector):
    with pytest.raises(ValueError):
        ReadQuery(operation="coordinator.status", **selector)


async def test_cached_status_enforces_budget(scenario, tmp_path, monkeypatch):  # noqa: F811
    s = scenario
    prepared(s, tmp_path, monkeypatch)
    with pytest.raises(BridgeError) as error:
        await read_query_async(
            s["bridge"], "codex", ReadQuery(operation="coordinator.status", max_bytes=1)
        )
    assert error.value.code == "read_result_limit"


async def test_native_followup_and_durable_completion_via_real_mcp(scenario, tmp_path, monkeypatch):  # noqa: F811
    s, b = scenario, scenario["bridge"]
    card = prepared(s, tmp_path, monkeypatch, grok=True)
    second = {**card, "task_id": "native.two", "title": "Second pinned task"}
    second["acceptance"] = {**card["acceptance"], "review_with_grok": False}
    content = json.dumps(second)
    entry = append_whiteboard(
        str(s["desk"]),
        "board",
        actor="operator",
        actor_type="human",
        entry_type="task",
        content=content,
        external_key="native-second",
    )
    s["config"].autonext.cards.append(
        ApprovedCard(
            task_id=second["task_id"], entry_id=entry["id"], content_sha256=text_sha(content)
        )
    )
    s["config"].autonext.completion_target = "native-coordinator-test"
    async with MCPClientPool() as pool:
        await pool.connect(Peer("owner", url=s["endpoint"], token="codex-team-test-" + "x" * 40))
        await pool.connect(Peer("other", url=s["endpoint"], token="grok-team-test-" + "x" * 40))
        initial = (await pool.call("owner", "coordinator_status", {})).structuredContent
        assert initial["tasks"] == []
        denied = (await pool.call("other", "coordinator_status", {})).structuredContent
        assert denied["error"]["code"] == "coordinator_owner_required"
        await s["start"]()
        await until(lambda: b.autonext.inspect()["state"] in {"complete", "stopped"}, timeout=30)
        assert b.autonext.inspect()["state"] == "complete", b.autonext.inspect()
        status = (await pool.call("owner", "coordinator_status", {})).structuredContent
        assert status["counts"] == {"completed": 2}
        assert status["controller_running"] is True
        assert all(
            item["receipt_recorded"] and item["checks_state"] == "completed"
            for item in status["tasks"]
        )
        assert all(item["work"]["worker"]["core_task_id"] for item in status["tasks"])
        assert "Inspect fixture only" not in json.dumps(status)
        cached = (
            await pool.call("owner", "read_query", {"query": {"operation": "coordinator.status"}})
        ).structuredContent
        assert cached == status
        # Completion can predate the consumer and the notices remain durable.
        inbox = (
            await pool.call(
                "owner",
                "completion_receive",
                {"target": "native-coordinator-test", "wait_seconds": 0},
            )
        ).structuredContent
        notices = inbox["notices"]
        assert len(notices) == 2
        assert {n["payload"]["task_id"] for n in notices} == {card["task_id"], "native.two"}
        assert all(
            n["payload"]["source"] == "autonext" and n["payload"]["outcome"] == "success"
            for n in notices
        )
        first, second_notice = notices
        selected = (
            await pool.call(
                "owner",
                "completion_receive",
                {"target": "native-coordinator-test", "source_id": "native.two", "wait_seconds": 0},
            )
        ).structuredContent
        assert [n["id"] for n in selected["notices"]] == [second_notice["id"]]
        for _ in range(2):
            ack = (
                await pool.call(
                    "owner",
                    "completion_ack",
                    {"notice_id": first["id"], "receipt": first["receipt"]},
                )
            ).structuredContent
            assert ack["id"] == first["id"]
        count = b.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0]
        await b.autonext.stop()
        await b.autonext.start()
        await b.autonext.tick()
        assert b.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == count
        remaining = (
            await pool.call(
                "owner",
                "completion_receive",
                {"target": "native-coordinator-test", "wait_seconds": 0},
            )
        ).structuredContent
        assert [n["id"] for n in remaining["notices"]] == [second_notice["id"]]
        assert remaining["notices"][0]["receipt"] == second_notice["receipt"]
