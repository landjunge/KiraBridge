"""Private acceptance only: prove physical isolation of one receipt-owned Terminal tab.

The product NativeSystemTransport supplies all AX/CG observations. Only the
receipt-owned tab is tagged; at most one exact detach-menu click follows. This
module never opens terminals, sends keys, changes preferences or retries effects.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections import Counter


def require(value, message):
    if not value:
        raise RuntimeError(message)


def cwd_guard(pid, workspace):
    require(
        not any(ord(char) < 32 or ord(char) == 127 for char in str(workspace)),
        "CWD contains controls",
    )
    return (
        "\nif(identityHost.doShellScript("
        + json.dumps(f"/usr/sbin/lsof -a -p {int(pid)} -d cwd -Fpfn")
        + ").replace(/\\r\\n?/g,'\\n').replace(/\\n$/,'')!=="
        + json.dumps(f"p{int(pid)}\nfcwd\nn{workspace}")
        + ")throw Error('Own CWD changed');checkTargetIdentity();\n"
    )


def created_row(rows, created, original_windows):
    matches = [row for row in rows if row.get("tty") == created["tty"]]
    require(len(matches) == 1, "Created TTY is missing or ambiguous")
    row = matches[0]
    require(
        row["pane_id"] == created["pane_id"]
        and row["expected_pid"] == created["expected_pid"]
        and row["window_id"] not in original_windows
        and not row.get("identity_ambiguous"),
        "Created logical target changed; no replacement is permitted",
    )
    return row


class PhysicalIsolation:
    def __init__(self, terminal, native, *, nonce, workspace, record):
        require(re.fullmatch(r"[a-f0-9]{16}", nonce), "Fresh own title nonce required")
        self.terminal, self.native = terminal, native
        self.nonce = "KB_WINDOW_" + nonce
        self.workspace, self.record = str(workspace), record
        self.app = self.worker = self.baseline = None
        self.created = self.identity = None
        self.tag_attempted = self.move_attempted = self.confirmed = False
        self.move_accepted = False

    async def read(self, operation, arguments):
        require(
            operation in {"apps.list", "apps.inspect", "windows.list", "accessibility.inspect"},
            "Physical observation cannot dispatch a mutating native operation",
        )
        result = await self.native.request(operation, arguments, principal="chatgpt")
        helper = result["native_helper"]
        worker = (helper["pid"], helper["generation"], helper["source_commit"])
        require(self.worker in {None, worker}, "Native observation worker changed")
        self.worker = worker
        if operation in {"apps.inspect", "accessibility.inspect"}:
            require(
                all(
                    result["application"][key] == self.app[key]
                    for key in ("pid", "started_at", "bundle_id")
                ),
                "Terminal application generation changed",
            )
        self.record({"native_read": operation, "arguments": arguments, "result": result})
        return result

    async def pages(self, operation, arguments, key, *, token=None):
        rows, revision, total = [], None, None
        offset = 0
        for _ in range(20):
            args = {**arguments, "offset": offset}
            if revision is not None:
                args["expected_revision"] = revision
                if operation == "accessibility.inspect":
                    args.update(token)
            result = await self.read(operation, args)
            require(result.get("offset") == offset, "Incomplete native page offset")
            size = result.get("total_children" if key == "children" else "total")
            require(type(size) is int and size >= 0, "Incomplete native page count")
            require(total in {None, size}, "Native page count changed")
            require(revision in {None, result.get("revision")}, "Native page revision changed")
            total, revision = size, result["revision"]
            if operation == "accessibility.inspect":
                require(
                    result["helper_pid"] == self.worker[0]
                    and result["worker_generation"] == self.worker[1]
                    and result["application"]["pid"] == self.app["pid"]
                    and result["application"]["started_at"] == self.app["started_at"],
                    "AX token application/worker generation changed",
                )
                token = {
                    name: result[name]
                    for name in ("element_token", "helper_pid", "worker_generation")
                }
                if arguments.get("element_token"):
                    require(
                        result["element_token"] == arguments["element_token"],
                        "AX target token changed",
                    )
            page = result[key]
            require(
                isinstance(page, list) and len(rows) + len(page) <= total, "Invalid native page"
            )
            rows.extend(page)
            if len(rows) == total:
                require(result.get("truncated") is False, "Incomplete native traversal")
                if key == "children":
                    require(result.get("eof") is True, "AX traversal is not complete")
                return result, rows
            require(page and result.get("next_offset") == len(rows), "Native traversal stalled")
            offset = len(rows)
        raise RuntimeError("Native traversal budget exceeded")

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
        return await self.pages("accessibility.inspect", args, "children")

    async def snapshot(self):
        if self.app is None:
            _, apps = await self.pages("apps.list", {"limit": 1000}, "applications")
            matches = [app for app in apps if app.get("bundle_id") == "com.apple.Terminal"]
            require(len(matches) == 1, "Exact existing Terminal application required")
            self.app = matches[0]
        inspected = await self.read(
            "apps.inspect", {"pid": self.app["pid"], "expected_started_at": self.app["started_at"]}
        )
        require(
            inspected["application"]["bundle_id"] == "com.apple.Terminal", "Terminal owner changed"
        )
        cg, windows = await self.pages(
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
        require(cg.get("titles_redacted") is False, "Native titles are unavailable")
        windows = [window for window in windows if window["layer"] == 0]
        require(
            len({window["window_id"] for window in windows}) == len(windows),
            "Duplicate CG window identity",
        )
        require(
            all(
                window["on_screen"] is True
                and window["title_available"] is True
                and window["owner_pid"] == self.app["pid"]
                and window["application_start"] == f"{self.app['started_at']:.6f}"
                and isinstance(window.get("title"), str)
                for window in windows
            ),
            "Incomplete visible Terminal CG inventory",
        )
        root, children = await self.ax()
        require(root["element"]["role"] == "AXApplication", "AX application root unavailable")
        ax_windows = [child for child in children if child["role"] == "AXWindow"]
        require(
            len({window["element_token"] for window in ax_windows}) == len(ax_windows),
            "Duplicate AX window identity",
        )
        require(
            len(ax_windows) == len(windows) == len(cg["accessibility_windows"]),
            "AX/CG physical inventory differs",
        )
        groups = []
        for window in ax_windows:
            require(
                not window.get("title_truncated") and not window.get("minimized"),
                "AX physical window unavailable",
            )
            observed, children = await self.ax(window["element_token"])
            require(observed["element"]["role"] == "AXWindow", "AX window token changed")
            require(
                observed["element"].get("title_truncated") is False
                and observed["element"].get("minimized") is False
                and observed["element"].get("subrole") == "AXStandardWindow",
                "Incomplete current AX window metadata",
            )
            tabs = [child for child in children if child["role"] == "AXTabGroup"]
            require(len(tabs) <= 1, "Ambiguous AX tab groups")
            radios = None
            if tabs:
                tab_group, members = await self.ax(tabs[0]["element_token"])
                require(tab_group["element"]["role"] == "AXTabGroup", "AX tab-group token changed")
                require(
                    all(child["role"] in {"AXRadioButton", "AXButton"} for child in members),
                    "Unknown AX tab-group structure",
                )
                radios = [child for child in members if child["role"] == "AXRadioButton"]
                require(
                    len({child["element_token"] for child in radios}) == len(radios),
                    "Duplicate AX tab identity",
                )
                require(
                    radios and all(not child.get("title_truncated") for child in radios),
                    "Incomplete AX tab members",
                )
            groups.append(
                {
                    "title": observed["element"]["title"],
                    "token": window["element_token"],
                    "radios": radios,
                    "tabs": len(radios) if radios is not None else None,
                }
            )
        result = {
            "app": inspected["application"],
            "worker": list(self.worker),
            "cg": windows,
            "ax": groups,
        }
        self.record({"observation": result})
        return result

    async def logical(self):
        inventory = await self.terminal.window_inventory()
        require(inventory["running"] is True, "Terminal is no longer running")
        windows = inventory["windows"]
        require(
            len({row["window_id"] for row in windows}) == len(windows)
            and all(len(row["ttys"]) == 1 for row in windows),
            "Logical scripting windows are not single unique tabs",
        )
        rows = await self.terminal.catalog()
        require(not self.terminal.last_catalog_incomplete, "Complete logical inventory required")
        require(
            {(row["window_id"], row["tty"]) for row in rows}
            == {(row["window_id"], row["ttys"][0]) for row in windows},
            "Logical catalog is incomplete",
        )
        require(
            len(rows) == len({row["tty"] for row in rows})
            and not any(row.get("identity_ambiguous") for row in rows),
            "Logical TTY mapping is ambiguous",
        )
        identities = {
            process["pid"]: await self.terminal.process_identity(process["pid"], detailed=True)
            for row in rows
            for process in row["processes"]
        }
        return {"rows": rows, "identities": identities}

    async def capture_baseline(self):
        logical, native = await self.logical(), await self.snapshot()
        require(
            all(group["tabs"] is not None for group in native["ax"]),
            "Baseline AX tab counts unavailable",
        )
        require(
            sum(group["tabs"] for group in native["ax"]) == len(logical["rows"]),
            "Baseline AX/logical topology differs",
        )
        self.baseline = {"logical": logical, "native": native}
        self.baseline["terminal_identity"] = await self.terminal.process_identity(
            self.app["pid"], detailed=True
        )
        self.record({"baseline": self.baseline})
        return self.baseline

    async def preserve_logical(self):
        current = await self.logical()
        old = self.baseline["logical"]
        ids = {row["window_id"] for row in old["rows"]}
        row = created_row(current["rows"], self.created, ids)
        require(
            {item["pane_id"] for item in current["rows"]}
            == {item["pane_id"] for item in old["rows"]} | {self.created["pane_id"]},
            "Logical tab inventory changed",
        )
        for original in old["rows"]:
            matching = [item for item in current["rows"] if item["pane_id"] == original["pane_id"]]
            require(
                len(matching) == 1
                and all(
                    matching[0].get(key) == original.get(key)
                    for key in ("tty", "expected_pid", "legacy_expected_pid")
                ),
                "Original logical binding changed",
            )
        require(
            all(
                current["identities"].get(pid) == identity
                for pid, identity in old["identities"].items()
            ),
            "Original process generation changed",
        )
        require(
            current["identities"].get(self.created["expected_pid"]) == self.identity,
            "Created process generation changed",
        )
        require(
            await self.terminal.process_working_directory(
                self.created["expected_pid"], expected_identity=self.identity
            )
            == self.workspace,
            "Created CWD changed",
        )
        return row

    def topology(self, snapshot, *, after_move=False):
        own_cg = [window for window in snapshot["cg"] if window["title"].count(self.nonce)]
        own_ax = [group for group in snapshot["ax"] if group["title"].count(self.nonce)]
        require(
            len(own_cg) == len(own_ax) == 1
            and own_cg[0]["title"].count(self.nonce) == own_ax[0]["title"].count(self.nonce) == 1,
            "Own nonce title is missing or ambiguous",
        )
        own = own_ax[0]
        others = [group["tabs"] for group in snapshot["ax"] if group is not own]
        require(all(count is not None for count in others), "Other AX tab topology is incomplete")
        baseline = Counter(group["tabs"] for group in self.baseline["native"]["ax"])
        count = own["tabs"]
        baseline_cg = self.baseline["native"]["cg"]
        baseline_ax = self.baseline["native"]["ax"]
        shared_ax = shared_cg = None
        if count is not None and count > 1:
            matched = [group for group in baseline_ax if group["token"] == own["token"]]
            require(len(matched) == 1, "Shared baseline AX identity is not preserved")
            shared_ax = matched[0]
            original_radios = [item["element_token"] for item in shared_ax["radios"]]
            remaining_radios = [
                item["element_token"]
                for item in own["radios"]
                if not item["title"].count(self.nonce)
            ]
            require(original_radios == remaining_radios, "Shared baseline tab identities changed")
            matched_cg = [
                window for window in baseline_cg if window["window_id"] == own_cg[0]["window_id"]
            ]
            if not matched_cg and len(baseline_cg) == len(baseline_ax) == 1:
                matched_cg = baseline_cg
            require(len(matched_cg) == 1, "Shared baseline CG identity is ambiguous")
            shared_cg = matched_cg[0]
        for original in baseline_cg:
            if original is shared_cg:
                continue
            fields = (
                "window_id",
                "owner_pid",
                "application_start",
                "bounds",
                "layer",
                "on_screen",
                "revision",
            )
            require(all(key in original for key in fields), "Baseline CG fingerprint unavailable")
            matches = [
                window for window in snapshot["cg"] if window["window_id"] == original["window_id"]
            ]
            require(
                len(matches) == 1
                and matches[0] is not own_cg[0]
                and all(matches[0].get(key) == original[key] for key in fields),
                "Original baseline CG physical identity changed",
            )
        for original in baseline_ax:
            if original is shared_ax:
                continue
            matches = [
                group
                for group in snapshot["ax"]
                if group is not own and group["token"] == original["token"]
            ]
            require(
                len(matches) == 1
                and matches[0]["tabs"] == original["tabs"]
                and [item["element_token"] for item in matches[0]["radios"] or []]
                == [item["element_token"] for item in original["radios"] or []],
                "Original baseline AX tab identities changed",
            )
        if count is None:
            require(
                after_move and self.move_accepted and Counter(others) == baseline,
                "Missing own AX tab group is not a standalone-window proof",
            )
            require(
                own_cg[0]["window_id"] not in {window["window_id"] for window in baseline_cg},
                "Missing own AX group needs a new non-baseline CG binding",
            )
            count = 1
        if count == 1:
            require(Counter(others) == baseline, "Remaining physical tab groups changed")
        else:
            require(
                count > 1 and Counter(others + [count - 1]) == baseline,
                "Shared own tab does not match baseline physical topology",
            )
            radios = [item for item in own["radios"] if item["title"].count(self.nonce)]
            require(
                len(radios) == 1 and radios[0].get("value") is True,
                "Own AX tab is not uniquely selected",
            )
        return {
            "tab_count": count,
            "cg_window_id": own_cg[0]["window_id"],
            "ax_window_token": own["token"],
        }

    async def context(self):
        physical = await self.snapshot()
        if self.tag_attempted:
            self.topology(physical, after_move=self.move_accepted)
        row = await self.preserve_logical()
        require(
            not row["busy"]
            and [p["pid"] for p in row["processes"]] == [self.created["expected_pid"]],
            "Own display target is not a child-free idle shell",
        )
        context = await self.terminal.prepare_shell_paste(row)
        require(
            context["identities"][self.created["expected_pid"]] == self.identity
            and context["screen"].rstrip("\n").split("\n")[-1] == "KiraBridge visible % ",
            "Own controlled shell context changed",
        )
        terminal_identity = await self.terminal.process_identity(self.app["pid"], detailed=True)
        require(
            terminal_identity == self.baseline["terminal_identity"],
            "Terminal process identity changed",
        )
        context["identities"][self.app["pid"]] = terminal_identity
        return context

    def source(self, context, *, detach):
        terminal, created = self.terminal, self.created
        pid, tty = created["expected_pid"], created["tty"]
        guard = (
            "\nfunction checkOwnFastBoundary(){" + "\nif(targetWindow.tabs().length!==1 || "
            "app.windows().flatMap(w=>w.tabs()).filter(t=>t.tty()==="
            + json.dumps(tty)
            + ").length!==1)throw Error('Own logical tab changed');"
            "if(tab.busy())throw Error('Own tab became busy');"
            + terminal.native_screen_guard(context["screen"])
            + "}\nfunction checkOwnDisplayTarget(){checkTargetIdentity();"
            + terminal.native_shell_guard(context["snapshot"])
            + cwd_guard(pid, self.workspace)
            + "checkOwnFastBoundary();}\n"
        )
        source = (
            terminal.native_target(created["pane_id"])
            + terminal.native_identity_guard(context["identities"])
            + guard
            + "checkOwnDisplayTarget();\n{"
            + terminal.native_focus(created["pane_id"])
            + "}\ncheckOwnDisplayTarget();\n"
        )
        if not detach:
            return (
                source
                + "if(app.windows().filter(w=>w.name().includes("
                + json.dumps(self.nonce)
                + ")).length)throw Error('Nonce already exists');"
                + "checkOwnFastBoundary();"
                + "tab.customTitle="
                + json.dumps(self.nonce)
                + ";tab.titleDisplaysCustomTitle=true;JSON.stringify({tagged:true});"
            )
        return (
            source
            + """
