"""Host callbacks here are SIMULATIONS. No assertion proves ChatGPT chat delivery."""

import asyncio
import base64
import hashlib
import hmac
import json
import time

import httpx
import pytest
from conftest import request

from kirabridge.event_push import (
    EVENT_NAME,
    EventError,
    EventJournal,
    EventPush,
    PublicNetwork,
    WebhookSender,
    callback_host,
    signed_headers,
    signing_key,
)

SECRET = "whsec_" + base64.b64encode(b"a" * 32).decode()
SECOND = "whsec_" + base64.b64encode(b"b" * 32).decode()
URL = "https://callbacks.example.test/host-assigned-chat-A"


class SimulatedHost:
    allowed_hosts = {"callbacks.example.test"}

    def __init__(self):
        self.calls = []
        self.status = 200
        self.bad_challenge = False
        self.timeout = False

    async def post(self, url, body, headers):
        self.calls.append((url, body, headers))
        value = json.loads(body)
        if value.get("type") == "verification":
            expected = signed_headers(
                {"id": headers["X-MCP-Subscription-Id"], "secret": self.key},
                headers["webhook-id"],
                body,
                timestamp=int(headers["webhook-timestamp"]),
            )
            assert expected["webhook-signature"] == headers["webhook-signature"]
            return 200, json.dumps(
                {"challenge": "wrong" if self.bad_challenge else value["challenge"]}
            ).encode()
        if self.timeout:
            raise httpx.ReadTimeout("SIMULATED timeout")
        return self.status, b"{}"


@pytest.fixture
def push(tmp_path, bridge, config):
    host = SimulatedHost()
    host.key = SECRET
    journal = EventJournal(tmp_path / "events")

    async def authorized(task_id):
        return True

    manager = EventPush(journal, config.state_path / "bridge.sqlite3", "local", host, authorized)
    yield manager
    journal.db.close()


async def subscribe(push, task="task-1", url=URL, secret=SECRET):
    push.sender.key = secret
    return await push.subscribe(
        EVENT_NAME, {"task_id": task}, {"mode": "webhook", "url": url, "secret": secret}
    )


def unsubscribe(push, task="task-1", url=URL):
    return push.unsubscribe(EVENT_NAME, {"task_id": task}, {"mode": "webhook", "url": url})


async def finish(push, bridge, config, *, task="task-1", code=0):
    config.principals["local"].approval_mode = "automatic"
    sub = await subscribe(push, task)
    value = request(arguments={"path": config.principals["local"].roots[0]}, task_id=task)
    bridge.prepare("local", value, completion_target=push.binding(task, sub["id"]))
    bridge.store.claim("test", 10)
    from kirabridge.bridge_core.models import State

    bridge.store.transition(task, State.RUNNING, {"session_id": "local-session"}, owner="test")
    bridge.store.transition(
        task,
        State.COMPLETED if not code else State.FAILED,
        {"exit_code": code, "summary": "fixture", "session_id": "local-session"},
        owner="test",
    )
    return sub


async def test_verified_refresh_rotation_and_stop(push):
    first = await subscribe(push)
    assert first["id"] == (await subscribe(push))["id"]
    assert len(push.sender.calls) == 1
    assert push.binding("task-1", first["id"]) == "push:" + first["id"]
    with pytest.raises(EventError, match="exact_verified"):
        push.binding("another-task", first["id"])
    second = await subscribe(push, secret=SECOND)
    assert first["id"] == second["id"]
    assert len(push.sender.calls) == 2
    row = push.journal.subscription("local", first["id"])
    headers = signed_headers(row, "evt", b"body", timestamp=1234)
    assert len(headers["webhook-signature"].split()) == 2
    with pytest.raises(EventError, match="not_found"):
        push.journal.subscription("other", first["id"])
    unsubscribe(push)
    with pytest.raises(EventError, match="exact_verified"):
        push.binding("task-1", first["id"])


async def test_challenge_failure_leaves_no_subscription(push):
    push.sender.bad_challenge = True
    with pytest.raises(EventError, match="challenge_failed"):
        await subscribe(push)
    assert push.db.execute("SELECT count(*) FROM subscriptions").fetchone()[0] == 0


@pytest.mark.parametrize(
    "url",
    [
        None,
        123,
        "http://callbacks.example.test/a",
        "https://127.0.0.1/a",
        "https://callbacks.example.test:8443/a",
        "https://user:secret@callbacks.example.test/a",
        "https://callbacks.example.test/a#frag",
        "https://unknown.example.test/a",
        "https://callbacks.example.test/\nsecret",
    ],
)
def test_callback_validation(url):
    with pytest.raises(EventError):
        callback_host(url, {"callbacks.example.test"})


