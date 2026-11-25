"""Platform-native direct terminal work: macOS visible shell or Linux owned PTY."""

from __future__ import annotations

import asyncio
import json
import secrets
import shlex
import shutil
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
            "Allow a separate controlled macOS window when no confirmed-empty shell is "
            "available; ambiguous existing prompts are preserved. Linux direct argv always "
            "uses a fresh short-lived owned PTY, regardless of this option."
        ),
    )

    @model_validator(mode="after")
    def exact_pair(self):
        if (self.pane_id is None) != (self.expected_pid is None):
            raise ValueError("pane_id and expected_pid must be supplied together")
        return self


# Fields that identify a window and its process state. Layout fields (ui_window_count,
# tab_selected, visual_window_id, tab_index, tab_count) change when any other window opens,
# closes or is clicked and must not abort a dispatch that send_confirmed verifies natively.
_VOLATILE = {"ui_window_count", "tab_selected", "visual_window_id", "tab_index", "tab_count"}
# A candidate that vanished or became ambiguous between catalog and read is skipped, not fatal.
_SKIPPABLE = {"session_selection_changed", "visible_target_ambiguous", "visible_target_changed"}
_ACTIVE_TASK_ENV = "KIRABRIDGE_ACTIVE_TERMINAL_TASK_ID"
_ACTIVE_PRINCIPAL_ENV = "KIRABRIDGE_ACTIVE_TERMINAL_PRINCIPAL"


def _same_target(left, right):
    return {k: v for k, v in left.items() if k not in _VOLATILE} == {
        k: v for k, v in right.items() if k not in _VOLATILE
    }


def _unsuitable_code(row):
    """The real reason a window is not a typing target, instead of a blanket session_busy."""
    if row.get("miniaturized"):
        return "visible_target_minimized", "Selected window is minimized to the Dock"
    if not row.get("processes"):
        return "visible_target_not_shell", "Selected window has no live shell"
    if row.get("busy", True):
        return "session_busy", "Selected window is busy"
    return "session_busy", "Selected window is not a confirmed empty shell"


def build_command_script(
    tty, cwd, argv, nonce, folder, result_path, *, task_id=None, task_principal=None
):
    """The one-shot zsh script typed into the visible window (never run by KiraBridge itself)."""
    ok = json.dumps({"nonce": nonce, "exit_code": "%s"}).replace('"%s"', "%s")
    setup_failed = json.dumps({"nonce": nonce, "exit_code": 125, "phase": "setup"})
    interrupted = json.dumps({"nonce": nonce, "exit_code": 130, "phase": "interrupted"})
    tmp_path = shlex.quote(str(folder / "result.tmp"))
    final = shlex.quote(str(result_path))
    # Every way out writes a receipt atomically (temp file, then rename): a failed
    # window/cwd check or an interrupt is reported at once instead of after the timeout.
    script = (
        "#!/bin/zsh -f\numask 077\n"
        + (
            "export " + _ACTIVE_TASK_ENV + "=" + shlex.quote(task_id) + "\n"
            if isinstance(task_id, str) and task_id
            else ""
        )
        + (
            "export " + _ACTIVE_PRINCIPAL_ENV + "=" + shlex.quote(task_principal) + "\n"
            if isinstance(task_principal, str) and task_principal
            else ""
        )
        + "kb_done() { printf "
        + shlex.quote("%s\n")
        + ' "$1" > '
        + tmp_path
        + " && /bin/mv -f "
        + tmp_path
        + " "
        + final
        + "; }\n"
        + "kb_int() { kb_done "
        + shlex.quote(interrupted)
        + "; exit 130; }\n"
        + "trap kb_int INT TERM HUP\n"
        + '[[ "$(/usr/bin/tty)" == '
        + shlex.quote(tty)
        + " ]] || { kb_done "
        + shlex.quote(setup_failed)
        + "; exit 125; }\n"
        + "cd -- "
        + shlex.quote(cwd)
        + " || { kb_done "
        + shlex.quote(setup_failed)
        + "; exit 125; }\n"
        + shlex.join(argv)
        + "\nkb_status=$?\n"
        + 'kb_done "$(printf '
        + shlex.quote(ok)
        + ' "$kb_status")"\n'
    )
    return script


COMMAND_FOLDER_MAX_AGE = 3 * 86400


