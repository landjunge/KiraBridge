"""Local operator application behavior, independent of HTTP, SQL and the Bridge object."""

from __future__ import annotations

import asyncio
import json
import os
import plistlib
import re
import secrets
import shlex
import time
from pathlib import Path

import kirabridge
from kirabridge.bridge_core.models import BridgeError
from kirabridge.operator_actions import action_identity
from kirabridge.permissions import LEVELS, level_for, permission_summary

SERVICE_LABELS = {
    "bridge": "com.kirabridge.bridge",
    "grok_app": "com.kirabridge.grok-app",
    "chatgpt": "com.kirabridge.chatgpt",
    "events": "com.kirabridge.chat-events",
}
NAMES = {
    "bridge": "KiraBridge",
    "grok_app": "Grok · Verbindung",
    "chatgpt": "Kira / ChatGPT · Verbindung",
    "events": "Antwortzustellung",
    "codex": "Codex · Terminal",
    "grok": "Grok · Terminal",
    "opencode": "OpenCode",
    "gemini": "Gemini",
    "claude": "Claude",
    "copilot": "Copilot",
    "console": "Steuerfenster",
}
INPUT_TERMINAL_STATES = {"completed", "failed", "cancelled", "unknown", "blocked", "rejected"}


def release_identity():
    """Version and source commit of this console's own installed release, for display.

    A development checkout or an unreadable manifest reports no commit.
    """
    try:
        from kirabridge.platform_adapters.macos.system_identity import installed_source_commit

        commit = installed_source_commit(Path(kirabridge.__file__).parent)
    except Exception:
        commit = None
    return {"version": kirabridge.__version__, "source_commit": commit or None}


