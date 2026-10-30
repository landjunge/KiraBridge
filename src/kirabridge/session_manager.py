"""Authorize exact existing sessions and invoke their selected transport once."""

from __future__ import annotations

import asyncio
import re
import shlex
import time
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from copy import deepcopy
from pathlib import Path

from pydantic import Field

from kirabridge.bridge_core.models import BridgeError, Input, digest
from kirabridge.filesystem_manager import PathScope
from kirabridge.platform_adapters.desktop import DESKTOP_MESSAGES
from kirabridge.platform_adapters.terminal_app import TerminalAppTransport
from kirabridge.platform_adapters.tmux import TmuxTransport
from kirabridge.session_ports import SessionPorts, SessionTransport, TerminalAppPort
from kirabridge.terminal_manager import check_executable


class SessionReference(Input):
    pane_id: str = Field(pattern=r"^(%[0-9]+|terminal:[0-9]+:ttys[0-9]+)$")
    expected_pid: int = Field(gt=0)


class SessionRead(SessionReference):
    max_bytes: int = Field(default=65536, ge=1, le=65536)
    since: str = Field(default="", max_length=64, pattern=r"^$|[0-9a-f]{64}")


def follow_screen(previous: str | None, screen: str, *, since: str) -> dict:
    """Describe new terminal bytes without dropping the current screen.

    An unknown cursor resets. It never borrows text stored for another pane.
    Terminal.app rewrites the last prompt, so a short changed tail still counts
    as appended output. A rewrite earlier in the screen resets instead.
    """
    if not since:
        return {"follow": "full"}
    if previous is None:
        return {"follow": "reset"}
    if previous == screen:
        return {"follow": "unchanged", "appended": ""}
    if screen.startswith(previous):
        return {"follow": "append", "appended": screen[len(previous) :]}
    common = 0
    limit = min(len(previous), len(screen))
    while common < limit and previous[common] == screen[common]:
        common += 1
    rewritten = len(previous) - common
    if common >= 32 and rewritten <= 256:
        return {"follow": "append", "appended": screen[common:]}
    return {"follow": "reset"}


class SessionSelect(SessionReference):
    """Address one current tab without sending text."""


class SessionInput(SessionReference):
    text: str = Field(min_length=1, max_length=16384)
    submit: bool = True
    require_idle: bool = False


class SessionOpen(Input):
    controlled_shell: bool = False
    cwd: str = Field(min_length=1, max_length=4096)
    argv: list[str] = Field(default_factory=list, max_length=256)
    window_authorization: str = Field(default="", max_length=128)


