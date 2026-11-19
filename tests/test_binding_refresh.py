"""Dead agent bindings are re-checked against one fresh catalogue (read-only)."""

from unittest.mock import AsyncMock

from kirabridge.bridge_core.config import VisibleTerminalBinding


def _binding(pane, expected, agent):
    return VisibleTerminalBinding(
        pane_id=pane, expected_pid=expected, agent_pid=agent, ready_pattern="❯"
    )


async def test_only_missing_bindings_go_through_the_replacement(bridge, monkeypatch):
    bound = {
        "claude": _binding("terminal:11:ttys001", 100, 101),  # still in the catalogue
        "codex": _binding("terminal:22:ttys002", 200, 201),  # gone
        "grok": _binding("terminal:33:ttys003", 300, 301),  # gone
    }
    bridge.config.visible_handoffs.bindings = dict(bound)
    live = [{"pane_id": "terminal:11:ttys001", "expected_pid": 100, "processes": []}]
    monkeypatch.setattr(bridge.sessions, "catalog", AsyncMock(return_value={"sessions": live}))
    replacement = _binding("terminal:44:ttys004", 400, 401)

    async def refreshed(principal, target, binding):
        return (replacement, []) if target == "codex" else (binding, None)

    mock = AsyncMock(side_effect=refreshed)
    monkeypatch.setattr(bridge.visible_handoffs, "refreshed_binding", mock)
    replaced = await bridge.refresh_agent_bindings_once()
    assert replaced == ["codex"]
    assert [call.args[1] for call in mock.await_args_list] == ["codex", "grok"]


async def test_an_unavailable_terminal_or_a_failing_replacement_never_raises(bridge, monkeypatch):
    bridge.config.visible_handoffs.bindings = {"codex": _binding("terminal:22:ttys002", 200, 201)}
    monkeypatch.setattr(bridge.sessions, "catalog", AsyncMock(side_effect=RuntimeError("down")))
    assert await bridge.refresh_agent_bindings_once() == []
    monkeypatch.setattr(bridge.sessions, "catalog", AsyncMock(return_value={"sessions": []}))
    monkeypatch.setattr(
        bridge.visible_handoffs, "refreshed_binding", AsyncMock(side_effect=RuntimeError("x"))
    )
    assert await bridge.refresh_agent_bindings_once() == []


async def test_no_bindings_means_no_catalogue_read(bridge, monkeypatch):
    bridge.config.visible_handoffs.bindings = {}
    catalog = AsyncMock(return_value={"sessions": []})
    monkeypatch.setattr(bridge.sessions, "catalog", catalog)
    assert await bridge.refresh_agent_bindings_once() == []
    catalog.assert_not_awaited()