@pytest.mark.parametrize("secret", [None, "fake", "whsec_@@", "whsec_YQ=="])
def test_key_validation(secret):
    with pytest.raises(EventError, match="invalid_signing"):
        signing_key(secret)


async def test_fast_completion_archive_survives_existing_consumer_ack(push, bridge, config):
    sub = await finish(push, bridge, config)
    notices = bridge.completions.receive("local", "push:" + sub["id"])["notices"]
    bridge.completions.ack("local", notices[0]["id"], notices[0]["receipt"])
    other = await subscribe(push, url=URL + "-other-chat")
    push.collect()
    push.collect()
    rows = push.db.execute("SELECT * FROM deliveries").fetchall()
    assert len(rows) == 1
    event = json.loads(rows[0]["body"])
    assert event["data"]["task_id"] == "task-1"
    assert event["data"]["outcome"] == "success"
    assert event["data"]["subscription_id"] != other["id"]
    assert event["data"]["session_id"] == "local-session"
    with pytest.raises(EventError, match="receipt_not_bound"):
        push.receipt(sub["id"], event["eventId"], "task-1", event["data"]["receipt_token"])
    assert await push.deliver_once()
    row = dict(push.db.execute("SELECT * FROM deliveries").fetchone())
    assert row["state"] == "webhook_accepted"
    assert row["assistant_receipt"] is None
    for task, token in [("wrong-task", event["data"]["receipt_token"]), ("task-1", "wrong-token")]:
        with pytest.raises(EventError, match="receipt_not_bound"):
            push.receipt(sub["id"], event["eventId"], task, token)
    receipt = push.receipt(sub["id"], event["eventId"], "task-1", event["data"]["receipt_token"])
    assert receipt["receipt_scope"] == "authenticated_payload_possession"
    assert receipt["chat_ui_receipt_independently_verified"] is False
    push.receipt(sub["id"], event["eventId"], "task-1", event["data"]["receipt_token"])
    assert not await push.deliver_once()
    assert not bridge.completions.receive("local", "push:" + sub["id"])["notices"]


@pytest.mark.parametrize(
    "status,state,attempts",
    [(503, "rejected", 3), (429, "rejected", 3), (410, "rejected", 1), (413, "rejected", 1)],
)
async def test_bounded_retries_stable_identity_and_no_retry_permanent(
    push, bridge, config, status, state, attempts
):
    await finish(push, bridge, config, code=7)
    push.sender.status = status
    for _ in range(5):
        await push.deliver_once()
        push.db.execute("UPDATE deliveries SET next_at=0")
    row = dict(push.db.execute("SELECT * FROM deliveries").fetchone())
    assert (row["state"], row["attempts"]) == (state, attempts)
    calls = [c for c in push.sender.calls if json.loads(c[1]).get("eventId")]
    assert len(calls) == attempts
    assert len({c[1] for c in calls}) == 1
    assert len({c[2]["webhook-id"] for c in calls}) == 1
    assert json.loads(calls[0][1])["data"]["outcome"] == "error"


async def test_unknown_delivery_recovery_and_no_resubmit(push, bridge, config):
    await finish(push, bridge, config)
    push.sender.timeout = True
    assert await push.deliver_once()
    push.db.execute("UPDATE deliveries SET state='sending',next_at=0")
    old = dict(push.db.execute("SELECT * FROM deliveries").fetchone())
    push.recover()
    push.sender.timeout = False
    assert await push.deliver_once()
    now = dict(push.db.execute("SELECT * FROM deliveries").fetchone())
    assert now["body"] == old["body"] and now["event_id"] == old["event_id"]
    assert now["state"] == "webhook_accepted" and now["attempts"] == 2
    assert bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 1
    push.db.execute("UPDATE deliveries SET state='sending',attempts=3")
    push.recover()
    assert push.db.execute("SELECT state FROM deliveries").fetchone()[0] == "unknown"


async def test_stop_expiry_revocation_and_race(push, bridge, config):
    sub = await finish(push, bridge, config)
    push.collect()
    push.db.execute("UPDATE subscriptions SET expires=?", (time.time() - 1,))
    assert not await push.deliver_once()
    await subscribe(push)

    async def revoked(task):
        return False

    push.authorize_task = revoked
    assert await push.deliver_once()
    assert push.journal.subscription("local", sub["id"])["state"] == "revoked"
    await subscribe(push)

    async def stop_during_authorize(task):
        unsubscribe(push)
        return True

    push.authorize_task = stop_during_authorize
    assert not await push.deliver_once()
    assert len(push.sender.calls) == 2  # verification only


