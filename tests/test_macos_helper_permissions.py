"""Diagnostic process boundaries; no host UI, clipboard or permission requests."""

import asyncio
import json
import shutil
import subprocess

import pytest

from kirabridge.bridge_core.models import BridgeError
from kirabridge.platform_adapters.macos import helper_permissions as helpers


def packet(pid=123):
    return {
        "pid": pid,
        "permissions": [
            {
                "resource": "accessibility",
                "target": None,
                "method": "AXIsProcessTrusted",
                "raw_granted": False,
            },
            {
                "resource": "screen_capture",
                "target": None,
                "method": "CGPreflightScreenCaptureAccess",
                "raw_granted": True,
            },
            *[
                {
                    "resource": "automation",
                    "target": target,
                    "method": "AEDeterminePermissionToAutomateTarget",
                    "event_class": "****",
                    "event_id": "****",
                    "ask_user_if_needed": False,
                    "target_pid": 456 + index,
                    "target_unchanged": True,
                    "os_status": status,
                }
                for index, (target, status) in enumerate(
                    zip(helpers.TARGETS, [0, -1744], strict=True)
                )
            ],
        ],
    }


class Stdin:
    def __init__(self):
        self.data = b""
        self.closed = False

    def write(self, data):
        self.data += data

    async def drain(self):
        pass

    def close(self):
        self.closed = True

    async def wait_closed(self):
        pass


class Child:
    def __init__(self, output=None, *, returncode=0):
        self.pid = 123
        self.stdin = Stdin()
        self.stdout = asyncio.StreamReader()
        self.stderr = None
        self.returncode = returncode
        self.killed = False
        self.finished = asyncio.Event()
        if output is not None:
            self.stdout.feed_data(output)
        if returncode is not None:
            self.stdout.feed_eof()
            self.finished.set()

    def kill(self):
        self.killed = True
        self.returncode = -9
        self.stdout.feed_eof()
        self.finished.set()

    async def wait(self):
        await self.finished.wait()
        return self.returncode


@pytest.fixture(autouse=True)
def darwin(monkeypatch):
    monkeypatch.setattr(helpers.sys, "platform", "darwin")


async def observe(value, **kwargs):
    child = Child(json.dumps(value).encode())

    async def factory(*args, **options):
        assert args == ("/usr/bin/osascript", "-l", "JavaScript", "-")
        assert options["stderr"] == asyncio.subprocess.DEVNULL
        assert options["limit"] == helpers.MAX_OUTPUT_BYTES + 1
        return child

    result = await helpers.inspect_helper_permissions(process_factory=factory, **kwargs)
    assert child.stdin.data == helpers.HELPER_SCRIPT.encode()
    assert child.stdin.closed
    return result


async def test_actual_child_identity_and_native_states_remain_diagnostic_only():
    result = await observe(packet(), clock=lambda: 100)
    assert result["status"] == "observed"
    assert result["identity"] == {"pid": 123, "executable": "/usr/bin/osascript"}
    assert result["observed_at"] == 100
    assert [row["state"] for row in result["permissions"]] == [
        "unknown",
        "granted",
        "granted",
        "not_determined",
    ]
    assert result["permissions"][0]["raw_granted"] is False
    for flag in (
        "authorizes_future_helpers",
        "updates_provider_permissions",
        "clipboard_content_read",
        "permission_requested",
        "target_started",
    ):
        assert result[flag] is False
    assert result["scope"] == "completed_diagnostic_process_only"


@pytest.mark.parametrize(
    "status,state",
    [(0, "granted"), (-1743, "denied"), (-1744, "not_determined"), (-600, "unknown")],
)
async def test_automation_status_is_exact_and_never_guessed(status, state):
    value = packet()
    value["permissions"][2]["os_status"] = status
    assert (await observe(value))["permissions"][2]["state"] == state


async def test_changed_target_never_reports_previous_grant():
    value = packet()
    value["permissions"][2]["target_unchanged"] = False
    row = (await observe(value))["permissions"][2]
    assert row["state"] == "unknown" and row["reason"] == "target_changed"


