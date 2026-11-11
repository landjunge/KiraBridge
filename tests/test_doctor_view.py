"""Live doctor sections: read-only observations rendered for people."""

import hashlib
import io
import json
import subprocess
import time
from datetime import datetime
from types import SimpleNamespace

import pytest

from kirabridge import doctor_view as doctor
from kirabridge.install_ui import SetupUI


def statuses(section):
    return [(entry["status"], entry["label"]) for entry in section["items"]]


def test_launchd_listing_is_parsed_without_touching_services(monkeypatch):
    monkeypatch.setattr(doctor.sys, "platform", "darwin")
    calls = []

    def runner(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(
            stdout="PID\tStatus\tLabel\n36463\t0\tcom.kirabridge.bridge\n"
            "-\t1\tcom.kirabridge.chat-events\nbroken line\n"
        )

    services = doctor.launchd_services(runner)
    assert calls == [["/bin/launchctl", "list"]]
    assert services == {
        "com.kirabridge.bridge": (36463, 0),
        "com.kirabridge.chat-events": (None, 1),
    }

    def failing(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, 5)

    assert doctor.launchd_services(failing) == {}
    monkeypatch.setattr(doctor.sys, "platform", "linux")
    assert doctor.launchd_services(runner) == {}


def test_relay_log_reports_the_newest_successful_request(tmp_path):
    log = tmp_path / "relay.log"
    log.write_text(
        '2026-11-08 12:00:00,1 INFO HTTP Request: POST https://td/api/x "HTTP/1.1 200 OK"\n'
        "2026-11-08 12:05:00,1 WARNING round failed: offline\n"
        '2026-11-08 12:01:30,9 INFO HTTP Request: POST https://td/api/y "HTTP/1.1 200 OK"\n'
        '2026-11-08 12:06:00,1 INFO HTTP Request: POST https://td/api/z "HTTP/1.1 503 Bad"\n'
    )
    expected = datetime(2026, 11, 8, 12, 1, 30).timestamp()
    assert doctor.last_relay_success(log) == expected
    assert doctor.last_relay_success(tmp_path / "missing.log") is None


def test_kirabridge_section_compares_version_and_loaded_settings(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text("x = 1\n")
    digest = hashlib.sha256(config.read_bytes()).hexdigest()
    health = {
        "version": "1.0",
        "runtime": {"pid": 7, "config_sha256": digest},
        "dispatcher_active": True,
        "message_receiver_active": True,
    }
    release = {"version": "1.0", "source_commit": "a" * 40}
    audit = {"valid": True, "records": 91017}
    section = doctor.kirabridge_section(
        health, None, release=release, config_path=config, audit=audit
    )
    assert statuses(section)[:4] == [
        ("ok", "Dienst läuft"),
        ("ok", "Einstellungen geladen"),
        ("ok", "Aufträge und Nachrichten werden verarbeitet"),
        ("ok", "Datenbank und Protokoll"),
    ]
    assert section["items"][3]["detail"] == "91 017 Einträge · Prüfkette gültig"
    assert section["items"][4]["detail"] == "1.0 · " + "a" * 12

    config.write_text("x = 2\n")
    stale = doctor.kirabridge_section(
        {**health, "version": "0.9", "dispatcher_active": False},
        None,
        release=release,
        config_path=config,
        audit={"valid": False},
    )
    assert [status for status, _ in statuses(stale)][:4] == ["warn", "warn", "warn", "fail"]
    assert all(entry["hint"] for entry in stale["items"][:3])

    down = doctor.kirabridge_section(
        {}, "connection refused", release=release, config_path=config, audit=audit
    )
    assert statuses(down)[0] == ("fail", "Dienst antwortet nicht")
    assert down["items"][0]["hint"] == doctor.CONSOLE_START


def test_services_show_only_installed_ones_with_a_next_step():
    section = doctor.services_section(
        {
            "com.kirabridge.approvals": (36485, 0),
            "com.kirabridge.chat-events": (None, 1),
            "com.example.other": (1, 0),
        }
    )
    assert statuses(section) == [("ok", "Steuerfenster"), ("warn", "Antwortzustellung")]
    assert section["items"][1]["detail"] == "läuft nicht · zuletzt Exit-Code 1"
    assert doctor.services_section({}) is None


def threaddesk_config(tmp_path, *, enabled=True, complete=True):
    tmp_path.mkdir(parents=True, exist_ok=True)
    command = tmp_path / "python"
    source = tmp_path / "threaddesk-770bbc9/src"
    workspace = tmp_path / "workspace"
    if complete:
        command.write_text("#!/bin/sh\n")
        command.chmod(0o700)
        source.mkdir(parents=True)
        workspace.mkdir()
    return SimpleNamespace(
        threaddesk=SimpleNamespace(
            enabled=enabled,
            command=str(command),
            source_root=str(source),
            workspace=str(workspace),
        )
    )


def relay_files(tmp_path, *, success_age):
    relay = tmp_path / "remote-relay.json"
    relay.write_text(
        json.dumps({"server": "https://td.example:8443", "poll_seconds": 60, "projects": {"a": {}}})
    )
    log = tmp_path / "relay.log"
    when = datetime.fromtimestamp(time.time() - success_age).strftime("%Y-%m-%d %H:%M:%S")
    log.write_text(f'{when},5 INFO HTTP Request: POST https://td/api "HTTP/1.1 200 OK"\n')
    return relay, log


def test_threaddesk_is_detected_installed_and_connected(tmp_path):
    relay, log = relay_files(tmp_path, success_age=20)
    section = doctor.threaddesk_section(
        threaddesk_config(tmp_path),
        {"tools": [1, 2, 3]},
        None,
        services={doctor.RELAY_LABEL: (99, 0)},
        relay_config=relay,
        relay_log=log,
    )
    assert statuses(section) == [
        ("ok", "ThreadDesk lokal installiert"),
        ("ok", "ThreadDesk lokal verbunden"),
        ("ok", "ThreadDesk-Server erkannt"),
        ("ok", "Mit dem Server verbunden"),
    ]
    details = [entry["detail"] for entry in section["items"]]
    assert details[0] == "Quelle threaddesk-770bbc9"
    assert details[1] == "3 Werkzeuge erreichbar"
    assert details[2] == "td.example · 1 Projekte"  # host only, never the token or URL path


def test_threaddesk_problems_are_hints_not_claimed_successes(tmp_path):
    relay, log = relay_files(tmp_path, success_age=3600)
    offline = doctor.threaddesk_section(
        threaddesk_config(tmp_path),
        {},
        "timeout",
        services={doctor.RELAY_LABEL: (99, 0)},
        relay_config=relay,
        relay_log=log,
    )
    assert statuses(offline)[1] == ("warn", "ThreadDesk lokal nicht erreichbar")
    assert statuses(offline)[3] == ("warn", "Server zurzeit nicht erreichbar")
    assert "genau einmal nachgeholt" in offline["items"][3]["hint"]

    stopped = doctor.threaddesk_section(
        threaddesk_config(tmp_path / "b", complete=False),
        {},
        None,
        services={doctor.RELAY_LABEL: (None, 1)},
        relay_config=relay,
        relay_log=log,
    )
    assert statuses(stopped)[0] == ("fail", "ThreadDesk lokal unvollständig")
    assert stopped["items"][0]["detail"] == "fehlt: Programm, Quellstand, Arbeitsbereich"
    assert statuses(stopped)[-1] == ("warn", "Relay läuft nicht")

    absent = doctor.threaddesk_section(
        threaddesk_config(tmp_path / "c", enabled=False),
        {},
        None,
        services={},
        relay_config=tmp_path / "none.json",
        relay_log=log,
    )
    assert [status for status, _ in statuses(absent)] == ["info", "info"]


def test_agents_use_product_names_and_never_claim_a_login():
    config = SimpleNamespace(
        agents={
            "opencode": SimpleNamespace(executable="/usr/local/bin/opencode"),
            "claude": SimpleNamespace(executable="/usr/local/bin/claude"),
        }
    )
    section = doctor.agents_section(
        config,
        {
            "agents": [
                {"id": "opencode", "executable_present": True, "executable_runnable": True},
                {"id": "claude", "executable_present": False, "executable_runnable": False},
            ]
        },
    )
    assert statuses(section) == [
        ("ok", "OpenCode"),
        ("warn", "Claude"),
        ("info", "Anmeldungen werden nicht getestet"),
    ]


@pytest.mark.parametrize(
    "counts,expected",
    [
        ({"ok": 9, "warn": 0, "fail": 0}, ("Alles in Ordnung", True)),
        ({"ok": 9, "warn": 1, "fail": 0}, ("1 Hinweis · alles andere in Ordnung", False)),
        (
            {"ok": 2, "warn": 2, "fail": 1},
            ("1 Problem · 2 Hinweise · alles andere in Ordnung", False),
        ),
    ],
)
def test_verdict(counts, expected):
    assert doctor.verdict(counts) == expected


class Console(io.StringIO):
    encoding = "utf-8"

    def isatty(self):
        return False


def test_render_draws_sections_hints_and_verdict_without_colors(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    stream = Console()
    report = {
        "release": {"version": "1.0", "source_commit": "abcdef1234"},
        "sections": [
            {
                "title": "Dienste",
                "items": [
                    doctor.item("ok", "Steuerfenster", "PID 1"),
                    doctor.item("warn", "Antwortzustellung", "läuft nicht", doctor.CONSOLE_START),
                    doctor.item("fail", "Kaputt"),
                    doctor.item("info", "Hinweis"),
                ],
            }
        ],
        "counts": {"ok": 1, "warn": 1, "fail": 1},
    }
    doctor.render(report, SetupUI("de", stream))
    text = stream.getvalue()
    assert "\x1b" not in text
    assert "KiraBridge · Doktor" in text and "1.0 · abcdef1" in text
    assert "\n  1  Dienste\n" in text
    assert "     ✓ Steuerfenster\n       PID 1\n" in text
    assert (
        "     ! Antwortzustellung\n       läuft nicht\n"
        "       → In der Konsole unter Prozesse auf „Start“ klicken\n"
    ) in text
    assert "     ✗ Kaputt\n" in text and "     · Hinweis\n" in text
    assert "! 1 Problem · 1 Hinweis · alles andere in Ordnung" in text


def test_live_checks_report_an_unreachable_daemon_as_finding(monkeypatch, tmp_path):
    import asyncio

    import kirabridge.local_runtime as runtime

    class Pool:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            raise ConnectionRefusedError("refused")

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(runtime, "MCPClientPool", Pool)
    monkeypatch.setattr(runtime, "connection_observer", lambda config, principal: None)
    monkeypatch.setattr(doctor, "launchd_services", lambda: {})
    config_path = tmp_path / "config.toml"
    config_path.write_text("")
    config = SimpleNamespace(
        threaddesk=SimpleNamespace(enabled=False, command=None, source_root=None, workspace=None),
        agents={},
    )
    report = asyncio.run(
        doctor.live_checks(
            config,
            "local",
            config_path=config_path,
            audit={"valid": True, "records": 1},
            agents={"agents": []},
            home=tmp_path,
        )
    )
    assert report["schema"] == "kirabridge.doctor.live.v1"
    first = report["sections"][0]["items"][0]
    assert (first["status"], first["detail"]) == ("fail", "refused")
    assert report["counts"]["fail"] == 1


def test_opencode_http_agent_is_reported_as_a_configured_server():
    config = SimpleNamespace(
        agents={
            "opencode_http": SimpleNamespace(
                kind="opencode_http",
                server_url="http://127.0.0.1:58836",
                executable=None,
            )
        }
    )
    section = doctor.agents_section(
        config,
        {
            "agents": [
                {
                    "id": "opencode_http",
                    "executable_present": False,
                    "executable_runnable": False,
                }
            ]
        },
    )
    assert statuses(section) == [
        ("ok", "OpenCode HTTP"),
        ("info", "Anmeldungen werden nicht getestet"),
    ]
    assert section["items"][0]["detail"] == "http://127.0.0.1:58836"
