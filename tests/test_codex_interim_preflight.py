"""One canonical session observation drives both read and interim admission."""
# ruff: noqa: F811

from test_codex_interim import arguments, setup_input
from test_literal_session_input import literal_visible  # noqa: F401
from test_visible_handoff import callback, visible  # noqa: F401


async def test_interim_uses_public_bounded_observer_not_separate_raw_frame(
    literal_visible,
    monkeypatch,
):
    bridge, transport, row = literal_visible
    await setup_input(bridge, transport, monkeypatch, row)
    actual = bridge.sessions.terminal_app.read

    async def raw_frame(pane):
        if not transport["literal_calls"]:
            return "raw transcript frame without current composer"
        return await actual(pane)

    monkeypatch.setattr(bridge.sessions.terminal_app, "read", raw_frame)
    seen = []

    async def progress(value):
        seen.append(value)

    result = await bridge.execute(
        {
            "id": "same-observer",
            "principal": "chatgpt",
            "operation": "session.input",
            "args": arguments(row),
        },
        callback,
        progress,
    )
    assert result["submitted"]
    assert transport["literal_calls"] == [("paste", "Kurzer Zwischenstand?"), ("return", None)]
    assert seen[0]["terminal_input_attempted"] is False
    assert seen[0]["observation"]["interim_ready"] is True


async def test_transient_read_only_frame_is_reobserved_without_repeating_input(
    literal_visible,
    monkeypatch,
):
    bridge, transport, row = literal_visible
    await setup_input(bridge, transport, monkeypatch, row)
    original = bridge.visible_handoffs.binding_readiness
    observations = 0

    async def transient(*args, **kwargs):
        nonlocal observations
        observations += 1
        if observations == 1:
            return {
                "state": "unknown",
                "ready": False,
                "interim_ready": False,
                "reason": "transient_renderer_frame",
            }
        return await original(*args, **kwargs)

    monkeypatch.setattr(bridge.visible_handoffs, "binding_readiness", transient)
    result = await bridge.execute(
        {
            "id": "transient-observer",
            "principal": "chatgpt",
            "operation": "session.input",
            "args": arguments(row),
        },
        callback,
        callback,
    )
    assert result["submitted"] and observations == 2
    assert transport["literal_calls"] == [("paste", "Kurzer Zwischenstand?"), ("return", None)]


async def test_observations_stop_on_real_draft_and_never_send(literal_visible, monkeypatch):
    from kirabridge.bridge_core.models import BridgeError

    bridge, transport, row = literal_visible
    await setup_input(bridge, transport, monkeypatch, row)
    seen = []

    async def observation(*args, **kwargs):
        if not seen:
            seen.append("unknown")
            return {"state": "unknown", "interim_ready": False, "reason": "transient_frame"}
        seen.append("draft")
        return {
            "state": "input_not_empty",
            "interim_ready": False,
            "reason": "existing_input_must_not_be_overwritten",
        }

    monkeypatch.setattr(bridge.visible_handoffs, "binding_readiness", observation)
    try:
        await bridge.execute(
            {
                "id": "draft-after-transient",
                "principal": "chatgpt",
                "operation": "session.input",
                "args": arguments(row),
            },
            callback,
            callback,
        )
    except BridgeError as error:
        assert error.observation["state"] == "input_not_empty"
    else:
        raise AssertionError("Existing draft must not be changed")
    assert seen == ["unknown", "draft"] and not transport["literal_calls"]


async def test_persistent_unknown_is_bounded_and_diagnosed_without_input(
    literal_visible, monkeypatch
):
    from kirabridge.bridge_core.models import BridgeError

    bridge, transport, row = literal_visible
    await setup_input(bridge, transport, monkeypatch, row)
    seen = []

    async def unknown(*args, **kwargs):
        return {"state": "unknown", "interim_ready": False, "reason": "unrecognized_current_frame"}

    async def progress(value):
        seen.append(value)

    monkeypatch.setattr(bridge.visible_handoffs, "binding_readiness", unknown)
    try:
        await bridge.execute(
            {
                "id": "persistent-unknown",
                "principal": "chatgpt",
                "operation": "session.input",
                "args": arguments(row),
            },
            callback,
            progress,
        )
    except BridgeError as error:
        assert error.observation["reason"] == "unrecognized_current_frame"
    else:
        raise AssertionError("Unknown composer cannot be submitted")
    assert [item["observation_attempt"] for item in seen] == [1, 2, 3]
    assert all(item["terminal_input_attempted"] is False for item in seen)
    assert not transport["literal_calls"]