async def test_dns_mixed_public_private_rejected(monkeypatch):
    async def lookup(*args, **kwargs):
        return [
            (None, None, None, "", ("1.1.1.1", 443)),
            (None, None, None, "", ("127.0.0.1", 443)),
        ]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", lookup)
    with pytest.raises(EventError, match="not_public"):
        await PublicNetwork().connect_tcp("callbacks.example.test", 443)


async def test_pinned_tcp_preserves_tls_hostname_and_signature(monkeypatch):
    from httpcore._backends.auto import AutoBackend

    observed = {}

    class Stream:
        async def read(self, max_bytes, timeout=None):
            return b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}"

        async def write(self, buffer, timeout=None):
            observed.setdefault("writes", []).append(buffer)

        async def aclose(self):
            pass

        async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
            observed["tls_host"] = server_hostname
            assert ssl_context.check_hostname
            return self

        def get_extra_info(self, info):
            return None

    async def connect(self, host, port, *args):
        observed["ip"] = host
        return Stream()

    async def lookup(*args, **kwargs):
        return [(None, None, None, "", ("1.1.1.1", 443))]

    monkeypatch.setattr(AutoBackend, "connect_tcp", connect)
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", lookup)
    body = b'{"data":"fixture"}'
    headers = signed_headers({"id": "sub-test", "secret": SECRET}, "evt-test", body, timestamp=123)
    status, _ = await WebhookSender({"callbacks.example.test"}).post(URL, body, headers)
    assert status == 200 and observed["ip"] == "1.1.1.1"
    assert observed["tls_host"] == "callbacks.example.test"
    assert b"Host: callbacks.example.test" in b"".join(observed["writes"])
    message = b"evt-test.123." + body
    expected = base64.b64encode(hmac.digest(b"a" * 32, message, hashlib.sha256)).decode()
    assert headers["webhook-signature"] == "v1," + expected


async def test_authorization_outage_stops_after_three_checks_without_sending(push, bridge, config):
    await finish(push, bridge, config)

    async def unavailable(task):
        raise httpx.ConnectError("SIMULATED backend unavailable")

    push.authorize_task = unavailable
    for _ in range(6):
        await push.deliver_once()
        push.db.execute("UPDATE deliveries SET next_at=0")
    row = dict(push.db.execute("SELECT * FROM deliveries").fetchone())
    assert row["state"] == "authorization_unknown"
    assert row["auth_failures"] == 3 and row["attempts"] == 0
    assert len(push.sender.calls) == 1  # challenge only
    assert push.status()["chat_ui_receipt_independently_verified"] is False


async def test_explicit_subscription_required_and_unknown_transport_stays_unknown(
    push, bridge, config
):
    await finish(push, bridge, config)
    with pytest.raises(EventError, match="explicit_verified"):
        push.binding("task-1")
    push.sender.timeout = True
    for _ in range(4):
        await push.deliver_once()
        push.db.execute("UPDATE deliveries SET next_at=0")
    row = dict(push.db.execute("SELECT * FROM deliveries").fetchone())
    assert row["state"] == "unknown" and row["attempts"] == 3
    observations = str([tuple(r) for r in push.db.execute("SELECT * FROM observations")])
    assert SECRET not in observations and URL not in observations
    assert json.loads(row["body"])["data"]["receipt_token"] not in observations


async def test_ordinary_submission_never_requires_or_creates_subscription(push):
    original = {"request": {"task_id": "ordinary"}}
    assert push.route_submission(original) == original
    assert "completion_target" not in original
    assert push.route_submission({**original, "completion_target": "existing-consumer"}) == {
        **original,
        "completion_target": "existing-consumer",
    }
    assert push.db.execute("SELECT count(*) FROM subscriptions").fetchone()[0] == 0
    assert push.route_submission({**original, "completion_subscription": ""}) == original


async def test_only_explicit_push_routes_require_exact_verified_subscription(push):
    sub = await subscribe(push)
    original = {"request": {"task_id": "task-1"}, "completion_target": "push:" + sub["id"]}
    assert push.route_submission(original) == original
    assert (
        push.route_submission(
            {"request": {"task_id": "task-1"}, "completion_subscription": sub["id"]}
        )
        == original
    )
    with pytest.raises(EventError, match="exact_verified"):
        push.route_submission({**original, "request": {"task_id": "wrong-task"}})
    with pytest.raises(EventError, match="does_not_match"):
        push.route_submission({**original, "completion_subscription": "another-subscription"})
    unsubscribe(push)
    with pytest.raises(EventError, match="exact_verified"):
        push.route_submission(original)