@pytest.mark.parametrize(
    "reason", ["target_not_running", "target_ambiguous", "public_preflight_unavailable"]
)
async def test_unavailable_target_or_preflight_is_unknown(reason):
    value = packet()
    value["permissions"][2]["reason"] = reason
    result = await observe(value)
    assert result["permissions"][2]["reason"] == reason
    assert result["permissions"][2]["state"] == "unknown"


async def test_missing_boolean_symbol_is_unknown_without_false_value():
    value = packet()
    row = value["permissions"][0]
    row.pop("raw_granted")
    row["reason"] = "public_symbol_unavailable"
    result = (await observe(value))["permissions"][0]
    assert result["state"] == "unknown" and "raw_granted" not in result


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.update(pid=999),
        lambda p: p.update(pid=True),
        lambda p: p["permissions"].pop(),
        lambda p: p["permissions"][0].update(raw_granted="false"),
        lambda p: p["permissions"][2].update(target="foreign.app"),
        lambda p: p["permissions"][2].update(ask_user_if_needed=True),
        lambda p: p["permissions"][2].update(event_class="core"),
        lambda p: p["permissions"][2].update(target_pid=True),
        lambda p: p["permissions"][2].update(os_status=False),
    ],
)
async def test_malformed_or_foreign_identity_packet_does_not_expose_permissions(mutate):
    value = packet()
    mutate(value)
    result = await observe(value)
    assert result["status"] == "helper_unavailable_or_invalid"
    assert result["permissions"] == [] and result["identity"] is None


@pytest.mark.parametrize(
    "output", [b"not json", b"[]", b"\xff", b"x" * (helpers.MAX_OUTPUT_BYTES + 1)]
)
async def test_invalid_or_oversized_output_is_bounded_and_reaped(output):
    child = Child(output, returncode=None)
    if len(output) <= helpers.MAX_OUTPUT_BYTES:
        child.returncode = 0
        child.stdout.feed_eof()
        child.finished.set()

    async def factory(*args, **kwargs):
        return child

    result = await helpers.inspect_helper_permissions(process_factory=factory)
    assert result["status"] == "helper_unavailable_or_invalid"
    assert result["permissions"] == []
    if len(output) > helpers.MAX_OUTPUT_BYTES:
        assert child.killed


async def test_timeout_reaps_exact_child_without_transferring_observation():
    child = Child(returncode=None)

    async def factory(*args, **kwargs):
        return child

    result = await helpers.inspect_helper_permissions(process_factory=factory, timeout=0.01)
    assert result["status"] == "helper_timeout"
    assert child.killed and result["identity"] is None


async def test_cancellation_reaps_child_and_preserves_cancellation():
    child = Child(returncode=None)
    started = asyncio.Event()

    async def factory(*args, **kwargs):
        started.set()
        return child

    task = asyncio.create_task(helpers.inspect_helper_permissions(process_factory=factory))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert child.killed


async def test_cleanup_failure_preserves_inflight_cancellation(monkeypatch):
    child = Child(returncode=None)
    started = asyncio.Event()

    async def factory(*args, **kwargs):
        started.set()
        return child

    async def failed_cleanup(process, *, process_group):
        assert process is child and process_group is False
        child.kill()
        raise BridgeError("process_cleanup_unknown", "test")

    monkeypatch.setattr(helpers, "reap_process", failed_cleanup)
    task = asyncio.create_task(helpers.inspect_helper_permissions(process_factory=factory))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert child.killed


async def test_repeated_cancellation_waits_for_exact_child_reaping():
    child = Child(returncode=None)
    started, killed, finish = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def factory(*args, **kwargs):
        started.set()
        return child

    def kill():
        child.killed = True
        child.returncode = -9
        child.stdout.feed_eof()
        killed.set()

    async def wait():
        await finish.wait()
        return child.returncode

    child.kill = kill
    child.wait = wait
    task = asyncio.create_task(helpers.inspect_helper_permissions(process_factory=factory))
    await started.wait()
    task.cancel()
    await killed.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert child.killed


async def test_helper_failure_does_not_report_partial_stdout_as_observed():
    child = Child(json.dumps(packet()).encode(), returncode=1)

    async def factory(*args, **kwargs):
        return child

    assert (await helpers.inspect_helper_permissions(process_factory=factory))[
        "status"
    ] == "helper_failed"