class OperatorControl:
    def __init__(
        self,
        *,
        config,
        queries,
        daemon,
        platform,
        actions,
        maintenance,
        grant_window,
        audit,
        connectors,
    ):
        self.config, self.queries = config, queries
        self.daemon, self.platform, self.actions = daemon, platform, actions
        self.maintenance, self.grant_window = maintenance, grant_window
        self.audit, self.connectors = audit, connectors
        self.operations = None  # Set by the composition root before exposure.
        self.lock = asyncio.Lock()
        self.status_lock = asyncio.Lock()
        self.cache = None
        self.cache_at = 0.0

    async def rpc(self, *args, **kwargs):
        return await self.daemon.call(*args, **kwargs)

    async def command(self, *args, **kwargs):
        return await self.platform.command(*args, **kwargs)

    async def processes(self):
        return await self.platform.processes()

    def record_surface(self, surface):
        self.audit.record("console.view", {"surface": surface})

    async def action(self, value):
        async with self.lock:
            result = await self.actions.execute(value, self.service_action)
            self.cache = None
            return result

    def connections(self):
        return {
            "grok": self.connectors.summary(),
            "checks": self.queries.recent_connection_checks(),
            "chatgpt_url": "https://chatgpt.com",
            "grok_url": "https://grok.com",
        }

    def busy(self):
        return self.queries.busy()

    async def snapshot(self, *, fresh=False):
        async with self.status_lock:
            return await self._snapshot(fresh=fresh)

    async def _snapshot(self, *, fresh=False):
        if not fresh and self.cache and time.monotonic() - self.cache_at < 2:
            return self.cache
        config = self.config()
        rows = await self.processes()
        try:
            health = await self.rpc("bridge_health", timeout=3)
        except Exception as exc:
            health = {
                "dispatcher_active": False,
                "error": {"code": getattr(exc, "code", "unreachable"), "message": str(exc)},
            }
        cards = []
        for name, label in SERVICE_LABELS.items():
            code, output, _ = await self.command(
                "/bin/launchctl", "print", f"gui/{os.getuid()}/{label}"
            )
            match = re.search(r"\bpid = (\d+)", output) if code == 0 else None
            pid = int(match[1]) if match else None
            if name == "chatgpt" and not pid:
                pid = next(
                    (
                        p["pid"]
                        for p in rows
                        if p["comm"] == "tunnel-client" and "--profile kirabridge" in p["args"]
                    ),
                    None,
                )
            if name == "bridge":
                pid = health.get("runtime", {}).get("pid") or pid
                active = bool(health.get("dispatcher_active")) or any(p["pid"] == pid for p in rows)
            else:
                active = any(p["pid"] == pid for p in rows) if pid else False
            cards.append(
                {
                    "id": name,
                    "name": NAMES[name],
                    "active": active,
                    "state": "warning"
                    if name == "bridge" and active and not health.get("dispatcher_active")
                    else "active"
                    if active
                    else "inactive",
                    "pid": pid,
                    "managed": bool(match),
                    "restart_available": bool(match) or (name == "chatgpt" and active),
                    "restart_label": "Neu verbinden"
                    if name in {"chatgpt", "grok_app"}
                    else "Neustart",
                    "detail": "Aktiv · Antwort fehlt"
                    if name == "bridge" and active and not health.get("dispatcher_active")
                    else "Aktiv"
                    if active
                    else "Inaktiv",
                }
            )
        for name in config.agents:
            executable = config.agents.get(name)
            paths = (
                {executable.executable, str(Path(executable.executable).resolve())}
                if executable and executable.executable
                else set()
            )

            def matches_process(process, agent_name=name, agent_paths=paths):
                if process["comm"] == agent_name:
                    return True
                try:
                    return bool(agent_paths.intersection(shlex.split(process["args"])[:3]))
                except ValueError:
                    return False

            pids = [
                p["pid"]
                for p in rows
                if matches_process(p)
                and "app-server" not in p["args"]
                and " daemon " not in p["args"]
            ]
            available = bool(
                executable and executable.executable and Path(executable.executable).is_file()
            )
            cards.append(
                {
                    "id": name,
                    "name": NAMES.get(name, name),
                    "active": bool(pids),
                    "state": "active" if pids else "inactive",
                    "pids": pids,
                    "installed": available,
                    "restart_available": False,
                    "detail": "Aktiv" if pids else "Inaktiv" if available else "Nicht installiert",
                }
            )
        cards.append(
            {
                "id": "console",
                "name": NAMES["console"],
                "active": True,
                "state": "active",
                "pid": os.getpid(),
                "managed": True,
                "restart_available": True,
                "detail": "Aktiv",
            }
        )
        levels = {name: level_for(policy) for name, policy in config.principals.items()}
        pending = self.queries.pending()
        result = {
            "observed_at": time.time(),
            "services": cards,
            "bridge": health,
            "release": release_identity(),
            "maintenance": self.maintenance(),
            "permission_levels": levels,
            "permission_choices": LEVELS,
            "permission_details": {
                name: permission_summary(config, name) for name in config.principals
            },
            "settings_loaded": health.get("runtime", {}).get("config_sha256")
            == config._source_sha256,
            "permissions_consistent": len(set(levels.values())) == 1,
            "peers_connected": all(
                set(p.message_peers) == set(config.principals) - {name}
                for name, p in config.principals.items()
            ),
            "level": levels.get("chatgpt", levels.get("local", "ask")),
            "pending": pending,
            "busy": self.busy(),
            "identities": [
                {"id": "chatgpt", "name": "Kira · ChatGPT", "url": "https://chatgpt.com"},
                {"id": "grok_app", "name": "Grok", "url": "https://grok.com"},
            ],
        }
        self.cache, self.cache_at = result, time.monotonic()
        return result

    async def terminal_input(self, value):
        identity = action_identity(value)
        arguments = {
            "pane_id": value.get("pane_id"),
            "expected_pid": value.get("expected_pid"),
            "text": value.get("text", ""),
            "submit": True,
        }
        for name in ("key", "expected_cursor", "expected_agent_pid"):
            if name in value:
                arguments[name] = value[name]
        result = await self.rpc(
            "action_request",
            {
                "completion_target": "ui-input:" + identity,
                "request": {
                    "task_id": "input-" + identity,
                    "idempotency_key": "input-" + identity,
                    "operation": "session.input",
                    "arguments": arguments,
                },
            },
        )
        return await self.terminal_input_status(
            identity, wait_seconds=5 if result.get("state") == "queued" else 0
        )

    async def terminal_input_status(self, identity, *, wait_seconds=0):
        """Read this UI intent and acknowledge only its processed completion.

        Status requests never enqueue or repeat input. Outcome and completion
        notice commit atomically; an absent notice after a terminal task can
        also mean it was already acknowledged or explicitly retired.
        """
        identity = action_identity({"action_id": identity})
        task_id, target = "input-" + identity, "ui-input:" + identity

        async def current():
            task = await self.rpc("task_get", {"task_id": task_id})
            if task.get("id") != task_id or task.get("operation") != "session.input":
                raise BridgeError("terminal_task_mismatch", "Terminalauftrag nicht zugeordnet")
            return task

        task = await current()
        processed = 0
        try:
            delivery = await self.rpc(
                "completion_receive",
                {
                    "target": target,
                    "source_id": task_id,
                    "limit": 20,
                    "wait_seconds": 0 if task["state"] in INPUT_TERMINAL_STATES else wait_seconds,
                },
            )
            notices = delivery.get("notices", [])
            for notice in notices:
                payload = notice.get("payload", {})
                if (
                    notice.get("target") != target
                    or payload.get("task_id") != task_id
                    or payload.get("source") != "task"
                ):
                    raise BridgeError(
                        "completion_scope_mismatch", "Rückmeldung gehört nicht zu dieser Eingabe"
                    )
                # A late notice may supersede an older unknown result. Read the
                # actual task immediately before acknowledging the observation.
                task = await current()
                if task["state"] not in INPUT_TERMINAL_STATES:
                    return {**task, "ui_completion": {"pending": True, "processed": processed}}
                await self.rpc(
                    "completion_ack",
                    {"notice_id": notice["id"], "receipt": notice["receipt"]},
                )
                processed += 1
            return {
                **task,
                "ui_completion": {"pending": len(notices) == 20, "processed": processed},
            }
        except BridgeError as exc:
            # Keep the original task identity/result. The next scoped status
            # read can reconcile a missing ACK reply; it never resends input.
            return {
                **task,
                "ui_completion": {
                    "pending": True,
                    "processed": processed,
                    "error": {"code": exc.code},
                },
            }

    async def reload_bridge(self):
        health = await self.operations.activate()
        return {
            **health,
            "state": "completed",
            "message": "Neustart und geladener Stand bestätigt.",
        }

    async def service_action(self, name, action, action_id):
        config = self.config()
        if (
            not isinstance(name, str)
            or not isinstance(action, str)
            or action not in {"start", "restart"}
        ):
            raise BridgeError("invalid_request", "Unbekannter Prozess oder unbekannte Aktion")
        if name == "grok_app" and action == "restart":
            health = await self.reload_bridge()
            return {
                "state": "reconnected",
                "runtime": health.get("runtime"),
                "gateway_preserved": True,
                "message": "Der Bridge-Zugriff ist neu verbunden. "
                "Adresse und Kontoverknüpfung bleiben erhalten.",
            }
        if name == "console" and action == "restart":

            async def restart_console():
                await asyncio.sleep(0.4)
                await self.command(
                    "/bin/launchctl",
                    "kickstart",
                    "-k",
                    f"gui/{os.getuid()}/com.kirabridge.approvals",
                )

            asyncio.create_task(restart_console())
            return {"state": "starting", "message": "Das Steuerfenster wird neu verbunden."}
        if name in config.agents:
            snapshot = await self.snapshot(fresh=True)
            current = next(row for row in snapshot["services"] if row["id"] == name)
            if current["active"]:
                return {
                    "state": "active",
                    "existing_session_preserved": True,
                    "message": "Die vorhandene Sitzung läuft weiter. Wähle sie unter Terminals.",
                }
            if action != "start":
                raise BridgeError(
                    "agent_window_missing",
                    "Kein vorhandenes Agentenfenster. "
                    "Ein neues Fenster erfordert deinen Startauftrag.",
                )
            profile = config.agents.get(name)
            if not profile or not profile.executable or not Path(profile.executable).is_file():
                raise BridgeError("agent_missing", "Das Terminalprogramm ist nicht installiert")
            cwd = str(Path.home() / "workspace/KiraBridge")
            if not Path(cwd).is_dir():
                cwd = str(Path.home())
            from kirabridge.agent_manager.full_access import bridge_server

            argv = [profile.executable]
            if profile.bridge_tools:
                spec = bridge_server(config._source_path, name)
                servers = json.dumps({"mcpServers": {"kirabridge": spec}})
                full = config.principals["local"].permission_level == "full"
                if name == "codex":
                    argv += [
                        "-c",
                        "mcp_servers.kirabridge.command=" + json.dumps(spec["command"]),
                        "-c",
                        "mcp_servers.kirabridge.args=" + json.dumps(spec["args"]),
                    ]
                    if full:
                        argv += ["--sandbox", "danger-full-access", "-c", 'approval_policy="never"']
                elif name == "grok" and full:
                    argv += ["--permission-mode", "bypassPermissions"]
                elif name == "claude":
                    argv += ["--mcp-config", servers]
                    if full:
                        argv += ["--permission-mode", "bypassPermissions"]
                elif name == "copilot":
                    argv += ["--additional-mcp-config", servers]
                    if full:
                        argv += ["--allow-all"]
                elif name == "gemini":
                    from kirabridge.chatgpt_setup import replace_private

                    settings = Path(config._source_path).parent / "gemini-terminal.json"
                    replace_private(settings, servers)
                    argv = [
                        "/usr/bin/env",
                        "GEMINI_CLI_SYSTEM_SETTINGS_PATH=" + str(settings),
                        *argv,
                    ]
                    if full:
                        argv += ["--approval-mode", "yolo"]
                elif name == "opencode":
                    from kirabridge.agent_manager.full_access import opencode_settings

                    native = opencode_settings(profile, spec, full=full)
                    environment = ["/usr/bin/env"]
                    if profile.base_url and profile.model:
                        environment += ["-u", profile.api_key_env]
                    argv = [*environment, "OPENCODE_CONFIG_CONTENT=" + json.dumps(native), *argv]
            if profile.model:
                argv += ["--model", profile.model]
            from kirabridge.session_manager import SessionOpen

            window_task_id = "control-" + action_id
            window_args = SessionOpen(cwd=cwd, argv=argv)
            window_grant = self.grant_window("local", window_task_id, window_args)
            return await self.rpc(
                "session_open",
                {
                    "cwd": cwd,
                    "task_id": "control-" + action_id,
                    "idempotency_key": "control-" + action_id,
                    "argv": argv,
                    "window_authorization": window_grant,
                },
            )
        if name not in SERVICE_LABELS or action not in {"start", "restart"}:
            raise BridgeError("invalid_request", "Unbekannter Prozess oder unbekannte Aktion")
        label = SERVICE_LABELS[name]
        target = f"gui/{os.getuid()}/{label}"
        path = Path.home() / "Library/LaunchAgents" / (label + ".plist")
        code, output, _ = await self.command("/bin/launchctl", "print", target)
        loaded = code == 0
        if name == "chatgpt":
            from kirabridge.chatgpt_service import (
                ensure_chatgpt_service,
                restore_chatgpt_service,
            )
            from kirabridge.setup_dependencies import local_client

            unmanaged_active = False
            if not loaded:
                current = next(
                    row
                    for row in (await self.snapshot(fresh=True))["services"]
                    if row["id"] == name
                )
                unmanaged_active = bool(current["active"])
            binary = local_client(Path(config._source_path))
            profile = Path(config._source_path).parent / "tunnel/kirabridge.yaml"
            if not binary or not profile.is_file():
                raise BridgeError(
                    "connection_missing", "Die ChatGPT-Verbindung muss einmal verknüpft werden"
                )
            update = ensure_chatgpt_service(
                Path(config._source_path),
                binary,
                create=True,
                loaded_output=output if loaded else None,
            )
            if unmanaged_active:
                return {
                    "state": "active",
                    "existing_runtime_preserved": True,
                    "autostart_updated": update["changed"],
                    "message": "Die vorhandene ChatGPT-Verbindung ist aktiv.",
                }
            if (update["changed"] or update["reload_required"]) and loaded:
                code, _, _ = await self.command("/bin/launchctl", "bootout", target)
                if code:
                    restore_chatgpt_service(update)
                    raise BridgeError(
                        "service_start", "ChatGPT-Dienst konnte nicht neu geladen werden"
                    )

                async def bootstrap():
                    deadline = time.monotonic() + 30
                    for attempt in range(30):
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            return 5
                        try:
                            code, _, _ = await self.command(
                                "/bin/launchctl",
                                "bootstrap",
                                f"gui/{os.getuid()}",
                                str(path),
                                timeout=min(8, remaining),
                            )
                        except TimeoutError as exc:
                            # A timed-out launchctl command may have succeeded.
                            # Preserve the receipt/definition; never replay it.
                            raise BridgeError(
                                "service_start_unknown",
                                "ChatGPT-Dienststart unklar; Zustand lokal prüfen.",
                            ) from exc
                        if code != 5 or attempt == 29:
                            return code
                        await asyncio.sleep(min(1, max(0, deadline - time.monotonic())))
                    return 5

                code = await bootstrap()
                if code:
                    restore_chatgpt_service(update)
                    restored = await bootstrap()
                    raise BridgeError(
                        "service_start",
                        "ChatGPT-Start fehlgeschlagen; vorheriger Dienst "
                        + ("wiederhergestellt" if restored == 0 else "muss lokal gestartet werden"),
                    )
                return {
                    "state": "starting",
                    "autostart_updated": True,
                    "message": "ChatGPT-Verbindung mit automatischem Wiederanlauf gestartet.",
                }
        if name == "bridge" and action == "restart" and loaded:
            return await self.reload_bridge()
        if not path.is_file():
            raise BridgeError("service_missing", "Dieser Dienst ist noch nicht eingerichtet")
        definition = plistlib.loads(path.read_bytes())
        if definition.get("Label") != label:
            raise BridgeError("service_conflict", "Die Dienstzuordnung stimmt nicht überein")
        if action == "restart" and loaded:
            argv = ["/bin/launchctl", "kickstart", "-k", target]
        elif loaded:
            argv = ["/bin/launchctl", "kickstart", target]
        else:
            argv = ["/bin/launchctl", "bootstrap", f"gui/{os.getuid()}", str(path)]
        code, _, error = await self.command(*argv)
        if code:
            raise BridgeError("service_start", "Start fehlgeschlagen: " + error[:300])
        return {
            "state": "starting",
            "message": "Start angefordert; der tatsächliche Zustand wird geprüft.",
        }

    async def permissions(self, value):
        level = value.get("level")
        revocations = value.get("revoke_operations")
        if level not in LEVELS and not (level is None and revocations):
            raise BridgeError("invalid_request", "Wähle eine der drei Rechtestufen")
        async with self.lock:
            health = await self.operations.configure(level=level, revoke_operations=revocations)
            self.cache = None
            return {
                "level": level,
                "label": LEVELS[level] if level else "Dauerhafte Ausnahme widerrufen",
                "active": True,
                "runtime": health.get("runtime"),
                "activation_id": health.get("activation_id"),
            }

    async def doctor(self, *, repair=False):
        repaired = []
        if repair:
            async with self.lock:
                try:
                    await self.rpc("bridge_health", timeout=2)
                except BridgeError:
                    # Bring up only the existing core service so that its
                    # durable barrier and prior configuration can be inspected.
                    await self.service_action(
                        "bridge", "start", "doctor-core-" + secrets.token_hex(6)
                    )
                    for _ in range(20):
                        try:
                            await self.rpc("bridge_health", timeout=2)
                            break
                        except BridgeError:
                            await asyncio.sleep(0.2)
                    else:
                        raise BridgeError(
                            "service_start_pending", "KiraBridge antwortet noch nicht"
                        )
                if self.maintenance():
                    await self.operations.recover()
                    repaired.append(
                        "Fehlgeschlagene Aktivierung mit vorherigen Einstellungen wiederhergestellt"
                    )
                else:
                    await self.operations.configure()
                    repaired.append("Konfiguration und geladener Dienst geprüft und aktiviert")
                snapshot = await self.snapshot(fresh=True)
                for item in snapshot["services"]:
                    if item["id"] in SERVICE_LABELS and not item["active"]:
                        try:
                            await self.service_action(
                                item["id"], "start", "doctor-" + secrets.token_hex(6)
                            )
                            repaired.append(item["name"] + ": Start angefordert")
                        except BridgeError as exc:
                            repaired.append(item["name"] + ": " + str(exc))
        snapshot = await self.snapshot(fresh=True)
        checks = [
            {"name": row["name"], "ok": row["active"], "message": row["detail"]}
            for row in snapshot["services"]
            if row["id"] in SERVICE_LABELS
        ]
        maintenance = self.maintenance()
        if maintenance:
            checks.append(
                {
                    "name": "Konfigurationsaktivierung",
                    "ok": False,
                    "message": "Aktivierung "
                    + maintenance["id"]
                    + ": "
                    + maintenance["state"]
                    + (" · " + maintenance["error"] if maintenance["error"] else ""),
                }
            )
        try:
            catalog = await self.rpc("session_catalog")
            native_error = catalog.get("transport_errors", {}).get("terminal_app", {})
            checks.append(
                {
                    "name": "Terminalzugriff",
                    "ok": catalog.get("status") == "available" and not native_error,
                    "message": native_error.get("message")
                    or "Terminaltransport nicht verfügbar: " + catalog.get("status", "unbekannt")
                    if catalog.get("status") != "available" or native_error
                    else str(len(catalog.get("sessions", []))) + " Sitzungen erreichbar",
                }
            )
        except BridgeError as exc:
            checks.append({"name": "Terminalzugriff", "ok": False, "message": str(exc)})
        config = self.config()
        all_names = set(config.principals)
        peers_ok = all(
            set(p.message_peers) == all_names - {n} for n, p in config.principals.items()
        )
        checks.append(
            {
                "name": "Agenten untereinander",
                "ok": peers_ok,
                "message": "Gegenseitige Nachrichtenrechte eingerichtet"
                if peers_ok
                else "Nachrichtenrechte fehlen",
            }
        )
        try:
            policy = await self.rpc("policy_inspect")
            fresh = not policy.get("source_files", {}).get(
                "changed_on_disk", True
            ) and not policy.get("configuration_file", {}).get("changed_on_disk", True)
            checks.append(
                {
                    "name": "Aktuelle Einstellungen",
                    "ok": fresh,
                    "message": "Geladen" if fresh else "Neustart der Bridge erforderlich",
                }
            )
        except BridgeError as exc:
            checks.append({"name": "Aktuelle Einstellungen", "ok": False, "message": str(exc)})
        return {
            "checks": checks,
            "repaired": repaired,
            "observed_at": time.time(),
            "all_ok": all(c["ok"] for c in checks),
        }