def test_concurrent_sender_frontend_initialization_shares_one_identity(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    directory = tmp_path / "concurrent-event-journal"

    def open_and_close(_):
        journal = EventJournal(directory)
        try:
            return journal.key
        finally:
            journal.db.close()

    with ThreadPoolExecutor(max_workers=4) as workers:
        identities = list(workers.map(open_and_close, range(8)))
    assert len(set(identities)) == 1


async def test_backend_startup_retries_only_read_only_health():
    from kirabridge.event_push import wait_backend_ready

    calls = []
    delays = []

    async def call(method, arguments):
        calls.append((method, arguments))
        if len(calls) < 3:
            raise httpx.ConnectError("SIMULATED startup race")
        return {"structuredContent": {"dispatcher_active": True}}

    async def sleep(seconds):
        delays.append(seconds)

    await wait_backend_ready(call, sleep=sleep)
    assert calls == [("bridge_health", {})] * 3
    assert delays == [0.5, 1]


async def test_backend_startup_has_finite_attempt_budget():
    from kirabridge.event_push import wait_backend_ready

    calls = []

    async def call(method, arguments):
        calls.append(method)
        raise httpx.ConnectError("SIMULATED offline backend")

    async def sleep(seconds):
        pass

    with pytest.raises(EventError, match="backend_startup_unavailable"):
        await wait_backend_ready(call, sleep=sleep)
    assert calls == ["bridge_health"] * 6


async def test_backend_auth_error_is_not_retried():
    from kirabridge.event_push import wait_backend_ready

    calls = []

    async def call(method, arguments):
        calls.append(method)
        return {"structuredContent": {"error": {"code": "unauthorized"}}}

    with pytest.raises(EventError, match="backend_readiness_failed"):
        await wait_backend_ready(call)
    assert calls == ["bridge_health"]


async def test_delivery_queue_pause_restore_and_revision_race(push, bridge, config):
    from kirabridge import event_queue

    await finish(push, bridge, config)
    push.collect()
    page = event_queue.entries(push)
    entry = page["entries"][0]
    assert "receipt_token" not in entry["body"]
    assert SECRET not in json.dumps(page) and URL not in json.dumps(page)
    event_queue.control(push, entry["event_id"], entry["revision"], "cancel")
    assert not await push.deliver_once()
    paused = event_queue.entries(push)["entries"][0]
    with pytest.raises(EventError, match="queue_changed"):
        event_queue.control(push, entry["event_id"], entry["revision"], "restore")
    event_queue.control(push, paused["event_id"], paused["revision"], "restore")
    assert await push.deliver_once()
    assert event_queue.entries(push)["entries"][0]["state"] == "webhook_accepted"


async def test_delivery_cancel_wins_during_authorization(push, bridge, config):
    from kirabridge import event_queue

    await finish(push, bridge, config)
    push.collect()
    entered, release = asyncio.Event(), asyncio.Event()

    async def authorize(task_id):
        entered.set()
        await release.wait()
        return True

    push.authorize_task = authorize
    pending = asyncio.create_task(push.deliver_once())
    await entered.wait()
    entry = event_queue.entries(push)["entries"][0]
    event_queue.control(push, entry["event_id"], entry["revision"], "cancel")
    release.set()
    assert not await pending
    assert event_queue.entries(push)["entries"][0]["attempts"] == 0


async def test_delivery_clear_preserves_unknown_and_inflight_evidence(push, bridge, config):
    from kirabridge import event_queue

    await finish(push, bridge, config)
    push.collect()
    entry = event_queue.entries(push)["entries"][0]
    push.db.execute("UPDATE deliveries SET state='sending',attempts=1")
    page = event_queue.entries(push)
    result = event_queue.control(push, "", page["queue_revision"], "clear")
    assert result["inflight_unresolved"] == [entry["event_id"]]
    push.db.execute("UPDATE deliveries SET state='unknown'")
    page = event_queue.entries(push)
    assert event_queue.control(push, "", page["queue_revision"], "clear")["paused"]
    paused = event_queue.entries(push)["entries"][0]
    with pytest.raises(EventError, match="attempted"):
        event_queue.control(push, paused["event_id"], paused["revision"], "restore")


async def test_event_queue_revalidates_before_exposing_captured_results(push, bridge, config):
    from kirabridge import event_queue

    await finish(push, bridge, config)
    push.collect()

    async def revoked(task_id):
        return False

    push.authorize_task = revoked
    result = await event_queue.inspect_entries(push)
    assert result["entries"][0]["content_authorization"] == "denied"
    assert "body" not in result["entries"][0]
