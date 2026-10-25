"""Clipboard lease protocol lifecycles with fake processes; never touch host clipboard."""

import asyncio
import base64
import json
from types import SimpleNamespace

import pytest

from kirabridge.bridge_core.models import BridgeError
from kirabridge.platform_adapters.clipboard_lease import OWNER_SCRIPT, clipboard_lease


class Owner:
    def __init__(
        self, *, ready=True, final="restored", hang=False, generation=23, ready_status="ready"
    ):
        self.stdout = asyncio.StreamReader()
        self.returncode = None
        self.killed = False
        self.input = b""
        self.final, self.hang = final, hang
        self.stdin = SimpleNamespace(write=self.write, drain=self.drain, close=self.close_input)
        if ready:
            self.stdout.feed_data(
                (json.dumps({"status": ready_status, "generation": generation}) + "\n").encode()
            )

    def write(self, value):
        self.input += value

    async def drain(self):
        pass

    def close_input(self):
        if not self.hang:
            self.stdout.feed_data((json.dumps({"status": self.final}) + "\n").encode())
            self.stdout.feed_eof()
            self.returncode = 0

    async def wait(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9
        self.stdout.feed_eof()


def setup(monkeypatch, **kwargs):
    monkeypatch.setattr("sys.platform", "darwin")
    owner = Owner(**kwargs)
    calls = []

    async def spawn(*args, **options):
        calls.append((args, options))
        return owner

    return owner, spawn, calls


async def test_payload_only_stdin_owner_source_static_and_restore_receipted(monkeypatch):
    owner, spawn, calls = setup(monkeypatch)
    text = "private fixture 🧠\nsecond line"
    async with clipboard_lease(text, process_factory=spawn) as lease:
        assert owner.returncode is None
        assert lease.generation == 23
        assert owner.input.isascii()
        packet = json.loads(owner.input)
        assert base64.b64decode(packet["text_b64"]).decode() == text
        assert text not in str(calls)
        assert calls[0][0][-1] == OWNER_SCRIPT
    assert lease.restore_status == "restored"
    assert not owner.killed


async def test_gui_worker_timeout_restores_without_replaying_body(monkeypatch):
    owner, spawn, _ = setup(monkeypatch)
    calls = 0
    with pytest.raises(TimeoutError):
        async with clipboard_lease("fixture", process_factory=spawn) as lease:
            calls += 1
            raise TimeoutError("GUI worker expired")
    assert lease.restore_status == "restored"
    assert calls == 1 and not owner.killed


async def test_task_cancellation_keeps_owner_alive_until_restore(monkeypatch):
    owner, spawn, _ = setup(monkeypatch)
    entered = asyncio.Event()
    leases = []

    async def run():
        async with clipboard_lease("fixture", process_factory=spawn) as lease:
            leases.append(lease)
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(run())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert leases[0].restore_status == "restored"
    assert not owner.killed


async def test_lost_ready_receipt_still_requests_owner_eof_cleanup(monkeypatch):
    owner, spawn, _ = setup(monkeypatch, ready=False)
    with pytest.raises(BridgeError) as exc:
        async with clipboard_lease("fixture", process_factory=spawn, startup_timeout=0.01):
            pytest.fail("No paste without a ready lease")
    assert exc.value.code == "clipboard_unavailable"
    assert owner.returncode == 0 and not owner.killed


async def test_user_changed_generation_is_preserved_without_claiming_restored(monkeypatch):
    owner, spawn, _ = setup(monkeypatch, final="user_changed")
    async with clipboard_lease("fixture", process_factory=spawn) as lease:
        pass
    assert lease.restore_status == "user_changed"
    assert not owner.killed


@pytest.mark.parametrize("final", ["restore_failed", "unexpected"])
async def test_unconfirmed_restore_is_explicit_even_when_gui_body_succeeded(monkeypatch, final):
    _, spawn, _ = setup(monkeypatch, final=final)
    with pytest.raises(BridgeError) as exc:
        async with clipboard_lease("fixture", process_factory=spawn):
            pass
    assert exc.value.code == "clipboard_restore_unknown"


async def test_wedged_owner_cleanup_is_bounded_and_never_claims_restoration(monkeypatch):
    owner, spawn, _ = setup(monkeypatch, hang=True)
    with pytest.raises(BridgeError) as exc:
        async with clipboard_lease("fixture", process_factory=spawn, cleanup_timeout=0.01):
            pass
    assert exc.value.code == "clipboard_restore_unknown"
    assert owner.killed


def test_owner_normalizes_numeric_lengths_and_preserves_all_formats_before_mutation():
    assert "const bytes=number(data.length); total+=bytes;" in OWNER_SCRIPT
    assert "count>32" in OWNER_SCRIPT and "formatsCount>64" in OWNER_SCRIPT
    assert "bytes>1048576 || total>4194304" in OWNER_SCRIPT
    assert OWNER_SCRIPT.index("formats.push([type,data])") < OWNER_SCRIPT.index("pb.clearContents")
    assert "if(number(pb.changeCount)!==generation) restore='user_changed'" in OWNER_SCRIPT
    assert "Application(" not in OWNER_SCRIPT


async def test_cancellation_during_owner_spawn_never_loses_process_cleanup(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    owner = Owner(ready=False, final="not_modified")
    spawning = asyncio.Event()
    release = asyncio.Event()

    async def spawn(*args, **options):
        spawning.set()
        await release.wait()
        return owner

    async def run():
        async with clipboard_lease("fixture", process_factory=spawn):
            pytest.fail("Cancelled before BEGIN")

    task = asyncio.create_task(run())
    await spawning.wait()
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not owner.input and owner.returncode == 0 and not owner.killed


@pytest.mark.parametrize("generation", [None, "23", True, -1, 2**53, 1.5])
async def test_invalid_ready_generation_prevents_gui_body_and_still_cleans_up(
    monkeypatch, generation
):
    owner, spawn, _ = setup(monkeypatch, generation=generation)
    with pytest.raises(BridgeError) as exc:
        async with clipboard_lease("fixture", process_factory=spawn):
            pytest.fail("No GUI operation without a safe exact generation")
    assert exc.value.code == "clipboard_unavailable"
    assert owner.returncode == 0 and not owner.killed


async def test_changed_clipboard_before_ready_does_not_grant_a_lease(monkeypatch):
    owner, spawn, _ = setup(monkeypatch, ready_status="user_changed", final="user_changed")
    with pytest.raises(BridgeError) as exc:
        async with clipboard_lease("fixture", process_factory=spawn):
            pytest.fail("User change did not grant clipboard ownership")
    assert exc.value.code == "clipboard_unavailable"
    assert owner.returncode == 0 and not owner.killed
