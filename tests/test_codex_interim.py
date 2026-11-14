"""Current-turn input uses exact existing sessions, no model or work resubmission."""

# ruff: noqa: F811

import copy
import json
import subprocess

import pytest
from conftest import request
from test_direct_delivery import delivery, settled  # noqa: F401
from test_literal_session_input import literal_visible  # noqa: F401
from test_visible_handoff import callback, visible  # noqa: F401
from test_visible_selection import new_native_selection, new_row

from kirabridge.bridge_core.models import BridgeError
from kirabridge.cli_adapters.codex import CodexAdapter
from kirabridge.message_manager import MessageSend
from kirabridge.platform_adapters.terminal_app import TerminalAppTransport

FOOTER = "\n\nGPT-6.1-Sol medium · ~\n← for agents · ? for shortcuts\n"
WORKING = "◦ Working (12m • esc to interrupt)\n\n› " + FOOTER


async def setup_input(bridge, transport, monkeypatch, row=None):
    row = row or new_row()
    await new_native_selection(bridge, monkeypatch, row)
    transport.update(text=WORKING, literal_calls=[], turn="original", turn_starts=1)

    async def read(pane):
        assert pane == row["pane_id"]
        return transport["text"]

    async def insert(pane, text, **guards):
        assert guards["composer_only"]
        assert guards["identity_guard"][901].endswith("/bin/codex")
        transport["literal_calls"].append(("paste", text))
        # Simulate ongoing model output and a different foreground tab.
        row["selected"] = False
        transport["text"] = "◦ Working (13m • esc to interrupt)\n\n› " + text + FOOTER

    async def press_return(pane, **guards):
        assert guards["composer_only"] and guards["expected_screen"] == transport["text"]
        transport["literal_calls"].append(("return", None))
        transport["text"] = "◦ Working (14m • esc to interrupt)\n\n› " + FOOTER

    monkeypatch.setattr(bridge.sessions.terminal_app, "read", read)
    monkeypatch.setattr(bridge.sessions.terminal_app, "insert", insert)
    monkeypatch.setattr(bridge.sessions.terminal_app, "press_return", press_return)
    return row


def arguments(row):
    return {
        "pane_id": row["pane_id"],
        "expected_pid": 900,
        "expected_agent_pid": 901,
        "text": "Kurzer Zwischenstand?",
        "intent": "interim",
    }


async def test_working_exact_session_one_question_and_original_turn_continues(
    literal_visible,
    monkeypatch,  # noqa: F811
):
    bridge, transport, row = literal_visible
    await setup_input(bridge, transport, monkeypatch, row)
    value = request("session.input", arguments(row), task_id="interim-once")
    before = bridge.config.visible_handoffs.bindings["codex"].model_dump()
    async with bridge:
        bridge.prepare("chatgpt", value)
        result = await bridge.tasks.wait("chatgpt", value.task_id, timeout=5)
        assert result["state"] == "completed", result
        assert bridge.submit("chatgpt", value, "")["state"] == "completed"
        assert not bridge.store.db.execute("SELECT 1 FROM messages").fetchone()
        assert not bridge.store.db.execute("SELECT 1 FROM visible_handoffs").fetchone()
    assert transport["literal_calls"] == [("paste", "Kurzer Zwischenstand?"), ("return", None)]
    assert transport["turn_starts"] == 1 and transport["turn"] == "original"
    assert "Working" in transport["text"]
    assert bridge.config.visible_handoffs.bindings["codex"].model_dump() == before


@pytest.mark.parametrize("case", ["user_block", "wrong_pid", "draft", "dialog", "idle"])
async def test_interim_refusals_send_no_input(literal_visible, monkeypatch, case):  # noqa: F811
    bridge, transport, row = literal_visible
    await setup_input(bridge, transport, monkeypatch, row)
    args = arguments(row)
    if case == "user_block":
        bridge.config.visible_handoffs.allow_interim_messages = False
    elif case == "wrong_pid":
        args["expected_agent_pid"] = 999
    elif case == "draft":
        transport["text"] = WORKING.replace("› ", "› user draft")
    elif case == "idle":
        transport["text"] = "› " + FOOTER
    else:
        transport["text"] = WORKING + "\nApproval required"
    with pytest.raises(BridgeError):
        await bridge.execute(
            {"id": "refused", "principal": "chatgpt", "operation": "session.input", "args": args},
            callback,
            callback,
        )
    assert not transport["literal_calls"]