def prune_command_folders(root, *, now=None, max_age=COMMAND_FOLDER_MAX_AGE):
    """Remove one-shot command folders (script with argv, receipt) older than ``max_age``.

    Only direct children named like a 32-character hex token are touched, so nothing else in
    the state directory is ever removed. Recent folders stay for late-receipt reconciliation.
    """
    removed, now = 0, time.time() if now is None else now
    try:
        children = list(Path(root).iterdir())
    except OSError:
        return removed
    for child in children:
        name = child.name
        if len(name) != 32 or any(c not in "0123456789abcdef" for c in name):
            continue
        try:
            if child.is_dir() and not child.is_symlink() and now - child.stat().st_mtime > max_age:
                shutil.rmtree(child, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    return removed


class VisibleTerminal:
    def __init__(self, config, security, sessions, environment):
        self.config, self.security, self.sessions, self.environment = (
            config,
            security,
            sessions,
            environment,
        )
        self.open_lock = asyncio.Lock()
        self.open_generation = 0

    async def _select_candidate(self, principal, sessions):
        unconfirmed_input, skipped = None, None
        for candidate in sorted(sessions, key=lambda item: item["pane_id"]):
            try:
                if await self.suitable(principal, candidate):
                    return candidate, unconfirmed_input, skipped
            except BridgeError as error:
                if error.code in _SKIPPABLE:
                    skipped = skipped or error
                    continue
                if error.code != "visible_input_unknown":
                    raise
                unconfirmed_input = error
        return None, unconfirmed_input, skipped

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
        if row.get("controlled_shell") is True:
            readiness = getattr(self.sessions, "zle_readiness", None)
            if readiness is None:
                raise BridgeError(
                    "zle_session_stale", "Controlled shell ZLE channel is unavailable"
                )
            await readiness.probe(row)
        elif not empty_shell_prompt(output["text"]):
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
                task_environment = dict(self.environment)
                task_environment[_ACTIVE_TASK_ENV] = task["id"]
                task_environment[_ACTIVE_PRINCIPAL_ENV] = task["principal"]
                result = await self.sessions.linux.execute_argv(
                    argv,
                    cwd_fd,
                    task_environment,
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
        unconfirmed_input, skipped, opened = None, None, None
        async with bridge.sessions.lock:
            if args.pane_id:
                row = await bridge.sessions.selected(principal, args.pane_id, args.expected_pid)
                if not await self.suitable(principal, row):
                    code, message = _unsuitable_code(row)
                    raise BridgeError(code, message)
            else:
                selection_generation = self.open_generation
                catalog = await bridge.sessions.catalog(principal)
                error = catalog.get("transport_errors", {}).get("terminal_app")
                if error:
                    raise BridgeError(error["code"], error.get("message", "Terminal unavailable"))
                # The lowest pane id with fresh empty-shell evidence is used, so checking
                # stops at the first suitable window instead of reading every idle shell.
                row, unconfirmed_input, skipped = await self._select_candidate(
                    principal, catalog["sessions"]
                )
                if row is None:
                    if unconfirmed_input is None and skipped is not None:
                        # Nothing else was usable: name the real problem, never open a window.
                        raise skipped
                    if unconfirmed_input is not None and not args.create_if_needed:
                        # Never infer emptiness or overwrite a draft. An explicit
                        # request to create a new shell may safely preserve this
                        # target and continue in a separate controlled window.
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

            async with self.open_lock:
                # Recheck only if another automatic open happened while we waited;
                # a normal first open needs no extra native catalogue roundtrip.
                if self.open_generation != selection_generation:
                    async with bridge.sessions.lock:
                        catalog = await bridge.sessions.catalog(principal)
                        if catalog.get("transport_errors", {}).get("terminal_app"):
                            error = catalog["transport_errors"]["terminal_app"]
                            raise BridgeError(
                                error["code"], error.get("message", "Terminal unavailable")
                            )
                        row, rechecked_input, _skipped = await self._select_candidate(
                            principal, catalog["sessions"]
                        )
                        unconfirmed_input = unconfirmed_input or rechecked_input
                        if row is not None:
                            reference = SessionReference(
                                pane_id=row["pane_id"], expected_pid=row["expected_pid"]
                            )
                if reference is None:
                    open_options = {"task_id": task["id"]}
                    if progress is not None:
                        open_options["on_created"] = window_created
                    opened = await bridge.sessions.open(
                        principal, SessionOpen(cwd=cwd, controlled_shell=True), **open_options
                    )
                    self.open_generation += 1
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
                                "visible_shell_not_ready",
                                "New window has no confirmed empty prompt",
                            )
        root = bridge.config.state_path / "visible-commands"
        from kirabridge.bridge_core.config import private_directory

        private_directory(root)
        prune_command_folders(root)
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
        script = build_command_script(
            row["tty"],
            cwd,
            argv,
            nonce,
            folder,
            result_path,
            task_id=task["id"],
            task_principal=task["principal"],
        )
        write_private(script_path, script)
        async with bridge.sessions.lock:
            current = await bridge.sessions.selected(
                principal, reference.pane_id, reference.expected_pid
            )
            if not _same_target(current, row) or not await self.suitable(
                principal, current, read_screen=False
            ):
                raise BridgeError(
                    "visible_target_changed", "Visible shell changed before dispatch; no input"
                )
            identity = await bridge.sessions.terminal_app.process_identity(reference.expected_pid)
            await running(
                {"execution_route": "visible_terminal", **reference.model_dump(), "tty": row["tty"]}
            )
            await bridge.sessions.terminal_app.send_confirmed(
                current,
                "/bin/zsh -f " + shlex.quote(str(script_path)),
                identity,
                require_physical_visibility=True,
                principal=principal,
            )
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            if result_path.exists():
                result = private_json(result_path)
                if result.get("nonce") != nonce or type(result.get("exit_code")) is not int:
                    raise UncertainExecution(
                        "visible_result_unknown", "Unexpected visible command receipt"
                    )
                if result.get("phase") == "setup":
                    # The script refused to run: wrong terminal or unusable cwd. Nothing ran.
                    shutil.rmtree(folder, ignore_errors=True)
                    raise BridgeError(
                        "visible_target_changed",
                        "The window or directory changed before the command ran; nothing ran",
                    )
                if result.get("phase") == "interrupted":
                    shutil.rmtree(folder, ignore_errors=True)
                    raise BridgeError(
                        "visible_command_interrupted", "The command was interrupted in the window"
                    )
                # Output is informational: reuse the row observed at dispatch instead of
                # another full window catalogue just to return the screen.
                with bridge.sessions.observation_scope(principal, current):
                    output = await bridge.sessions.read(
                        principal, reference.pane_id, reference.expected_pid
                    )
                # The receipt is read: the script (it holds the argv) is no longer needed.
                shutil.rmtree(folder, ignore_errors=True)
                return {
                    **reference.model_dump(),
                    "tty": row["tty"],
                    "execution_route": "visible_terminal",
                    "terminal_target": {
                        "route": "new_controlled_visible_shell"
                        if opened is not None
                        else "existing_visible_shell",
                        "preserved_existing_input_issue": (
                            unconfirmed_input.code if unconfirmed_input is not None else None
                        ),
                    },
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
