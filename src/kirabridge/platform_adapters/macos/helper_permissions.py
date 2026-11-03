"""Explicit no-prompt observations from one short-lived osascript process.

This diagnostic never feeds PermissionProbe or authorizes a later worker. A
successful preflight belongs only to the exact process that returned it.
"""

from __future__ import annotations

import asyncio
import json
import math
import sys
import time

from kirabridge.bridge_core.models import BridgeError
from kirabridge.platform_adapters import reap_process

HELPER_PATH = "/usr/bin/osascript"
MAX_OUTPUT_BYTES = 16384
TARGETS = ("com.apple.Terminal", "com.apple.systemevents")

# Fixed program on stdin, not caller-provided code. No Application(), event send,
# activation, UI read, pasteboard object or authorization request is involved.
HELPER_SCRIPT = r"""
ObjC.import('Foundation'); ObjC.import('AppKit');
function run() {
 const output={pid:Number($.NSProcessInfo.processInfo.processIdentifier),permissions:[]};
 function booleanCheck(resource,framework,name,nativeType) {
  const row={resource:resource,target:null,method:name};
  try {
   ObjC.import(framework);
   // Framework import alone omits some public C symbols from JXA metadata.
   ObjC.bindFunction(name,[nativeType,[]]);
   row.raw_granted=Boolean($[name]());
  } catch(error) { row.reason='public_symbol_unavailable'; }
  output.permissions.push(row);
 }
 booleanCheck('accessibility','ApplicationServices','AXIsProcessTrusted','unsigned char');
 booleanCheck('screen_capture','CoreGraphics','CGPreflightScreenCaptureAccess','bool');
 for(const bundle of ['com.apple.Terminal','com.apple.systemevents']) {
  const row={resource:'automation',target:bundle,
   method:'AEDeterminePermissionToAutomateTarget',event_class:'****',event_id:'****',
   ask_user_if_needed:false};
  try {
   const before=$.NSRunningApplication.runningApplicationsWithBundleIdentifier($(bundle));
   if(Number(before.count)!==1) {
    row.reason=Number(before.count)===0 ? 'target_not_running' : 'target_ambiguous';
   } else {
    const app=before.objectAtIndex(0), pid=Number(app.processIdentifier);
    row.target_pid=pid;
    ObjC.import('CoreServices');
    // NSAppleEventDescriptor owns this AEDesc; pass its pointer opaquely rather
    // than asking JXA to convert between incompatible struct-reference wrappers.
    ObjC.bindFunction('AEDeterminePermissionToAutomateTarget',
     ['int',['void *','unsigned int','unsigned int','unsigned char']]);
    const descriptor=$.NSAppleEventDescriptor.descriptorWithProcessIdentifier(pid);
    row.os_status=Number($.AEDeterminePermissionToAutomateTarget(
     descriptor.aeDesc,0x2a2a2a2a,0x2a2a2a2a,false));
    const after=$.NSRunningApplication.runningApplicationsWithBundleIdentifier($(bundle));
    row.target_unchanged=Number(after.count)===1 &&
     Number(after.objectAtIndex(0).processIdentifier)===pid && !Boolean(app.terminated);
   }
  } catch(error) { row.reason='public_preflight_unavailable'; }
  output.permissions.push(row);
 }
 return JSON.stringify(output);
}
"""


def _envelope(reason, *, observed_at, identity=None, permissions=None, cleanup_confirmed=True):
    return {
        "schema_version": 1,
        "scope": "completed_diagnostic_process_only",
        "status": reason,
        "observed_at": observed_at,
        "identity": identity,
        "permissions": permissions or [],
        "authorizes_future_helpers": False,
        "updates_provider_permissions": False,
        "clipboard_content_read": False,
        "permission_requested": False,
        "target_started": False,
        "cleanup_confirmed": cleanup_confirmed,
    }