async def test_message_uses_explicit_session_during_existing_turn_without_new_work(
    delivery,
    monkeypatch,  # noqa: F811
):
    bridge, transport, direct, _, _ = delivery
    bridge.config.session_input_policy.enabled = False
    row = await setup_input(bridge, transport, monkeypatch)
    # Existing recipient ownership must not block a separately addressed question.
    direct.targets.add(("recipient", "codex"))
    direct.targets.add(("pane", row["pane_id"]))
    before = copy.deepcopy(direct.targets)
    original = bridge.messages._send(
        "chatgpt",
        MessageSend(
            recipient="codex",
            conversation_id="original-running",
            idempotency_key="original-work",
            kind="work",
            body="Continue work",
            dispatch=False,
        ),
        visible_internal=True,
    )
    _, binding = bridge.sessions.explicit_agent_binding(row)
    bridge.store.db.execute(
        "INSERT INTO visible_handoffs VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            "original-turn",
            "chatgpt",
            "codex",
            "original-request-hash",
            json.dumps(binding.model_dump()),
            original["id"],
            "sent",
            1,
            1,
            json.dumps({"return_sent": True}),
        ),
    )
    original_handoff = tuple(
        bridge.store.db.execute(
            "SELECT * FROM visible_handoffs WHERE id='original-turn'"
        ).fetchone()
    )

    async def no_agent(*args, **kwargs):
        raise AssertionError("Interim messages must never call agent.execute")

    monkeypatch.setattr(bridge.agents, "execute", no_agent)
    msg = MessageSend(
        recipient="codex",
        conversation_id="interim",
        idempotency_key="once",
        body="Kurzer Zwischenstand?",
        kind="question",
        request_reply=False,
        interim_session={
            k: v
            for k, v in arguments(row).items()
            if k in {"pane_id", "expected_pid", "expected_agent_pid"}
        },
    )
    sent = bridge.messages.send("chatgpt", msg)
    direct.submit("chatgpt", sent["id"])
    await settled(direct)
    current = bridge.messages.get("chatgpt", sent["id"])
    assert current["processing"]["state"] == "completed", current
    assert current["processing"]["evidence"]["new_agent_turn"] is False
    assert not current["acknowledged"]  # Delivery is not invented agent processing/ACK.
    assert bridge.messages.send("chatgpt", msg)["id"] == sent["id"]
    assert not direct.submit("chatgpt", sent["id"])
    assert transport["literal_calls"] == [("paste", msg.body), ("return", None)]
    assert direct.targets == before and transport["turn_starts"] == 1
    assert (
        tuple(
            bridge.store.db.execute(
                "SELECT * FROM visible_handoffs WHERE id='original-turn'"
            ).fetchone()
        )
        == original_handoff
    )
    assert bridge.store.db.execute("SELECT count(*) FROM visible_handoffs").fetchone()[0] == 1


def test_native_guard_allows_output_and_tab_change_but_not_composer_change():
    guard = TerminalAppTransport.native_screen_guard(WORKING, composer_only=True)

    def run(screen):
        script = "const tab={history:()=>" + json.dumps(screen) + "};" + guard
        return subprocess.run(["node", "-e", script], capture_output=True).returncode

    assert run(WORKING.replace("12m", "13m")) == 0
    assert run(WORKING.replace("› ", "› foreign draft")) != 0
    assert run("Finished response\n\n› " + FOOTER) != 0
    assert run("Approval required\n◦ Working (13m • esc to interrupt)\n\n› " + FOOTER) != 0
    assert run("Approval required\n\n" + WORKING) == 0


