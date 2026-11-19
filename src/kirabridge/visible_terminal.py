"""Platform-native direct terminal work: macOS visible shell or Linux owned PTY."""

from __future__ import annotations

import asyncio
import json
import secrets
import shlex
import time
from pathlib import Path

from pydantic import Field, model_validator

from kirabridge.bridge_core.models import BridgeError, TerminalInput, UncertainExecution
from kirabridge.filesystem_manager import PathScope
from kirabridge.platform_adapters import current_platform
from kirabridge.platform_adapters.shell_prompt import empty_shell_prompt
from kirabridge.private_files import private_json, write_private
from kirabridge.session_manager import SessionOpen, SessionReference
from kirabridge.terminal_manager import check_executable
from kirabridge.timing import timed


class VisibleTerminalInput(TerminalInput):
    pane_id: str | None = Field(default=None, pattern=r"^terminal:[0-9]+:ttys[0-9]+$")
    expected_pid: int | None = Field(default=None, gt=0)
    create_if_needed: bool = Field(
        default=True,
        description=(
            "Allow a new visible macOS window. Linux direct argv always uses a fresh "
            "short-lived owned PTY; this option does not select or create a persistent session."
        ),
    )

    @model_validator(mode="after")
    def exact_pair(self):
        if (self.pane_id is None) != (self.expected_pid is None):
            raise ValueError("pane_id and expected_pid must be supplied together")
        return self