async def test_spawn_failure_is_bounded_unknown():
    async def factory(*args, **kwargs):
        raise OSError("local failure details must not leak")

    result = await helpers.inspect_helper_permissions(process_factory=factory)
    assert result["status"] == "helper_unavailable_or_invalid"
    assert "details" not in result and result["permissions"] == []


async def test_cleanup_failure_does_not_claim_observed_process_completion(monkeypatch):
    async def failed_cleanup(child, *, process_group):
        assert process_group is False
        raise BridgeError("process_cleanup_unknown", "test")

    monkeypatch.setattr(helpers, "reap_process", failed_cleanup)
    result = await observe(packet())
    assert result["status"] == "helper_cleanup_unknown"
    assert result["cleanup_confirmed"] is False and result["permissions"] == []


async def test_non_darwin_does_not_spawn_a_helper(monkeypatch):
    monkeypatch.setattr(helpers.sys, "platform", "linux")

    async def forbidden(*args, **kwargs):
        raise AssertionError("Must not spawn")

    assert (await helpers.inspect_helper_permissions(process_factory=forbidden))[
        "status"
    ] == "not_applicable"


@pytest.mark.parametrize("timeout", [True, 0, -1, 11, float("inf"), float("nan"), "5"])
async def test_invalid_diagnostic_timeout_is_rejected(timeout):
    with pytest.raises(ValueError):
        await helpers.inspect_helper_permissions(timeout=timeout)


def test_static_script_uses_no_prompt_preflight_and_has_no_effect_path():
    script = helpers.HELPER_SCRIPT
    assert "descriptorWithProcessIdentifier(pid)" in script
    assert "0x2a2a2a2a,0x2a2a2a2a,false" in script
    for forbidden in (
        "Application(",
        "activate(",
        "AXIsProcessTrustedWithOptions",
        "RequestScreenCapture",
        "NSPasteboard",
        "AESend",
        "doScript",
        "keystroke",
        "launchApplication",
    ):
        assert forbidden not in script
    assert "runningApplicationsWithBundleIdentifier" in script


def test_missing_jxa_c_metadata_and_opaque_descriptor_are_explicitly_bound():
    node = shutil.which("node")
    if not node:
        pytest.skip("JavaScript parser unavailable")
    # Simulate the actual failure: import supplies ObjC classes, but no C
    # functions. AE pointers are accepted only by an opaque-pointer binding.
    harness = r"""
const bindings=[];
const $=value=>value;
$.NSProcessInfo={processInfo:{processIdentifier:123}};
const application={processIdentifier:456,terminated:false};
$.NSRunningApplication={runningApplicationsWithBundleIdentifier(bundle) {
 const rows=bundle==='com.apple.Terminal' ? [application] : [];
 return {count:rows.length,objectAtIndex:index=>rows[index]};
}};
$.NSAppleEventDescriptor={descriptorWithProcessIdentifier(pid) {
 if(pid!==456) throw Error('unbound target');
 return {aeDesc:{opaque:true}};
}};
const ObjC={import() {},bindFunction(name,signature) {
 const signatures={AXIsProcessTrusted:['unsigned char',[]],
 CGPreflightScreenCaptureAccess:['bool',[]],
 AEDeterminePermissionToAutomateTarget:
 ['int',['void *','unsigned int','unsigned int','unsigned char']]};
 if(JSON.stringify(signature)!==JSON.stringify(signatures[name]))
  throw Error('wrong public ABI');
 bindings.push(name);
 $[name]=name==='AEDeterminePermissionToAutomateTarget' ?
  (pointer,eventClass,eventID,ask)=> {
   if(!pointer.opaque || eventClass!==0x2a2a2a2a ||
      eventID!==0x2a2a2a2a || ask!==false) throw Error('invalid preflight');
   return 0;
  } : ()=>true;
}};
"""
    result = subprocess.run(
        [node, "-e", harness + helpers.HELPER_SCRIPT + "console.log(run());"],
        capture_output=True,
        text=True,
        timeout=3,
        check=True,
    )
    observed = helpers._permissions(json.loads(result.stdout), 123)
    assert [row["state"] for row in observed] == ["granted", "granted", "granted", "unknown"]
    assert observed[-1]["reason"] == "target_not_running"
