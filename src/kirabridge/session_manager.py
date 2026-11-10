"""Authorize exact existing sessions and invoke their selected transport once."""

from __future__ import annotations

import asyncio
import re
import shlex
import sys
import time
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from copy import deepcopy
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from kirabridge.bridge_core.models import BridgeError, Input, UncertainExecution, digest
from kirabridge.filesystem_manager import PathScope
from kirabridge.platform_adapters.linux.owned_terminal import LinuxOwnedTerminal
from kirabridge.platform_adapters.terminal_app import TerminalAppTransport
from kirabridge.platform_adapters.tmux import TmuxTransport
from kirabridge.session_ports import SessionPorts, SessionTransport, TerminalAppPort
from kirabridge.terminal_manager import check_executable
from kirabridge.timing import timed_async


class SessionReference(Input):
    pane_id: str = Field(pattern=r"^(%[0-9]+|terminal:[0-9]+:ttys[0-9]+|linux:[1-9][0-9]*)$")
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
    """Literal text, or key='enter' bound to an observed cursor and current agent PID."""

    text: str = Field(default="", max_length=16384)
    submit: bool = True
    require_idle: bool = False
    key: Literal["enter", "escape"] | None = None
    expected_cursor: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    expected_agent_pid: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def explicit_input_mode(self):
        if self.key is not None:
            if self.text or not self.submit or not self.expected_cursor:
                raise ValueError(
                    "A bound key requires empty text, submit=true and an observed cursor"
                )
            if self.key == "escape" and self.expected_agent_pid is None:
                raise ValueError("Navigation requires the observed agent PID")
        elif not self.text or self.expected_cursor or self.expected_agent_pid is not None:
            raise ValueError("Literal text must be nonempty and cannot include Return-only guards")
        return self


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
        linux: LinuxOwnedTerminal | None = None,
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
        self.linux = linux if linux is not None else LinuxOwnedTerminal()
        self.desktop = self.terminal_app.desktop

    def direct(self, principal):
        return (
            self.ports.visible_required(principal)
            if self.ports.visible_required
            else principal == "chatgpt"
        )

    def transport(self, pane_id):
        if pane_id.startswith("linux:"):
            return self.linux
        return self.terminal_app if pane_id.startswith("terminal:") else self.tmux

    @timed_async("session_catalog")
    async def catalog(self, principal, *, transport=None):
        """Discover both transports, or observe only an explicitly selected one."""
        self.authorization.principal(principal, "session.inspect")
        if transport not in {None, "terminal_app", "tmux", "linux"}:
            raise BridgeError("invalid_arguments", "Unknown session catalog transport")
        if transport == "linux":
            return await self._linux_catalog()
        native_rows, errors = [], {}
        if transport != "tmux" and self.terminal_app.available and self.socket_name is None:
            try:
                native_rows = await self.terminal_app.catalog()
            except BridgeError as exc:
                errors["terminal_app"] = {
                    "code": exc.code,
                    "message": str(exc),
                    **(
                        {"provider_error": exc.provider_error}
                        if getattr(exc, "provider_error", None) is not None
                        else {}
                    ),
                }
        elif transport == "terminal_app":
            errors["terminal_app"] = {
                "code": "session_transport_unavailable",
                "message": "Native Terminal.app catalog is unavailable",
            }
        if transport == "terminal_app":
            return self._catalog_result(
                native_rows,
                transport="terminal_app",
                status=errors.get("terminal_app", {}).get("code", "available"),
                errors=errors,
                truncated=getattr(self.terminal_app, "last_catalog_incomplete", False),
            )
        try:
            rows = await self.tmux.catalog()
        except BridgeError as exc:
            return self._catalog_result(
                native_rows,
                transport="terminal_app" if native_rows else "tmux",
                status="available"
                if native_rows
                else errors.get("terminal_app", {}).get("code", exc.code),
                errors={
                    **errors,
                    "tmux": {
                        "code": exc.code,
                        **(
                            {"provider_error": exc.provider_error}
                            if getattr(exc, "provider_error", None) is not None
                            else {}
                        ),
                    },
                },
                truncated=transport != "tmux"
                and getattr(self.terminal_app, "last_catalog_incomplete", False),
            )
        linux_rows = []
        if sys.platform.startswith("linux"):
            try:
                linux_rows = await self.linux.catalog()
            except BridgeError as exc:
                errors["linux"] = {"code": exc.code, "message": str(exc)}
        return self._catalog_result(
            native_rows + rows + linux_rows,
            transport="terminal_app_and_tmux" if native_rows else "tmux",
            status="available",
            errors=errors,
            truncated=getattr(self.tmux, "last_catalog_truncated", False)
            or transport != "tmux"
            and getattr(self.terminal_app, "last_catalog_incomplete", False),
        )

    async def _linux_catalog(self):
        try:
            rows = await self.linux.catalog()
        except BridgeError as exc:
            return self._catalog_result(
                [],
                transport="linux",
                status=exc.code,
                errors={"linux": {"code": exc.code, "message": str(exc)}},
                scope="Bridge-owned Linux PTY sessions; no user terminal attached",
            )
        return self._catalog_result(
            rows,
            transport="linux",
            status="available",
            errors={},
            scope="Bridge-owned Linux PTY sessions; no user terminal attached",
        )

    def _catalog_result(
        self, rows, *, transport, status, errors, truncated=False, scope=None
    ):
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
            "scope": scope
            or "Exact Terminal.app tabs and tmux panes; existing sessions preserved",
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
                from kirabridge.cli_adapters import default_registry

                row["cli_adapter"] = default_registry().describe(process["name"])
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
            target = self.assigned_agent(selected)
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
                    args.pane_id,
                    args.text,
                    identity_guard=identities,
                    expected_screen=text,
                    agent_target=target,
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

    async def return_key(self, principal, args, *, expected_screen, before_transport):
        """One key for the separately authorized, observed view; never paste text."""
        self.authorization.principal(principal, "session.input")
        self.authorization.principal(principal, "terminal.execute")
        if args.key not in {"enter", "escape"} or args.text or not args.submit:
            raise BridgeError("invalid_arguments", "A standalone Return requires explicit key mode")
        async with self.lock:
            selected = await self.selected(principal, args.pane_id, args.expected_pid)
            if selected.get("transport") != "terminal_app":
                raise BridgeError(
                    "visible_terminal_required", "Return requires a visible native tab"
                )
            target = self.assigned_agent(selected)
            snapshot = None
            if target:
                identities = self.selected_identities(selected)
                selection = self.current_selection()
                if (
                    identities is None
                    or not selection
                    or args.expected_agent_pid != selection[1].agent_pid
                ):
                    raise BridgeError("visible_target_changed", "Observed agent identity changed")
            else:
                if args.expected_agent_pid is not None:
                    raise BridgeError(
                        "visible_target_changed", "Observed agent is no longer present"
                    )
                context = await self.terminal_app.prepare_shell_paste(selected)
                if context["screen"] != expected_screen:
                    raise BridgeError("visible_input_changed", "Observed terminal view changed")
                identities, snapshot = context["identities"], context["snapshot"]
            await before_transport()
            guards = {
                "identity_guard": identities,
                "expected_screen": expected_screen,
                **({"shell_snapshot": snapshot} if snapshot is not None else {}),
            }
            if args.key == "enter":
                await self.terminal_app.press_return(args.pane_id, **guards)
            else:
                await self.terminal_app.press_key(args.pane_id, "escape", **guards)
        return {
            "paste_event_sent": False,
            "return_sent": args.key == "enter",
            "navigation_key_sent": args.key == "escape",
            "agent_confirmed": False,
        }

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
                identities = None
                if args.pane_id.startswith("terminal:"):
                    identity = await self.terminal_app.process_identity(
                        selected["expected_pid"], detailed=True
                    )
                    fields = identity.split(None, 8)
                    if len(fields) != 9 or fields[1] != args.pane_id.rsplit(":", 1)[1]:
                        raise BridgeError(
                            "visible_target_changed", "Selected process TTY identity changed"
                        )
                    identities = {selected["expected_pid"]: identity}
                if before_transport is not None:
                    await before_transport()
                await self.transport(args.pane_id).send(
                    args.pane_id,
                    args.text,
                    submit=args.submit,
                    require_idle=args.require_idle,
                    **({"identity_guard": identities} if identities is not None else {}),
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

    @timed_async("session_selected")
    async def selected(self, principal, pane_id, expected_pid):
        if pane_id.startswith("linux:"):
            transport = "linux"
        elif pane_id.startswith("terminal:"):
            transport = "terminal_app"
        else:
            transport = "tmux"
        catalog = await self.catalog(principal, transport=transport)
        error = catalog.get("transport_errors", {}).get(transport, {})
        if error:
            failure = BridgeError(
                error["code"], error.get("message", "Selected session observation failed")
            )
            if error.get("provider_error") is not None:
                failure.provider_error = error["provider_error"]
            raise failure
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

    async def _open_owned_linux(self, principal, task_id, cwd, argv):
        try:
            opened = await self.linux.open_shell(cwd)
        except BaseException:
            self.authorization.window_outcome(principal, task_id, "unknown")
            raise
        self.authorization.window_outcome(principal, task_id, "opened")
        if not argv:
            return opened
        try:
            await self.linux.send(
                opened["pane_id"], shlex.join(argv), submit=True, require_idle=True
            )
        except Exception as cause:
            error = UncertainExecution(
                getattr(cause, "code", "session_open_unknown"),
                "Owned shell opened; command outcome unconfirmed; never reopen or resend",
            )
            error.provider_error = {
                "creation_receipt": {"pane_id": opened["pane_id"], "tty": opened["tty"]},
                "automatic_retry": False,
                "cause_code": getattr(cause, "code", type(cause).__name__),
            }
            raise error from cause
        return {**opened, "command_submitted": True}

    async def open(self, principal, args, *, task_id=None, on_created=None):
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
        async with self.lock:
            self.authorization.check_window(principal, task_id, args)
            if sys.platform.startswith("linux"):
                return await self._open_owned_linux(principal, task_id, cwd, argv)
            try:
                result = await self.terminal_app.open(
                    command, on_created=on_created, principal=principal
                )
            except BaseException:
                self.authorization.window_outcome(principal, task_id, "unknown")
                raise
            self.authorization.window_outcome(principal, task_id, "opened")
            try:
                for _ in range(20):
                    sessions = await self.terminal_app.catalog()
                    matches = [s for s in sessions if s["tty"] == result["tty"]]
                    if len(matches) > 1 or any(s.get("identity_ambiguous") for s in matches):
                        raise BridgeError(
                            "visible_target_ambiguous",
                            "New terminal TTY has several live views; select an unambiguous view",
                        )
                    selected = matches[0] if matches else None
                    if selected:
                        if argv:
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
                                selected["expected_pid"], detailed=True
                            )
                            actual_cwd = await self.terminal_app.process_working_directory(
                                selected["expected_pid"], expected_identity=identity
                            )
                            if actual_cwd != cwd:
                                await asyncio.sleep(0.1)
                                continue
                            await self.terminal_app.send_confirmed(
                                selected,
                                shlex.join(argv),
                                identity,
                                expected_cwd=cwd,
                                before_transport=lambda: self.terminal_app.verify_opened(
                                    result, principal=principal
                                ),
                            )
                        return {
                            **selected,
                            "opened": True,
                            "agent_processed": False,
                            "creation_receipt": result,
                            "separate_window": result.get("separate_window", False),
                        }
                    await asyncio.sleep(0.05)
                if argv:
                    raise UncertainExecution(
                        "session_open_pending", "Window opened; argv was not dispatched"
                    )
                return {**result, "session_handle_pending": True, "agent_processed": False}
            except Exception as cause:
                error = UncertainExecution(
                    getattr(cause, "code", "session_open_unknown"),
                    "Window opened; later outcome unconfirmed; never reopen or resend",
                )
                error.provider_error = {
                    "creation_receipt": result,
                    "automatic_retry": False,
                    "cause_code": getattr(cause, "code", type(cause).__name__),
                    "cause_message": str(cause)[:512],
                }
                raise error from cause
