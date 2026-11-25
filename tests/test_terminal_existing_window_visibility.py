"""Existing Terminal reuse needs an independent physical on-screen proof."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from kirabridge.bridge_core.models import BridgeError
from kirabridge.platform_adapters.macos.terminal_window import TerminalWindowProof
from kirabridge.platform_adapters.terminal_app import TerminalAppTransport

ROW = {
    "pane_id": "terminal:4390:ttys002",
    "window_id": 4390,
    "tty": "/dev/ttys002",
    "expected_pid": 48600,
}
SURFACE = {
    "window_id": 4390,
    "tty": "/dev/ttys002",
    "owner_pid": 24143,
    "title": "KiraBridge terminal",
    "bounds": {"x": 20, "y": 30, "width": 900, "height": 650},
}
CG_WINDOW = {
    "window_id": 9921,
    "owner_pid": 24143,
    "application_start": "1795375000.123456",
    "layer": 0,
    "on_screen": True,
    "title": "KiraBridge terminal",
    "bounds": {"X": 20.0, "Y": 30.0, "Width": 900.0, "Height": 650.0},
}
HELPER = {"pid": 710, "generation": 1, "source_commit": "a" * 40}


def observer(*, windows, app_pid=24143, app_start=1795375000.123456):
    async def request(operation, arguments, **kwargs):
        assert kwargs.get("principal") == "chatgpt"
        if operation == "apps.list":
            return {
                "native_helper": HELPER,
                "applications": [
                    {
                        "pid": app_pid,
                        "started_at": app_start,
                        "bundle_id": "com.apple.Terminal",
                    }
                ],
                "offset": 0,
                "total": 1,
                "truncated": False,
            }
        if operation == "windows.list":
            assert arguments["owner_pid"] == app_pid
            assert arguments["expected_start"] == f"{app_start:.6f}"
            return {
                "native_helper": HELPER,
                "windows": windows,
                "offset": 0,
                "total": len(windows),
                "truncated": False,
                "titles_redacted": False,
            }
        raise AssertionError(f"unexpected observer operation: {operation}")

    return request


async def test_exact_existing_terminal_surface_binds_both_window_id_spaces():
    native = TerminalAppTransport(asyncio.Lock())
    native.system_transport = SimpleNamespace(request=observer(windows=[CG_WINDOW]))
    proof = TerminalWindowProof(native, native.system_transport, "chatgpt")

    binding = await proof.prove_existing_target(ROW, SURFACE)

    assert binding["terminal_window_id"] == 4390
    assert binding["cg_window_id"] == 9921
    assert binding["cg_window_id"] != binding["terminal_window_id"]
    assert binding["owner_pid"] == SURFACE["owner_pid"]
    assert "KiraBridge terminal" == binding["title"]


@pytest.mark.parametrize(
    "windows,code",
    [
        ([], "visible_target_not_on_screen"),
        ([{**CG_WINDOW, "title": "another window"}], "visible_target_not_on_screen"),
        (
            [CG_WINDOW, {**CG_WINDOW, "window_id": 9922}],
            "visible_target_ambiguous",
        ),
    ],
)
async def test_unmatched_or_ambiguous_physical_window_is_not_proven(windows, code):
    native = TerminalAppTransport(asyncio.Lock())
    native.system_transport = SimpleNamespace(request=observer(windows=windows))

    with pytest.raises(BridgeError) as failure:
        await native.prove_existing_target(ROW, SURFACE, principal="chatgpt")
    assert failure.value.code == code


async def test_physical_observation_deadline_includes_wait_for_native_transport():
    class StalledObserver:
        timeout = 0.01

        async def request(self, operation, arguments, *, principal):
            await asyncio.Event().wait()

    native = TerminalAppTransport(asyncio.Lock())
    native.system_transport = StalledObserver()

    with pytest.raises(BridgeError) as failure:
        await native.prove_existing_target(ROW, SURFACE, principal="chatgpt")

    assert failure.value.code == "visible_window_unconfirmed"
    assert "timed out" in str(failure.value).lower()


async def test_offscreen_explicit_target_is_never_sent_input():
    native = TerminalAppTransport(asyncio.Lock())
    native.system_transport = SimpleNamespace(request=observer(windows=[]))
    native.read = AsyncMock(return_value="KiraBridge visible % ")
    before_transport = AsyncMock()
    native.native = AsyncMock(return_value={"screen": "KiraBridge visible % ", "surface": SURFACE})

    with pytest.raises(BridgeError) as failure:
        await native.send_confirmed(
            ROW,
            "pwd",
            "501 ttys002 Wed Nov 4 12:00:00 2026",
            before_transport=before_transport,
            require_physical_visibility=True,
            principal="chatgpt",
        )

    assert failure.value.code == "visible_target_not_on_screen"
    assert native.native.await_count == 1
    assert native.native.await_args.kwargs["mutation"] is True
    before_transport.assert_not_awaited()
    assert "app.doScript(" not in native.native.await_args.args[0]


async def test_exact_visible_target_gets_last_surface_guard_before_one_input():
    native = TerminalAppTransport(asyncio.Lock())
    native.system_transport = SimpleNamespace(request=observer(windows=[CG_WINDOW]))
    native.read = AsyncMock(return_value="KiraBridge visible % ")
    events = []

    async def before_transport():
        assert native.native.await_count == 1
        events.append("attempt")

    async def dispatch(source, *, mutation):
        assert mutation is True
        if "app.doScript(" in source:
            assert events == ["focus", "attempt"]
            events.append("input")
            return {"sent": True}
        events.append("focus")
        return {"screen": "KiraBridge visible % ", "surface": SURFACE}

    native.native = AsyncMock(side_effect=dispatch)

    result = await native.send_confirmed(
        ROW,
        "pwd",
        "501 ttys002 Wed Nov 4 12:00:00 2026",
        before_transport=before_transport,
        require_physical_visibility=True,
        principal="chatgpt",
    )

    assert result == {"sent": True}
    assert events == ["focus", "attempt", "input"]
    assert native.native.await_count == 2
    final_source = native.native.await_args.args[0]
    assert "Physical Terminal window changed" in final_source
    assert "targetWindow.id()!==4390" in final_source
    assert "KiraBridge terminal" in final_source
    guard_position = final_source.index("Physical Terminal window changed")
    input_position = final_source.index("app.doScript(")
    assert guard_position < input_position
    assert "app.doScript(" in final_source


async def test_visible_paste_does_not_reactivate_after_physical_proof():
    events = []

    @asynccontextmanager
    async def clipboard_owner(_text):
        events.append("clipboard")
        yield SimpleNamespace(generation=3)

    native = TerminalAppTransport(asyncio.Lock(), clipboard_owner=clipboard_owner)
    native.system_transport = SimpleNamespace(request=observer(windows=[CG_WINDOW]))

    async def dispatch(source, *, mutation):
        assert mutation is True
        if "app.activate()" in source:
            events.append("focus")
            return {"screen": "KiraBridge visible % ", "surface": SURFACE}
        assert "app.doScript(" not in source
        events.append("input")
        return {"paste_event_sent": True, "return_sent": False}

    native.native = AsyncMock(side_effect=dispatch)

    async def before_transport():
        assert events == ["focus"]
        events.append("attempt")

    await native.insert(
        ROW["pane_id"],
        "literal",
        require_physical_visibility=True,
        principal="chatgpt",
        before_transport=before_transport,
    )

    assert native.native.await_count == 2
    assert events == ["focus", "attempt", "clipboard", "input"]
    final_source = native.native.await_args.args[0]
    assert "app.activate()" not in final_source
    assert final_source.index("Physical Terminal window changed") < final_source.index(
        'paste.actions.byName("AXPress").perform();'
    )


def test_jxa_surface_and_last_guard_use_object_bounds_and_fail_closed():
    transport = TerminalAppTransport(asyncio.Lock())
    focus_source = transport.native_focus(ROW["pane_id"], include_surface=True)
    guard = transport.native_window_surface_guard(
        {
            "terminal_window_id": 4390,
            "tty": "/dev/ttys002",
            "title": "KiraBridge terminal",
            "bounds": SURFACE["bounds"],
        }
    )

    assert "bounds:{x:focusedBounds.x,y:focusedBounds.y" in focus_source
    assert "focusedBounds[0]" not in focus_source
    assert "Number.isFinite(v)" in guard
    assert "provenBounds.x" in guard and "provenBounds.width" in guard
    assert "provenBounds[0]" not in guard
