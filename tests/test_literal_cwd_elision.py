"""Captured CWD elision change needs an independently bound, unchanged process CWD."""

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from conftest import request
from test_literal_session_input import literal_visible  # noqa: F401
from test_visible_handoff import visible  # noqa: F401

from kirabridge.bridge_core.models import BridgeError
from kirabridge.literal_session_input import insertion_observed
from kirabridge.platform_adapters.terminal_app import TerminalAppTransport

HOME = "/Users/fixture"
CWD = (
    HOME
    + "/.local/share/kirabridge/backups/rc20-return-key-20261031-01/native-acceptance/workspace"
)
MODEL = "  GPT-6.1-Sol max · "
# Exact current composer/footer geometry from the saved live captures. The
# private home prefix is substituted; the two actual displayed ~ paths remain.
BEFORE = (
    "• Diagnostic reply\n\n  Worked for 4s • 11:42\n \n \n"
    "› Ask Codex to do anything\n \n"
    + MODEL
    + "~/.local/share/kirabridge/ba…  ⚠ 2 warnings · f2 to view\n"
)
AFTER = (
    "• Diagnostic reply\n\n  Worked for 4s • 11:42\n \n"
    "› /resume  resume a saved chat                                               \n \n"
    "› /resume\n \n" + MODEL + "~/.local/share/kirabridge/backups/rc20-return-key-202610…\n"
)


def test_captured_warning_hide_extends_only_the_same_bound_cwd():
    assert not insertion_observed("codex", AFTER, "/resume", BEFORE)
    assert insertion_observed("codex", AFTER, "/resume", BEFORE, cwd=CWD, home=HOME)


def test_hint_and_warning_can_hide_together_only_with_matching_bound_cwd():
    before = BEFORE + "  ← for agents · ? for shortcuts\n"
    assert not insertion_observed("codex", AFTER, "/resume", before)
    assert insertion_observed("codex", AFTER, "/resume", before, cwd=CWD, home=HOME)


@pytest.mark.parametrize(
    "after,before,cwd",
    [
        (AFTER, BEFORE, HOME + "/.local/share/kirabridge/backups/another-project"),
        (AFTER.replace("GPT-6.1-Sol", "GPT-OTHER"), BEFORE, CWD),
        (AFTER + "Confirm another operation?\n", BEFORE, CWD),
        (AFTER, BEFORE + "  UNAUTHORIZED\n", CWD),
        (AFTER.replace("› /resume\n", "› /resume EXTRA\n"), BEFORE, CWD),
        (AFTER, BEFORE.replace("  ⚠ 2 warnings · f2 to view", ""), CWD),
    ],
)
def test_combined_hint_cwd_reflow_preserves_all_other_guards(after, before, cwd):
    before += "  ← for agents · ? for shortcuts\n"
    assert not insertion_observed("codex", after, "/resume", before, cwd=cwd, home=HOME)


@pytest.mark.parametrize(
    "after,before,cwd",
    [
        (AFTER.replace("› /resume\n", "› /resume UNAUTHORIZED\n"), BEFORE, CWD),
        (AFTER.replace("GPT-6.1-Sol", "GPT-OTHER"), BEFORE, CWD),
        (AFTER.replace("/rc20-return-key-202610…", "/another-project…"), BEFORE, CWD),
        (AFTER, BEFORE, HOME + "/.local/share/kirabridge/backups/another-project"),
        (AFTER.replace("\n \n" + MODEL, "\n  GPT-EXTRA-CONTINUATION\n \n" + MODEL), BEFORE, CWD),
        (AFTER + "Approve a new operation?\n", BEFORE, CWD),
        (AFTER.replace("202610…", "202610"), BEFORE, CWD),
        (AFTER, BEFORE.replace("  ⚠ 2 warnings · f2 to view", ""), CWD),
        (AFTER + "  ⚠ 2 warnings · f2 to view\n", BEFORE, CWD),
        (AFTER, BEFORE, None),
        (AFTER.replace("backups/rc20-return-key-202610…", "…"), BEFORE, CWD),
    ],
)
def test_cwd_proof_does_not_relax_payload_model_path_or_other_footer_rows(after, before, cwd):
    assert not insertion_observed("codex", after, "/resume", before, cwd=cwd, home=HOME)


@pytest.mark.parametrize("absolute", [False, True])
def test_bound_cwd_full_path_is_an_exact_valid_renderer_variant(absolute):
    before = BEFORE
    after = AFTER.replace(
        "~/.local/share/kirabridge/backups/rc20-return-key-202610…", "~" + CWD[len(HOME) :]
    )
    if absolute:
        before = before.replace("~/.local", HOME + "/.local")
        after = after.replace("~/.local", HOME + "/.local")
    assert insertion_observed("codex", after, "/resume", before, cwd=CWD, home=HOME)


