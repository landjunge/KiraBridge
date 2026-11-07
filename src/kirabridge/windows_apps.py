"""Windows application list, visible launch and focus. Window control stays shared."""

from __future__ import annotations

import sys

from pydantic import Field, model_validator

from kirabridge.bridge_core.models import BridgeError, Input
from kirabridge.platform_adapters.windows.apps import (
    Win32ProcessLauncher,
    assert_visible_plan,
    launch_plan,
)
from kirabridge.platform_adapters.windows.windows import WindowIdentity, WindowsWindows


class WindowsAppListInput(Input):
    limit: int = Field(default=32, ge=1, le=64, strict=True)


class WindowsAppLaunchInput(Input):
    image: str = Field(min_length=8, max_length=260, strict=True)
    argv: list[str] = Field(default_factory=list, max_length=8)
    console: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def visible_plan(self):
        launch_plan(self.image, tuple(self.argv), console=self.console)
        return self


class WindowsAppFocusInput(Input):
    pid: str = Field(pattern=r"^[1-9][0-9]{0,9}$", strict=True)
    process_created_100ns: str = Field(pattern=r"^[1-9][0-9]{0,19}$", strict=True)
    hwnd: str | None = Field(default=None, pattern=r"^[1-9][0-9]{0,19}$", strict=True)


WINDOWS_APP_INPUTS = {
    "windows.app.list": WindowsAppListInput,
    "windows.app.launch": WindowsAppLaunchInput,
    "windows.app.focus": WindowsAppFocusInput,
}


def group_apps(windows: list[dict], limit: int) -> list[dict]:
    grouped = []
    positions = {}
    for window in windows:
        target = window["target"]
        key = (target["pid"], target["process_created_100ns"])
        item = positions.get(key)
        if item is None:
            if len(grouped) >= limit:
                continue
            item = {
                "pid": target["pid"],
                "process_created_100ns": target["process_created_100ns"],
                "windows": [],
            }
            positions[key] = item
            grouped.append(item)
        item["windows"].append(target["hwnd"])
    return grouped


class WindowsAppManager:
    def __init__(self, authorize, desktop_input, *, windows_factory=WindowsWindows, host=None):
        self.authorize, self.desktop_input = authorize, desktop_input
        self.windows_factory, self.windows = windows_factory, None
        self.launcher = None
        self.host = sys.platform if host is None else host

    def require_windows(self):
        if self.host != "win32":
            raise BridgeError("unsupported_platform", "Windows application tasks require Windows")
        if self.windows is None:
            self.windows = self.windows_factory()
        return self.windows

    def catalog(self, decide):
        return [
            {
                "operation": operation,
                "provider_id": "windows.apps.v1",
                "host_platform": self.host,
                "available": self.host == "win32",
                "eligible_for_submission": self.host == "win32" and decide(operation)["authorized"],
                "policy": decide(operation),
                "scope": (
                    "Visible top-level windows grouped by process; launch uses CreateProcess "
                    "with a shown window and never a hidden console"
                ),
            }
            for operation in WINDOWS_APP_INPUTS
        ]

    async def execute(self, task, args, running, progress=None):
        operation, principal = task["operation"], task["principal"]
        self.authorize(principal, operation)
        backend = self.require_windows()
        async with self.desktop_input.transaction() as turn:
            await running({"evidence_type": "windows_app_started", "automatic_retry": False})
            if operation == "windows.app.list":
                listed = backend.list(args.limit)
                return {
                    "apps": group_apps(listed["windows"], args.limit),
                    "truncated": listed["truncated"],
                    "provider": "windows.apps.v1",
                    "effect_attempted": False,
                }
            if operation == "windows.app.launch":
                plan = launch_plan(args.image, tuple(args.argv), console=args.console)
                assert_visible_plan(plan)

                def before_launch():
                    self.authorize(principal, operation)
                    self.authorize(principal, "windows.app.list")
                    turn.mark_attempted()

                before_launch()
                if self.launcher is None:
                    self.launcher = Win32ProcessLauncher()
                result = self.launcher.launch(plan)
                return {**result, "provider": "windows.apps.v1"}
            listed = backend.list(64)
            matches = [
                window
                for window in listed["windows"]
                if window["target"]["pid"] == args.pid
                and window["target"]["process_created_100ns"] == args.process_created_100ns
                and (args.hwnd is None or window["target"]["hwnd"] == args.hwnd)
            ]
            if len(matches) != 1:
                raise BridgeError(
                    "windows_app_target_ambiguous",
                    "Focus needs exactly one visible window for that process",
                )
            target = WindowIdentity.from_wire(matches[0]["target"])

            def before_focus():
                self.authorize(principal, operation)
                self.authorize(principal, "windows.app.list")
                self.authorize(principal, "windows.window.control")
                turn.mark_attempted()

            result = backend.control(target, "activate", before_effect=before_focus)
            return {**result, "provider": "windows.apps.v1", "app_pid": args.pid}
