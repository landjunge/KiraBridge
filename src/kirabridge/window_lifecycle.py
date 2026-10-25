"""Ownership journal and guarded cleanup for windows created by this bridge only."""

import asyncio
import time

from kirabridge.bridge_core.models import BridgeError
from kirabridge.platform_adapters.shell_prompt import empty_shell_prompt, idle_shell


class OwnedWindows:
    def __init__(self, store, sessions):
        self.store, self.sessions = store, sessions
        self.reaper = None
        self.last_error = None
        self.leases = {}
        with store.transaction():
            store.db.execute(
                "CREATE TABLE IF NOT EXISTS owned_terminal_windows ("
                "pane_id TEXT PRIMARY KEY, principal TEXT NOT NULL, expected_pid INTEGER NOT NULL,"
                "tty TEXT NOT NULL, identity TEXT NOT NULL, task_id TEXT NOT NULL,"
                "created REAL NOT NULL,"
                "state TEXT NOT NULL, result_path TEXT, nonce TEXT)"
            )

    async def register(self, principal, task_id, row):
        identity = await self.sessions.terminal_app.process_identity(row["expected_pid"])
        with self.store.transaction():
            written = self.store.db.execute(
                "INSERT INTO owned_terminal_windows VALUES(?,?,?,?,?,?,?,'owned',NULL,NULL) "
                "ON CONFLICT(pane_id) DO UPDATE SET principal=excluded.principal,"
                "expected_pid=excluded.expected_pid,"
                "tty=excluded.tty,identity=excluded.identity,task_id=excluded.task_id,created=excluded.created,"
                "state='owned',result_path=NULL,nonce=NULL "
                "WHERE owned_terminal_windows.state='closed'",
                (
                    row["pane_id"],
                    principal,
                    row["expected_pid"],
                    row["tty"],
                    identity,
                    task_id,
                    time.time(),
                ),
            ).rowcount
            if written != 1:
                raise BridgeError(
                    "window_ownership_conflict", "Existing window ownership needs reconciliation"
                )
            self.store.audit(
                "window.owned", principal, task_id, {"pane_id": row["pane_id"], "tty": row["tty"]}
            )

    def is_reserved(self, pane_id, task_id=None):
        owned = self.store.db.execute(
            "SELECT state,task_id FROM owned_terminal_windows WHERE pane_id=?", (pane_id,)
        ).fetchone()
        if owned and owned["state"] == "closing":
            return True
        identifier = self.leases.get(pane_id) or (owned["task_id"] if owned else None)
        if identifier and identifier != task_id:
            task = self.store.db.execute(
                "SELECT state FROM tasks WHERE id=?", (identifier,)
            ).fetchone()
            if task and task[0] in {"created", "accepted", "running"}:
                return True
        return False

    def creation_blocked(self):
        return bool(
            self.store.db.execute(
                "SELECT 1 FROM owned_terminal_windows WHERE state='closing'"
            ).fetchone()
        )

    def reserve(self, task_id, pane_id):
        if self.is_reserved(pane_id, task_id):
            raise BridgeError("session_busy", "Window belongs to another active task")
        self.leases[pane_id] = task_id

    def release(self, task_id):
        self.leases = {pane: owner for pane, owner in self.leases.items() if owner != task_id}

    def command(self, pane_id, task_id, result_path, nonce):
        with self.store.transaction():
            self.store.db.execute(
                "UPDATE owned_terminal_windows SET task_id=?,state='executing',"
                "result_path=?,nonce=? WHERE pane_id=? AND state IN ('owned','executing')",
                (task_id, str(result_path), nonce, pane_id),
            )

    async def cleanup(self):
        from pathlib import Path

        from kirabridge.private_files import private_json

        rows = self.store.db.execute(
            "SELECT * FROM owned_terminal_windows WHERE state!='closed'"
        ).fetchall()
        for saved in rows:
            task = self.store.db.execute(
                "SELECT state FROM tasks WHERE id=?", (saved["task_id"],)
            ).fetchone()
            if task is None or task[0] in {"created", "queued", "accepted", "running"}:
                continue  # Never close a resource still owned by an admitted operation.
            if saved["state"] == "closing":
                catalog = await self.sessions.catalog(saved["principal"])
                if (
                    catalog.get("status") == "available"
                    and not catalog.get("transport_errors", {}).get("terminal_app")
                    and not any(r["pane_id"] == saved["pane_id"] for r in catalog["sessions"])
                ):
                    with self.store.transaction():
                        self.store.db.execute(
                            "UPDATE owned_terminal_windows SET state='closed' WHERE pane_id=?",
                            (saved["pane_id"],),
                        )
                        self.store.audit(
                            "window.observed_absent",
                            saved["principal"],
                            saved["task_id"],
                            {"close_operation_confirmed": False},
                        )
                continue  # Never repeat an uncertain native close.
            # Running/uncertain commands need their exact completion receipt first.
            if saved["result_path"]:
                try:
                    receipt = private_json(Path(saved["result_path"]))
                except (OSError, BridgeError, ValueError):
                    self.last_error = "window_receipt_unavailable"
                    continue
                if (
                    receipt.get("nonce") != saved["nonce"]
                    or type(receipt.get("exit_code")) is not int
                ):
                    continue
            try:
                async with self.sessions.lock:
                    if self.is_reserved(saved["pane_id"], saved["task_id"]):
                        continue  # A later operation has leased this same owned shell.
                    row = await self.sessions.selected(
                        saved["principal"], saved["pane_id"], saved["expected_pid"]
                    )
                    if not idle_shell(row) or row.get("tty") != saved["tty"]:
                        continue
                    identity = await self.sessions.terminal_app.process_identity(
                        row["expected_pid"]
                    )
                    if identity != saved["identity"]:
                        continue
                    view = await self.sessions.read(
                        saved["principal"], row["pane_id"], row["expected_pid"]
                    )
                    if not empty_shell_prompt(view["text"]):
                        continue
                    captured = self.sessions.audit.observe_terminal(
                        saved["principal"],
                        {**view, "pane_id": row["pane_id"], "expected_pid": row["expected_pid"]},
                    )
                    with self.store.transaction():
                        self.store.db.execute(
                            "UPDATE owned_terminal_windows SET state='closing' WHERE pane_id=?",
                            (saved["pane_id"],),
                        )
                        self.store.audit(
                            "window.close_attempt",
                            saved["principal"],
                            saved["task_id"],
                            {"pane_id": row["pane_id"], "output_ref": captured.get("output_ref")},
                        )
                    response = await self.sessions.terminal_app.close_idle(row, identity)
                    catalog = await self.sessions.catalog(saved["principal"])
                    if (
                        not isinstance(response, dict)
                        or response.get("closed") is not True
                        or catalog.get("status") != "available"
                        or catalog.get("transport_errors", {}).get("terminal_app")
                        or any(r["pane_id"] == saved["pane_id"] for r in catalog["sessions"])
                    ):
                        self.last_error = "window_close_unconfirmed"
                        continue
                with self.store.transaction():
                    self.store.db.execute(
                        "UPDATE owned_terminal_windows SET state='closed' WHERE pane_id=?",
                        (saved["pane_id"],),
                    )
                    self.store.audit(
                        "window.closed",
                        saved["principal"],
                        saved["task_id"],
                        {"pane_id": saved["pane_id"], "identity_verified": True},
                    )
            except BridgeError as exc:
                self.last_error = exc.code
                if exc.code in {
                    "session_busy",
                    "visible_input_not_empty",
                    "visible_target_changed",
                    "window_contains_other_tabs",
                }:
                    with self.store.transaction():
                        self.store.db.execute(
                            "UPDATE owned_terminal_windows SET state=? WHERE pane_id=? "
                            "AND state='closing'",
                            (saved["state"], saved["pane_id"]),
                        )
                continue  # Identity changed or user activity: preserve the window.

    async def start(self):
        if self.reaper is None:
            self.reaper = asyncio.create_task(self._watch())

    async def _watch(self):
        while True:
            await asyncio.sleep(5)
            try:
                await self.cleanup()
            except Exception as exc:
                self.last_error = getattr(exc, "code", type(exc).__name__)

    async def stop(self):
        if self.reaper:
            self.reaper.cancel()
            await asyncio.gather(self.reaper, return_exceptions=True)
            self.reaper = None
