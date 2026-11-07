"""Actual CLI parser/client over local MCP; all agent processes are fixtures."""

import asyncio
import sys
from pathlib import Path

import pytest
from test_mcp import http_bridge  # noqa: F401
from test_messages import channel, configure_receivers  # noqa: F401

from kirabridge import cli
from kirabridge.local_runtime import peer
from kirabridge.mcp_gateway.client import MCPClientPool
from kirabridge.message_manager import MessageSend


@pytest.fixture
def invoke(config, monkeypatch, tmp_path):
    # Keep the actual parser and authenticated HTTP client. Only supply the
    # isolated in-memory test policy instead of loading an operator config.
    monkeypatch.setattr(cli, "load_config", lambda _: config)

    async def run(principal, *arguments, command="message"):
        output = []
        monkeypatch.setattr(cli, "emit", lambda value, **_: output.append(value))
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "kirabridge",
                "--config",
                str(tmp_path / "isolated.toml"),
                "--principal",
                principal,
                command,
                *arguments,
            ],
        )
        await asyncio.to_thread(cli.main)
        assert len(output) == 1 and "error" not in output[0], output
        return output[0]

    return run


def send_arguments(kind, key, *extra):
    return (
        "send",
        "codex",
        "Harmless return, no new work",
        "--kind",
        kind,
        "--conversation",
        "cli-returns",
        "--key",
        key,
        *extra,
    )


@pytest.mark.parametrize("kind", ["answer", "result"])
async def test_cli_return_defaults_to_inbox_without_new_agent_work(
    channel,  # noqa: F811
    http_bridge,  # noqa: F811
    config,
    tmp_path,
    invoke,
    kind,
):
    bridge, _ = http_bridge
    configure_receivers(bridge, config, tmp_path)
    result = await invoke("grok", *send_arguments(kind, "return-" + kind))
    assert result["processing"] is None
    received = channel.receive("codex")["messages"]
    assert [item["id"] for item in received] == [result["id"]]
    assert received[0]["kind"] == kind
    channel.ack("codex", result["id"], received[0]["receipt"])
    assert (await invoke("grok", *send_arguments(kind, "return-" + kind)))["id"] == result["id"]
    assert not channel.receive("codex")["messages"]
    assert bridge.store.db.execute("SELECT count(*) FROM message_jobs").fetchone()[0] == 0
    assert bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0


@pytest.mark.parametrize("kind", ["answer", "result"])
async def test_existing_inbox_only_switch_is_an_effective_return_workaround(
    channel,  # noqa: F811
    http_bridge,  # noqa: F811
    config,
    tmp_path,
    invoke,
    kind,
):
    bridge, _ = http_bridge
    configure_receivers(bridge, config, tmp_path)
    result = await invoke("grok", *send_arguments(kind, "workaround-" + kind, "--inbox-only"))
    assert result["processing"] is None
    assert bridge.store.db.execute("SELECT count(*) FROM message_jobs").fetchone()[0] == 0


