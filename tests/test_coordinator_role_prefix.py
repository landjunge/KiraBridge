"""Only the current coordinator receives the role prefix; roles never grant rights."""
# Imported isolated fixtures are supplied by pytest.
# ruff: noqa: F811

import time

from test_direct_delivery import delivery  # noqa: F401
from test_visible_handoff import visible  # noqa: F401

from kirabridge.message_manager import MessageSend
from kirabridge.team_manager.coordinator_prefix import ROLE_TEXT, matches_body, with_role


def set_coordinator(bridge, principal):
    bridge.store.db.execute("DELETE FROM teams")
    if principal:
        bridge.store.db.execute(
            "INSERT INTO teams VALUES('t1','team','chatgpt',?,1,?)", (principal, time.time())
        )


async def received_prompt(delivery, monkeypatch, key, body="Mach das."):
    bridge, _, _, _, Pool = delivery
    sent = bridge.messages.send(
        "chatgpt",
        MessageSend(
            recipient="codex",
            conversation_id=key,
            idempotency_key=key,
            body=body,
            kind="work",
            dispatch=True,
            request_reply=False,
        ),
    )
    received = []

    async def execute(task, args, policy, running, progress, **kwargs):
        received.append(args.prompt)
        await running({"return_sent": True})
        return {"success": True, "scope": "visible_input_delivery", "evidence": {}}

    monkeypatch.setattr(bridge.agents, "execute", execute)
    message, run_id = bridge.message_receiver._claim(sent["id"], direct=True)
    pool = Pool()
    await pool.connect("codex")
    await bridge.message_receiver._process(pool, message, run_id)
    return received[0]


async def test_coordinator_gets_prefix_worker_does_not_and_role_change_applies(
    delivery, monkeypatch
):
    bridge = delivery[0]
    set_coordinator(bridge, "codex")
    prompt = await received_prompt(delivery, monkeypatch, "coord-1")
    assert ROLE_TEXT in prompt and prompt.endswith("Mach das.")
    assert "codex" in prompt.split("Verfuegbare CLIs:")[1]

    set_coordinator(bridge, "grok")  # codex is now a worker
    assert await received_prompt(delivery, monkeypatch, "worker-1") == "Mach das."

    set_coordinator(bridge, None)
    assert await received_prompt(delivery, monkeypatch, "none-1") == "Mach das."

    set_coordinator(bridge, "codex")  # role returns, no other state involved
    assert ROLE_TEXT in await received_prompt(delivery, monkeypatch, "coord-2")


def test_prefix_never_pushes_a_body_over_its_limit(delivery):
    bridge = delivery[0]
    set_coordinator(bridge, "codex")
    text, prefix = with_role(bridge, "codex", "x" * 16384, limit=16384)
    assert (text, prefix) == ("x" * 16384, "")
    assert with_role(bridge, "codex", "x" * 20000, limit=16384)[1] == ""
    text, prefix = with_role(bridge, "codex", "x" * 100, limit=16384)
    assert prefix and len(text) < 16384 and text.endswith("x" * 100)
    assert len(prefix) < 2000
    assert "Keine Rechteausweitung" in prefix


def test_role_change_and_two_teams_bind_the_prefix_to_the_current_coordinator(delivery):
    bridge = delivery[0]
    set_coordinator(bridge, "codex")
    assert with_role(bridge, "codex", "x")[1] and not with_role(bridge, "grok", "x")[1]
    set_coordinator(bridge, "grok")  # A -> B
    assert with_role(bridge, "grok", "x")[1] and not with_role(bridge, "codex", "x")[1]
    bridge.store.db.execute(
        "INSERT INTO teams VALUES('t2','other','chatgpt','codex',1,?)", (time.time(),)
    )
    assert with_role(bridge, "grok", "x")[1] and with_role(bridge, "codex", "x")[1]
    assert not with_role(bridge, "local", "x")[1]  # no alias exists for coordinators
    assert not with_role(bridge, "codex ", "x")[1]  # exact principal match only


def test_prefixed_prompt_matches_its_original_body_only(delivery):
    bridge = delivery[0]
    set_coordinator(bridge, "codex")
    text, _ = with_role(bridge, "codex", "Mach das.")
    assert matches_body(text, "Mach das.") and matches_body("Mach das.", "Mach das.")
    assert not matches_body("anderer Text\n\nMach das.", "Mach das.")
    assert "Daniel" not in ROLE_TEXT and "Kira" not in ROLE_TEXT


def test_role_text_fixed_rules_short():
    for term in ("Sonnet", "Opus nur", "schwierigen", "Teamkanal", "NICHTS selbst", "ChatGPT"):
        assert term in ROLE_TEXT
    assert len(ROLE_TEXT) < 1500
