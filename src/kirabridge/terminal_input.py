"""Private terminal text/Return adapter under the original task and desktop turn."""

from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import json
import unicodedata
from dataclasses import dataclass

from kirabridge.bridge_core.models import BridgeError, UncertainExecution, canonical, digest
from kirabridge.keyboard_text import native_frame_bytes, utf16_chunks

ORIGIN_OPERATIONS = frozenset(
    {
        "terminal.visible",
        "terminal.execute",
        "admin.execute",
        "session.input",
        "session.open",
        "agent.execute",
    }
)
PRIVATE_OPERATIONS = frozenset(
    {"apps.list", "terminal.input.inspect", "terminal.input.return"}
    | {"terminal.input.text." + phase for phase in ("begin", "chunk", "commit", "abort")}
)


def terminal_literal(text):
    try:
        raw = text.encode("utf-8")
    except (AttributeError, UnicodeError):
        raise BridgeError("invalid_arguments", "Terminal input must be literal Unicode") from None
    if (
        not raw
        or len(raw) > 1024 * 1024
        or any(unicodedata.category(c) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for c in text)
    ):
        raise BridgeError("invalid_arguments", "Terminal input cannot contain control characters")
    return raw


def terminal_target_supported(row):
    """Logical scripting IDs never substitute for a confirmed physical single tab."""
    visual = row.get("visual_window_id")
    return (
        type(visual) is int
        and visual > 0
        and type(row.get("tab_count")) is int
        and row["tab_count"] == 1
        and row.get("identity_ambiguous") is False
        and row.get("selection_ambiguous") is False
    )


def terminal_text_plan(text, target, owner, terminal):
    raw = terminal_literal(text)
    chunks = utf16_chunks(text)
    binding = {
        "task_id": owner["task_id"],
        "principal": owner["principal"],
        "target": target,
        "submit": False,
        "utf8_bytes": len(raw),
        "utf16_units": sum(map(len, chunks)) // 2,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "chunk_count": len(chunks),
        "encoding": "utf-16-le",
        "route": "terminal_shell",
        "owner": owner,
        "terminal": terminal,
    }
    manifest = {"transfer_id": digest(binding), **binding}
    begin = {**manifest, "binding_json": canonical(binding)}
    packets = [
        {
            "transfer_id": manifest["transfer_id"],
            "index": i,
            "data_b64": base64.b64encode(c).decode(),
        }
        for i, c in enumerate(chunks)
    ]
    for operation, value in [
        ("terminal.input.text.begin", begin),
        *[("terminal.input.text.chunk", p) for p in packets],
    ]:
        native_frame_bytes(operation, value, principal=owner["principal"])
    return manifest, begin, packets


@dataclass(frozen=True)
class _OwnedTerminalStageCleanup:
    """Only the original staging memory; no input/Return verb or caller overrides."""

    transport: object
    begin_json: str
    stage_worker: object

    async def abort(self):
        begin = json.loads(self.begin_json)
        binding = json.loads(begin["binding_json"])
        if (
            binding != {k: v for k, v in begin.items() if k not in {"binding_json", "transfer_id"}}
            or binding["route"] != "terminal_shell"
            or binding["submit"] is not False
            or binding["task_id"] != binding["owner"]["task_id"]
            or binding["principal"] != binding["owner"]["principal"]
            or digest(binding) != begin["transfer_id"]
        ):
            raise BridgeError("terminal_stage_invalid", "Original terminal stage binding changed")
        child = self.stage_worker
        if child.returncode is not None or getattr(self.transport, "closed", False):
            return  # Never start a worker solely to clear its former memory.
        async with asyncio.timeout(1):
            await self.transport.request(
                "terminal.input.text.abort",
                {"transfer_id": begin["transfer_id"]},
                principal=binding["principal"],
                _existing_process=child,
            )