def _permissions(value, pid):
    if not isinstance(value, dict) or type(value.get("pid")) is not int or value["pid"] != pid:
        raise ValueError("Helper process identity does not match")
    rows = value.get("permissions")
    if not isinstance(rows, list) or len(rows) != 4:
        raise ValueError("Incomplete helper observations")
    expected = (
        ("accessibility", None, "AXIsProcessTrusted"),
        ("screen_capture", None, "CGPreflightScreenCaptureAccess"),
        ("automation", TARGETS[0], "AEDeterminePermissionToAutomateTarget"),
        ("automation", TARGETS[1], "AEDeterminePermissionToAutomateTarget"),
    )
    result = []
    for row, (resource, target, method) in zip(rows, expected, strict=True):
        if not isinstance(row, dict) or (
            row.get("resource"),
            row.get("target"),
            row.get("method"),
        ) != (
            resource,
            target,
            method,
        ):
            raise ValueError("Unexpected helper observation")
        observed = {"resource": resource, "target": target, "method": method, "state": "unknown"}
        if resource != "automation":
            if type(row.get("raw_granted")) is bool:
                observed["raw_granted"] = row["raw_granted"]
                observed["state"] = "granted" if row["raw_granted"] else "unknown"
            elif row.get("reason") == "public_symbol_unavailable":
                observed["reason"] = row["reason"]
            else:
                raise ValueError("Invalid native Boolean observation")
        else:
            if (
                row.get("event_class") != "****"
                or row.get("event_id") != "****"
                or row.get("ask_user_if_needed") is not False
            ):
                raise ValueError("Unexpected automation preflight scope")
            observed.update(event_class="****", event_id="****", ask_user_if_needed=False)
            if row.get("reason") in {
                "target_not_running",
                "target_ambiguous",
                "public_preflight_unavailable",
            }:
                observed["reason"] = row["reason"]
            elif (
                type(row.get("target_pid")) is int
                and row["target_pid"] > 0
                and type(row.get("os_status")) is int
                and type(row.get("target_unchanged")) is bool
            ):
                observed.update(target_pid=row["target_pid"], os_status=row["os_status"])
                if row["target_unchanged"]:
                    observed["state"] = {
                        0: "granted",
                        -1743: "denied",
                        -1744: "not_determined",
                    }.get(row["os_status"], "unknown")
                else:
                    observed["reason"] = "target_changed"
            else:
                raise ValueError("Invalid target preflight observation")
        result.append(observed)
    return result


async def _read_bounded(stream):
    output = bytearray()
    while chunk := await stream.read(min(4096, MAX_OUTPUT_BYTES + 1 - len(output))):
        output.extend(chunk)
        if len(output) > MAX_OUTPUT_BYTES:
            raise ValueError("Helper output limit exceeded")
    return bytes(output)


async def inspect_helper_permissions(*, process_factory=None, clock=None, timeout=5.0):
    """Explicit diagnostic only; no cache, discovery probe or transferable grant.

    Both native Boolean checks are for osascript itself. Apple Events preflights
    use exact running PIDs and askUserIfNeeded=false. Unsupported APIs remain
    unknown. The returned identity is verified against the created child handle.
    """
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise ValueError("Invalid helper diagnostic timeout")
    if not math.isfinite(timeout) or not 0 < timeout <= 10:
        raise ValueError("Invalid helper diagnostic timeout")
    observed_at = (clock or time.time)()
    if sys.platform != "darwin":
        return _envelope("not_applicable", observed_at=observed_at)
    factory = process_factory or asyncio.create_subprocess_exec
    child = None
    result = _envelope("helper_unavailable_or_invalid", observed_at=observed_at)
    try:
        # Cancellation during process creation is handled by asyncio's subprocess
        # implementation. Once returned, the exact child is always reaped below.
        async with asyncio.timeout(timeout):
            child = await factory(
                HELPER_PATH,
                "-l",
                "JavaScript",
                "-",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                limit=MAX_OUTPUT_BYTES + 1,
            )
            child.stdin.write(HELPER_SCRIPT.encode("utf-8"))
            await child.stdin.drain()
            child.stdin.close()
            output = await _read_bounded(child.stdout)
            await child.wait()
            if child.returncode != 0:
                result = _envelope("helper_failed", observed_at=observed_at)
            else:
                rows = _permissions(json.loads(output), child.pid)
                identity = {"pid": child.pid, "executable": HELPER_PATH}
                result = _envelope(
                    "observed", observed_at=observed_at, identity=identity, permissions=rows
                )
    except TimeoutError:
        result = _envelope("helper_timeout", observed_at=observed_at)
    except (OSError, ValueError, UnicodeError):
        result = _envelope("helper_unavailable_or_invalid", observed_at=observed_at)
    finally:
        was_cancelled = isinstance(sys.exc_info()[1], asyncio.CancelledError)
        if child is not None:
            try:
                await reap_process(child, process_group=False)
            except BridgeError:
                if was_cancelled:
                    raise asyncio.CancelledError from None
                result = _envelope(
                    "helper_cleanup_unknown", observed_at=observed_at, cleanup_confirmed=False
                )
    return result
