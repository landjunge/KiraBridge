"""Two-phase terminal dispatch without native apps, OS input or production stores."""

import asyncio
import base64
import copy
import hashlib
import inspect
from types import SimpleNamespace

import pytest

from kirabridge.bridge_core.models import BridgeError, UncertainExecution
from kirabridge.desktop_input import DesktopInput, InputTurn
from kirabridge.keyboard_manager import KeyboardManager
from kirabridge.terminal_input import TerminalNativeInput, terminal_literal


class Native:
    def __init__(self, shell):
        self.shell, self.calls, self.manifest, self.received = shell, [], None, 0
        self.mode = None
        self.process = SimpleNamespace(pid=5, returncode=None)
        self.generation = "12345678-1234-1234-1234-123456789012"
        self.stage = None

    async def request(
        self, operation, args, *, principal, before_send=None, _existing_process=None
    ):
        if _existing_process is not None and (
            self.process is not _existing_process or _existing_process.returncode is not None
        ):
            raise BridgeError("system_stage_worker_changed", "Original stage worker changed")
        if before_send:
            result = before_send()
            if inspect.isawaitable(result):
                await result
        self.calls.append((operation, principal, copy.deepcopy(args)))
        if operation == "apps.list":
            return {
                "eof": True,
                "applications": [
                    {"bundle_id": "com.apple.Terminal", "pid": 4, "started_at": 100.0}
                ],
            }
        if operation == "terminal.input.inspect":
            return {
                "target": {
                    "pid": 4,
                    "expected_started_at": 100.0,
                    "target_token": "a" * 32,
                    "helper_pid": 5,
                    "worker_generation": "12345678-1234-1234-1234-123456789012",
                    "expected_revision": "b" * 64,
                }
            }
        if operation.endswith(".begin"):
            self.manifest = args
            self.stage = {
                "transfer_id": args["transfer_id"],
                "principal": principal,
                "family": "terminal.input.text",
            }
            if self.mode == "begin_revoked":
                self.shell.security.denied = "session.input"
            if self.mode == "begin_request_changed":
                self.shell.security.row["request_sha256"] = "e" * 64
            if self.mode in {"foreign_principal", "foreign_transfer", "foreign_family"}:
                self.shell.security.denied = "session.input"
                if self.mode == "foreign_principal":
                    self.stage["principal"] = "foreign-owner"
                elif self.mode == "foreign_transfer":
                    self.stage["transfer_id"] = "f" * 64
                else:
                    self.stage["family"] = "keyboard.text"
            return {
                "transfer_id": args["transfer_id"],
                "state": "accepted",
                "input_attempted": False,
                "native_helper": {"pid": self.process.pid, "generation": self.generation},
            }
        if operation.endswith(".chunk"):
            self.received += len(base64.b64decode(args["data_b64"])) // 2
            return {
                "transfer_id": args["transfer_id"],
                "state": "received",
                "input_attempted": False,
                "received_chunks": args["index"] + 1,
                "received_utf16_units": self.received,
            }
        if operation.endswith(".commit"):
            self.shell.text = "prompt> /bin/echo literal"
            if self.mode == "cwd_changed":
                self.shell.cwd = "/other"
            if self.mode == "screen_changed":
                self.shell.change_on_return = True
            if self.mode == "revoked":
                self.shell.security.denied = "session.input"
            if self.mode == "terminal_execute_revoked":
                self.shell.security.denied = "terminal.execute"
            if self.mode == "request_changed":
                self.shell.security.row["request_sha256"] = "e" * 64
            if self.mode == "identity_changed":
                self.shell.identity += " changed"
            if self.mode == "tty_changed":
                self.shell.row["tty"] = "/dev/ttys999"
            if self.mode == "window_changed":
                self.shell.row["visual_window_id"] = 100
            if self.mode == "new_child":
                self.shell.row["processes"].append({"pid": 43})
            return {
                "transfer_id": args["transfer_id"],
                "task_id": self.manifest["task_id"],
                "staging_verified": True,
                "text_verified": self.mode != "lost_leading_slash",
                "selection_verified": True,
                "return_posted": False,
                "text_sha256": self.manifest["sha256"],
                "value_sha256": hashlib.sha256(self.shell.text.encode()).hexdigest(),
                "selection_utf16": {"location": len(self.shell.text), "length": 0},
            }
        if operation == "terminal.input.return":
            return {
                "transfer_id": args["transfer_id"],
                "return_posted": True,
                "post_calls_returned": 2,
            }
        if operation.endswith(".abort"):
            if self.stage != {
                "transfer_id": args["transfer_id"],
                "principal": principal,
                "family": "terminal.input.text",
            }:
                raise BridgeError("stage_owner_mismatch", "Foreign stage preserved")
            self.stage = None
            return {"state": "aborted"}
        raise AssertionError(operation)