@dataclass
class TerminalInputAuthority:
    adapter: object
    owner: dict
    turn: object
    opening: bool = False
    inspect_sessions: bool = True
    origin_guard: object = None
    used: bool = False

    def check(self, operation):
        a = self.adapter
        a.desktop_input.require_turn(self.turn)
        if operation not in PRIVATE_OPERATIONS:
            raise BridgeError("terminal_authority_required", "Private terminal operation required")
        row = a.security.store.get(
            self.owner["task_id"], self.owner["principal"], resolve_output=False
        )
        actual = {
            "task_id": row["id"],
            "principal": row["principal"],
            "operation": row["operation"],
            "request_sha256": row["request_sha256"],
        }
        if actual != self.owner or row["state"] not in {"accepted", "running"}:
            raise BridgeError("terminal_authority_changed", "Original terminal task changed")
        a.security.authorize(actual["principal"], actual["operation"], text=row["args"].get("text"))
        a.security.principal(actual["principal"], "terminal.execute")
        if self.inspect_sessions or not (
            self.opening and actual["operation"] == "session.open" and not row["args"].get("argv")
        ):
            a.security.principal(actual["principal"], "session.inspect")
        if self.opening:
            a.security.principal(actual["principal"], "session.open")
        if not self.opening or actual["operation"] in {
            "terminal.visible",
            "terminal.execute",
            "admin.execute",
            "session.input",
        }:
            a.security.principal(actual["principal"], "session.input")
        if actual["operation"] == "agent.execute":
            policy = a.security.principal(actual["principal"], "agent.execute")
            if not self.opening or row["args"].get("agent") not in policy.agents:
                raise BridgeError("agent_denied", "Original configured agent grant required")
        if self.origin_guard is not None:
            self.origin_guard()

    async def submit(self, transport, row, text, identity, cwd):
        return await self.adapter.submit(self, transport, row, text, identity, cwd)


