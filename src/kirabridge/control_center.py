"""One local operator window backed by real daemon, process and durable event evidence."""

from __future__ import annotations

import asyncio
import json
import os
import plistlib
import re
import secrets
import shlex
import shutil
import time
from pathlib import Path

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from kirabridge.bridge_core.config import load_config
from kirabridge.bridge_core.models import BridgeError, canonical, digest
from kirabridge.local_runtime import peer, write_private
from kirabridge.mcp_gateway.client import MCPClientPool
from kirabridge.permissions import LEVELS, level_for, permission_summary

ASSETS = Path(__file__).with_name("console_assets")
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


def replace_section(text, header, values):
    body = (
        "\n["
        + header
        + "]\n"
        + "".join(
            key + " = " + json.dumps(value, ensure_ascii=False) + "\n"
            for key, value in values.items()
            if value is not None
        )
    )
    pattern = r"(?ms)^\[" + re.escape(header) + r"\][^\n]*\n.*?(?=^\[|\Z)"
    if re.search(pattern, text):
        return re.sub(pattern, lambda _: body.lstrip("\n"), text, count=1)
    return text.rstrip() + "\n" + body


def configure_access(config_path: Path, *, level=None, revoke_operations=None):
    """Keep credentials and existing grants. The full level uses the operator's full grant."""
    from kirabridge.bridge_core.bridge import INPUTS
    from kirabridge.chatgpt_setup import replace_private

    config = load_config(str(config_path))
    if level is not None and level not in LEVELS:
        raise BridgeError("invalid_request", "Wähle eine der drei Rechtestufen")
    revoke_operations = revoke_operations or {}
    if not isinstance(revoke_operations, dict) or any(
        name not in config.principals
        or not isinstance(operations, list)
        or any(op != "session.input" for op in operations)
        for name, operations in revoke_operations.items()
    ):
        raise BridgeError("invalid_request", "Ungültiger Widerruf einer dauerhaften Ausnahme")
    text = config_path.read_text()
    names = list(config.principals)
    if len(names) > 17:
        raise BridgeError("peer_capacity", "Mehr Teilnehmer als die Postfachkapazität erlaubt")
    for name, policy in config.principals.items():
        policy.automatic_operations = [
            op for op in policy.automatic_operations if op not in revoke_operations.get(name, [])
        ]
        policy.message_peers = [other for other in names if other != name]
        policy.capabilities = list(
            dict.fromkeys(
                policy.capabilities
                + [
                    "message.send",
                    "connection.check",
                    "message.read",
                    "message.ack",
                    "session.inspect",
                    "session.input",
                    "session.open",
                    "team.read",
                    "team.write",
                ]
            )
        )
        if level:
            policy.permission_level = level
            policy.approval_mode = "manual" if level == "ask" else "automatic"
        if level == "full":
            policy.capabilities = list(
                dict.fromkeys(
                    policy.capabilities
                    + list(INPUTS)
                    + [
                        "bridge.health",
                        "task.read",
                        "task.cancel",
                        "agent.inspect",
                        "team.manage",
                        "agent.local_tools",
                    ]
                )
            )
            policy.roots = policy.read_roots = policy.terminal_roots = ["/"]
            policy.allow_any_executable = True
            policy.team_only_execution = False
            policy.agents = list(config.agents)
        text = replace_section(text, "principals." + name, policy.model_dump())
    for name, profile in config.agents.items():
        if level == "full":
            profile.allow_local_tools = True
            profile.bridge_tools = True
            if profile.kind == "codex":
                profile.sandbox_mode = "danger-full-access"
            text = replace_section(text, "agents." + name, profile.model_dump())
    # Every installed worker gets an inbox. App identities are consumers, not spawned models.
    for name in config.agents:
        if name in config.principals and name not in config.messaging.receivers:
            directory = config_path.parent / "workers" / name
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            text = replace_section(
                text, "messaging.receivers." + name, {"cwd": str(directory), "timeout": 180.0}
            )
    # Validate before replacing. The operator's existing credentials are never rotated.
    import tomllib

    from kirabridge.bridge_core.config import Config

    Config.model_validate(tomllib.loads(text))
    if text != config_path.read_text():
        backup = (
            config_path.parent
            / "backups"
            / ("control-" + time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3) + ".toml")
        )
        backup.parent.mkdir(exist_ok=True, mode=0o700)
        write_private(backup, config_path.read_bytes())
        replace_private(config_path, text)
    return load_config(str(config_path))