const seOwn=Application('System Events');
const processesOwn=seOwn.processes().filter(p=>p.unixId()===__OWNER__);
if(processesOwn.length!==1 || !processesOwn[0].frontmost())
 throw Error('Own Terminal owner/focus changed');
const nonceOwn=__NONCE__;
const ownAXWindows=processesOwn[0].windows().filter(w=>{
 try{return w.name().includes(nonceOwn);}catch(e){return false;}});
if(ownAXWindows.length!==1 || !targetWindow.name().includes(nonceOwn) ||
 app.windows().filter(w=>w.name().includes(nonceOwn)).length!==1 ||
 app.windows()[0].id()!==__WINDOW__ || app.windows()[0].selectedTab().tty()!==__TTY__)
 throw Error('Own nonce/selected tab changed');
const bars=processesOwn[0].menuBars();
if(bars.length!==1)throw Error('Own menu bar changed');
const menus=bars[0].menuBarItems().filter(m=>{
 try{return ['Window','Fenster'].includes(m.name());}catch(e){return false;}});
if(menus.length!==1 || menus[0].menus().length!==1)throw Error('Own window menu ambiguous');
const labels=['Move Tab to New Window','Tab in ein neues Fenster bewegen'];
const entries=menus[0].menus()[0].menuItems().filter(m=>{
 try{return labels.includes(m.name());}catch(e){return false;}});