class TerminalNativeInput:
    def __init__(self, keyboard, security):
        self.keyboard, self.security = keyboard, security
        self.desktop_input = keyboard.desktop_input

    def bind(self, task, turn, *, opening=False, inspect_sessions=True, origin_guard=None):
        owner = {
            "task_id": task["id"],
            "principal": task["principal"],
            "operation": task["operation"],
            "request_sha256": task["request_sha256"],
        }
        if owner["operation"] not in ORIGIN_OPERATIONS:
            raise BridgeError("terminal_authority_required", "Original terminal task required")
        if not inspect_sessions and not opening:
            raise BridgeError(
                "terminal_authority_required", "Private inspection requires owned open"
            )
        authority = TerminalInputAuthority(
            self,
            copy.deepcopy(owner),
            turn,
            opening=opening,
            inspect_sessions=inspect_sessions,
            origin_guard=origin_guard,
        )
        authority.check("terminal.input.inspect")
        return authority

    def bind_stored(self, principal, task_id, turn, **options):
        return self.bind(
            self.security.store.get(task_id, principal, resolve_output=False), turn, **options
        )

    async def submit(self, authority, transport, row, text, identity, cwd):
        row = copy.deepcopy(row)
        terminal_literal(text)
        authority.check("terminal.input.inspect")
        if authority.used:
            raise BridgeError("terminal_input_consumed", "Original terminal dispatch is one-shot")
        authority.used = True
        if len(identity.split(None, 8)) != 9 or not cwd:
            raise BridgeError("visible_target_changed", "Detailed shell identity and CWD required")
        if not terminal_target_supported(row):
            raise BridgeError(
                "terminal_window_unsupported", "A confirmed physical single-tab shell is required"
            )
        cg = row["visual_window_id"]
        terminal = {
            "cg_window_id": cg,
            "tty": row["tty"],
            "shell_pid": row["expected_pid"],
            "shell_identity_sha256": hashlib.sha256(identity.encode()).hexdigest(),
            "cwd_sha256": hashlib.sha256(cwd.encode()).hexdigest(),
        }

        async def request(operation, value, *, before_send=None):
            return await self.keyboard.terminal_request_in_turn(
                authority, operation, value, authority.turn, before_send=before_send
            )

        async def guard(expected_screen=None):
            authority.check("terminal.input.return")
            if await transport.process_identity(row["expected_pid"], detailed=True) != identity:
                raise BridgeError("visible_target_changed", "Shell identity changed before Return")
            if (
                await transport.process_working_directory(
                    row["expected_pid"], expected_identity=identity
                )
                != cwd
            ):
                raise BridgeError("visible_target_changed", "Shell CWD changed before Return")
            catalog = await transport.catalog()
            matches = [r for r in catalog if r["pane_id"] == row["pane_id"]]
            if transport.last_catalog_incomplete or len(matches) != 1:
                raise BridgeError("visible_target_ambiguous", "Terminal inventory is incomplete")
            current = matches[0]
            if (
                current["expected_pid"] != row["expected_pid"]
                or current["tty"] != row["tty"]
                or current.get("visual_window_id") != cg
                or current.get("busy", True)
                or current.get("identity_ambiguous")
                or current.get("tab_count") != 1
                or current.get("selection_ambiguous")
                or not current.get("process_owner_verified")
                or [p["pid"] for p in current["processes"]] != [row["expected_pid"]]
            ):
                raise BridgeError("visible_target_changed", "Exact idle shell/window changed")
            screen = await transport.read(row["pane_id"])
            if expected_screen is not None and screen != expected_screen:
                raise BridgeError(
                    "visible_input_changed", "Typed terminal view changed; preserve it"
                )
            # Observe focus/tab/screen together immediately before the native Return request.
            await transport.native(
                transport.native_target(row["pane_id"])
                + transport.native_identity_guard({row["expected_pid"]: identity})
                + transport.native_focus_check(row["pane_id"])
                + "\ncheckFocus();if(tab.busy()||targetWindow.tabs().length!==1)"
                + "throw Error('Terminal changed');"
                + transport.native_screen_guard(screen)
                + "\nJSON.stringify({guarded:true});"
            )
            return screen

        began = committed = False
        manifest = cleanup = None
        try:
            apps = await request("apps.list", {"limit": 1000})
            terminals = [
                a for a in apps["applications"] if a.get("bundle_id") == "com.apple.Terminal"
            ]
            if apps.get("eof") is not True or len(terminals) != 1:
                raise BridgeError("visible_target_ambiguous", "Exact Terminal application required")
            app = terminals[0]
            observed = await request(
                "terminal.input.inspect",
                {
                    "pid": app["pid"],
                    "expected_started_at": app["started_at"],
                    "owner": authority.owner,
                    "terminal": terminal,
                },
            )
            target = observed["target"]
            manifest, begin, chunks = terminal_text_plan(text, target, authority.owner, terminal)
            reply = await request("terminal.input.text.begin", begin)
            began = True
            if (
                reply.get("transfer_id") != manifest["transfer_id"]
                or reply.get("state") != "accepted"
                or reply.get("input_attempted") is not False
            ):
                raise BridgeError("terminal_stage_invalid", "Terminal staging was not acknowledged")
            worker = getattr(self.keyboard.transport, "process", None)
            helper = reply.get("native_helper", {})
            if (
                worker is not None
                and worker.returncode is None
                and helper.get("pid") == worker.pid
                and helper.get("generation") == self.keyboard.transport.generation
            ):
                cleanup = _OwnedTerminalStageCleanup(
                    self.keyboard.transport, canonical(begin), worker
                )
            received = 0
            for index, chunk in enumerate(chunks):
                received += len(base64.b64decode(chunk["data_b64"])) // 2
                reply = await request("terminal.input.text.chunk", chunk)
                if (
                    reply.get("transfer_id") != manifest["transfer_id"]
                    or reply.get("state") != "received"
                    or reply.get("input_attempted") is not False
                    or type(reply.get("received_chunks")) is not int
                    or reply.get("received_chunks") != index + 1
                    or type(reply.get("received_utf16_units")) is not int
                    or reply.get("received_utf16_units") != received
                ):
                    raise BridgeError("terminal_stage_invalid", "Terminal chunk counts differ")

            async def commit_guard():
                nonlocal committed
                await guard()
                committed = True

            typed = await request(
                "terminal.input.text.commit",
                {"transfer_id": manifest["transfer_id"]},
                before_send=commit_guard,
            )
            caret = typed.get("selection_utf16")
            if not (
                typed.get("transfer_id") == manifest["transfer_id"]
                and typed.get("task_id") == authority.owner["task_id"]
                and typed.get("staging_verified") is True
                and typed.get("text_verified") is True
                and typed.get("selection_verified") is True
                and typed.get("return_posted") is False
                and typed.get("text_sha256") == manifest["sha256"]
                and isinstance(typed.get("value_sha256"), str)
                and len(typed["value_sha256"]) == 64
                and all(c in "0123456789abcdef" for c in typed["value_sha256"])
                and isinstance(caret, dict)
                and set(caret) == {"location", "length"}
                and type(caret["location"]) is int
                and caret["location"] >= 0
                and type(caret["length"]) is int
                and caret["length"] == 0
            ):
                raise UncertainExecution(
                    "terminal_text_unknown", "Literal terminal text is not verified"
                )
            screen = await transport.read(row["pane_id"])

            async def return_guard():
                await guard(screen)

            result = await request(
                "terminal.input.return",
                {
                    "transfer_id": manifest["transfer_id"],
                    "owner": authority.owner,
                    "target": target,
                    "expected_value_sha256": typed["value_sha256"],
                    "selection_utf16": typed["selection_utf16"],
                },
                before_send=return_guard,
            )
            if (
                result.get("return_posted") is not True
                or type(result.get("post_calls_returned")) is not int
                or result.get("post_calls_returned") != 2
                or result.get("transfer_id") != manifest["transfer_id"]
            ):
                raise UncertainExecution("terminal_return_unknown", "Return outcome is unconfirmed")
            return {"sent": True}
        except BaseException as error:
            if committed:
                raise UncertainExecution(
                    "terminal_input_unknown",
                    "Terminal text/Return outcome is uncertain; preserve input and never replay",
                    native_failure=getattr(error, "native_failure", None),
                ) from error
            if began and cleanup is not None:
                try:
                    await cleanup.abort()
                except BaseException:
                    pass
            raise
