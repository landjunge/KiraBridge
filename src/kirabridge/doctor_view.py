"""Live doctor: read-only checks for people, in the installer's terminal design.

Nothing here repairs, restarts, logs in or starts an agent. Every check reads an
existing source (daemon health, launchd, files, the relay log) and reports what
it observed. Unknown stays a hint, never a claimed success.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

OK, WARN, FAIL, INFO = "ok", "warn", "fail", "info"

# Long-running macOS services shown in the console, plus the console itself.
SERVICES = (
    ("com.kirabridge.approvals", "Steuerfenster"),
    ("com.kirabridge.chatgpt", "ChatGPT-Verbindung"),
    ("com.kirabridge.grok-app", "Grok-Verbindung"),
    ("com.kirabridge.chat-events", "Antwortzustellung"),
)
RELAY_LABEL = "com.kirabridge.remote-relay"
AGENT_NAMES = {"opencode": "OpenCode", "codex": "Codex", "grok": "Grok", "gemini": "Gemini"}
CONSOLE_START = "In der Konsole unter Prozesse auf „Start“ klicken"
CONSOLE_RESTART = "In der Konsole bei „KiraBridge“ auf „Neustart“ klicken"
RELAY_SUCCESS = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ INFO HTTP Request: \S+ \S+ \"HTTP/1\.1 200"
)


def item(status, label, detail="", hint=""):
    return {"status": status, "label": label, "detail": detail, "hint": hint}


def grouped(number):
    return f"{number:,}".replace(",", " ")


def ago(seconds):
    seconds = max(0, int(seconds))
    if seconds < 90:
        return f"vor {seconds} s"
    if seconds < 5400:
        return f"vor {round(seconds / 60)} min"
    return f"vor {round(seconds / 3600)} h"


def launchd_services(runner=subprocess.run):
    """launchctl list as {label: (pid or None, last exit status)}; empty if unavailable."""
    if sys.platform != "darwin":
        return {}
    try:
        result = runner(
            ["/bin/launchctl", "list"], capture_output=True, text=True, timeout=5, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    services = {}
    for line in result.stdout.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        pid, status, label = parts
        services[label] = (
            int(pid) if pid.isdigit() else None,
            int(status) if status.lstrip("-").isdigit() else None,
        )
    return services


def last_relay_success(log, *, tail=262144):
    """Timestamp of the newest successful server request in the relay log, if any."""
    try:
        with open(log, "rb") as stream:
            stream.seek(max(0, os.path.getsize(log) - tail))
            lines = stream.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        match = RELAY_SUCCESS.match(line)
        if match:
            return datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S").timestamp()
    return None


def kirabridge_section(health, error, *, release, config_path, audit):
    items = []
    if error is not None:
        items.append(item(FAIL, "Dienst antwortet nicht", error, CONSOLE_START))
    else:
        version = health.get("version", "?")
        runtime = health.get("runtime") or {}
        detail = f"Version {version} · PID {runtime.get('pid', '?')}"
        if release.get("version") and version != release["version"]:
            items.append(
                item(
                    WARN,
                    "Dienst läuft mit einer anderen Version",
                    f"{detail} · installiert {release['version']}",
                    CONSOLE_RESTART,
                )
            )
        else:
            items.append(item(OK, "Dienst läuft", detail))
        try:
            loaded = runtime.get("config_sha256")
            current = hashlib.sha256(Path(config_path).read_bytes()).hexdigest()
            if loaded == current:
                items.append(item(OK, "Einstellungen geladen", "Datei und Dienst stimmen überein"))
            else:
                items.append(
                    item(
                        WARN,
                        "Einstellungen geändert, aber noch nicht geladen",
                        str(config_path),
                        CONSOLE_RESTART,
                    )
                )
        except OSError as exc:
            items.append(item(WARN, "Einstellungsdatei nicht lesbar", str(exc)))
        workers = [
            name
            for name, key in (
                ("Aufträge", "dispatcher_active"),
                ("Nachrichten", "message_receiver_active"),
            )
            if not health.get(key)
        ]
        if workers:
            items.append(item(WARN, "Verarbeitung angehalten", ", ".join(workers), CONSOLE_RESTART))
        else:
            items.append(item(OK, "Aufträge und Nachrichten werden verarbeitet"))
    if audit.get("valid"):
        records = audit.get("records")
        detail = (f"{grouped(records)} Einträge · " if isinstance(records, int) else "") + (
            "Prüfkette gültig"
        )
        items.append(item(OK, "Datenbank und Protokoll", detail))
    else:
        items.append(
            item(FAIL, "Protokoll-Prüfkette ungültig", "", "Nichts löschen; Befund sichern")
        )
    commit = release.get("source_commit")
    items.append(
        item(
            INFO,
            "Installierte Version",
            f"{release.get('version', '?')} · "
            + (commit[:12] if commit else "Entwicklungsstand ohne Release"),
        )
    )
    return {"title": "KiraBridge", "items": items}


def services_section(services):
    if not services:
        return None
    items = []
    for label, name in SERVICES:
        if label not in services:
            continue
        pid, status = services[label]
        if pid:
            items.append(item(OK, name, f"PID {pid}"))
        else:
            detail = "läuft nicht" + (f" · zuletzt Exit-Code {status}" if status else "")
            items.append(item(WARN, name, detail, CONSOLE_START))
    return {"title": "Dienste", "items": items} if items else None


def threaddesk_section(config, catalog, catalog_error, *, services, relay_config, relay_log):
    items = []
    settings = config.threaddesk
    if not settings.enabled:
        items.append(
            item(INFO, "ThreadDesk lokal nicht eingerichtet", "[threaddesk] enabled = false")
        )
    else:
        missing = []
        command = settings.command
        if not command or not (Path(command).is_file() and os.access(command, os.X_OK)):
            missing.append("Programm")
        if settings.source_root and not Path(settings.source_root).is_dir():
            missing.append("Quellstand")
        if settings.workspace and not Path(settings.workspace).is_dir():
            missing.append("Arbeitsbereich")
        source = Path(settings.source_root).parent.name if settings.source_root else ""
        if missing:
            items.append(
                item(
                    FAIL,
                    "ThreadDesk lokal unvollständig",
                    "fehlt: " + ", ".join(missing),
                    "Pfade unter [threaddesk] in der Konfiguration prüfen",
                )
            )
        else:
            items.append(
                item(OK, "ThreadDesk lokal installiert", f"Quelle {source}" if source else "")
            )
            if catalog_error is not None:
                items.append(item(WARN, "ThreadDesk lokal nicht erreichbar", catalog_error))
            else:
                tools = len(catalog.get("tools") or [])
                items.append(
                    item(OK, "ThreadDesk lokal verbunden", f"{tools} Werkzeuge erreichbar")
                )
    try:
        relay = json.loads(Path(relay_config).read_text())
    except (OSError, ValueError):
        relay = None
    if not isinstance(relay, dict):
        items.append(item(INFO, "Kein Server-Relay eingerichtet"))
        return {"title": "ThreadDesk", "items": items}
    host = urlparse(str(relay.get("server", ""))).hostname or "unbekannt"
    projects = len(relay.get("projects") or {})
    items.append(item(OK, "ThreadDesk-Server erkannt", f"{host} · {projects} Projekte"))
    pid, status = services.get(RELAY_LABEL, (None, None)) if services else (None, None)
    poll = relay.get("poll_seconds", 60)
    poll = poll if isinstance(poll, int) and poll > 0 else 60
    last = last_relay_success(relay_log)
    if services and RELAY_LABEL in services and not pid:
        items.append(
            item(
                WARN,
                "Relay läuft nicht",
                f"zuletzt Exit-Code {status}" if status else "",
                f"launchctl kickstart -k gui/{os.getuid()}/{RELAY_LABEL}",
            )
        )
    elif last is None:
        items.append(item(WARN, "Noch keine erfolgreiche Serverabfrage gefunden", str(relay_log)))
    elif time.time() - last <= 3 * poll:
        items.append(
            item(OK, "Mit dem Server verbunden", "letzte Abfrage " + ago(time.time() - last))
        )
    else:
        items.append(
            item(
                WARN,
                "Server zurzeit nicht erreichbar",
                "letzte erfolgreiche Abfrage " + ago(time.time() - last),
                "Internetverbindung prüfen. Aufträge bleiben auf dem Server und werden "
                "genau einmal nachgeholt.",
            )
        )
    return {"title": "ThreadDesk", "items": items}


def agents_section(config, inventory):
    items = []
    for row in (inventory or {}).get("agents") or []:
        name = row.get("id", "?")
        executable = getattr(config.agents.get(name), "executable", None) or ""
        if row.get("executable_present") and row.get("executable_runnable"):
            items.append(item(OK, AGENT_NAMES.get(name, name.capitalize()), executable))
        elif row.get("executable_present"):
            items.append(
                item(
                    WARN,
                    AGENT_NAMES.get(name, name.capitalize()),
                    f"{executable} · nicht ausführbar",
                )
            )
        else:
            items.append(
                item(
                    WARN,
                    AGENT_NAMES.get(name, name.capitalize()),
                    f"{executable or 'Programm'} nicht gefunden",
                    f"Pfad unter [agents.{name}] prüfen",
                )
            )
    if items:
        items.append(
            item(INFO, "Anmeldungen werden nicht getestet", "Ein echter Test würde Tokens kosten")
        )
    return {"title": "Agenten", "items": items} if items else None


async def live_checks(config, principal, *, config_path, audit, agents, home=None):
    """Collect every section; daemon calls share one short-lived MCP connection."""
    from kirabridge.local_runtime import MCPClientPool, connection_observer, peer
    from kirabridge.operator_control import release_identity

    home = Path(home or Path.home())
    health, error, catalog, catalog_error = {}, None, {}, None
    try:
        async with MCPClientPool(
            call_timeout=8, observer=connection_observer(config, principal)
        ) as pool:
            await pool.connect(peer(config, principal))
            health = (await pool.call("daemon", "bridge_health", {})).structuredContent or {}
            if config.threaddesk.enabled:
                try:
                    reply = await pool.call("daemon", "threaddesk_dynamic_catalog", {})
                    catalog = reply.structuredContent or {}
                    if catalog.get("error"):
                        catalog_error = catalog["error"].get("code", "error")
                except Exception as exc:  # noqa: BLE001 - reported, never raised
                    catalog_error = type(exc).__name__
    except Exception as exc:  # noqa: BLE001 - an unreachable daemon is a finding
        error = str(exc) or type(exc).__name__
        catalog_error = "Dienst nicht erreichbar"
    services = launchd_services()
    sections = [
        kirabridge_section(
            health, error, release=release_identity(), config_path=config_path, audit=audit
        ),
        services_section(services),
        threaddesk_section(
            config,
            catalog,
            catalog_error,
            services=services,
            relay_config=home / ".config/kirabridge/remote-relay.json",
            relay_log=home / "Library/Logs/kirabridge-remote-relay.log",
        ),
        agents_section(config, agents),
    ]
    sections = [section for section in sections if section]
    counts = {
        status: sum(entry["status"] == status for s in sections for entry in s["items"])
        for status in (OK, WARN, FAIL)
    }
    return {
        "schema": "kirabridge.doctor.live.v1",
        "observed_at": time.time(),
        "release": release_identity(),
        "sections": sections,
        "counts": counts,
    }


def verdict(counts):
    problems, hints = counts.get(FAIL, 0), counts.get(WARN, 0)
    if not problems and not hints:
        return "Alles in Ordnung", True
    parts = []
    if problems:
        parts.append(f"{problems} Problem" + ("e" if problems != 1 else ""))
    if hints:
        parts.append(f"{hints} Hinweis" + ("e" if hints != 1 else ""))
    return " · ".join(parts) + " · alles andere in Ordnung", False


def render(report, ui):
    """Draw a live report with the installer presenter (stream, colors, wrapping)."""
    release = report.get("release") or {}
    commit = (release.get("source_commit") or "")[:7]
    meta = release.get("version", "") + (f" · {commit}" if commit else "")
    ui.heading("KiraBridge · Doktor", meta=meta)
    for section in report["sections"]:
        ui.phase(section["title"])
        for entry in section["items"]:
            method = {OK: ui.ok, WARN: ui.warn, FAIL: ui.fail, INFO: ui.note}[entry["status"]]
            method(entry["label"], detail=entry["detail"] or None, hint=entry["hint"] or None)
    title, success = verdict(report["counts"])
    ui.summary(title, rows=[], success=success)