class VisibleTerminal:
    def __init__(self, config, security, sessions, environment):
        self.config, self.security, self.sessions, self.environment = (
            config,
            security,
            sessions,
            environment,
        )

    async def suitable(self, principal, row, *, read_screen=True):
        if (
            row.get("transport") != "terminal_app"
            or row.get("busy", True)
            or not row.get("processes")
            # A window minimized to the Dock cannot be brought front by the focus step.
            or row.get("miniaturized")
        ):
            return False
        # Idle shell only: an interactive agent/editor is never an interchangeable shell.
        processes = row["processes"]
        if any(p["name"].lstrip("-") not in {"login", "zsh", "bash", "sh"} for p in processes):
            return False
        self.security.principal(principal, "session.inspect")
        if row.get("identity_ambiguous"):
            raise BridgeError(
                "visible_target_ambiguous", "Several live tabs report this tty; no input"
            )
        if not read_screen:
            # Row checks only. The native dispatch reads the screen and confirms the empty
            # prompt itself in the same call (send_confirmed), so no second read is needed.
            return True
        # The caller just observed this row. Scope only this fresh screen read;
        # final selection and native dispatch still verify input authority anew.
        with self.sessions.observation_scope(principal, row):
            output = await self.sessions.read(principal, row["pane_id"], row["expected_pid"])
        if not empty_shell_prompt(output["text"]):
            error = BridgeError(
                "visible_input_unknown",
                "Selected process is an idle shell, but empty input is not confirmed; preserve it",
            )
            error.provider_error = {"process_state": "idle_shell", "input_state": "unknown"}
            raise error
        return True

    async def execute(self, task, args, running, *, progress=None, privileged=False):
        bridge, principal = self, task["principal"]
        policy = bridge.security.principal(principal, "terminal.execute")
        bridge.security.principal(principal, "session.inspect")
        bridge.security.principal(principal, "session.input")
        scope = PathScope(policy.terminal_roots or policy.roots)
        scope.split(args.cwd)
        cwd = str(Path(args.cwd).resolve(strict=True))
        scope.split(cwd)
        executable = check_executable(
            args.argv[0],
            policy.executables,
            policy.allow_any_executable,
            self.environment["PATH"],
        )
        argv = [executable, *args.argv[1:]]
        if current_platform().name == "linux":
            if args.pane_id is not None:
                raise BridgeError(
                    "unsupported_terminal_target",
                    "Linux direct commands use a fresh owned PTY; "
                    "use session.input for a selected session",
                )
            if privileged:
                raise BridgeError(
                    "unsupported_platform", "Privileged visible terminal execution requires macOS"
                )
            if any("\x00" in item for item in argv):
                raise BridgeError("invalid_arguments", "NUL in command")
            # Opening the directory is read-only and descriptor-bound. No session or
            # executable is created by readiness or before authorization above.
            with scope.directory(cwd) as cwd_fd:
                result = await self.sessions.linux.execute_argv(
                    argv,
                    cwd_fd,
                    self.environment,
                    timeout=args.timeout,
                    max_output=args.max_output,
                    running=running,
                )
            return {**result, "cwd": cwd, "task_id": task["id"]}
        if privileged:
            self.security.principal(principal, "admin.execute")
            # Authorization stays in the confirmed visible TTY; the user types any
            # required OS credential there. No password is read/stored by KiraBridge.
            argv = ["/usr/bin/sudo", "--", *argv]
        if any("\x00" in item for item in argv):
            raise BridgeError("invalid_arguments", "NUL in command")
        async with bridge.sessions.lock:
            if args.pane_id:
                row = await bridge.sessions.selected(principal, args.pane_id, args.expected_pid)
                if not await self.suitable(principal, row):
                    raise BridgeError(
                        "session_busy", "Selected window is not a confirmed empty shell"
                    )
            else:
                catalog = await bridge.sessions.catalog(principal)
                error = catalog.get("transport_errors", {}).get("terminal_app")
                if error:
                    raise BridgeError(error["code"], error.get("message", "Terminal unavailable"))
                row, unconfirmed_input = None, None
                # The lowest pane id with fresh empty-shell evidence is used, so checking
                # stops at the first suitable window instead of reading every idle shell.
                for candidate in sorted(catalog["sessions"], key=lambda item: item["pane_id"]):
                    try:
                        if await self.suitable(principal, candidate):
                            row = candidate
                            break
                    except BridgeError as error:
                        if error.code != "visible_input_unknown":
                            raise
                        unconfirmed_input = error
                if row is None:
                    if unconfirmed_input is not None:
                        # An ambiguous existing shell is not evidence that more
                        # windows are needed. Preserve it and report input state.
                        raise unconfirmed_input
                    if not args.create_if_needed:
                        raise BridgeError(
                            "visible_shell_missing", "No unique suitable visible shell"
                        )
                    # Do not acquire sessions.lock recursively; open has its own lock.
            if row is not None:
                reference = SessionReference(
                    pane_id=row["pane_id"], expected_pid=row["expected_pid"]
                )
            else:
                reference = None
        if reference is None:

            async def window_created(receipt):
                await progress(
                    {
                        "evidence_type": "session_window_created",
                        "creation_receipt": receipt,
                        "automatic_retry": False,
                    }
                )

            open_options = {"task_id": task["id"]}
            if progress is not None:
                open_options["on_created"] = window_created
            opened = await bridge.sessions.open(
                principal, SessionOpen(cwd=cwd, controlled_shell=True), **open_options
            )
            if opened.get("session_handle_pending"):
                raise UncertainExecution(
                    "visible_window_pending", "Window opened; reconcile this task"
                )
            reference = SessionReference(
                pane_id=opened["pane_id"], expected_pid=opened["expected_pid"]
            )
            # A newly created shell must finish startup before its first command.
            with timed("visible_shell_wait") as wait_fields:
                for attempt in range(1, 41):
                    wait_fields["attempts"] = attempt
                    catalog = await bridge.sessions.catalog(principal)
                    matches = [
                        candidate
                        for candidate in catalog["sessions"]
                        if candidate["pane_id"] == opened["pane_id"]
                        and candidate.get("tty") == opened.get("tty")
                    ]
                    if len(matches) == 1:
                        row = matches[0]
                        reference = SessionReference(
                            pane_id=row["pane_id"], expected_pid=row["expected_pid"]
                        )
                        try:
                            if await self.suitable(principal, row):
                                break
                        except BridgeError as exc:
                            if exc.code not in {
                                "session_selection_changed",
                                "visible_input_unknown",
                            }:
                                raise
                    await asyncio.sleep(0.1)
                else:
                    raise BridgeError(
                        "visible_shell_not_ready", "New window has no confirmed empty prompt"
                    )
        root = bridge.config.state_path / "visible-commands"
        from kirabridge.bridge_core.config import private_directory

        private_directory(root)
        folder = root / secrets.token_hex(16)
        folder.mkdir(mode=0o700)
        result_path, script_path = folder / "result.json", folder / "command.zsh"
        nonce = secrets.token_hex(24)
        # Keep the observation that selected this reference as the comparison
        # baseline. The locked selection below is fresh and must still match it;
        # another catalogue here would only replace that baseline before the
        # same final revalidation, adding a native roundtrip without authority.
        # A one-shot script in this window inherits its real TTY. No subprocess
        # daemon, tmux pane, detached session or provider adapter executes the command.
        result = json.dumps({"nonce": nonce, "exit_code": "%s"}).replace('"%s"', "%s")
        script = (
            "#!/bin/zsh -f\numask 077\n"
            + '[[ "$(/usr/bin/tty)" == '
            + shlex.quote(row["tty"])
            + " ]] || exit 125\n"
            + "cd -- "
            + shlex.quote(cwd)
            + " || exit 125\n"
            + shlex.join(argv)
            + "\nkb_status=$?\n"
            + "printf "
            + shlex.quote(result + "\n")
            + ' "$kb_status" > '
            + shlex.quote(str(result_path))
            + "\n"
        )
        write_private(script_path, script)
        async with bridge.sessions.lock:
            current = await bridge.sessions.selected(
                principal, reference.pane_id, reference.expected_pid
            )
            if current != row or not await self.suitable(principal, current, read_screen=False):
                raise BridgeError(
                    "visible_target_changed", "Visible shell changed before dispatch; no input"
                )
            identity = await bridge.sessions.terminal_app.process_identity(reference.expected_pid)
            await running(
                {"execution_route": "visible_terminal", **reference.model_dump(), "tty": row["tty"]}
            )
            await bridge.sessions.terminal_app.send_confirmed(
                current, "/bin/zsh -f " + shlex.quote(str(script_path)), identity
            )
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            if result_path.exists():
                result = private_json(result_path)
                if result.get("nonce") != nonce or type(result.get("exit_code")) is not int:
                    raise UncertainExecution(
                        "visible_result_unknown", "Unexpected visible command receipt"
                    )
                # Output is informational: reuse the row observed at dispatch instead of
                # another full window catalogue just to return the screen.
                with bridge.sessions.observation_scope(principal, current):
                    output = await bridge.sessions.read(
                        principal, reference.pane_id, reference.expected_pid
                    )
                return {
                    **reference.model_dump(),
                    "tty": row["tty"],
                    "execution_route": "visible_terminal",
                    "exit_code": result["exit_code"],
                    "success": result["exit_code"] == 0,
                    "terminal_output": output["text"],
                    "output_scope": "visible screen; includes prompt/history",
                    "timed_out": False,
                    "terminated": False,
                    "evidence": {
                        "visible_window_confirmed": True,
                        "tty_checked_in_window": True,
                        "exit_code": result["exit_code"],
                        "automatic_retry": False,
                    },
                }
            await asyncio.sleep(0.1)
        # The visible foreground command is deliberately left alone. Its unknown
        # outcome must not cause an automatic resend or interruption of the window.
        raise UncertainExecution(
            "visible_command_pending", "Visible command still unconfirmed; do not resend"
        )