class SessionManager:
    def __init__(
        self,
        ports: SessionPorts,
        *,
        socket_name=None,
        terminal_app: TerminalAppPort | None = None,
        tmux: SessionTransport | None = None,
    ):
        self.ports, self.socket_name = ports, socket_name
        self.authorization, self.input_release, self.audit = (
            ports.authorization,
            ports.input_release,
            ports.audit,
        )
        self.environment, self.agent_registry = ports.environment, ports.agent_registry
        self.readiness = ports.readiness
        self.lock = asyncio.Lock()
        self._selection = ContextVar("kirabridge_visible_selection", default=None)
        self._observation = ContextVar("kirabridge_terminal_observation", default=None)
        self.terminal_app = (
            terminal_app if terminal_app is not None else TerminalAppTransport(ports.clipboard_lock)
        )
        self.tmux = (
            tmux if tmux is not None else TmuxTransport(ports.environment, socket_name=socket_name)
        )
        self.desktop = self.terminal_app.desktop

    def direct(self, principal):
        return (
            self.ports.visible_required(principal)
            if self.ports.visible_required
            else principal == "chatgpt"
        )

    def transport(self, pane_id):
        return self.terminal_app if pane_id.startswith("terminal:") else self.tmux

    async def catalog(self, principal):
        self.authorization.principal(principal, "session.inspect")
        native_rows, errors = [], {}
        if self.terminal_app.available and self.socket_name is None:
            try:
                native_rows = await self.terminal_app.catalog()
            except BridgeError as exc:
                errors["terminal_app"] = {"code": exc.code, "message": str(exc)}
        try:
            rows = await self.tmux.catalog()
        except BridgeError as exc:
            return self._catalog_result(
                native_rows,
                transport="terminal_app" if native_rows else "tmux",
                status="available"
                if native_rows
                else errors.get("terminal_app", {}).get("code", exc.code),
                errors={**errors, "tmux": {"code": exc.code}},
                truncated=getattr(self.terminal_app, "last_catalog_incomplete", False),
            )
        return self._catalog_result(
            native_rows + rows,
            transport="terminal_app_and_tmux" if native_rows else "tmux",
            status="available",
            errors=errors,
            truncated=getattr(self.tmux, "last_catalog_truncated", False)
            or getattr(self.terminal_app, "last_catalog_incomplete", False),
        )

    def _catalog_result(self, rows, *, transport, status, errors, truncated=False):
        from kirabridge.platform_adapters.terminal_app import annotate_views

        sessions = annotate_views(self.describe(rows))
        visual = {
            row.get("visual_window_id")
            for row in sessions
            if row.get("visual_window_id") is not None
        }
        return {
            "transport": transport,
            "status": status,
            "ui_window_count": len(visual),
            "sessions": sessions,
            "transport_errors": errors,
            "truncated": truncated,
            "scope": "Exact Terminal.app tabs and tmux panes; existing sessions preserved",
        }

    def describe(self, rows):
        agents, bindings = self.agent_registry()
        for row in rows:
            observed = [p for p in row.get("processes", []) if p["name"] in agents]
            row["agent_identity_verified"] = False
            row["agent_identity_scope"] = (
                "current-user OS process observation, not cryptographic identity"
            )
            if len(observed) == 1:
                process = observed[0]
                binding = bindings.get(process["name"])
                row["agent_candidate"] = process["name"]
                row["agent_pid"] = process["pid"]
                row["configured_binding_current"] = bool(
                    binding and self.binding_matches(row, binding, process["name"])
                )
                row["agent_activity"] = "not_probed"
                row["busy_scope"] = "transport process presence; not an agent-turn activity result"
            elif observed:
                row["agent_candidates_ambiguous"] = True
        return rows

    @staticmethod
    def binding_matches(selected, binding, target):
        return (
            binding.pane_id == selected.get("pane_id")
            and binding.expected_pid
            in {selected.get("expected_pid"), selected.get("legacy_expected_pid")}
            and any(
                p["pid"] == binding.agent_pid and p["name"] == target
                for p in selected.get("processes", [])
            )
        )

    def explicit_agent_binding(self, selected):
        """A caller selected THIS current handle; never rewrite configured/default targets."""
        agents, bindings = self.agent_registry()
        matches = [p for p in selected.get("processes", []) if p["name"] in agents]
        if not matches:
            return None, None
        if len(matches) != 1:
            raise BridgeError(
                "visible_target_ambiguous", "Multiple CLI agents in selected terminal"
            )
        process = matches[0]
        original = bindings.get(process["name"])
        if original is None or not selected["pane_id"].startswith("terminal:"):
            raise BridgeError(
                "visible_target_missing",
                "Agent needs an operator-configured visible input contract",
            )
        changed = not self.binding_matches(selected, original, process["name"])
        updates = {
            "pane_id": selected["pane_id"],
            "expected_pid": selected["expected_pid"],
            "agent_pid": process["pid"],
        }
        if changed:
            # A restarted/different process is not the previous Codex thread.
            updates.update(codex_thread_id=None, codex_rollout_path=None)
        return process["name"], original.model_copy(update=updates)

    @asynccontextmanager
    async def agent_selection(self, principal, target, binding):
        selected = await self.selected(principal, binding.pane_id, binding.expected_pid)
        if not self.binding_matches(selected, binding, target) or not any(
            p["pid"] == binding.agent_pid and p["name"] == target
            for p in selected.get("processes", [])
        ):
            raise BridgeError("visible_target_changed", "Selected agent changed before dispatch")
        identities = None
        if selected.get("transport") == "terminal_app":
            identities = {}
            for pid in {selected["expected_pid"], binding.agent_pid}:
                identity = await self.terminal_app.process_identity(pid, detailed=True)
                fields = identity.split(None, 8)
                process = next((p for p in selected["processes"] if p["pid"] == pid), None)
                if (
                    len(fields) != 9
                    or not fields[0].isdigit()
                    or not fields[7].isdigit()
                    or fields[1] != Path(selected["tty"]).name
                    or process is None
                    or int(fields[7]) != process.get("ppid")
                    or fields[8] != process.get("image")
                ):
                    raise BridgeError(
                        "visible_target_changed", "Selected process image/parent/TTY changed"
                    )
                identities[pid] = identity
        token = self._selection.set((target, binding, identities, asyncio.current_task()))
        try:
            yield
        finally:
            self._selection.reset(token)

    def current_selection(self):
        selection = self._selection.get()
        if selection and selection[3] is not asyncio.current_task():
            raise BridgeError("visible_selection_required", "Selection belongs to another task")
        return selection

    def selected_identities(self, selected):
        selection = self.current_selection()
        if selection and not self.binding_matches(selected, selection[1], selection[0]):
            raise BridgeError(
                "visible_target_changed", "Input differs from this task's selected target"
            )
        return selection[2] if selection else None

    @contextmanager
    def observation_scope(self, principal, selected):
        """Reuse a privately observed row only during this task's single read chain.

        This is not selection authority for input, and is never accepted from MCP.
        Expiration also invalidates inherited contexts after the operation returns.
        """
        observation = {
            "principal": principal,
            "row": deepcopy(selected),
            "task": asyncio.current_task(),
            "active": True,
        }
        token = self._observation.set(observation)
        try:
            yield
        finally:
            observation["active"] = False
            self._observation.reset(token)

    async def observed_selected(self, principal, pane_id, expected_pid):
        observation = self._observation.get()
        if observation is None:
            return await self.selected(principal, pane_id, expected_pid)
        row = observation["row"]
        if (
            not observation["active"]
            or observation["task"] is not asyncio.current_task()
            or observation["principal"] != principal
            or row.get("pane_id") != pane_id
            or expected_pid not in {row.get("expected_pid"), row.get("legacy_expected_pid")}
        ):
            raise BridgeError(
                "session_observation_changed", "Read observation scope changed or expired"
            )
        return deepcopy(row)

    async def prove_original_target_gone(self, principal, original):
        """Fresh read-only evidence for a persisted binding, never a current-target guess."""
        from kirabridge.bridge_core.config import VisibleTerminalBinding

        self.authorization.principal(principal, "session.inspect")
        if not self.terminal_app.available:
            raise BridgeError("visible_absence_unproven", "Native observation is unavailable")
        try:
            if (
                not isinstance(original, dict)
                or type(original.get("expected_pid")) is not int
                or type(original.get("agent_pid")) is not int
            ):
                raise ValueError("Original PID types must be exact")
            binding = VisibleTerminalBinding.model_validate(original)
            window = int(binding.pane_id.split(":")[1])
            if window <= 0 or binding.expected_pid == binding.agent_pid:
                raise ValueError("Ambiguous original binding")
        except (ValueError, TypeError):
            raise BridgeError("visible_absence_unproven", "Original binding is not exact") from None
        expected = {binding.expected_pid, binding.agent_pid}
        observations = []

        async def absent_pids():
            pids = await self.terminal_app.process_ids()
            if (
                not isinstance(pids, (set, frozenset))
                or not pids
                or any(type(pid) is not int or pid < 0 for pid in pids)
                or expected.intersection(pids)
            ):
                raise BridgeError(
                    "visible_absence_unproven", "Original PID exists or inventory is invalid"
                )
            observations.append(
                {
                    "observed_at": time.time(),
                    "pid_count": len(pids),
                    "inventory_sha256": digest(sorted(pids)),
                }
            )

        await absent_pids()
        catalog = await self.terminal_app.window_inventory()
        catalog_at = time.time()
        if (
            not isinstance(catalog, dict)
            or set(catalog) != {"running", "windows"}
            or type(catalog.get("running")) is not bool
            or not isinstance(catalog.get("windows"), list)
            or not catalog["running"]
            and catalog["windows"]
        ):
            raise BridgeError("visible_absence_unproven", "Native window inventory is invalid")
        seen = set()
        for row in catalog["windows"]:
            if (
                not isinstance(row, dict)
                or type(row.get("window_id")) is not int
                or row["window_id"] <= 0
                or row["window_id"] in seen
                or not isinstance(row.get("ttys"), list)
                or any(
                    not isinstance(tty, str) or not re.fullmatch(r"/dev/ttys[0-9]+", tty)
                    for tty in row["ttys"]
                )
            ):
                raise BridgeError(
                    "visible_absence_unproven", "Native window inventory is incomplete"
                )
            seen.add(row["window_id"])
        if window in seen:
            raise BridgeError("visible_absence_unproven", "Original window still exists")
        await absent_pids()
        return {
            "original_binding_sha256": digest(binding.model_dump()),
            "original_window": window,
            "original_pids": sorted(expected),
            "original_pids_gone": True,
            "native_window_absent": True,
            "native_window_count": len(seen),
            "catalog_observed_at": catalog_at,
            "process_observations": observations,
            "observed_at": time.time(),
        }

    async def read(self, principal, pane_id, expected_pid, *, max_bytes=65536):
        await self.observed_selected(principal, pane_id, expected_pid)
        text = await self.transport(pane_id).read(pane_id)
        text = text.encode("utf-8")[-max_bytes:].decode("utf-8", "ignore")
        return {
            "pane_id": pane_id,
            "expected_pid": expected_pid,
            "text": text,
            "scope": "selected terminal output; not proof of project completion",
        }

    async def insert(self, principal, args, *, before_transport=None):
        self.authorization.principal(principal, "session.input")
        self.authorization.principal(principal, "terminal.execute")
        if args.submit or "\x00" in args.text:
            raise BridgeError("invalid_arguments", "Insertion must not submit a line")
        async with self.lock:
            selected = await self.selected(principal, args.pane_id, args.expected_pid)
            self.assigned_agent(selected)
            identities = self.selected_identities(selected)
            # Native agent process presence is not turn activity. A task-owned
            # identity requires the fresh widget/readiness check below instead.
            if args.require_idle and selected.get("busy", True) and identities is None:
                raise BridgeError("session_busy", "Selected terminal is not an idle shell")
            if selected.get("transport") == "terminal_app" and identities is None:
                raise BridgeError(
                    "visible_selection_required",
                    "Native agent input requires a task-owned selection",
                )
            if identities is not None:
                text = await self.terminal_app.read(args.pane_id)
                if self.readiness is None:
                    raise BridgeError(
                        "visible_target_unknown", "No readiness assessor for agent input"
                    )
                observation = await self.readiness(
                    principal,
                    {"pane_id": args.pane_id, "expected_pid": args.expected_pid, "text": text},
                )
                if not observation or not observation.get("ready"):
                    raise BridgeError(
                        "visible_target_not_ready", "Current agent widget is not ready"
                    )
                if before_transport is not None:
                    await before_transport()
                await self.terminal_app.insert(
                    args.pane_id, args.text, identity_guard=identities, expected_screen=text
                )
            else:
                if before_transport is not None:
                    await before_transport()
                await self.transport(args.pane_id).insert(args.pane_id, args.text)
        return {"paste_event_sent": True, "return_sent": False, "agent_confirmed": False}

    async def press_return(self, principal, pane_id, expected_pid, *, expected_screen=None):
        self.authorization.principal(principal, "session.input")
        self.authorization.principal(principal, "terminal.execute")
        async with self.lock:
            selected = await self.selected(principal, pane_id, expected_pid)
            self.assigned_agent(selected)
            identities = self.selected_identities(selected)
            if selected.get("transport") == "terminal_app" and identities is None:
                raise BridgeError(
                    "visible_selection_required",
                    "Native agent input requires a task-owned selection",
                )
            if identities is not None:
                if expected_screen is None:
                    raise BridgeError(
                        "visible_input_unknown", "Return requires the verified inserted widget"
                    )
                await self.terminal_app.press_return(
                    pane_id, identity_guard=identities, expected_screen=expected_screen
                )
            else:
                await self.transport(pane_id).press_return(pane_id)
        return {"return_sent": True, "agent_confirmed": False}

    async def send(self, principal, args, *, task_id=None, before_transport=None):
        self.authorization.principal(principal, "session.input")
        self.authorization.principal(principal, "terminal.execute")
        if "\x00" in args.text:
            raise BridgeError("invalid_arguments", "NUL in input")
        async with self.lock:
            selected = await self.selected(principal, args.pane_id, args.expected_pid)
            # Recognition, exact assignment and central handoff are mandatory for
            # every CLI tab, including an unbound idle-looking tab. A raw shortcut
            # cannot establish readiness or the task's durable input intent.
            if self.assigned_agent(selected):
                raise BridgeError(
                    "visible_handoff_required", "CLI handoffs require the central route"
                )
            if (args.require_idle or self.direct(principal)) and selected.get("busy", True):
                raise BridgeError("session_busy", "Selected terminal is not an idle shell")
            if self.direct(principal) and not args.pane_id.startswith("terminal:"):
                raise BridgeError(
                    "visible_terminal_required",
                    "ChatGPT direct input requires a visible Terminal.app window",
                )
            plain_paste = args.pane_id.startswith("terminal:") and not args.submit
            args = self.input_release.dispatch(principal, args, task_id)
            if plain_paste:
                self.terminal_app.validate_shell_paste_text(args.text)
                context = await self.terminal_app.prepare_shell_paste(selected)
                if before_transport is not None:
                    await before_transport()
                await self.terminal_app.insert(
                    args.pane_id,
                    args.text,
                    identity_guard=context["identities"],
                    expected_screen=context["screen"],
                    shell_snapshot=context["snapshot"],
                )
            elif self.direct(principal):
                identity = await self.terminal_app.process_identity(selected["expected_pid"])
                await self.terminal_app.send_confirmed(
                    selected, args.text, identity, before_transport=before_transport
                )
            else:
                if before_transport is not None:
                    await before_transport()
                await self.transport(args.pane_id).send(
                    args.pane_id, args.text, submit=args.submit, require_idle=args.require_idle
                )
            self.input_release.sent(principal, task_id)
        return {
            "pane_id": args.pane_id,
            "expected_pid": args.expected_pid,
            "input_handed_to_transport": True,
            "agent_processed": False,
            "submitted": args.submit,
            **(
                {
                    "paste_event_sent": True,
                    "return_sent": False,
                    "agent_confirmed": False,
                    "execution_confirmed": False,
                }
                if plain_paste
                else {}
            ),
        }

    async def selected(self, principal, pane_id, expected_pid):
        catalog = await self.catalog(principal)
        native_error = catalog.get("transport_errors", {}).get("terminal_app", {})
        if pane_id.startswith("terminal:") and native_error.get("code") in DESKTOP_MESSAGES:
            raise BridgeError(native_error["code"], native_error["message"])
        matches = [
            row
            for row in catalog["sessions"]
            if row["pane_id"] == pane_id
            and expected_pid in {row["expected_pid"], row.get("legacy_expected_pid")}
        ]
        if len(matches) == 1:
            selected = matches[0]
            if selected.get("identity_ambiguous"):
                raise BridgeError(
                    "visible_target_ambiguous",
                    "Several live tabs report this tty; no input until the view is unique",
                )
            return selected
        raise BridgeError(
            "session_selection_changed",
            "Select an exact current pane_id and expected_pid from session_catalog",
        )

    async def focus(self, principal, pane_id, expected_pid):
        self.authorization.principal(principal, "session.input")
        selected = await self.selected(principal, pane_id, expected_pid)
        if not pane_id.startswith("terminal:"):
            raise BridgeError("visible_terminal_required", "Focus requires a Terminal.app tab")
        before = await self.terminal_app.front_tab()
        await self.terminal_app.focus(pane_id)
        after = await self.terminal_app.front_tab()
        return {
            "pane_id": pane_id,
            "expected_pid": expected_pid,
            "visual_window_id": selected.get("visual_window_id"),
            "tab_index": selected.get("tab_index"),
            "before": before,
            "after": after,
            "focused": after.get("tty") == selected.get("tty")
            and after.get("window_id") == selected.get("window_id"),
        }

    async def close_tab(self, principal, pane_id, expected_pid):
        self.authorization.principal(principal, "session.input")
        selected = await self.selected(principal, pane_id, expected_pid)
        if selected.get("tab_count", 1) < 2 and selected.get("ui_window_count", 1) < 2:
            raise BridgeError(
                "terminal_window_required", "Refusing to close the only visible terminal"
            )
        if not pane_id.startswith("terminal:"):
            raise BridgeError("visible_terminal_required", "Close requires a Terminal.app tab")
        result = await self.terminal_app.close_tab(pane_id)
        return {
            "pane_id": pane_id,
            "expected_pid": expected_pid,
            "closed": bool(result.get("closed")),
            "remaining": result.get("remaining"),
        }

    def assigned_agent(self, selected):
        """Recognized CLI input always needs the persistent original binding."""
        selected = selected or {}
        agents, bindings = self.agent_registry()
        matches = [p for p in selected.get("processes", []) if p["name"] in agents]
        if not matches:
            return None
        if len(matches) != 1:
            raise BridgeError("visible_target_ambiguous", "Multiple CLI agents in this terminal")
        process = matches[0]
        selection = self.current_selection()
        binding = (
            selection[1]
            if selection and selection[0] == process["name"]
            else bindings.get(process["name"])
        )
        if (
            not binding
            or binding.pane_id != selected.get("pane_id")
            or binding.agent_pid != process["pid"]
            or binding.expected_pid
            not in {selected.get("expected_pid"), selected.get("legacy_expected_pid")}
        ):
            raise BridgeError(
                "visible_target_changed", "CLI input requires its assigned original window"
            )
        return process["name"]

    async def read_observed(self, principal, pane_id, expected_pid, *, max_bytes=65536, since=""):
        selected = await self.selected(principal, pane_id, expected_pid)
        with self.observation_scope(principal, selected):
            result = await self.read(principal, pane_id, expected_pid, max_bytes=max_bytes)
            if self.readiness:
                observation = await self.readiness(principal, result)
                if observation is not None:
                    result = {**result, "input_readiness": observation}
            previous = None
            if since and hasattr(self.audit, "captured_text"):
                previous = self.audit.captured_text(
                    principal,
                    "session_capture",
                    f"{pane_id}:{expected_pid}",
                    since,
                )
            result.update(follow_screen(previous, result["text"], since=since))
            result = self.audit.observe_terminal(principal, result)
            reference = result.get("output_ref") or {}
            if isinstance(reference, dict) and isinstance(reference.get("sha256"), str):
                result["next_cursor"] = reference["sha256"]
            return result

    async def open(self, principal, args, *, task_id=None):
        policy = self.authorization.principal(principal, "session.open")
        self.authorization.principal(principal, "terminal.execute")
        self.authorization.validate_window(principal, task_id, args)
        PathScope(policy.terminal_roots or policy.roots).split(args.cwd)
        cwd = str(Path(args.cwd).resolve(strict=True))
        PathScope(policy.terminal_roots or policy.roots).split(cwd)
        argv = list(args.argv)
        if argv:
            argv[0] = check_executable(
                argv[0],
                policy.executables,
                policy.allow_any_executable,
                self.environment["PATH"],
            )
        if any("\x00" in arg for arg in argv):
            raise BridgeError("invalid_arguments", "NUL in command")
        command = "cd -- " + shlex.quote(cwd)
        if args.controlled_shell:
            if argv:
                raise BridgeError(
                    "invalid_arguments", "Controlled shell setup takes no initial command"
                )
            command += (
                " && exec /usr/bin/env PS1="
                + shlex.quote("KiraBridge visible %% ")
                + " /bin/zsh -f"
            )
        if argv and not self.direct(principal):
            command += " && " + shlex.join(argv)
        async with self.lock:
            self.authorization.check_window(principal, task_id, args)
            try:
                result = await self.terminal_app.open(command)
            except BaseException:
                self.authorization.window_outcome(principal, task_id, "unknown")
                raise
            self.authorization.window_outcome(principal, task_id, "opened")
            for _ in range(20):
                sessions = await self.terminal_app.catalog()
                selected = next((s for s in sessions if s["tty"] == result["tty"]), None)
                if selected:
                    if self.direct(principal) and argv:
                        from kirabridge.platform_adapters.shell_prompt import empty_shell_prompt

                        if selected.get("busy", True):
                            await asyncio.sleep(0.1)
                            continue
                        view = await self.read(
                            principal, selected["pane_id"], selected["expected_pid"]
                        )
                        if not empty_shell_prompt(view["text"]):
                            await asyncio.sleep(0.1)
                            continue
                        identity = await self.terminal_app.process_identity(
                            selected["expected_pid"]
                        )
                        await self.terminal_app.send_confirmed(selected, shlex.join(argv), identity)
                    return {**selected, "opened": True, "agent_processed": False}
                await asyncio.sleep(0.05)
        return {**result, "session_handle_pending": True, "agent_processed": False}