@pytest.mark.parametrize(
    "condition",
    [
        "same",
        "same-hidden-hint",
        "changed",
        "before-unavailable",
        "after-unavailable",
        "strict-unavailable",
    ],
)
async def test_literal_submit_binds_cwd_observations_to_the_selected_task(
    literal_visible,  # noqa: F811
    monkeypatch,
    condition,
):
    bridge, transport, row = literal_visible
    bridge.config.visible_handoffs.bindings[
        "codex"
    ].ready_pattern = r"(?m)^›(?: Ask Codex to do anything)?\s*$"
    before = BEFORE
    if condition == "same-hidden-hint":
        before += "  ← for agents · ? for shortcuts\n"
    transport["text"] = before
    probes = []
    actual_cwd = str(Path.home()) + CWD.removeprefix(HOME)

    async def cwd(pid, *, expected_identity):
        assert pid == 901 and expected_identity.endswith("/bin/codex")
        probes.append((pid, expected_identity))
        if (
            condition == "before-unavailable"
            or condition == "strict-unavailable"
            or (condition == "after-unavailable" and len(probes) == 2)
        ):
            raise BridgeError("process_cwd_unavailable", "No optional CWD proof")
        if condition == "changed" and len(probes) == 2:
            return actual_cwd + "-different"
        return actual_cwd

    async def paste(pane, text, **guards):
        assert text == "/resume" and guards["expected_screen"] == before
        transport["literal_calls"].append(("paste", text))
        transport["text"] = AFTER
        if condition == "strict-unavailable":
            transport["text"] = AFTER.replace(
                "~/.local/share/kirabridge/backups/rc20-return-key-202610…",
                "~/.local/share/kirabridge/ba…",
            )

    monkeypatch.setattr(bridge.sessions.terminal_app, "process_working_directory", cwd)
    monkeypatch.setattr(bridge.sessions.terminal_app, "insert", paste)
    value = request(
        "session.input",
        {"pane_id": row["pane_id"], "expected_pid": 900, "text": "/resume"},
        task_id="cwd-bound-literal",
    )
    async with bridge:
        bridge.prepare("chatgpt", value)
        task = await bridge.tasks.wait("chatgpt", value.task_id, timeout=5)
        if condition in {"same", "same-hidden-hint", "strict-unavailable"}:
            assert task["state"] == "completed", task
            assert task["result"]["return_sent"] is True
            assert transport["literal_calls"] == [("paste", "/resume"), ("return", None)]
        else:
            assert task["state"] == "unknown", task
            assert task["error"]["code"] == "visible_insert_unknown"
            assert transport["literal_calls"] == [("paste", "/resume")]
        assert bridge.submit("chatgpt", value, "")["state"] == task["state"]
    assert len(probes) == (1 if condition in {"before-unavailable", "strict-unavailable"} else 2)


@pytest.mark.parametrize("paste_only", [False, True])
async def test_optional_cwd_probe_is_not_used_for_ineligible_or_paste_only_frames(
    literal_visible,  # noqa: F811
    monkeypatch,
    paste_only,
):
    bridge, transport, row = literal_visible
    probe = AsyncMock(side_effect=AssertionError("No host CWD probe permitted"))
    monkeypatch.setattr(bridge.sessions.terminal_app, "process_working_directory", probe)
    if paste_only:
        transport["footer"] = (
            "\n \n" + MODEL + "~/.local/share/kirabridge/ba…  ⚠ 2 warnings · f2 to view\n"
        )
    else:
        transport["footer"] = "\n \n" + MODEL + "~\n"
    transport["text"] = "› " + transport["footer"]
    value = request(
        "session.input",
        {
            "pane_id": row["pane_id"],
            "expected_pid": 900,
            "text": "/resume",
            "submit": not paste_only,
        },
        task_id="no-cwd-probe",
    )
    async with bridge:
        bridge.prepare("chatgpt", value)
        task = await bridge.tasks.wait("chatgpt", value.task_id, timeout=5)
        assert task["state"] == "completed", task
    probe.assert_not_awaited()