class Shell:
    identity = "501 ttys000 Sat Nov 14 00:50:33 2026 20 -zsh"

    def __init__(self):
        self.cwd, self.text = "/owned", "prompt> "
        self.last_catalog_incomplete = False
        self.change_on_return, self.guard_reads = False, 0
        self.row = {
            "pane_id": "terminal:10:ttys000",
            "window_id": 10,
            "visual_window_id": 99,
            "tty": "/dev/ttys000",
            "expected_pid": 42,
            "busy": False,
            "identity_ambiguous": False,
            "tab_count": 1,
            "selection_ambiguous": False,
            "process_owner_verified": True,
            "processes": [{"pid": 42}],
        }

    async def process_identity(self, *_args, **_kwargs):
        return self.identity

    async def process_working_directory(self, *_args, **_kwargs):
        return self.cwd

    async def catalog(self):
        return [copy.deepcopy(self.row)]

    async def read(self, *_):
        if self.change_on_return:
            self.guard_reads += 1
            if self.guard_reads > 1:
                return self.text + "user input"
        return self.text

    native_target = staticmethod(lambda *_: "target;")
    native_identity_guard = staticmethod(lambda *_: "identity;")
    native_focus_check = staticmethod(lambda *_: "focus;")
    native_screen_guard = staticmethod(lambda *_: "screen;")

    async def native(self, *_args, **_kwargs):
        return {"guarded": True}


class Security:
    def __init__(self):
        self.row = {
            "id": "real-terminal-task",
            "principal": "actual-owner",
            "operation": "terminal.visible",
            "request_sha256": "d" * 64,
            "state": "running",
            "args": {},
        }
        self.store, self.denied, self.checked = self, None, []

    def get(self, task_id, principal, **_):
        if task_id != self.row["id"] or principal != self.row["principal"]:
            raise BridgeError("not_found", "Owned task missing")
        return copy.deepcopy(self.row)

    def principal(self, principal, operation):
        assert principal == "actual-owner"
        self.checked.append(operation)
        if operation == self.denied:
            raise BridgeError("forbidden", "Capability revoked")
        return SimpleNamespace(agents={"codex"})

    def authorize(self, principal, operation, **_):
        self.principal(principal, operation)


def setup():
    shell, security = Shell(), Security()
    shell.security = security
    native = Native(shell)
    desktop = DesktopInput(asyncio.Lock())
    keyboard = KeyboardManager(
        transport=native, desktop_input=desktop, authorize=security.authorize
    )
    adapter = TerminalNativeInput(keyboard, security)
    return shell, security, native, desktop, adapter


async def submit(case):
    shell, security, native, desktop, adapter = case
    async with desktop.transaction() as turn:
        authority = adapter.bind(copy.deepcopy(security.row), turn)
        return await authority.submit(
            shell, shell.row, "/bin/echo literal", shell.identity, "/owned"
        )


async def test_original_task_authority_and_single_turn_are_retained_without_keyboard_grants():
    case = setup()
    case[0].row.update(window_id=12674, visual_window_id=10621, pane_id="terminal:12674:ttys000")
    assert await submit(case) == {"sent": True}
    shell, security, native, desktop, _ = case
    assert not desktop.lock.locked()
    assert not any(op.startswith("keyboard.") for op in security.checked)
    assert all(principal == "actual-owner" for _, principal, _ in native.calls)
    begin = next(args for op, _, args in native.calls if op.endswith(".begin"))
    assert begin["owner"] == {
        k: security.row[k] for k in ("principal", "operation", "request_sha256")
    } | {"task_id": security.row["id"]}
    assert begin["submit"] is False and begin["terminal"]["cg_window_id"] == 10621
    assert begin["terminal"]["cg_window_id"] != case[0].row["window_id"]
    assert [op for op, _, _ in native.calls].count("terminal.input.return") == 1


@pytest.mark.parametrize(
    "operation", ["terminal.execute", "terminal.visible", "admin.execute", "session.input"]
)
async def test_real_origin_operation_remains_unchanged(operation):
    case = setup()
    case[1].row["operation"] = operation
    assert await submit(case) == {"sent": True}
    begin = next(args for op, _, args in case[2].calls if op.endswith(".begin"))
    assert begin["owner"]["operation"] == operation


@pytest.mark.parametrize("operation", ["session.open", "agent.execute"])
async def test_owned_window_argv_uses_its_existing_session_and_agent_authority(operation):
    shell, security, native, desktop, adapter = setup()
    security.row.update(operation=operation, args={"agent": "codex"})
    async with desktop.transaction() as turn:
        authority = adapter.bind(security.row, turn, opening=True)
        assert await authority.submit(
            shell, shell.row, "/bin/echo literal", shell.identity, "/owned"
        ) == {"sent": True}
    assert "session.open" in security.checked and "terminal.execute" in security.checked
    assert "session.input" not in security.checked
    assert not any(op.startswith("keyboard.") for op in security.checked)


