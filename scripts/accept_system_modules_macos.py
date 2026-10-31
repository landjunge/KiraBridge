"""Opt-in native leaf acceptance against an exact app and a UUID-owned Cocoa fixture.

Run with the chosen isolated Core's Python. This exercises SystemModules directly;
no HTTP/MCP daemon, live installation, permission request, clipboard or user window
content is part of this gate. Missing OS grants are findings, never fake passes.
Window screenshots require macOS 14+ and the executing native worker's existing
Screen Recording grant; Accessibility checks likewise require its existing grant.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import plistlib
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

KEY = "capture_max_side"
BUNDLE_ID = "de.netzwerkpunkt.kirabridge"
ALLOWED = frozenset(
    {
        "system.permissions",
        "system.processes",
        "system.process",
        "system.signal",
        "apps.list",
        "apps.inspect",
        "apps.launch",
        "apps.quit",
        "app.focus",
        "windows.list",
        "windows.inspect",
        "windows.focus",
        "accessibility.inspect",
        "accessibility.set",
        "accessibility.action",
        "capture.window",
        "notifications.status",
        "preferences.read",
        "preferences.write",
        "preferences.reset",
    }
)


class AcceptanceError(RuntimeError):
    pass


def require(value, message):
    if not value:
        raise AcceptanceError(message)


def atomic_json(path, value):
    temporary = path.with_suffix(".tmp")
    require(not temporary.is_symlink() and not path.is_symlink(), "Evidence symlink refused")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.chmod(0o600)
    os.replace(temporary, path)


def bounded_json(path, limit=65536):
    require(not path.is_symlink(), "Owned receipt symlink refused")
    with path.open("rb") as stream:
        value = stream.read(limit + 1)
    require(len(value) <= limit, "Owned receipt exceeds limit")
    return json.loads(value)


def compile_fixture(root, nonce, source):
    """Build harmless acceptance material only; never open/execute the resulting app."""
    app = root / "OwnedSystemFixture.app"
    binary = app / "Contents/MacOS/OwnedSystemFixture"
    binary.parent.mkdir(parents=True)
    subprocess.run(
        [
            "/usr/bin/xcrun",
            "swiftc",
            "-swift-version",
            "5",
            "-target",
            f"{os.uname().machine}-apple-macosx12.0",
            str(source),
            "-framework",
            "Cocoa",
            "-o",
            str(binary),
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )
    binary.chmod(0o755)
    (app / "Contents/Info.plist").write_bytes(
        plistlib.dumps(
            {
                "CFBundleIdentifier": "de.netzwerkpunkt.owned-system-fixture." + nonce,
                "CFBundleExecutable": binary.name,
                "CFBundleName": "OwnedSystemFixture",
                "CFBundlePackageType": "APPL",
                "CFBundleVersion": "1",
                "LSMinimumSystemVersion": "12.0",
                "NSHighResolutionCapable": True,
                "FixtureUUID": nonce,
                "FixtureStatePath": str(root / "fixture-state.json"),
                "FixtureExitPath": str(root / "fixture-exit.request"),
            }
        )
    )
    (app / "Contents/Info.plist").chmod(0o644)
    subprocess.run(
        ["/usr/bin/codesign", "--force", "--sign", "-", str(app)],
        check=True,
        capture_output=True,
        timeout=30,
    )
    subprocess.run(
        ["/usr/bin/codesign", "--verify", "--strict", str(app)],
        check=True,
        capture_output=True,
        timeout=30,
    )
    return app


def inspect_process(binary, pid):
    """Independent public-sysctl helper mode. It never enters NSApplication."""
    result = subprocess.run(
        [str(binary), "--inspect-process", str(pid)],
        capture_output=True,
        text=True,
        check=True,
        timeout=5,
    )
    value = json.loads(result.stdout)
    require(
        isinstance(value, dict) and type(value.get("pid")) is int and value["pid"] == pid,
        "Independent process probe returned another PID",
    )
    require(value.get("state") in {"present", "absent", "unknown"}, "Invalid process probe state")
    if value["state"] == "present":
        require(
            valid_start(value.get("start")) and type(value.get("uid")) is int,
            "Present process probe has no valid kernel identity",
        )
    return value


def valid_start(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9]{1,12}\.[0-9]{6}", value) is not None


def owned_window_id(fixture, receipt, nonce):
    require(
        isinstance(receipt, dict)
        and type(fixture.get("pid")) is int
        and fixture["pid"] > 0
        and receipt.get("fixture_uuid") == nonce
        and receipt.get("state") == "present"
        and receipt.get("phase") == "ready"
        and type(receipt.get("pid")) is int
        and receipt["pid"] == fixture["pid"]
        and type(receipt.get("uid")) is int
        and receipt["uid"] == os.getuid()
        and valid_start(receipt.get("start"))
        and type(receipt.get("window_id")) is int
        and 0 < receipt["window_id"] <= 2**32 - 1,
        "Owned ready receipt has no exact window identity",
    )
    return receipt["window_id"]


def select_owned_window(result, fixture, receipt, nonce):
    """None means only that our exact ready window is not yet in the CG inventory."""
    wanted = owned_window_id(fixture, receipt, nonce)
    rows = result.get("windows")
    require(
        isinstance(rows, list)
        and len(rows) <= 100
        and result.get("truncated") is False
        and type(result.get("total")) is int
        and result["total"] == len(rows)
        and result.get("offset") == 0,
        "Owned window inventory is incomplete or malformed",
    )
    require(
        isinstance(result.get("revision"), str)
        and re.fullmatch(r"[a-f0-9]{64}", result["revision"]),
        "Owned window inventory revision unavailable",
    )
    seen, selected = set(), None
    expected_start = f"{fixture['started_at']:.6f}"
    for row in rows:
        require(
            isinstance(row, dict)
            and type(row.get("window_id")) is int
            and 0 < row["window_id"] <= 2**32 - 1
            and row["window_id"] not in seen
            and type(row.get("owner_pid")) is int
            and row["owner_pid"] == fixture["pid"]
            and row.get("application_start") == expected_start
            and type(row.get("layer")) is int
            and isinstance(row.get("revision"), str)
            and re.fullmatch(r"[a-f0-9]{64}", row["revision"]),
            "Owned window inventory has a foreign, duplicate or changed identity",
        )
        seen.add(row["window_id"])
        if row["window_id"] == wanted:
            require(
                row["layer"] == 0 and row.get("on_screen") is True,
                "Owned ready window is not an on-screen application window",
            )
            selected = row
    return selected


def original_absent(observed, identity):
    if (
        type(identity.get("pid")) is not int
        or identity["pid"] <= 0
        or not valid_start(identity.get("start"))
        or type(observed.get("pid")) is not int
        or observed["pid"] != identity["pid"]
    ):
        return False
    if observed.get("state") == "absent":
        return True
    return (
        observed.get("state") == "present"
        and valid_start(observed.get("start"))
        and observed["start"] != identity["start"]
    )


def package_source_identity(package):
    digest, count = hashlib.sha256(), 0
    for path in sorted(package.rglob("*.py")):
        require(not path.is_symlink(), "Imported package source symlink refused")
        digest.update(path.relative_to(package).as_posix().encode() + b"\0" + path.read_bytes())
        count += 1
    return {
        "python_file_count": count,
        "python_source_sha256": digest.hexdigest(),
        "hash_format": "sorted relative path + NUL + Python source bytes",
    }


def restorable_preference(snapshot):
    require(snapshot.get("key") == KEY, "Unexpected preference key")
    require(type(snapshot.get("exists")) is bool, "Unknown preference presence")
    if snapshot["exists"]:
        require(
            type(snapshot.get("value")) is int and 64 <= snapshot["value"] <= 4096,
            "Existing preference is not safely restorable; no mutation attempted",
        )
    return snapshot


def preference_equal(left, right):
    return left.get("exists") == right.get("exists") and (
        not left.get("exists") or left.get("value") == right.get("value")
    )


def authorize_owned(operation, arguments, fixture, app):
    require(operation in ALLOWED, "Operation outside acceptance allowlist")
    if operation.startswith("preferences."):
        require(arguments.get("key") == KEY, "Only the restorable capture preference is allowed")
    if operation == "apps.launch":
        require(
            Path(arguments["app_path"]).resolve() == app.resolve(), "Foreign app launch refused"
        )
    if operation in {
        "apps.inspect",
        "apps.quit",
        "accessibility.inspect",
        "accessibility.set",
        "accessibility.action",
        "system.process",
        "system.signal",
    }:
        require(
            fixture is not None and arguments.get("pid") == fixture["pid"],
            "Foreign process/AX target refused",
        )
    if operation in {"app.focus", "windows.inspect", "windows.focus", "capture.window"}:
        require(
            fixture is not None and arguments.get("expected_pid") == fixture["pid"],
            "Foreign window target refused",
        )
    if operation == "windows.list":
        require(
            fixture is not None and arguments.get("owner_pid") == fixture["pid"],
            "Unscoped window enumeration refused",
        )


class Harness:
    def __init__(self, args):
        self.args = args
        self.root = args.root.resolve()
        self.nonce = uuid.uuid4().hex
        self.fixture = self.receipt = self.fixture_app = self.modules = None
        self.launch_attempted = False
        self.preference_before = None
        self.preference_written = None
        self.counter = 0
        self.evidence = {
            "schema": "kirabridge.native-system-acceptance.v1",
            "fixture_uuid": self.nonce,
            "scope": "Direct SystemModules in recorded Python; no live Core HTTP/MCP claim",
            "live_service_used": False,
            "capture_minimum_macos": "14.0",
            "caller_pid": os.getpid(),
            "parent_pid": os.getppid(),
            "checks": [],
            "trace": [],
            "cleanup": {"complete": False},
            "forbidden_operations_executed": [],
            "started_at": time.time(),
        }

    def save(self):
        atomic_json(self.root / "evidence.json", self.evidence)

    def check(self, name, state, **details):
        self.evidence["checks"].append({"name": name, "state": state, **details})
        self.save()

    async def call(self, operation, arguments):
        authorize_owned(operation, arguments, self.fixture, self.fixture_app)
        self.counter += 1
        trace = {
            "operation": operation,
            "sequence": self.counter,
            "task_context": f"accept_{self.nonce}_{self.counter}",
        }
        self.evidence["trace"].append(trace)
        try:
            result = await self.modules.execute(
                operation,
                arguments,
                principal="owned-system-acceptance",
                task_id=trace["task_context"],
            )
            trace.update(state="returned", native_helper=result.get("native_helper"))
            return result
        except BaseException as error:
            trace.update(state="error", code=getattr(error, "code", type(error).__name__))
            raise
        finally:
            self.save()

    async def stage(self, name, action):
        try:
            details = await action()
            self.check(name, "passed", **(details or {}))
        except Exception as error:
            self.check(
                name,
                "failed",
                code=getattr(error, "code", type(error).__name__),
                detail=str(error)[:300],
            )

    def app_target(self):
        return {"pid": self.fixture["pid"], "expected_started_at": self.fixture["started_at"]}

    def window_target(self):
        return {
            "expected_pid": self.fixture["pid"],
            "expected_start": f"{self.fixture['started_at']:.6f}",
        }

    async def wait_receipt(self):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            try:
                value = bounded_json(self.root / "fixture-state.json")
                require(
                    value.get("fixture_uuid") == self.nonce and value.get("state") == "present",
                    "Receipt is not owned by this fixture",
                )
                require(
                    value.get("pid") == self.fixture["pid"] and value.get("uid") == os.getuid(),
                    "Receipt PID/UID differs from launched fixture",
                )
                require(
                    re.fullmatch(r"[0-9]{1,12}\.[0-9]{6}", value.get("start", "")),
                    "Fixture kernel start token unavailable",
                )
                require(value.get("phase") == "ready", "Fixture did not report ready")
                owned_window_id(self.fixture, value, self.nonce)
                self.receipt = value
                return
            except FileNotFoundError:
                await asyncio.sleep(0.1)
        raise AcceptanceError("Owned fixture did not produce its identity receipt")

    async def owned_window(self):
        wanted = owned_window_id(self.fixture, self.receipt, self.nonce)
        deadline = time.monotonic() + 8
        probes = self.evidence.setdefault("window_probes", [])
        while time.monotonic() < deadline:
            try:
                async with asyncio.timeout(deadline - time.monotonic()):
                    result = await self.call(
                        "windows.list",
                        {
                            "owner_pid": self.fixture["pid"],
                            "expected_start": self.window_target()["expected_start"],
                            "include_titles": False,
                            "limit": 100,
                        },
                    )
            except TimeoutError:
                break
            rows = result.get("windows")
            probes.append(
                {
                    "expected_window_id": wanted,
                    "owner_pid": self.fixture["pid"],
                    "row_count": len(rows) if isinstance(rows, list) else None,
                    "truncated": result.get("truncated"),
                    "revision": result.get("revision"),
                    "owned_rows": [
                        {key: row.get(key) for key in ("window_id", "layer", "revision")}
                        for row in rows[:100]
                        if isinstance(row, dict)
                        and type(row.get("owner_pid")) is int
                        and row["owner_pid"] == self.fixture["pid"]
                    ]
                    if isinstance(rows, list)
                    else [],
                    "probe_rows_capped": isinstance(rows, list) and len(rows) > 100,
                }
            )
            self.save()
            row = select_owned_window(result, self.fixture, self.receipt, self.nonce)
            if row is not None and time.monotonic() < deadline:
                return row
            await asyncio.sleep(min(0.1, max(0, deadline - time.monotonic())))
        raise AcceptanceError(f"Owned ready window {wanted} missing before 8-second deadline")

    async def windows(self):
        row = await self.owned_window()
        target = {
            **self.window_target(),
            "window_id": row["window_id"],
            "expected_revision": row["revision"],
        }
        inspected = await self.call("windows.inspect", target)
        require(
            inspected["window"]["window_id"] == row["window_id"]
            and inspected["window"]["owner_pid"] == self.fixture["pid"]
            and inspected["window"]["application_start"] == self.window_target()["expected_start"]
            and inspected["window"]["revision"] == row["revision"],
            "Window inspect identity changed",
        )
        await self.call("app.focus", self.window_target())
        return {"window_id": row["window_id"], "owner_pid": row["owner_pid"]}

    async def ax(self):
        await self.call(
            "windows.focus",
            {
                **self.window_target(),
                "ax_identifier": f"fixture-{self.nonce}-window",
            },
        )
        wanted = {
            f"fixture-{self.nonce}-{name}" for name in ("text", "secure", "button", "counter")
        }
        found, queue, seen = {}, [None], set()
        base = self.app_target()
        helper = None
        while queue and len(seen) < 128 and wanted - set(found):
            token = queue.pop(0)
            if token in seen:
                continue
            seen.add(token)
            arguments = dict(base)
            if token is not None:
                arguments.update(
                    element_token=token, helper_pid=helper[0], worker_generation=helper[1]
                )
            result = await self.call("accessibility.inspect", arguments)
            helper = result["helper_pid"], result["worker_generation"]
            require(not result.get("truncated"), "Fixture AX child page unexpectedly truncated")
            for child in result["children"]:
                identifier = child.get("identifier")
                if identifier in wanted:
                    require(
                        identifier not in found or found[identifier] == child["element_token"],
                        "Fixture AX identifier is ambiguous",
                    )
                    found[identifier] = child["element_token"]
                queue.append(child["element_token"])
        require(set(found) == wanted, "Owned AX controls were not all discovered")

        async def inspect(name):
            return await self.call(
                "accessibility.inspect",
                {
                    **base,
                    "element_token": found[f"fixture-{self.nonce}-{name}"],
                    "helper_pid": helper[0],
                    "worker_generation": helper[1],
                },
            )

        text = await inspect("text")
        require(text.get("value") == "owned-text-" + self.nonce, "Unexpected initial fixture text")
        changed = "owned-changed-" + self.nonce
        await self.call(
            "accessibility.set",
            {
                **base,
                "element_token": text["element_token"],
                "helper_pid": helper[0],
                "worker_generation": helper[1],
                "expected_revision": text["element"]["revision"],
                "attribute": "value",
                "value": changed,
            },
        )
        require((await inspect("text")).get("value") == changed, "AX set readback differs")
        button = await inspect("button")
        await self.call(
            "accessibility.action",
            {
                **base,
                "element_token": button["element_token"],
                "helper_pid": helper[0],
                "worker_generation": helper[1],
                "expected_revision": button["element"]["revision"],
                "action": "press",
            },
        )
        require(
            (await inspect("counter")).get("value") == "owned-count-1",
            "Button action readback differs",
        )
        secure = await inspect("secure")
        require(
            secure["element"].get("secure_value_redacted") is True and "value" not in secure,
            "Secure fixture field leaked a value",
        )
        require("synthetic-secret-" + self.nonce not in json.dumps(secure), "Secure marker leaked")
        return {"text_readback_verified": True, "button_count": 1, "secure_redacted": True}

    async def capture(self, filename="fixture-window.png", max_side=1024):
        from kirabridge.image_manager import validate_png

        row = await self.owned_window()
        args = {
            **self.window_target(),
            "window_id": row["window_id"],
            "expected_revision": row["revision"],
        }
        if max_side is not None:
            args["max_side"] = max_side
        result = await self.call("capture.window", args)
        require(
            result["target"]["owner_pid"] == self.fixture["pid"]
            and result["target"]["window_id"] == row["window_id"],
            "Capture returned a foreign target",
        )
        data = base64.b64decode(result["image_data"], validate=True)
        width, height = validate_png(data)
        require(
            hashlib.sha256(data).hexdigest() == result["content_sha256"], "Capture hash mismatch"
        )
        require(len(data) == result["bytes"], "Capture byte count mismatch")
        (self.root / filename).write_bytes(data)
        (self.root / filename).chmod(0o600)
        return {
            "path": filename,
            "width": width,
            "height": height,
            "sha256": result["content_sha256"],
            "owned_window_id": row["window_id"],
        }

    async def restore_preference(self):
        if self.preference_before is None:
            return True
        current = (await self.call("preferences.read", {"key": KEY}))["preference"]
        original = self.preference_before
        if preference_equal(current, original):
            return True
        require(
            not current["exists"] or current.get("value") == self.preference_written,
            "Preference changed externally; restoration refused to avoid overwriting it",
        )
        if original["exists"]:
            await self.call(
                "preferences.write",
                {"key": KEY, "value": original["value"], "expected_revision": current["revision"]},
            )
        else:
            await self.call(
                "preferences.reset", {"key": KEY, "expected_revision": current["revision"]}
            )
        final = (await self.call("preferences.read", {"key": KEY}))["preference"]
        require(preference_equal(final, original), "Preference restoration readback differs")
        return True

    async def preferences(self):
        before = restorable_preference(
            (await self.call("preferences.read", {"key": KEY}))["preference"]
        )
        self.preference_before = before
        self.preference_written = 128 if before.get("value") != 128 else 256
        self.evidence["preference_original"] = before
        self.save()
        try:
            await self.call(
                "preferences.write",
                {
                    "key": KEY,
                    "value": self.preference_written,
                    "expected_revision": before["revision"],
                },
            )
            written = (await self.call("preferences.read", {"key": KEY}))["preference"]
            require(
                written.get("value") == self.preference_written, "Preference write readback differs"
            )
            await self.call(
                "preferences.reset", {"key": KEY, "expected_revision": written["revision"]}
            )
            reset = (await self.call("preferences.read", {"key": KEY}))["preference"]
            require(reset["exists"] is False, "Preference reset did not remove value")
        finally:
            await self.restore_preference()
        return {"key": KEY, "restored": True, "appearance_and_window_preferences_touched": False}

    async def processes(self):
        inventory = await self.call("system.processes", {"limit": 500})
        require(inventory.get("include_system") is False, "Process inventory default scope differs")
        selected = await self.call(
            "system.process",
            {
                "pid": self.fixture["pid"],
                "expected_start": self.receipt["start"],
            },
        )
        row = selected["process"]
        require(
            row["pid"] == self.fixture["pid"]
            and row["uid"] == os.getuid()
            and row["start"] == self.receipt["start"],
            "Process inspect identity differs",
        )
        self.evidence["fixture_process"] = row
        return {
            "inventory_count": inventory["total"],
            "inventory_complete": inventory["observation_complete"],
            "fixture_pid": row["pid"],
            "path_available": row["path_available"],
        }

    async def signal_fixture(self):
        row = self.evidence.get("fixture_process", {})
        binary = self.fixture_app / "Contents/MacOS/OwnedSystemFixture"
        if not (
            row.get("path_available")
            and Path(row.get("path", "")).resolve() == binary.resolve()
            and row.get("start") == self.receipt["start"]
            and row.get("uid") == os.getuid()
        ):
            self.check(
                "owned_signal",
                "refused",
                reason="Public owned-process executable binding unavailable",
            )
            return
        try:
            result = await self.call(
                "system.signal",
                {
                    "pid": self.fixture["pid"],
                    "expected_start": self.receipt["start"],
                    "signal": "TERM",
                },
            )
            require(result.get("signal_accepted") is True, "Signal not accepted")
            self.check(
                "owned_signal",
                "passed",
                termination_claimed=False,
                scope="One TERM to exact UUID-owned fixture only; no replay",
            )
        except Exception as error:
            self.check(
                "owned_signal",
                "refused" if getattr(error, "code", "").startswith("macos_process_") else "failed",
                code=getattr(error, "code", type(error).__name__),
                replayed=False,
            )

    async def cleanup(self):
        details = self.evidence["cleanup"]
        try:
            # Only our random-UUID app watches this private request file.
            (self.root / "fixture-exit.request").write_text(self.nonce)
            (self.root / "fixture-exit.request").chmod(0o600)
            if self.launch_attempted and self.receipt is None:
                try:
                    receipt = bounded_json(self.root / "fixture-state.json")
                    require(
                        receipt.get("fixture_uuid") == self.nonce
                        and receipt.get("uid") == os.getuid()
                        and type(receipt.get("pid")) is int
                        and receipt["pid"] > 0
                        and isinstance(receipt.get("start"), str)
                        and re.fullmatch(r"[0-9]{1,12}\.[0-9]{6}", receipt["start"]),
                        "Unknown launch receipt cannot authorize cleanup",
                    )
                    if self.fixture is not None:
                        require(
                            self.fixture["pid"] == receipt["pid"], "Cleanup receipt PID differs"
                        )
                    else:
                        self.fixture = {"pid": receipt["pid"]}
                    self.receipt = receipt
                except (OSError, ValueError, AcceptanceError):
                    details["launch_identity_unconfirmed"] = True
            if self.preference_before is not None:
                try:
                    details["preference_restored"] = await self.restore_preference()
                except Exception as error:
                    details["preference_restored"] = False
                    details["preference_error"] = getattr(error, "code", type(error).__name__)
            if self.fixture and self.receipt:
                binary = self.fixture_app / "Contents/MacOS/OwnedSystemFixture"
                before = await asyncio.to_thread(inspect_process, binary, self.fixture["pid"])
                if not original_absent(before, self.receipt):
                    require(
                        before.get("start") == self.receipt["start"]
                        and before.get("uid") == os.getuid(),
                        "Owned fixture cleanup identity is unknown",
                    )
                    if "started_at" in self.fixture:
                        try:
                            await self.call("apps.quit", self.app_target())
                        except Exception as error:
                            details["quit_code"] = getattr(error, "code", type(error).__name__)
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    observed = await asyncio.to_thread(inspect_process, binary, self.fixture["pid"])
                    if original_absent(observed, self.receipt):
                        details["fixture_absent_independently"] = True
                        break
                    await asyncio.sleep(0.1)
                else:
                    details["fixture_absent_independently"] = False
            else:
                details["fixture_absent_independently"] = not self.launch_attempted
        except Exception as error:
            details["error"] = getattr(error, "code", type(error).__name__)
        finally:
            if self.modules is not None:
                child = self.modules.transport.process
                try:
                    await self.modules.close()
                    details["worker_reaped"] = child is None or child.returncode is not None
                except Exception as error:
                    details["worker_reaped"] = False
                    details["worker_error"] = getattr(error, "code", type(error).__name__)
            details["complete"] = (
                details.get("fixture_absent_independently") is True
                and details.get("preference_restored", True) is True
                and details.get("worker_reaped", True) is True
            )
            self.save()

    async def run(self):
        require(not self.root.exists() and not self.root.is_symlink(), "Use a new acceptance root")
        self.root.mkdir(parents=True, mode=0o700)
        self.root.chmod(0o700)
        self.save()
        try:
            import kirabridge
            from kirabridge.platform_adapters.macos.system_identity import installed_native_contract
            from kirabridge.platform_adapters.macos.system_transport import SystemModules

            app = self.args.app.resolve(strict=True)
            metadata = plistlib.loads((app / "Contents/Info.plist").read_bytes())
            commit = metadata.get("KiraBridgeSourceCommit", "")
            require(re.fullmatch(r"[a-f0-9]{40}", commit), "Native app source commit unavailable")
            if self.args.expected_commit:
                require(commit == self.args.expected_commit, "Native app is from another commit")
            binary = app / "Contents/MacOS/KiraBridge"
            binary_hash = hashlib.sha256(binary.read_bytes()).hexdigest()
            await asyncio.to_thread(
                subprocess.run,
                ["/usr/bin/codesign", "--verify", "--strict", str(app)],
                check=True,
                capture_output=True,
                timeout=30,
            )
            core_contract = installed_native_contract(kirabridge.__file__)
            if core_contract.get("expected_commit") is not None:
                require(
                    core_contract.get("expected_commit") == commit
                    and Path(core_contract.get("app_path", "")).resolve() == app
                    and core_contract.get("expected_binary_sha256") == binary_hash,
                    "Imported installed Core and native app manifest do not match",
                )
            self.evidence["source"] = {
                "python": sys.executable,
                "package": str(Path(kirabridge.__file__).resolve()),
                "version": kirabridge.__version__,
                "app": str(app),
                "commit": commit,
                "binary_sha256": binary_hash,
                "installed_core_contract": core_contract.get("expected_commit"),
                **package_source_identity(Path(kirabridge.__file__).resolve().parent),
                "fixture_source_sha256": hashlib.sha256(
                    self.args.fixture_source.read_bytes()
                ).hexdigest(),
            }
            self.fixture_app = await asyncio.to_thread(
                compile_fixture, self.root, self.nonce, self.args.fixture_source
            )
            fixture_binary = self.fixture_app / "Contents/MacOS/OwnedSystemFixture"
            self.evidence["caller_identity"] = inspect_process(fixture_binary, os.getpid())
            self.evidence["parent_identity"] = inspect_process(fixture_binary, os.getppid())
            self.modules = SystemModules(
                app_path=app, expected_commit=commit, expected_binary_sha256=binary_hash
            )
            require(
                self.modules.snapshot_metadata().get("available"),
                "Native protocol metadata is unavailable",
            )
            permissions = await self.call("system.permissions", {})
            require(
                permissions.get("permission_requested") is False,
                "Permission read requested an OS grant",
            )
            self.check(
                "permissions_read_only",
                "passed",
                **{
                    key: permissions.get(key)
                    for key in ("actor_pid", "accessibility_granted", "screen_capture_granted")
                },
            )
            apps = await self.call("apps.list", {"limit": 1000})
            self.evidence["original_ui_pids"] = [
                {"pid": row["pid"], "started_at": row["started_at"], "app_path": row["app_path"]}
                for row in apps["applications"]
                if row.get("bundle_id") == BUNDLE_ID
                and row.get("pid") != permissions.get("actor_pid")
            ]
            self.launch_attempted = True
            launched = await self.call("apps.launch", {"app_path": str(self.fixture_app)})
            candidate = launched["application"]
            require(
                Path(candidate["app_path"]).resolve() == self.fixture_app.resolve(),
                "Launch returned a foreign app",
            )
            require(
                candidate.get("bundle_id") == "de.netzwerkpunkt.owned-system-fixture." + self.nonce,
                "Launched app UUID differs",
            )
            self.fixture = candidate
            self.evidence["fixture_application"] = self.fixture
            await self.wait_receipt()
            await self.call("apps.inspect", self.app_target())
            await self.stage("owned_window_list_inspect_focus", self.windows)
            if permissions.get("accessibility_granted") is True:
                await self.stage("owned_ax_set_press_secure", self.ax)
            else:
                self.check(
                    "owned_ax_set_press_secure",
                    "blocked",
                    reason="Native worker Accessibility grant absent; no request made",
                )
            if permissions.get("screen_capture_granted") is True:
                await self.stage("owned_window_capture_png", self.capture)
            else:
                self.check(
                    "owned_window_capture_png",
                    "blocked",
                    reason="Native worker Screen Recording grant absent; no request made",
                )
            await self.stage("own_preference_write_reset_restore", self.preferences)
            await self.stage("public_process_inventory_inspect", self.processes)
            await self.stage("notifications_status_read_only", lambda: self.notification_status())
            await self.signal_fixture()
        except BaseException as error:
            self.check(
                "harness",
                "failed",
                code=getattr(error, "code", type(error).__name__),
                detail=str(error)[:300],
            )
        finally:
            await self.cleanup()
            self.evidence["finished_at"] = time.time()
            self.evidence["fully_verified"] = self.evidence["cleanup"]["complete"] and all(
                row["state"] == "passed" for row in self.evidence["checks"]
            )
            self.save()
        return self.evidence

    async def notification_status(self):
        result = await self.call("notifications.status", {})
        require(
            result.get("requests_authorization") is False,
            "Notification status requested authorization",
        )
        return {
            "authorization_status": result["authorization_status"],
            "notification_posted": False,
        }


def parser():
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--app", type=Path, required=True)
    value.add_argument("--root", type=Path, required=True)
    value.add_argument("--allow-owned-fixture", action="store_true", required=True)
    value.add_argument("--expected-commit")
    value.add_argument(
        "--fixture-source",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "integrations/acceptance/SystemFixture.swift",
    )
    return value


def main():
    args = parser().parse_args()
    require(sys.platform == "darwin", "Native acceptance requires macOS")
    evidence = asyncio.run(Harness(args).run())
    print(
        json.dumps(
            {
                "fully_verified": evidence["fully_verified"],
                "evidence": str(args.root / "evidence.json"),
                "scope": evidence["scope"],
                "cleanup": evidence["cleanup"],
            },
            indent=2,
        )
    )
    return 0 if evidence["fully_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