@pytest.mark.parametrize(
    "failure", [None, "extra", "pid", "stderr", "limit", "identity", "timeout"]
)
async def test_process_cwd_probe_is_bounded_scoped_and_never_uses_shell(monkeypatch, failure):
    adapter = TerminalAppTransport(None)
    identity = f"{os.getuid()} ttys006 Sat Oct 31 12:00:00 2026 900 /bin/codex"
    observe = AsyncMock(
        side_effect=[identity, identity + " changed"]
        if failure == "identity"
        else [identity, identity]
    )
    monkeypatch.setattr(adapter, "process_identity", observe)
    output = b"p901\x00\nfcwd\x00n/Users/fixture/project\x00\n"
    if failure == "extra":
        output += b"n/another/path\x00"
    elif failure == "pid":
        output = output.replace(b"p901", b"p902")
    elif failure == "limit":
        output += b"x" * 65536

    def pipe(data):
        async def read(limit):
            nonlocal data
            result, data = data[:limit], data[limit:]
            return result

        return SimpleNamespace(read=AsyncMock(side_effect=read))

    child = SimpleNamespace(
        returncode=0,
        stdout=pipe(output),
        stderr=pipe(b"denied" if failure == "stderr" else b""),
        wait=AsyncMock(return_value=0),
    )
    if failure == "timeout":
        child.stdout.read.side_effect = TimeoutError()
    create = AsyncMock(return_value=child)
    cleanup = AsyncMock()
    monkeypatch.setattr(
        "kirabridge.platform_adapters.terminal_app.asyncio.create_subprocess_exec", create
    )
    monkeypatch.setattr("kirabridge.platform_adapters.terminal_app.reap_process", cleanup)
    if failure is None:
        assert (
            await adapter.process_working_directory(901, expected_identity=identity)
            == "/Users/fixture/project"
        )
    else:
        with pytest.raises(BridgeError):
            await adapter.process_working_directory(901, expected_identity=identity)
    assert create.call_args.args == ("/usr/sbin/lsof", "-a", "-p", "901", "-d", "cwd", "-F0pfn")
    assert create.call_args.kwargs.get("shell") is not True
    cleanup.assert_awaited_once()


@pytest.mark.parametrize("late", [None, "extra", "stderr"])
async def test_streamed_cwd_output_is_read_to_eof_before_it_is_trusted(monkeypatch, late):
    adapter = TerminalAppTransport(None)
    identity = f"{os.getuid()} ttys006 Sat Oct 31 12:00:00 2026 900 /bin/codex"
    monkeypatch.setattr(adapter, "process_identity", AsyncMock(return_value=identity))
    stdout, stderr = asyncio.StreamReader(), asyncio.StreamReader()
    child = SimpleNamespace(
        returncode=0, stdout=stdout, stderr=stderr, wait=AsyncMock(return_value=0)
    )
    cleanup = AsyncMock()
    monkeypatch.setattr(
        "kirabridge.platform_adapters.terminal_app.asyncio.create_subprocess_exec",
        AsyncMock(return_value=child),
    )
    monkeypatch.setattr("kirabridge.platform_adapters.terminal_app.reap_process", cleanup)

    async def emit():
        for chunk in [b"p901\x00", b"\nfcwd\x00", b"n/Users/fixture/project\x00\n"]:
            stdout.feed_data(chunk)
            await asyncio.sleep(0)
        if late == "extra":
            stdout.feed_data(b"n/unexpected/late/path\x00\n")
        if late == "stderr":
            stderr.feed_data(b"late warning")
        stdout.feed_eof()
        stderr.feed_eof()

    emission = asyncio.create_task(emit())
    try:
        if late is None:
            assert (
                await adapter.process_working_directory(901, expected_identity=identity)
                == "/Users/fixture/project"
            )
        else:
            with pytest.raises(BridgeError) as failed:
                await adapter.process_working_directory(901, expected_identity=identity)
            assert failed.value.code == "process_cwd_unavailable"
    finally:
        await emission
    cleanup.assert_awaited_once()


async def test_cwd_probe_does_not_read_a_replaced_process_or_launch_missing_lsof(monkeypatch):
    adapter = TerminalAppTransport(None)
    identity = f"{os.getuid()} ttys006 Sat Oct 31 12:00:00 2026 900 /bin/codex"
    observe = AsyncMock(return_value=identity + " changed")
    create = AsyncMock(side_effect=FileNotFoundError())
    monkeypatch.setattr(adapter, "process_identity", observe)
    monkeypatch.setattr(
        "kirabridge.platform_adapters.terminal_app.asyncio.create_subprocess_exec", create
    )
    with pytest.raises(BridgeError) as changed:
        await adapter.process_working_directory(901, expected_identity=identity)
    assert changed.value.code == "visible_target_changed"
    create.assert_not_awaited()
    observe.return_value = identity
    with pytest.raises(BridgeError) as missing:
        await adapter.process_working_directory(901, expected_identity=identity)
    assert missing.value.code == "process_cwd_unavailable"