async def test_agent_origin_cannot_be_used_outside_its_owned_window_start():
    shell, security, native, desktop, adapter = setup()
    security.row.update(operation="agent.execute", args={"agent": "codex"})
    async with desktop.transaction() as turn:
        with pytest.raises(BridgeError, match="agent grant"):
            adapter.bind(security.row, turn)
    assert native.calls == []


@pytest.mark.parametrize("operation", ["session.open", "terminal.visible"])
async def test_private_open_hint_cannot_remove_existing_inspection_rights(operation):
    shell, security, native, desktop, adapter = setup()
    security.row.update(operation=operation, args={"argv": ["/bin/echo"]})
    security.denied = "session.inspect"
    async with desktop.transaction() as turn:
        with pytest.raises(BridgeError):
            adapter.bind(security.row, turn, opening=True, inspect_sessions=False)
    assert native.calls == []


@pytest.mark.parametrize(
    "mode",
    [
        "lost_leading_slash",
        "cwd_changed",
        "screen_changed",
        "revoked",
        "terminal_execute_revoked",
        "request_changed",
        "identity_changed",
        "tty_changed",
        "window_changed",
        "new_child",
    ],
)
async def test_unverified_text_or_prereturn_change_is_unknown_without_return_or_clear(mode):
    case = setup()
    case[2].mode = mode
    with pytest.raises(UncertainExecution, match="preserve input"):
        await submit(case)
    assert "terminal.input.return" not in [op for op, _, _ in case[2].calls]
    assert case[0].text == "prompt> /bin/echo literal"
    assert not case[3].lock.locked()


@pytest.mark.parametrize("mode", ["begin_revoked", "begin_request_changed"])
async def test_revoked_authority_cleans_only_its_original_staging_memory_without_input(mode):
    case = setup()
    case[2].mode = mode
    with pytest.raises(BridgeError):
        await submit(case)
    assert [op for op, _, _ in case[2].calls] == [
        "apps.list",
        "terminal.input.inspect",
        "terminal.input.text.begin",
        "terminal.input.text.abort",
    ]
    assert case[2].stage is None
    assert case[2].calls[-1][1:] == (
        "actual-owner",
        {"transfer_id": case[2].manifest["transfer_id"]},
    )
    assert case[0].text == "prompt> " and not case[3].lock.locked()


@pytest.mark.parametrize("mode", ["foreign_principal", "foreign_transfer", "foreign_family"])
async def test_abort_only_cleanup_preserves_a_foreign_stage(mode):
    case = setup()
    case[2].mode = mode
    with pytest.raises(BridgeError):
        await submit(case)
    assert case[2].stage is not None
    assert case[2].calls[-1][0] == "terminal.input.text.abort"
    assert case[2].calls[-1][1:] == (
        "actual-owner",
        {"transfer_id": case[2].manifest["transfer_id"]},
    )
    assert not any(
        op.endswith(".commit") or op == "terminal.input.return" for op, _, _ in case[2].calls
    )
    assert case[0].text == "prompt> "


@pytest.mark.parametrize(
    "key,bad",
    [("request_sha256", "e" * 64), ("operation", "keyboard.text"), ("principal", "invented-owner")],
)
async def test_mismatched_persisted_original_authority_is_rejected_before_native_input(key, bad):
    shell, security, native, desktop, adapter = setup()
    task = copy.deepcopy(security.row)
    task[key] = bad
    async with desktop.transaction() as turn:
        with pytest.raises(BridgeError):
            adapter.bind(task, turn)
    assert native.calls == []


async def test_missing_expired_or_foreign_turn_cannot_authorize_terminal_input():
    shell, security, native, desktop, adapter = setup()
    with pytest.raises(BridgeError, match="desktop turn"):
        adapter.bind(security.row, InputTurn())
    async with desktop.transaction() as turn:
        authority = adapter.bind(security.row, turn)

        async def foreign():
            authority.check("terminal.input.inspect")

        with pytest.raises(BridgeError, match="desktop turn"):
            await asyncio.create_task(foreign())
    with pytest.raises(BridgeError, match="desktop turn"):
        authority.check("terminal.input.inspect")
    assert native.calls == []


@pytest.mark.parametrize(
    "control",
    ["\t", "\r", "\n", "\x00", "\x1b", "\x7f", "\u0085", "\u2028", "\u2029", "\ufeff", "\u202e"],
)
def test_terminal_controls_cannot_submit_while_typing(control):
    with pytest.raises(BridgeError):
        terminal_literal("/bin/echo " + control + " hidden")


def test_literal_unicode_is_preserved_without_normalization():
    value = "/bin/echo '日本語 e\u0301 😀'"
    assert terminal_literal(value) == value.encode()
