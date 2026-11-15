"""Wire/host callbacks are synthetic; none of these tests prove a ChatGPT turn."""

import asyncio
import base64
import json
import sys

import pytest
from test_mcp import http_bridge  # noqa: F401

from kirabridge.event_push import (
    MESSAGE_EVENT_NAME,
    EventJournal,
    EventPush,
    signed_headers,
)
from kirabridge.mcp_gateway.event_envelope import EventEnvelope, serve
from kirabridge.message_manager import MessageSend

SECRET = "whsec_" + base64.b64encode(b"s" * 32).decode()
URL = "https://callbacks.example.test/synthetic-host"


class MockChatGPT:
    """Signature-validating synthetic webhook receiver, not OpenAI."""

    allowed_hosts = {"callbacks.example.test"}

    def __init__(self):
        self.events = []
        self.status = 200

    async def post(self, url, body, headers):
        assert url == URL
        expected = signed_headers(
            {"id": headers["X-MCP-Subscription-Id"], "secret": SECRET},
            headers["webhook-id"],
            body,
            timestamp=int(headers["webhook-timestamp"]),
        )
        assert expected["webhook-signature"] == headers["webhook-signature"]
        value = json.loads(body)
        if value.get("type") == "verification":
            return 200, json.dumps({"challenge": value["challenge"]}).encode()
        self.events.append((body, headers))
        return self.status, b"{}"


@pytest.fixture
def message_push(bridge, config, tmp_path):
    for name in ("codex_channel", "chatgpt", "other"):
        policy = config.principals["local"].model_copy(deep=True)
        policy.capabilities += ["message.send", "message.read", "message.ack"]
        policy.approval_mode = "automatic"
        policy.message_peers = [
            peer for peer in ("codex_channel", "chatgpt", "other") if peer != name
        ]
        config.principals[name] = policy
    journal = EventJournal(tmp_path / "events")

    async def authorized(message_id):
        value = bridge.messages.get("chatgpt", message_id)
        return value.get("recipient") == "chatgpt"

    async def task_authorized(task_id):
        return True

    push = EventPush(
        journal,
        config.state_path / "bridge.sqlite3",
        "chatgpt",
        MockChatGPT(),
        task_authorized,
        authorize_message=authorized,
    )
    yield push
    journal.db.close()


def send(bridge, *, recipient="chatgpt", sender="codex_channel", key="one", body="Hello"):
    return bridge.messages.send(
        sender,
        MessageSend(
            recipient=recipient,
            conversation_id=sender + "-" + recipient,
            idempotency_key=key,
            body=body,
            dispatch=False,
            request_reply=False,
        ),
    )


def subscription(recipient="chatgpt"):
    return {
        "name": MESSAGE_EVENT_NAME,
        "arguments": {"recipient": recipient, "sender": "codex_channel"},
        "delivery": {"mode": "webhook", "url": URL, "secret": SECRET},
    }


async def wire(envelope, method, params=None, id=1):
    line = (
        json.dumps({"jsonrpc": "2.0", "id": id, "method": method, "params": params or {}}).encode()
        + b"\n"
    )
    response, forwarded = await envelope.from_host(line)
    assert forwarded is None
    return json.loads(response)


@pytest.mark.parametrize("version", ["2024-11-05", "2025-03-26", "2025-11-25"])
async def test_wire_subscription_message_webhook_stop_and_no_foreign_inbox(
    message_push,
    bridge,
    version,
):
    push = message_push
    send(bridge, key="old")  # An initial subscription does not replay old inbox data.
    envelope = EventEnvelope(push)
    init = (
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": "init",
                "method": "initialize",
                "params": {
                    "protocolVersion": version,
                    "capabilities": {},
                    "clientInfo": {"name": "SYNTHETIC-HOST", "version": "1"},
                },
            }
        ).encode()
        + b"\n"
    )
    response, forwarded = await envelope.from_host(init)
    assert response is None and forwarded == init
    initialized = envelope.from_child(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": "init",
                "result": {
                    "protocolVersion": version,
                    "capabilities": {"tools": {"listChanged": True}},
                    "serverInfo": {"name": "real-proxy-fixture", "version": "1"},
                },
            }
        ).encode()
        + b"\n"
    )
    assert json.loads(initialized)["result"]["capabilities"]["events"] == {}
    events = await wire(envelope, "events/list")
    assert MESSAGE_EVENT_NAME in [item["name"] for item in events["result"]["events"]]
    denied = await wire(envelope, "events/subscribe", subscription("other"))
    assert denied["error"]["data"]["reason"] == "invalid_message_filter"
    sub = (await wire(envelope, "events/subscribe", subscription()))["result"]
    message = send(bridge)
    send(bridge, recipient="other", key="foreign")
    send(bridge, sender="other", key="filtered")
    assert await push.deliver_once()
    body, headers = push.sender.events[0]
    event = json.loads(body)
    assert event["data"]["message_id"] == message["id"]
    assert event["data"]["recipient"] == "chatgpt" and event["data"]["text"] == "Hello"
    assert headers["X-MCP-Subscription-Id"] == sub["id"]
    assert not await push.deliver_once()
    assert len(push.sender.events) == 1
    assert bridge.store.db.execute(
        "SELECT delivered,acknowledged FROM messages WHERE id=?", (message["id"],)
    ).fetchone()[:] == (None, None)
    # Refresh and sender recovery preserve the original message watermark/dedupe.
    assert (await wire(envelope, "events/subscribe", subscription()))["result"]["id"] == sub["id"]
    push.recover()
    assert not await push.deliver_once()
    params = subscription()
    params["delivery"].pop("secret")
    assert (await wire(envelope, "events/unsubscribe", params))["result"] == {}
    send(bridge, key="after-stop")
    assert not await push.deliver_once()