if(entries.length!==1 || !entries[0].enabled())throw Error('Own detach menu unavailable');
checkOwnDisplayTarget();
checkOwnFastBoundary();
if(!processesOwn[0].frontmost() || app.windows()[0].id()!==__WINDOW__ ||
 app.windows()[0].selectedTab().tty()!==__TTY__)throw Error('Own focus changed before detach');
if(!targetWindow.name().includes(nonceOwn) ||
 processesOwn[0].windows().filter(w=>w.name().includes(nonceOwn)).length!==1 ||
 !labels.includes(entries[0].name()) || !entries[0].enabled())
 throw Error('Own nonce/menu changed before detach');
entries[0].click();JSON.stringify({detached:true});
""".replace("__OWNER__", str(self.app["pid"]))
            .replace("__NONCE__", json.dumps(self.nonce))
            .replace("__WINDOW__", str(int(created["pane_id"].split(":")[1])))
            .replace("__TTY__", json.dumps(tty))
        )

    async def isolate(self, created, identity):
        require(
            self.baseline is not None and not self.tag_attempted,
            "Display attempt must never be replayed",
        )
        self.created, self.identity = created, identity
        context = await self.context()
        self.tag_attempted = True
        self.record({"title_attempted": True, "automatic_retry": False})
        result = await self.terminal.native(self.source(context, detach=False), mutation=True)
        require(result.get("tagged") is True, "Own title result unknown; never retry")
        await self.preserve_logical()
        before = await self.snapshot()
        bound = self.topology(before)
        if bound["tab_count"] > 1:
            require(before["app"]["active"] is True, "Terminal is not active for detach")
            context = await self.context()
            self.move_attempted = True
            self.record({"move_attempted": True, "automatic_retry": False})
            result = await self.terminal.native(self.source(context, detach=True), mutation=True)
            require(result.get("detached") is True, "Detach result unknown; never retry or adopt")
            self.move_accepted = True
        await self.preserve_logical()
        async with asyncio.timeout(10):
            while True:  # noqa: ASYNC110 -- observe one known display action; never retry it
                await self.preserve_logical()
                bound = self.topology(await self.snapshot(), after_move=self.move_accepted)
                if bound["tab_count"] == 1:
                    break
                require(self.move_accepted, "Own physical window is not isolated")
                await asyncio.sleep(0.15)
        self.confirmed = True
        self.record({"confirmed": True, "binding": bound})
        return bound

    async def current(self):
        require(self.confirmed, "Fresh physical proof required before input or geometry")
        row = await self.preserve_logical()
        bound = self.topology(await self.snapshot(), after_move=self.move_accepted)
        require(bound["tab_count"] == 1, "Own physical isolation changed")
        return row