async def test_cli_explicit_followup_work_runs_once_and_auto_result_never_kicks_requester(
    channel,  # noqa: F811
    http_bridge,  # noqa: F811
    config,
    tmp_path,
    invoke,
):
    bridge, _ = http_bridge
    configure_receivers(bridge, config, tmp_path)
    await bridge.message_receiver.start()
    root = Path(config.principals["grok"].roots[0])

    for number in (1, 2):
        arguments = (
            "send",
            "grok",
            "Eine harmlose Frage",
            "--kind",
            "work",
            "--conversation",
            "explicit-followup",
            "--key",
            "explicit-work-" + str(number),
        )
        sent = await invoke("codex", *arguments)
        async with asyncio.timeout(15):
            while channel.get("codex", sent["id"])["processing"]["state"] != "completed":
                await asyncio.sleep(0.02)
        # The original parent result is the completion; no prompt acknowledgement.
        result = channel.get("codex", sent["id"])
        assert result["processing"]["state"] == "completed"
        returned = (await invoke("codex", "receive"))["messages"]
        assert len(returned) == 1
        assert returned[0]["reply_to"] == sent["id"]
        assert returned[0]["kind"] == "result" and returned[0]["processing"] is None
        assert returned[0]["body"] == "GROK_CHANNEL_ACK"
        await invoke("codex", "ack", returned[0]["id"], "--receipt", returned[0]["receipt"])
        assert (await invoke("codex", *arguments))["id"] == sent["id"]
        assert not (await invoke("codex", "receive"))["messages"]
        assert (root / "grok-invocations").read_text() == "1\n" * number
        assert not (root / "codex-invocations").exists()
        assert bridge.store.db.execute("SELECT count(*) FROM message_jobs").fetchone()[0] == number

    assert bridge.store.db.execute("SELECT count(*) FROM messages").fetchone()[0] == 4
    assert all(
        item[0] == "completed" for item in bridge.store.db.execute("SELECT state FROM message_jobs")
    )


async def test_existing_mcp_completion_can_be_consumed_by_cli_watch_without_another_turn(
    channel,  # noqa: F811
    http_bridge,  # noqa: F811
    config,
    tmp_path,
    invoke,
):
    bridge, _ = http_bridge
    configure_receivers(bridge, config, tmp_path)
    await bridge.message_receiver.start()
    message = MessageSend(
        recipient="grok",
        conversation_id="completion-parent",
        idempotency_key="completion-work",
        kind="work",
        body="Eine harmlose Frage",
        dispatch=True,
    )
    async with MCPClientPool() as client:
        await client.connect(peer(config, "codex"))
        sent = (
            await client.call(
                "daemon",
                "message_send",
                {"message": message.model_dump(), "completion_target": "cli-owner"},
            )
        ).structuredContent
    notice = await invoke(
        "codex", "--target", "cli-owner", "--once", "--timeout", "10", command="watch"
    )
    assert notice["payload"]["message_id"] == sent["id"]
    assert notice["payload"]["source"] == "message"
    assert notice["payload"]["outcome"] == "success"
    assert not bridge.completions.receive("codex", "cli-owner")["notices"]
    returned = channel.receive("codex")["messages"]
    assert len(returned) == 1 and returned[0]["reply_to"] == sent["id"]
    assert returned[0]["kind"] == "result" and returned[0]["processing"] is None
    root = Path(config.principals["grok"].roots[0])
    assert (root / "grok-invocations").read_text() == "1\n"
    assert not (root / "codex-invocations").exists()
    assert bridge.store.db.execute("SELECT count(*) FROM message_jobs").fetchone()[0] == 1


@pytest.mark.parametrize("kind", ["answer", "result"])
async def test_cli_return_retry_preserves_historical_unknown_dispatch(
    channel,  # noqa: F811
    http_bridge,  # noqa: F811
    config,
    tmp_path,
    invoke,
    kind,
):
    bridge, _ = http_bridge
    configure_receivers(bridge, config, tmp_path)
    original = channel.send(
        "grok",
        MessageSend(
            recipient="codex",
            conversation_id="cli-returns",
            idempotency_key="old-" + kind,
            body="Harmless return, no new work",
            kind=kind,
            dispatch=True,
        ),
    )
    bridge.message_receiver._finish(
        original["id"], "unknown", {"reason": "original_outcome_uncertain"}, "fixture_unknown"
    )
    before = channel.get("grok", original["id"])["processing"]
    retry = await invoke("grok", *send_arguments(kind, "old-" + kind))
    assert retry["id"] == original["id"] and retry["processing"] == before
    assert retry["processing"]["state"] == "unknown"
    assert bridge.store.db.execute("SELECT count(*) FROM message_jobs").fetchone()[0] == 1
    root = Path(config.principals["grok"].roots[0])
    assert not (root / "codex-invocations").exists()