async def test_retry_uses_same_event_bytes_and_revocation_stops(message_push, bridge):
    push = message_push
    params = subscription()
    await push.subscribe(params["name"], params["arguments"], params["delivery"])
    message = send(bridge)
    push.sender.status = 503
    assert await push.deliver_once()
    push.db.execute("UPDATE deliveries SET next_at=0")
    push.sender.status = 200
    assert await push.deliver_once()
    assert push.sender.events[0][0] == push.sender.events[1][0]
    assert push.sender.events[0][1]["webhook-id"] == push.sender.events[1][1]["webhook-id"]
    send(bridge, key="revoke")

    async def denied(message_id):
        return False

    push.authorize_message = denied
    assert await push.deliver_once()
    assert len(push.sender.events) == 2
    assert bridge.messages.get("chatgpt", message["id"])["acknowledged"] is None


async def test_cross_principal_delivery_is_not_selected(message_push, bridge):
    push = message_push
    params = subscription()
    await push.subscribe(params["name"], params["arguments"], params["delivery"])
    send(bridge)
    push.collect()
    push.db.execute("UPDATE subscriptions SET principal='other'")
    assert not await push.deliver_once()
    assert not push.sender.events


async def test_opaque_wire_passthrough_with_real_child(message_push, tmp_path):
    # A real child echoes bytes. The envelope must preserve aliases, custom meta,
    # notifications and complete structured outputs without rebuilding tool schemas.
    child = tmp_path / "echo.py"
    child.write_text(
        "import sys\nfor line in sys.stdin.buffer:\n"
        " sys.stdout.buffer.write(line);sys.stdout.buffer.flush()\n"
    )
    reader = asyncio.StreamReader()
    lines = [
        b'{ "jsonrpc": "2.0", "id": "library", "method": "tools/call", '
        b'"params": {"name":"td_td_library_uquery","arguments":{"workspace_id":"scope",'
        b'"arguments":{"action":"preview","id":"original"}}}}\n',
        b'{"jsonrpc":"2.0","method":"notifications/tools/list_changed","params":{"_meta":{"opaque":"x"}}}\n',
    ]
    for line in lines:
        reader.feed_data(line)
    reader.feed_eof()
    outputs = []

    async def write(line):
        outputs.append(line)

    await serve(EventEnvelope(message_push), [sys.executable, str(child)], reader, write)
    assert outputs == lines


async def test_disabled_events_do_not_advertise_or_handle():
    envelope = EventEnvelope(None)
    line = b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n'
    assert await envelope.from_host(line) == (None, line)
    result = b'{"jsonrpc":"2.0","id":1,"result":{"capabilities":{"tools":{}}}}\n'
    assert envelope.from_child(result) == result
    request = b'{"jsonrpc":"2.0","id":2,"method":"events/list"}\n'
    assert await envelope.from_host(request) == (None, request)