class ControlCenter:
    def __init__(self, bridge, authenticate):
        self.bridge, self.authenticate = bridge, authenticate
        self.lock = asyncio.Lock()
        self.status_lock = asyncio.Lock()
        self.cache = None
        self.cache_at = 0.0
        self.seen_surfaces = set()
        self.bridge.store.db.execute(
            "CREATE TABLE IF NOT EXISTS control_actions ("
            "id TEXT PRIMARY KEY,request_hash TEXT NOT NULL,state TEXT NOT NULL,"
            "created REAL NOT NULL,result TEXT)"
        )
        self.routes = [
            Route("/protocol", self.protocol_page),
            Route("/api/control/status", self.status),
            Route("/api/control/action", self.action, methods=["POST"]),
            Route("/api/control/doctor", self.doctor, methods=["GET", "POST"]),
            Route("/api/control/permissions", self.permissions, methods=["POST"]),
            Route("/api/control/protocol", self.protocol),
            Route("/api/control/connections", self.connections),
            Route("/api/control/terminals", self.terminals),
            Route("/api/control/terminal/read", self.terminal_read, methods=["POST"]),
            Route("/api/control/terminal/input", self.terminal_input, methods=["POST"]),
            Route("/api/control/consent/{request_id}", self.consent, methods=["POST"]),
        ]

    def config(self):
        path = self.bridge.config._source_path
        return load_config(path) if path else self.bridge.config

    async def rpc(self, tool, arguments=None, principal="local", timeout=8):
        async with MCPClientPool(call_timeout=timeout) as pool:
            await pool.connect(peer(self.config(), principal))
            result = await pool.call("daemon", tool, arguments or {})
            value = result.structuredContent
            if (
                result.isError
                or not isinstance(value, dict)
                or (value.get("error") and "id" not in value)
            ):
                error = value.get("error", {}) if isinstance(value, dict) else {}
                raise BridgeError(
                    error.get("code", "daemon_response"),
                    error.get("message", "Die Bridge hat nicht geantwortet"),
                )
            return value

    async def command(self, *argv, timeout=8):
        child = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            async with asyncio.timeout(timeout):
                out, err = await child.communicate()
            return child.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")
        finally:
            if child.returncode is None:
                child.kill()
                await child.wait()

    async def processes(self):
        code, text, _ = await self.command("/bin/ps", "-axo", "uid=,pid=,ppid=,ucomm=,args=")
        if code:
            raise BridgeError("process_observation", "Prozesszustände konnten nicht gelesen werden")
        rows = []
        for line in text.splitlines():
            parts = line.strip().split(None, 4)
            if len(parts) == 5 and parts[0] == str(os.getuid()):
                rows.append(
                    {
                        "pid": int(parts[1]),
                        "ppid": int(parts[2]),
                        "comm": Path(parts[3]).name,
                        "args": parts[4],
                    }
                )
        return rows

    def busy(self):
        db = self.bridge.store.db
        counts = {}
        for table, states in [
            ("tasks", ("queued", "accepted", "running")),
            ("message_jobs", ("queued", "running")),
            (
                "team_work",
                ("queued", "dispatching", "created", "accepted", "running", "processing_result"),
            ),
        ]:
            present = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if present:
                counts[table] = db.execute(
                    f"SELECT count(*) FROM {table} "
                    f"WHERE state IN ({','.join('?' for _ in states)})",
                    states,
                ).fetchone()[0]
        return counts

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
        pending = self.bridge.store.db.execute(
            "SELECT id,principal,operation FROM tasks WHERE state='created' "
            "ORDER BY created LIMIT 20"
        ).fetchall()
        result = {
            "observed_at": time.time(),
            "services": cards,
            "bridge": health,
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
            "pending": [dict(r) for r in pending],
            "busy": self.busy(),
            "identities": [
                {"id": "chatgpt", "name": "Kira · ChatGPT", "url": "https://chatgpt.com"},
                {"id": "grok_app", "name": "Grok", "url": "https://grok.com"},
            ],
        }
        self.cache, self.cache_at = result, time.monotonic()
        return result

    async def status(self, request):
        self.authenticate(request)
        surface = (
            "desktop" if "KiraBridgeDesktop" in request.headers.get("user-agent", "") else "browser"
        )
        if surface not in self.seen_surfaces:
            self.seen_surfaces.add(surface)
            with self.bridge.store.transaction():
                self.bridge.store.audit("console.view", "local", None, {"surface": surface})
        return JSONResponse(await self.snapshot())

    async def terminals(self, request):
        self.authenticate(request)
        return JSONResponse(await self.rpc("session_catalog"))

    async def terminal_read(self, request):
        self.authenticate(request)
        value = await self.body(request)
        if not isinstance(value.get("pane_id"), str) or type(value.get("expected_pid")) is not int:
            raise BridgeError("invalid_request", "Bitte eine aktuelle Sitzung wählen")
        return JSONResponse(
            await self.rpc(
                "session_read",
                {
                    "pane_id": value["pane_id"],
                    "expected_pid": value["expected_pid"],
                },
            )
        )

    async def terminal_input(self, request):
        self.authenticate(request)
        value = await self.body(request)
        identity = value.get("action_id", "")
        if not isinstance(identity, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", identity):
            raise BridgeError("invalid_request", "Eine Aktionskennung fehlt")
        result = await self.rpc(
            "action_request",
            {
                "completion_target": "ui-input:" + identity,
                "request": {
                    "task_id": "input-" + identity,
                    "idempotency_key": "input-" + identity,
                    "operation": "session.input",
                    "arguments": {
                        "pane_id": value.get("pane_id"),
                        "expected_pid": value.get("expected_pid"),
                        "text": value.get("text"),
                        "submit": True,
                    },
                },
            },
        )
        if result.get("state") == "queued":
            delivery = await self.rpc(
                "completion_receive",
                {
                    "target": "ui-input:" + identity,
                    "limit": 1,
                    "wait_seconds": 5,
                },
            )
            for notice in delivery.get("notices", []):
                if notice["payload"].get("task_id") == "input-" + identity:
                    result = await self.rpc("task_get", {"task_id": "input-" + identity})
                    await self.rpc(
                        "completion_ack",
                        {
                            "notice_id": notice["id"],
                            "receipt": notice["receipt"],
                        },
                    )
        return JSONResponse(result)

    async def body(self, request):
        from kirabridge.approval_console import limited_body

        try:
            value = json.loads(await limited_body(request))
        except (ValueError, UnicodeDecodeError):
            raise BridgeError("invalid_request", "Die Eingabe ist ungültig") from None
        if not isinstance(value, dict):
            raise BridgeError("invalid_request", "Die Eingabe ist ungültig")
        return value

    async def reload_bridge(self):
        # Write lock closes the enqueue race. No observed terminal is ever killed here.
        with self.bridge.store.transaction():
            counts = self.busy()
            if any(counts.values()):
                raise BridgeError(
                    "service_busy",
                    "Ein Auftrag läuft oder wartet. Neustart nach Abschluss möglich.",
                )
            code, _, _ = await self.command(
                "/bin/launchctl", "kickstart", "-k", f"gui/{os.getuid()}/com.kirabridge.bridge"
            )
            if code:
                raise BridgeError("service_restart", "KiraBridge konnte nicht neu gestartet werden")
        for _ in range(20):
            try:
                value = await self.rpc("bridge_health", timeout=2)
                if value.get("dispatcher_active") and (
                    value.get("runtime", {}).get("config_sha256") == self.config()._source_sha256
                ):
                    return value
            except Exception:
                pass
            await asyncio.sleep(0.2)
        raise BridgeError(
            "service_start_pending", "Start angefordert, Antwort noch nicht bestätigt"
        )

    async def service_action(self, name, action, action_id):
        config = self.config()
        if name in {"chatgpt", "grok_app"} and action == "restart":
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
            window_grant = self.bridge.security.grant_window("local", window_task_id, window_args)
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
        if name == "chatgpt" and not loaded:
            current = next(
                row for row in (await self.snapshot(fresh=True))["services"] if row["id"] == name
            )
            if current["active"]:
                return {
                    "state": "active",
                    "existing_runtime_preserved": True,
                    "message": "Die vorhandene ChatGPT-Verbindung ist aktiv.",
                }
            binary = shutil.which("tunnel-client")
            profile = Path(config._source_path).parent / "tunnel/kirabridge.yaml"
            if not binary or not profile.is_file():
                raise BridgeError(
                    "connection_missing", "Die ChatGPT-Verbindung muss einmal verknüpft werden"
                )
            definition = {
                "Label": label,
                "RunAtLoad": True,
                "KeepAlive": {"SuccessfulExit": False},
                "Umask": 63,
                "ProgramArguments": [
                    binary,
                    "run",
                    "--profile-dir",
                    str(profile.parent),
                    "--profile",
                    "kirabridge",
                ],
            }
            if not path.exists():
                write_private(path, plistlib.dumps(definition))
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

    async def action(self, request: Request):
        self.authenticate(request)
        value = await self.body(request)
        identity = value.get("action_id", "")
        if not isinstance(identity, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", identity):
            raise BridgeError("invalid_request", "Eine Aktionskennung fehlt")
        hashed = digest(value)
        async with self.lock:
            row = self.bridge.store.db.execute(
                "SELECT * FROM control_actions WHERE id=?", (identity,)
            ).fetchone()
            if row:
                if row["request_hash"] != hashed:
                    raise BridgeError(
                        "idempotency_conflict", "Die Aktionskennung wurde bereits verwendet"
                    )
                return JSONResponse(
                    json.loads(row["result"])
                    if row["result"]
                    else {"state": row["state"], "message": "Aktion bereits angefordert"}
                )
            with self.bridge.store.transaction():
                self.bridge.store.db.execute(
                    "INSERT INTO control_actions VALUES(?,?,?,?,NULL)",
                    (identity, hashed, "requested", time.time()),
                )
                self.bridge.store.audit(
                    "control.requested",
                    "local",
                    None,
                    {
                        "action_id": identity,
                        "service": value.get("service"),
                        "action": value.get("action"),
                    },
                )
            try:
                result = await self.service_action(
                    value.get("service"), value.get("action"), identity
                )
            except BridgeError as exc:
                result = {"state": "failed", "error": {"code": exc.code, "message": str(exc)}}
            except Exception as exc:
                result = {
                    "state": "unknown",
                    "error": {
                        "code": "action_outcome_unknown",
                        "message": "Der Ausgang ist unklar. Zustand neu prüfen: " + str(exc)[:200],
                    },
                }
            with self.bridge.store.transaction():
                self.bridge.store.db.execute(
                    "UPDATE control_actions SET state=?,result=? WHERE id=?",
                    (result.get("state", "requested"), canonical(result), identity),
                )
                self.bridge.store.audit(
                    "control.result",
                    "local",
                    None,
                    {"action_id": identity, "service": value.get("service"), "result": result},
                )
            self.cache = None
            return JSONResponse(result)

    async def permissions(self, request):
        self.authenticate(request)
        value = await self.body(request)
        level = value.get("level")
        revocations = value.get("revoke_operations")
        if level not in LEVELS and not (level is None and revocations):
            raise BridgeError("invalid_request", "Wähle eine der drei Rechtestufen")
        async with self.lock:
            with self.bridge.store.transaction():
                if any(self.busy().values()):
                    raise BridgeError(
                        "service_busy", "Ein Auftrag läuft. Die bisherigen Rechte bleiben aktiv."
                    )
                updated = configure_access(
                    Path(self.config()._source_path), level=level, revoke_operations=revocations
                )
                self.bridge.config.principals = updated.principals
                self.bridge.config.agents = updated.agents
                self.bridge.store.audit(
                    "control.permissions",
                    "local",
                    None,
                    {"level": level, "revoke_operations": revocations or {}},
                )
            health = await self.reload_bridge()
            self.cache = None
            return JSONResponse(
                {
                    "level": level,
                    "label": LEVELS[level] if level else "Dauerhafte Ausnahme widerrufen",
                    "active": True,
                    "runtime": health.get("runtime"),
                }
            )

    async def doctor(self, request):
        self.authenticate(request)
        repaired = []
        if request.method == "POST":
            async with self.lock:
                config = self.config()
                before = config._source_sha256
                with self.bridge.store.transaction():
                    if any(self.busy().values()):
                        raise BridgeError(
                            "service_busy",
                            "Laufende Aufträge bleiben erhalten. Prüfen ist möglich.",
                        )
                    updated = configure_access(Path(config._source_path))
                if updated._source_sha256 != before:
                    await self.reload_bridge()
                    repaired.append("Kommunikationswege zwischen allen Agenten verbunden")
                else:
                    try:
                        loaded = await self.rpc("policy_inspect")
                        changed = loaded.get("source_files", {}).get(
                            "changed_on_disk"
                        ) or loaded.get("configuration_file", {}).get("changed_on_disk")
                        if changed:
                            await self.reload_bridge()
                            repaired.append("Aktuelle Programmdateien und Einstellungen geladen")
                    except BridgeError:
                        pass
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
        try:
            catalog = await self.rpc("session_catalog")
            checks.append(
                {
                    "name": "Terminalzugriff",
                    "ok": catalog.get("status") == "available",
                    "message": str(len(catalog.get("sessions", []))) + " Sitzungen erreichbar",
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
                "message": "Alle verbunden" if peers_ok else "Kommunikationswege fehlen",
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
        return JSONResponse(
            {
                "checks": checks,
                "repaired": repaired,
                "observed_at": time.time(),
                "all_ok": all(c["ok"] for c in checks),
            }
        )

    async def connections(self, request):
        self.authenticate(request)
        from kirabridge.grok_connector import effective_settings
        from kirabridge.grok_connector.auth_store import OAuthStore

        config = self.config()
        settings = effective_settings(config)
        grok = {
            "url": (settings.public_origin + "/mcp") if settings.public_origin else None,
            "pending": [],
            "last_use": None,
        }
        if settings.enabled:
            store = OAuthStore(
                config.state_path / "grok-app-connector/oauth.sqlite3",
                issuer=settings.public_origin,
                principal=settings.principal,
                redirect_hosts=settings.redirect_hosts,
            )
            try:
                grok["pending"] = store.list_pending()
                grok["last_use"] = store.status().get("last_use")
            finally:
                store.close()
        records = self.bridge.store.db.execute(
            "SELECT at,principal,metadata FROM audit WHERE kind='connection.checked' "
            "ORDER BY seq DESC LIMIT 50"
        ).fetchall()
        return JSONResponse(
            {
                "grok": grok,
                "checks": [
                    {"at": r["at"], "principal": r["principal"], **json.loads(r["metadata"])}
                    for r in records
                ],
                "chatgpt_url": "https://chatgpt.com",
                "grok_url": "https://grok.com",
            }
        )

    async def consent(self, request):
        self.authenticate(request)
        from kirabridge.grok_connector import effective_settings
        from kirabridge.grok_connector.auth_store import OAuthStore

        config = self.config()
        settings = effective_settings(config)
        value = await self.body(request)
        if type(value.get("allow")) is not bool:
            raise BridgeError("invalid_request", "Eine Entscheidung fehlt")
        store = OAuthStore(
            config.state_path / "grok-app-connector/oauth.sqlite3",
            issuer=settings.public_origin,
            principal=settings.principal,
            redirect_hosts=settings.redirect_hosts,
        )
        try:
            return JSONResponse(store.decide(request.path_params["request_id"], value["allow"]))
        finally:
            store.close()

    async def protocol_page(self, request):
        return HTMLResponse((ASSETS / "protocol.html").read_text())

    async def protocol(self, request):
        self.authenticate(request)
        try:
            after = max(0, int(request.query_params.get("after", "0")))
            before = max(0, int(request.query_params.get("before", "0")))
        except ValueError:
            raise BridgeError("invalid_request", "Ungültige Protokollposition") from None
        db = self.bridge.store.db
        condition, parameter = (
            ("seq>?", after) if after else ("seq<?", before) if before else ("seq>?", 0)
        )
        order = "ASC" if after else "DESC"
        records = db.execute(
            f"SELECT * FROM audit WHERE {condition} AND ("
            "kind LIKE 'message.%' OR kind LIKE 'task.%' OR kind LIKE 'control.%' "
            "OR kind LIKE 'session.input.%' "
            "OR kind LIKE 'console.%' OR kind='connection.checked' OR kind='terminal.output' "
            "OR json_extract(metadata,'$.error_code') IS NOT NULL) "
            f"ORDER BY seq {order} LIMIT 100",
            (parameter,),
        ).fetchall()
        if not after:
            records = list(reversed(records))
        entries = []
        for r in records:
            metadata = json.loads(r["metadata"])
            entry = {
                "seq": r["seq"],
                "at": r["at"],
                "kind": r["kind"],
                "principal": r["principal"],
                "task_id": r["task_id"],
                "details": metadata,
            }
            message_id = metadata.get("message_id")
            if message_id:
                m = db.execute(
                    "SELECT sender,recipient,body,delivered,acknowledged FROM messages WHERE id=?",
                    (message_id,),
                ).fetchone()
                if m:
                    entry["message"] = dict(m)
            if r["task_id"]:
                t = db.execute(
                    "SELECT operation,state,args,result,error,evidence,finished "
                    "FROM tasks WHERE id=?",
                    (r["task_id"],),
                ).fetchone()
                if t:
                    entry["task"] = {
                        k: json.loads(t[k])
                        if k in {"args", "result", "error", "evidence"} and t[k]
                        else t[k]
                        for k in t.keys()
                    }
                    observed = db.execute(
                        "SELECT state,evidence FROM events WHERE task_id=? AND at<=? "
                        "ORDER BY seq DESC LIMIT 1",
                        (r["task_id"], r["at"]),
                    ).fetchone()
                    if observed:
                        entry["task"]["state"] = observed["state"]
                        entry["task"]["evidence"] = json.loads(observed["evidence"])
                    if t["finished"] is None or t["finished"] > r["at"]:
                        entry["task"]["result"] = None
                        entry["task"]["error"] = None
            entries.append(entry)
        return JSONResponse(
            {
                "entries": entries,
                "last_seq": entries[-1]["seq"] if entries else after,
                "observed_at": time.time(),
            }
        )
