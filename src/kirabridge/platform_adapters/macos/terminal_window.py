"""Read-only native evidence for one freshly returned Terminal.app tab.

Creation and the optional single detach remain in the existing session JXA route.
This module uses the Core's existing native worker and never sends terminal input.
"""

from __future__ import annotations

import asyncio
import hashlib
import json

from kirabridge.bridge_core.models import BridgeError


def require(value, message):
    if not value:
        raise BridgeError("session_window_unconfirmed", message)


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def logical_windows(inventory):
    windows = inventory["windows"]
    require(len({w["window_id"] for w in windows}) == len(windows), "Duplicate scripting window")
    return sorted([[w["window_id"], sorted(w["ttys"])] for w in windows])


class TerminalWindowProof:
    def __init__(self, terminal, native, principal):
        require(native is not None, "The installed native window observer is unavailable")
        self.terminal, self.native, self.principal = terminal, native, principal
        self.app = self.worker = None

    async def read(self, operation, arguments):
        for attempt in range(3):
            try:
                result = await self.native.request(operation, arguments, principal=self.principal)
                break
            except BridgeError as error:
                if (
                    operation != "accessibility.inspect"
                    or error.code != "macos_tree_changed"
                    or attempt == 2
                ):
                    raise
                await asyncio.sleep(0.05)
        helper = result["native_helper"]
        worker = (helper["pid"], helper["generation"], helper["source_commit"])
        require(self.worker in {None, worker}, "Native window observer generation changed")
        self.worker = worker
        if "application" in result:
            require(
                all(
                    result["application"][k] == self.app[k]
                    for k in ("pid", "started_at", "bundle_id")
                ),
                "Terminal application generation changed",
            )
        return result

    async def page(self, operation, arguments, key):
        result = await self.read(operation, {**arguments, "offset": 0})
        total = result["total_children" if key == "children" else "total"]
        require(
            result.get("offset") == 0
            and result.get("truncated") is False
            and type(total) is int
            and total == len(result[key]),
            "Native window inventory is incomplete",
        )
        if key == "children":
            require(
                result.get("eof") is True
                and result["helper_pid"] == self.worker[0]
                and result["worker_generation"] == self.worker[1],
                "Native AX traversal is incomplete",
            )
            if arguments.get("element_token"):
                require(
                    result["element_token"] == arguments["element_token"],
                    "Native AX target changed",
                )
        return result

    async def application(self, expected_pid=None):
        result = await self.page("apps.list", {"limit": 1000}, "applications")
        matches = [
            app for app in result["applications"] if app["bundle_id"] == "com.apple.Terminal"
        ]
        require(len(matches) <= 1, "Terminal application is ambiguous")
        if expected_pid is not None:
            require(
                len(matches) == 1 and matches[0]["pid"] == expected_pid,
                "Created Terminal owner changed",
            )
        self.app = matches[0] if matches else None

    async def ax(self, token=None):
        args = {
            "pid": self.app["pid"],
            "expected_started_at": self.app["started_at"],
            "limit": 250,
            "max_value_chars": 1,
        }
        if token:
            args.update(
                element_token=token, helper_pid=self.worker[0], worker_generation=self.worker[1]
            )
        return await self.page("accessibility.inspect", args, "children")

    async def snapshot(self):
        await self.read(
            "apps.inspect", {"pid": self.app["pid"], "expected_started_at": self.app["started_at"]}
        )
        cg = await self.page(
            "windows.list",
            {
                "owner_pid": self.app["pid"],
                "expected_start": f"{self.app['started_at']:.6f}",
                "include_titles": True,
                "include_ax": True,
                "limit": 100,
            },
            "windows",
        )
        require(cg.get("titles_redacted") is False, "Native window titles are unavailable")
        windows = [w for w in cg["windows"] if w["layer"] == 0]
        require(
            len({w["window_id"] for w in windows}) == len(windows)
            and all(
                w["on_screen"] is True
                and w["title_available"] is True
                and w["owner_pid"] == self.app["pid"]
                and w["application_start"] == f"{self.app['started_at']:.6f}"
                for w in windows
            ),
            "Native CG window inventory changed",
        )
        root = await self.ax()
        require(root["element"]["role"] == "AXApplication", "Native AX application is unavailable")
        ax_windows = [w for w in root["children"] if w["role"] == "AXWindow"]
        require(
            len(ax_windows)
            == len(windows)
            == sum(w.get("role") == "AXWindow" for w in cg["accessibility_windows"])
            and len({w["element_token"] for w in ax_windows}) == len(ax_windows),
            "Native AX/CG window inventory differs",
        )
        groups = []
        for window in ax_windows:
            observed = await self.ax(window["element_token"])
            element = observed["element"]
            require(
                element["role"] == "AXWindow"
                and element.get("subrole") == "AXStandardWindow"
                and element.get("minimized") is False
                and element.get("title_truncated") is False,
                "Native AX window is incomplete",
            )
            tabs = [child for child in observed["children"] if child["role"] == "AXTabGroup"]
            require(len(tabs) <= 1, "Native AX tab group is ambiguous")
            radios = None
            if tabs:
                members = await self.ax(tabs[0]["element_token"])
                require(
                    members["element"]["role"] == "AXTabGroup"
                    and all(
                        c["role"] in {"AXRadioButton", "AXButton"} for c in members["children"]
                    ),
                    "Native AX tab structure changed",
                )
                radios = [
                    {"token": c["element_token"], "selected": c.get("value") is True}
                    for c in members["children"]
                    if c["role"] == "AXRadioButton"
                ]
                require(
                    radios and len({r["token"] for r in radios}) == len(radios),
                    "Native AX tab membership is incomplete",
                )
            groups.append(
                {
                    "token": observed["element_token"],
                    "title": element["title"],
                    "position": element.get("position"),
                    "size": element.get("size"),
                    "radios": radios,
                }
            )
        tokens = [r["token"] for group in groups for r in group["radios"] or []]
        require(len(tokens) == len(set(tokens)), "Native AX radio appears in several groups")
        return {"cg": windows, "ax": groups}

    async def prepare(self):
        self.logical_before = logical_windows(await self.terminal.window_inventory())
        await self.application()
        require(
            self.app is not None or not self.logical_before,
            "Terminal before-inventory is unavailable",
        )
        self.before = await self.snapshot() if self.app else {"cg": [], "ax": []}
        self.app_identity = (
            await self.terminal.process_identity(self.app["pid"], detailed=True)
            if self.app
            else None
        )
        if self.logical_before and not self.before["cg"] and not self.before["ax"]:
            source = self.terminal.native_existing_app_activation_source(
                self.app["pid"], self.app_identity
            )
            activated = await self.terminal.native(source, mutation=True)
            require(
                activated.get("activation_sent") is True
                and activated.get("pid") == self.app["pid"],
                "Existing Terminal activation is unconfirmed; never repeat",
            )
            for _ in range(3):
                await asyncio.sleep(0.15)
                self.before = await self.snapshot()
                if self.before["cg"] or self.before["ax"]:
                    break
        require(
            not self.logical_before or self.before["cg"],
            "Existing Terminal surfaces are not observable",
        )

    @staticmethod
    def own(snapshot, *, nonce=None, binding=None):
        if binding is None:
            cg = [w for w in snapshot["cg"] if w["title"].count(nonce) == 1]
            ax = [w for w in snapshot["ax"] if w["title"].count(nonce) == 1]
        else:
            cg = [w for w in snapshot["cg"] if w["window_id"] == binding["cg_window_id"]]
            ax = [w for w in snapshot["ax"] if w["token"] == binding["ax_window_token"]]
        require(len(cg) == len(ax) == 1, "Created native window is missing or ambiguous")
        cg, ax = cg[0], ax[0]
        require(
            binding is not None or cg["title"] == ax["title"],
            "Created native titles are not coherent",
        )
        bounds = cg["bounds"]
        require(
            ax["position"] == [bounds["X"], bounds["Y"]]
            and ax["size"] == [bounds["Width"], bounds["Height"]],
            "Created native geometry is not coherent",
        )
        return cg, ax

    @staticmethod
    def members(group):
        return None if group["radios"] is None else [r["token"] for r in group["radios"]]

    def retained(self, before, after, *, exclude=None):
        for original in before["ax"]:
            if original is exclude:
                continue
            matches = [g for g in after["ax"] if g["token"] == original["token"]]
            require(
                len(matches) == 1 and self.members(matches[0]) == self.members(original),
                "Original native AX group was replaced",
            )

    async def logical(self, receipt):
        logical = logical_windows(await self.terminal.window_inventory())
        require(
            logical == sorted(self.logical_before + [[receipt["window_id"], [receipt["tty"]]]]),
            "Created logical TTY/window inventory changed",
        )
        return logical

    def partition(self, snapshot, own, own_cg_id):
        return fingerprint(
            {
                "cg": sorted(
                    [
                        [w["window_id"], None if w["window_id"] == own_cg_id else w["bounds"]]
                        for w in snapshot["cg"]
                    ]
                ),
                "ax": sorted(
                    [[g["token"], self.members(g)] for g in snapshot["ax"] if g is not own]
                ),
            }
        )

    async def isolate(self, receipt):
        if self.app is None:
            await self.application(receipt["app_pid"])
        require(
            self.app["pid"] == receipt["app_pid"]
            and await self.terminal.process_identity(self.app["pid"], detailed=True)
            == receipt["app_identity"],
            "Created Terminal process generation changed",
        )
        logical = await self.logical(receipt)
        before = await self.snapshot()
        own_cg, own = self.own(before, nonce=receipt["nonce"])
        binding = {"cg_window_id": own_cg["window_id"], "ax_window_token": own["token"]}
        radios = own["radios"]
        selected = [r["token"] for r in radios or [] if r["selected"]]
        if radios is not None:
            require(len(selected) == 1, "Created native tab is not uniquely selected")
        own_radio = selected[0] if selected else None
        moved = bool(radios and len(radios) > 1)
        if moved:
            original = [r["token"] for r in radios if r["token"] != own_radio]
            old_hosts = [group for group in self.before["ax"] if self.members(group) == original]
            require(
                len(old_hosts) == 1 and len(before["ax"]) == len(self.before["ax"]),
                "Shared host is not positively bound to the pre-open radio partition",
            )
            old_host = old_hosts[0]
            require(
                old_host["position"] == own["position"] and old_host["size"] == own["size"],
                "Pre-open host native layout changed",
            )
            self.retained(self.before, before, exclude=old_host)
            await self.terminal.move_created_tab(receipt)
            for attempt in range(10):
                after = await self.snapshot()
                new_cg, new_own = self.own(after, binding=binding)
                if self.members(new_own) == self.members(own) and len(after["ax"]) == len(
                    before["ax"]
                ):
                    require(attempt < 9, "Created native tab did not detach")
                    await asyncio.sleep(0.1)
                    continue
                require(
                    len(after["ax"]) == len(before["ax"]) + 1,
                    "Detached native partition is incomplete",
                )
                hosts = [g for g in after["ax"] if g is not new_own and self.members(g) == original]
                require(len(hosts) == 1, "Original host radio partition changed")
                self.retained(before, after, exclude=own)
                for old in before["cg"]:
                    if old["window_id"] != own_cg["window_id"]:
                        require(
                            any(
                                w["window_id"] == old["window_id"] and w["bounds"] == old["bounds"]
                                for w in after["cg"]
                            ),
                            "Unrelated native CG surface changed",
                        )
                host = hosts[0]
                new_hosts = [
                    w
                    for w in after["cg"]
                    if w["window_id"] not in {old["window_id"] for old in before["cg"]}
                ]
                require(
                    len(new_hosts) == 1
                    and new_hosts[0]["bounds"] == own_cg["bounds"]
                    and host["position"] == own["position"]
                    and host["size"] == own["size"],
                    "Original host native layout changed",
                )
                require(
                    new_own["radios"] is None
                    or (self.members(new_own) == [own_radio] and new_own["radios"][0]["selected"]),
                    "Detached own radio was replaced",
                )
                own_cg, own, before = new_cg, new_own, after
                break
        else:
            require(
                len(before["ax"]) == len(self.before["ax"]) + 1,
                "New standalone surface is not proven",
            )
            self.retained(self.before, before)
            require(
                own_cg["window_id"] not in {w["window_id"] for w in self.before["cg"]}
                and own["token"] not in {g["token"] for g in self.before["ax"]},
                "Standalone surface is not new",
            )
            for old in self.before["cg"]:
                require(
                    any(
                        w["window_id"] == old["window_id"] and w["bounds"] == old["bounds"]
                        for w in before["cg"]
                    ),
                    "Original native CG surface changed",
                )
        logical = await self.logical(receipt)
        return {
            **binding,
            "app": self.app,
            "worker": list(self.worker),
            "own_radio_token": own_radio,
            "own_tabbar_hidden": own["radios"] is None,
            "move_confirmed": moved,
            "logical_sha256": fingerprint(logical),
            "partition_sha256": self.partition(before, own, own_cg["window_id"]),
        }

    async def verify(self, receipt, binding):
        self.app, self.worker = binding["app"], tuple(binding["worker"])
        current = await self.snapshot()
        own_cg, own = self.own(current, binding=binding)
        require(
            self.partition(current, own, own_cg["window_id"]) == binding["partition_sha256"],
            "Bound physical partition changed",
        )
        require(
            self.members(own)
            == ([binding["own_radio_token"]] if own["radios"] is not None else None)
            and (own["radios"] is not None or binding["own_tabbar_hidden"]),
            "Bound own tab membership changed",
        )
        require(
            fingerprint(logical_windows(await self.terminal.window_inventory()))
            == binding["logical_sha256"],
            "Bound logical TTY inventory changed",
        )
        require(
            await self.terminal.process_identity(self.app["pid"], detailed=True)
            == receipt["app_identity"],
            "Bound Terminal process generation changed",
        )