async def test_real_proxy_wire_subscribe_message_and_signed_mock_callback(
    http_bridge,  # noqa: F811
    tmp_path,
):
    """Real stdio envelope -> existing proxy -> real HTTP daemon; callback is MOCK."""
    import os
    from pathlib import Path

    bridge, _ = http_bridge
    for name, peer in (("local", "codex_channel"), ("codex_channel", "local")):
        if name not in bridge.config.principals:
            bridge.config.principals[name] = bridge.config.principals["local"].model_copy(deep=True)
        policy = bridge.config.principals[name]
        policy.capabilities += ["message.send", "message.read"]
        policy.message_peers = [peer]
        policy.approval_mode = "automatic"
    root = Path(__file__).resolve().parents[1]
    captured = tmp_path / "MOCK-callback.json"
    config_path = tmp_path / "events.toml"
    config_path.write_text(
        f"data_dir = {json.dumps(bridge.config.data_dir)}\nport = {bridge.config.port}\n"
        '[principals.local]\ntoken_env="BRIDGE_TEST_TOKEN"\n'
        'capabilities=["task.read","message.read"]\n'
    )
    driver = tmp_path / "mock_only_driver.py"
    driver.write_text(
        "import asyncio,json,sys\nfrom pathlib import Path\n"
        f"sys.path.insert(0,{str(root / 'integrations/chat-events')!r})\n"
        "import connect\nfrom test_message_event_envelope import MockChatGPT\n"
        "class CapturingMock(MockChatGPT):\n"
        " async def post(self,url,body,headers):\n"
        "  result=await super().post(url,body,headers)\n"
        "  if self.events:\n"
        f"   Path({str(captured)!r}).write_text(json.dumps(json.loads(body)))\n"
        "  return result\n"
        "connect.WebhookSender=lambda hosts: CapturingMock()\n"
        "real_stdio=connect.stdio\n"
        "async def mock_sender_stdio(envelope,child):\n"
        " async def deliver():\n"
        "  while True:\n"
        "   await envelope.push.deliver_once()\n"
        "   await asyncio.sleep(.01)\n"
        " worker=asyncio.create_task(deliver())\n"
        " try: return await real_stdio(envelope,child)\n"
        " finally:\n"
        "  worker.cancel()\n"
        "  await asyncio.gather(worker,return_exceptions=True)\n"
        "connect.stdio=mock_sender_stdio\nconnect.main()\n"
    )
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(driver),
        "--config",
        str(config_path),
        "--principal",
        "local",
        "--state",
        str(tmp_path / "wire-events"),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=16 * 1024 * 1024,
        env={
            "PATH": os.environ["PATH"],
            "PYTHONPATH": str(root / "src") + os.pathsep + str(root / "tests"),
            "BRIDGE_TEST_TOKEN": "local-test-" + "a" * 40,
        },
    )

    async def rpc(id, method, params):
        process.stdin.write(
            json.dumps({"jsonrpc": "2.0", "id": id, "method": method, "params": params}).encode()
            + b"\n"
        )
        await process.stdin.drain()
        async with asyncio.timeout(15):
            while line := await process.stdout.readline():
                value = json.loads(line)
                if value.get("id") == id:
                    assert "error" not in value, value
                    return value["result"]
        raise AssertionError("Synthetic child closed before response")

    try:
        initialized = await rpc(
            1,
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "SYNTHETIC-HOST", "version": "1"},
            },
        )
        assert initialized["capabilities"]["events"] == {}
        process.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
        await process.stdin.drain()
        assert MESSAGE_EVENT_NAME in [
            e["name"] for e in (await rpc(2, "events/list", {}))["events"]
        ]
        params = subscription("local")
        sub = await rpc(3, "events/subscribe", params)
        sent = send(bridge, recipient="local", key="real-wire")
        async with asyncio.timeout(10):
            while not captured.exists():
                await asyncio.sleep(0.01)
        event = json.loads(captured.read_text())
        assert event["data"]["message_id"] == sent["id"]
        assert event["data"]["subscription_id"] == sub["id"]
        # Existing tools continue through the same child after native Events traffic.
        tools = await rpc(4, "tools/list", {})
        assert "message_get" in [tool["name"] for tool in tools["tools"]]
        result = await rpc(
            5, "tools/call", {"name": "message_get", "arguments": {"message_id": sent["id"]}}
        )
        assert result["structuredContent"]["id"] == sent["id"]
        params["delivery"].pop("secret")
        assert await rpc(6, "events/unsubscribe", params) == {}
        assert bridge.messages.get("local", sent["id"])["acknowledged"] is None
    finally:
        process.stdin.close()
        try:
            await asyncio.wait_for(process.wait(), 10)
        except TimeoutError:
            process.kill()
            await process.wait()
        stderr = (await process.stderr.read()).decode()
        assert process.returncode == 0, stderr


async def test_stopped_subscription_resume_does_not_release_backlog(message_push, bridge):
    push = message_push
    params = subscription()
    sub = await push.subscribe(params["name"], params["arguments"], params["delivery"])
    send(bridge, key="pending-before-stop")
    push.collect()
    delivery = push.db.execute("SELECT * FROM deliveries").fetchone()
    assert delivery["state"] == "pending"
    push.unsubscribe(params["name"], params["arguments"], params["delivery"])
    send(bridge, key="during-stop")
    resumed = await push.subscribe(params["name"], params["arguments"], params["delivery"])
    assert resumed["id"] == sub["id"]
    assert not await push.deliver_once()
    assert not push.sender.events
    assert push.db.execute("SELECT state FROM deliveries").fetchone()[0] == "paused"
    latest = send(bridge, key="after-resume")
    assert await push.deliver_once()
    assert json.loads(push.sender.events[0][0])["data"]["message_id"] == latest["id"]


async def test_large_escaped_message_payload_remains_schema_valid_and_bounded(message_push, bridge):
    from jsonschema import validate

    push = message_push
    params = subscription()
    await push.subscribe(params["name"], params["arguments"], params["delivery"])
    bridge.config.messaging.max_body_bytes = 65536
    send(bridge, body="\x01" * 65536)
    assert await push.deliver_once()
    body = push.sender.events[0][0]
    event = json.loads(body)
    definition = next(e for e in push.event_list()["events"] if e["name"] == MESSAGE_EVENT_NAME)
    validate(event["data"], definition["payloadSchema"])
    assert event["data"]["text_truncated"] is True
    assert len(body) < 262144