def test_working_observation_separates_new_work_and_interim_action(literal_visible):  # noqa: F811
    bridge, _, _ = literal_visible
    binding = bridge.config.visible_handoffs.bindings["codex"]
    state = CodexAdapter().observe(WORKING, binding)
    assert state["ready"] is False and state["interim_ready"] is True
    assert state["allowed_actions"] == ["interim_message"]


def test_old_message_hash_shape_is_unchanged():
    msg = MessageSend(
        recipient="codex", conversation_id="existing", idempotency_key="old", body="Hi"
    )
    assert "interim_session" not in msg.model_dump()


async def test_unknown_paste_is_not_replayed_or_submitted(delivery, monkeypatch):
    bridge, transport, direct, _, _ = delivery
    bridge.config.session_input_policy.enabled = False
    row = await setup_input(bridge, transport, monkeypatch)

    async def ambiguous_insert(pane, text, **guards):
        transport["literal_calls"].append(("paste", text))
        transport["text"] = "◦ Working (13m • esc to interrupt)\n\n› foreign draft" + FOOTER

    monkeypatch.setattr(bridge.sessions.terminal_app, "insert", ambiguous_insert)
    msg = MessageSend(
        recipient="codex",
        conversation_id="uncertain",
        idempotency_key="unknown-once",
        body="Kurzer Zwischenstand?",
        kind="question",
        request_reply=False,
        interim_session={
            k: v
            for k, v in arguments(row).items()
            if k in {"pane_id", "expected_pid", "expected_agent_pid"}
        },
    )
    sent = bridge.messages.send("chatgpt", msg)
    direct.submit("chatgpt", sent["id"])
    await settled(direct)
    assert bridge.messages.get("chatgpt", sent["id"])["processing"]["state"] == "unknown"
    assert bridge.messages.send("chatgpt", msg)["id"] == sent["id"]
    assert not direct.submit("chatgpt", sent["id"])
    assert transport["literal_calls"] == [("paste", msg.body)]


def test_busy_composer_native_echo_and_verifier(literal_visible):
    bridge, _, _ = literal_visible
    binding = bridge.config.visible_handoffs.bindings["codex"]
    before = WORKING.replace("›", "»")
    after = before.replace("» ", "» Frage?")
    adapter = CodexAdapter()
    assert adapter.interim_readiness(before, binding)["ready"]
    script = (
        adapter.paste_source("Frage?")
        + "console.log(observedPaste("
        + json.dumps(before)
        + ","
        + json.dumps(after)
        + ",100));"
    )
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "true"
    from kirabridge.interim_message import normalized_composer

    assert adapter.insertion_observed(
        normalized_composer(after), "Frage?", normalized_composer(before)
    )


async def test_interim_target_is_part_of_original_idempotency(delivery):
    bridge, _, _, _, _ = delivery
    value = MessageSend(
        recipient="codex",
        conversation_id="bound",
        idempotency_key="bound-once",
        body="Frage?",
        interim_session={
            "pane_id": "terminal:202:ttys006",
            "expected_pid": 900,
            "expected_agent_pid": 901,
        },
    )
    original = bridge.messages.send("chatgpt", value)
    changed = value.model_copy(
        update={
            "interim_session": value.interim_session.model_copy(update={"expected_agent_pid": 999})
        }
    )
    with pytest.raises(BridgeError) as caught:
        bridge.messages.send("chatgpt", changed)
    assert caught.value.code == "idempotency_conflict"
    assert bridge.messages.interim_target(original["id"]).expected_agent_pid == 901


async def test_user_block_is_exposed_by_session_observation(literal_visible, monkeypatch):
    bridge, transport, row = literal_visible
    await setup_input(bridge, transport, monkeypatch, row)
    bridge.config.visible_handoffs.allow_interim_messages = False
    state = await bridge.visible_handoffs.observe_readiness(
        "chatgpt",
        {"pane_id": row["pane_id"], "expected_pid": 900, "text": WORKING},
    )
    assert not state["interim_ready"]
    assert "interim_message" not in state["allowed_actions"]
