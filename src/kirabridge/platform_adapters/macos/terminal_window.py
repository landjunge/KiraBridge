"""Read-only native evidence for one freshly returned Terminal.app tab.

Creation and the optional single detach remain in the existing session JXA route.
This module uses the Core's existing native worker and never sends terminal input.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import time

from kirabridge.bridge_core.models import BridgeError
from kirabridge.timing import timed_async


def require(value, message, *, observation=None):
    if not value:
        error = BridgeError("session_window_unconfirmed", message)
        if observation is not None:
            error.window_observation = observation
        raise error


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def geometry_pair(value):
    """Diagnostics retain finite coordinates, never arbitrary native values."""
    return (
        list(value)
        if isinstance(value, (list, tuple))
        and len(value) == 2
        and all(type(item) in (int, float) and math.isfinite(item) for item in value)
        else None
    )


def logical_windows(inventory):
    windows = inventory["windows"]
    require(len({w["window_id"] for w in windows}) == len(windows), "Duplicate scripting window")
    return sorted([[w["window_id"], sorted(w["ttys"])] for w in windows])


class TerminalWindowProof:
    def __init__(self, terminal, native, principal):
        require(native is not None, "The installed native window observer is unavailable")
        self.terminal, self.native, self.principal = terminal, native, principal
        self.app = self.worker = None
        self.phase, self.phase_started = "initial", time.monotonic()
        self.phase_timings = []
        self.preparation_started = self.prepared = self.consumed = False

    def mark_phase(self, phase):
        now = time.monotonic()
        self.phase_timings.append(
            {"phase": self.phase, "elapsed_ms": round((now - self.phase_started) * 1000, 3)}
        )
        self.phase, self.phase_started = phase, now

    def phase_observation(self):
        return {
            "phase": self.phase,
            "elapsed_ms": round((time.monotonic() - self.phase_started) * 1000, 3),
            "completed": list(self.phase_timings),
        }

    async def read(self, operation, arguments):
        for attempt in range(3):
            try:
                result = await self.native.request(operation, arguments, principal=self.principal)
                break
            except BridgeError as error:
                if (
                    operation not in {"accessibility.inspect", "windows.list"}
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
            len({w["element_token"] for w in ax_windows}) == len(ax_windows),
            "Duplicate native AX window identity",
        )
        ax_list_count = sum(w.get("role") == "AXWindow" for w in cg["accessibility_windows"])

        def inventory_pending(visible_count=None, minimized_count=None):
            error = BridgeError(
                "session_window_inventory_pending",
                f"Native AX/CG window inventory differs (CG={len(windows)}, "
                f"AX={len(ax_windows)}, AX-list={ax_list_count})",
            )
            observation = {
                "phase": "native_window_inventory",
                "cg_window_count": len(windows),
                "ax_window_count": len(ax_windows),
                "ax_list_window_count": ax_list_count,
                "visible_ax_window_count": visible_count,
                "minimized_ax_window_count": minimized_count,
            }
            error.window_observation = observation
            error.provider_error = {"window_observation": observation}
            return error

        if len(ax_windows) != ax_list_count:
            raise inventory_pending()
        groups, minimized = [], []
        for window in ax_windows:
            observed = await self.ax(window["element_token"])
            element = observed["element"]
            require(element["role"] == "AXWindow", "Native AX window role changed")
            if element.get("minimized") is True:
                # A minimized AXDialog can legitimately have no on-screen CG
                # surface. Preserve only its anchor; never adopt or restore it.
                minimized.append({"token": observed["element_token"], "minimized": True})
                continue
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
        if len(groups) != len(windows):
            raise inventory_pending(len(groups), len(minimized))
        return {"cg": windows, "ax": groups, "minimized": minimized}

    @timed_async("terminal_window_prepare_readonly")
    async def prepare_readonly(self):
        require(not self.preparation_started and not self.consumed, "Window proof is one-shot")
        self.preparation_started = True
        self.mark_phase("prepare_readonly")
        self.logical_before = logical_windows(await self.terminal.window_inventory())
        await self.application()
        require(
            self.app is not None or not self.logical_before,
            "Terminal before-inventory is unavailable",
        )
        self.before = await self.snapshot() if self.app else {"cg": [], "ax": [], "minimized": []}
        self.app_identity = (
            await self.terminal.process_identity(self.app["pid"], detailed=True)
            if self.app
            else None
        )
        self.prepared = True
        self.mark_phase("prepared")

    async def prepare(self):
        # Compatibility for direct callers: the coordinator separates the pure
        # reads, while all activation effects remain in its real creation turn.
        await self.prepare_readonly()
        await self.activate_prepared()

    @timed_async("terminal_window_activate_prepared")
    async def activate_prepared(self):
        require(self.prepared and not self.consumed, "Prepared window proof is unavailable")
        self.consumed = True
        if (
            self.logical_before
            and not self.before["cg"]
            and not self.before["ax"]
            and not self.before["minimized"]
        ):
            self.mark_phase("activate_existing")
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
            not self.logical_before or self.before["cg"] or self.before["minimized"],
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
        require(
            sorted(item["token"] for item in before.get("minimized", []))
            == sorted(item["token"] for item in after.get("minimized", [])),
            "Original minimized native AX anchors changed",
        )
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
                "minimized": sorted(item["token"] for item in snapshot.get("minimized", [])),
            }
        )

    def bind_shared_host(self, current, own_cg, own, original):
        """Bind the original tabs, rather than assuming their AX wrapper is permanent.

        Terminal can replace its AXWindow when selecting the newly created tab.
        The retained, ordered child references are the continuity evidence here;
        titles and equal geometry alone never establish that transition.
        """
        hosts = [group for group in self.before["ax"] if self.members(group) == original]
        hidden_host = False
        if not hosts and len(original) == 1:
            # A singleton with its tab bar hidden has no AXRadioButton yet.
            # Bind only the unique missing AX window in an otherwise complete,
            # retained partition. The old AX anchor must return after detach;
            # this provisional observation never authorizes command dispatch.
            current_tokens = {group["token"] for group in current["ax"]}
            hosts = [
                group
                for group in self.before["ax"]
                if group["radios"] is None and group["token"] not in current_tokens
            ]
            hidden_host = True
        require(
            len(hosts) == 1 and len(current["ax"]) == len(self.before["ax"]),
            "Shared host is not positively bound to the pre-open radio partition",
        )
        host = hosts[0]
        observation = {
            "phase": "pre_detach_host_binding",
            "before_host_position": geometry_pair(host["position"]),
            "before_host_size": geometry_pair(host["size"]),
            "after_host_position": geometry_pair(own["position"]),
            "after_host_size": geometry_pair(own["size"]),
            "current_cg_window_id": own_cg["window_id"],
            "worker": list(self.worker),
            "before_radio_partition_sha256": fingerprint(self.members(host)),
            "after_retained_radio_partition_sha256": fingerprint(original),
        }
        radios = own.get("radios") or []
        selected = [radio["token"] for radio in radios if radio.get("selected")]
        tokens = [radio["token"] for radio in radios]
        previous_radios = {
            token for group in self.before["ax"] for token in self.members(group) or []
        }
        require(
            original
            and len(set(original)) == len(original)
            and len(selected) == 1
            and selected[0] not in previous_radios
            and len(set(tokens)) == len(tokens)
            and [token for token in tokens if token != selected[0]] == original
            and own["token"]
            not in {group["token"] for group in self.before["ax"] if group is not host}
            and len([group for group in current["ax"] if group["token"] == own["token"]]) == 1,
            "Shared host retained tab identities changed",
            observation=observation,
        )
        old_cg = [
            window
            for window in self.before["cg"]
            if host["position"] == [window["bounds"]["X"], window["bounds"]["Y"]]
            and host["size"] == [window["bounds"]["Width"], window["bounds"]["Height"]]
        ]
        require(
            len(old_cg) == 1,
            "Pre-open host CG geometry is ambiguous",
            observation=observation,
        )
        unrelated = [window for window in self.before["cg"] if window is not old_cg[0]]
        unrelated_ids = {window["window_id"] for window in unrelated}
        require(
            own_cg["window_id"] not in unrelated_ids
            and {window["window_id"] for window in current["cg"]}
            == unrelated_ids | {own_cg["window_id"]}
            and all(
                any(
                    item["window_id"] == window["window_id"] and item["bounds"] == window["bounds"]
                    for item in current["cg"]
                )
                for window in unrelated
            ),
            "Unrelated pre-open native CG surface changed",
            observation=observation,
        )
        self.retained(self.before, current, exclude=host)
        self.hidden_host = host if hidden_host else None
        if hidden_host:
            return "hidden_singleton_partition"
        return "same_ax_window" if host["token"] == own["token"] else "retained_tab_identities"

    @timed_async("terminal_window_isolate")
    async def isolate(self, receipt):
        self.mark_phase("isolate")
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
        radios = own["radios"]
        selected = [r["token"] for r in radios or [] if r["selected"]]
        if radios is not None:
            require(len(selected) == 1, "Created native tab is not uniquely selected")
        own_radio = selected[0] if selected else None
        moved = bool(radios and len(radios) > 1)
        host_identity_basis = own_identity_basis = "same_ax_window"
        if moved:
            original = [r["token"] for r in radios if r["token"] != own_radio]
            host_identity_basis = self.bind_shared_host(before, own_cg, own, original)
            self.mark_phase("detach")
            await self.terminal.move_created_tab(receipt)
            self.mark_phase("post_detach")
            for attempt in range(10):
                try:
                    after = await self.snapshot()
                except BridgeError as error:
                    if error.code != "session_window_inventory_pending" or attempt == 9:
                        raise
                    await asyncio.sleep(0.1)
                    continue
                new_cg, new_own = self.own(after, nonce=receipt["nonce"])
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
                hidden_host = getattr(self, "hidden_host", None)
                hosts = [
                    g
                    for g in after["ax"]
                    if g is not new_own
                    and (
                        g["token"] == hidden_host["token"] and self.members(g) in (None, original)
                        if hidden_host
                        else self.members(g) == original
                    )
                ]
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
                unrelated_ids = {w["window_id"] for w in before["cg"]} - {own_cg["window_id"]}
                split = [w for w in after["cg"] if w["window_id"] not in unrelated_ids]
                split_ids = {w["window_id"] for w in split}
                old_ids = {w["window_id"] for w in before["cg"]}
                require(
                    len(split) == 2
                    and own_cg["window_id"] in split_ids
                    and len(split_ids - old_ids) == 1
                    and new_cg["window_id"] in split_ids,
                    "Shared CG surface did not split into one retained and one new surface",
                )
                host_surfaces = [w for w in split if w["window_id"] != new_cg["window_id"]]
                host_layout = (
                    host["position"] == own["position"]
                    and host["size"] == own["size"]
                    and host_surfaces
                    and host_surfaces[0]["bounds"] == own_cg["bounds"]
                )
                if hidden_host and len(host_surfaces) == 1:
                    # Hiding the singleton tab bar again can reflow its height.
                    # Require the original AX anchor and coherent CG/AX geometry,
                    # retaining its position and width, rather than equal heights.
                    bounds = host_surfaces[0]["bounds"]
                    host_layout = (
                        host["position"] == hidden_host["position"] == [bounds["X"], bounds["Y"]]
                        and host["size"] == [bounds["Width"], bounds["Height"]]
                        and host["size"][0] == hidden_host["size"][0]
                    )
                require(
                    len(host_surfaces) == 1 and host_layout,
                    "Original host native layout changed",
                )
                require(
                    new_own["radios"] is None
                    or (self.members(new_own) == [own_radio] and new_own["radios"][0]["selected"]),
                    "Detached own radio was replaced",
                )
                # After the one recorded detach, the complete native split and
                # retained host have been proved above. If the AXWindow wrapper
                # changed, still require either the same CG surface or the same
                # selected child reference; a new title alone is insufficient.
                if new_own["token"] != own["token"]:
                    require(
                        new_cg["window_id"] == own_cg["window_id"]
                        or self.members(new_own) == [own_radio],
                        "Detached own native identity is unconfirmed",
                    )
                    own_identity_basis = (
                        "same_cg_window"
                        if new_cg["window_id"] == own_cg["window_id"]
                        else "same_selected_tab"
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
            "cg_window_id": own_cg["window_id"],
            "ax_window_token": own["token"],
            "app": self.app,
            "worker": list(self.worker),
            "own_radio_token": own_radio,
            "own_tabbar_hidden": own["radios"] is None,
            "move_confirmed": moved,
            "host_identity_basis": host_identity_basis,
            "own_identity_basis": own_identity_basis,
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
