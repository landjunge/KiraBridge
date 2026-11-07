"""German Windows setup UI; workers never touch Tk or print secret values."""

from __future__ import annotations

import queue
import sys
import threading
from dataclasses import dataclass, replace
from typing import Protocol

OFFICIAL_PAGES = {
    "tunnels": "https://platform.openai.com/settings/organization/tunnels",
    "keys": "https://platform.openai.com/settings/organization/api-keys",
    "chatgpt": "https://chatgpt.com/#settings/Connectors",
}
STEPS = ("Windows starten", "Verbindung vorbereiten", "ChatGPT verbinden", "Rückweg prüfen")
WINDOWS_CONNECTION_HINT = (
    "Wenn du KiraBridge auch auf einem Mac nutzt, lege für diesen Windows-PC "
    "einen eigenen Tunnel und eine eigene ChatGPT-Verbindung an, "
    "zum Beispiel KiraBridge Windows."
)
WRITE_OPERATIONS = {"start_local", "install_client", "connect", "begin_verification"}
UNKNOWN_STATES = {"unknown", "uncertain", "unknown_no_retry"}
ERROR_MESSAGES = {
    "setup_already_open": (
        "Ein Einrichtungsassistent ist bereits geöffnet.",
        "Wechsle zu diesem Fenster.",
    ),
    "setup_port_busy": (
        "Der vorgesehene Anschluss wird bereits verwendet.",
        "Lass die vorhandene Instanz unverändert und prüfe ihren Status.",
    ),
    "setup_listener_changed": (
        "Die bisherige Instanz ist nicht mehr eindeutig erreichbar.",
        "Prüfe den Status. Starte keine zweite Instanz auf Verdacht.",
    ),
    "setup_start_unknown": (
        "Der Startstatus ist unklar.",
        "Lass vorhandene Fenster offen und prüfe den Status.",
    ),
    "setup_start_pending": (
        "KiraBridge wird noch gestartet.",
        "Lass das Fenster offen und prüfe den Status erneut.",
    ),
    "setup_health_failed": (
        "KiraBridge antwortet noch nicht zuverlässig.",
        "Lass die vorhandenen Fenster offen und prüfe den Status erneut.",
    ),
    "setup_version_mismatch": (
        "Die vorhandene Instanz hat einen anderen Stand.",
        "Lass sie geöffnet. Verwende den Assistenten aus dem passenden Windows-Paket.",
    ),
    "setup_local_missing": (
        "KiraBridge läuft lokal noch nicht.",
        "Gehe zu Schritt 1 und starte KiraBridge.",
    ),
    "setup_client_missing": ("Der offizielle Client fehlt noch.", "Installiere ihn in Schritt 2."),
    "invalid_tunnel": (
        "Die Tunnel-ID ist nicht gültig.",
        "Übernimm die vollständige ID von der Tunnelseite; sie beginnt mit tunnel_.",
    ),
    "invalid_runtime_key": (
        "Der Runtime-Schlüssel ist nicht gültig.",
        "Trage den eingeschränkten Runtime-Schlüssel erneut lokal ein, ohne Leerzeichen.",
    ),
    "existing_tunnel": (
        "Es gibt bereits eine andere Verbindung.",
        "Die vorhandene Verbindung bleibt erhalten. Prüfe zunächst ihren Status.",
    ),
    "setup_connection_missing": (
        "Es ist noch keine Verbindung gespeichert.",
        "Trage in Schritt 2 einmal die Tunnel-ID und den Runtime-Schlüssel ein.",
    ),
    "preview_credentials_invalid": (
        "Die vorhandenen Zugangsdaten können nicht sicher gelesen werden.",
        "Die Daten bleiben erhalten. Lass die Einrichtung lokal prüfen.",
    ),
    "unsafe_state": (
        "Der lokale Zustand kann nicht sicher verwendet werden.",
        "Vorhandene Daten bleiben erhalten. Lass den Zustand lokal prüfen.",
    ),
    "download_failed": (
        "Der offizielle Client konnte nicht heruntergeladen werden.",
        "Prüfe die Internetverbindung und starte den Download danach erneut.",
    ),
    "download_checksum": (
        "Die heruntergeladene Datei hat nicht die erwartete Prüfsumme.",
        "Verwende diese Datei nicht. Prüfe Verbindung und Anbieterdownload.",
    ),
}
RECONCILE_CODES = {
    "setup_start_unknown",
    "setup_start_pending",
    "setup_listener_changed",
    "existing_tunnel",
}
for _code in (
    "setup_client_download_failed",
    "setup_client_download_limit",
    "setup_client_download_origin",
    "setup_client_checksum",
    "setup_client_archive",
):
    ERROR_MESSAGES[_code] = (
        "Die Verbindungshilfe konnte nicht sicher heruntergeladen werden.",
        "Prüfe die Internetverbindung. Eine ungeprüfte Datei wird nicht verwendet.",
    )
for _code in (
    "setup_client_health_unavailable",
    "setup_client_health_limit",
    "setup_client_health_schema",
    "setup_client_health_origin",
    "setup_client_health_owner",
):
    ERROR_MESSAGES[_code] = (
        "Die Verbindungshilfe ist noch nicht sicher erreichbar.",
        "Lass vorhandene Fenster offen und prüfe den Verbindungsstatus erneut.",
    )
for _code in (
    "setup_client_io",
    "setup_client_path",
    "setup_client_file",
    "setup_client_binary",
    "setup_client_existing",
    "setup_client_profile_mismatch",
    "setup_client_start_unknown",
    "setup_client_endpoint",
    "setup_client_platform",
):
    ERROR_MESSAGES[_code] = (
        "Die vorhandene Verbindungshilfe braucht eine lokale Prüfung.",
        "Vorhandene Dateien und Instanzen bleiben erhalten. Prüfe zuerst ihren Status.",
    )
RECONCILE_CODES.update(
    {
        "setup_client_io",
        "setup_client_start_unknown",
        "setup_client_profile_mismatch",
        "setup_client_existing",
    }
)
ERROR_MESSAGES["setup_verification_expired"] = (
    "Der Prüfauftrag ist abgelaufen.",
    "Erstelle in Schritt 3 einen neuen Prüfauftrag.",
)
PROOF_RESTART_CODES = {
    "setup_verification_expired",
    "setup_reply_unavailable",
    "setup_reply_consumed",
    "setup_reply_replayed",
    "setup_verification_consumed",
    "setup_verification_replayed",
    "setup_challenge_answered",
    "setup_challenge_unknown",
    "setup_record_invalid",
}
for _code in PROOF_RESTART_CODES - {"setup_verification_expired"}:
    ERROR_MESSAGES[_code] = (
        "Dieser Rückgabecode kann nicht mehr bestätigt werden.",
        "Eine Antwort gilt nur einmal. Erstelle in Schritt 3 einen neuen Prüfauftrag.",
    )


class SetupController(Protocol):
    def inspect(self) -> dict: ...
    def start_local(self) -> dict: ...
    def install_client(self) -> dict: ...
    def connect(self, tunnel_id: str, runtime_key: str) -> dict: ...
    def connection_status(self) -> dict: ...
    def begin_verification(self) -> dict: ...
    def finish_verification(self, response_code: str) -> dict: ...
    def close(self) -> None: ...


class SetupView(Protocol):
    def render(self, state: "SetupState") -> None: ...
    def clear_runtime_key(self) -> None: ...
    def clear_response_code(self) -> None: ...
    def copy_public_text(self, value: str) -> None: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class SetupState:
    step: int = 0
    busy: bool = False
    operation: str = ""
    consent: bool = False
    message: str = "Wir richten KiraBridge gemeinsam ein."
    next_action: str = "Prüfe zuerst Windows und starte KiraBridge."
    local_ready: bool = False
    client_ready: bool = False
    connection_saved: bool = False
    connected: bool = False
    verification_pending: bool = False
    verified: bool = False
    prompt: str = ""
    account_help: bool = False
    blocked_operations: tuple[str, ...] = ()


def _spawn(job):
    threading.Thread(target=job, name="kirabridge-windows-setup", daemon=True).start()


def _public_result(result, secrets):
    """Only fixed public fields cross the worker queue, never an exception/string dump."""
    if not isinstance(result, dict):
        raise ValueError("Controller response must be a status object")
    public = {}
    for name, maximum in (
        ("state", 64),
        ("message", 2000),
        ("next_action", 2000),
        ("prompt", 16000),
    ):
        value = result.get(name, "")
        if not isinstance(value, str) or len(value) > maximum:
            raise ValueError("Invalid public setup status")
        if any(secret and secret in value for secret in secrets):
            raise ValueError("Sensitive value in setup status")
        public[name] = value
    for name in (
        "verified",
        "local_ready",
        "client_ready",
        "client_installed",
        "connection_saved",
        "connected",
        "tunnel_ready",
        "simulated",
        "safe_to_retry",
    ):
        if type(result.get(name)) is bool:
            public[name] = result[name]
    return public


class WindowsSetupPresenter:
    """One in-flight action. Only poll() applies worker results to the main-thread view."""

    def __init__(self, controller, view, *, submit=_spawn, browser_open=None):
        if browser_open is None:
            import webbrowser

            browser_open = webbrowser.open
        self.controller, self.view = controller, view
        self.submit, self.browser_open = submit, browser_open
        self.state = SetupState()
        self._queue, self._main_thread = queue.Queue(), threading.get_ident()
        self._request, self._closed = 0, False
        self.view.render(self.state)

    def _main(self):
        if threading.get_ident() != self._main_thread:
            raise RuntimeError("Setup UI updates require the main thread")

    def _render(self, **changes):
        self._main()
        if not self._closed:
            self.state = replace(self.state, **changes)
            self.view.render(self.state)

    def _dispatch(self, operation, function, arguments=(), *, sensitive=(), clear=None):
        self._main()
        if self._closed or self.state.busy or operation in self.state.blocked_operations:
            return False
        self._request += 1
        request = self._request
        self._render(busy=True, operation=operation, message="Bitte einen Moment …", next_action="")
        if clear is not None:
            clear()  # Tk entry is cleared on its owning thread before the worker starts.

        def work():
            nonlocal arguments, sensitive
            try:
                status = _public_result(function(*arguments), sensitive)
                failure = False
            except BaseException as error:
                # Exception messages may contain a key, URL or account detail.
                code = getattr(error, "code", None)
                known = type(code) is str and code in ERROR_MESSAGES
                message, next_action = (
                    ERROR_MESSAGES[code]
                    if known
                    else (
                        "Der Vorgang konnte nicht sicher abgeschlossen werden.",
                        "Prüfe den Status. Vorhandene Instanzen und Daten bleiben erhalten.",
                    )
                )
                status = {
                    "state": "unknown" if not known or code in RECONCILE_CODES else "error",
                    "message": message,
                    "next_action": next_action,
                    "code": code if known else None,
                }
                failure = not known or code in RECONCILE_CODES
            finally:
                arguments, sensitive = (), ()  # Do not retain a key in a completed worker closure.
            self._queue.put((request, operation, status, failure))

        try:
            self.submit(work)
        except BaseException:
            # A submitter may have started a worker before it raised. No second start.
            self._queue.put(
                (
                    request,
                    operation,
                    {
                        "state": "unknown",
                        "message": "Der Startstatus ist unklar.",
                        "next_action": "Prüfe den Status, bevor du den Vorgang erneut startest.",
                    },
                    True,
                )
            )
        return True

    def poll(self):
        self._main()
        while True:
            try:
                request, operation, status, failure = self._queue.get_nowait()
            except queue.Empty:
                return
            if self._closed or request != self._request or not self.state.busy:
                continue
            state = status["state"]
            blocked = set(self.state.blocked_operations)
            if operation in WRITE_OPERATIONS and (failure or state in UNKNOWN_STATES):
                blocked.add(operation)
            if (
                operation in {"inspect", "connection_status"}
                and status.get("safe_to_retry") is True
            ):
                blocked.clear()
            changes = {
                "busy": False,
                "operation": "",
                "message": status["message"] or "Der Status wurde geprüft.",
                "next_action": status["next_action"],
                "blocked_operations": tuple(sorted(blocked)),
            }
            if status.get("code") in PROOF_RESTART_CODES:
                changes.update(verified=False, verification_pending=False, prompt="")
            if not failure and state not in UNKNOWN_STATES | {
                "error",
                "failed",
                "cancelled",
                "blocked",
            }:
                if type(status.get("local_ready")) is bool:
                    changes["local_ready"] = status["local_ready"]
                    if status["local_ready"] is False:
                        changes.update(
                            connected=False, verified=False, verification_pending=False, prompt=""
                        )
                if type(status.get("client_installed")) is bool:
                    changes["client_ready"] = status["client_installed"]
                if type(status.get("connection_saved")) is bool:
                    changes["connection_saved"] = status["connection_saved"]
                if status.get("local_ready") is True or (
                    operation == "start_local" and state in {"ready", "running", "local_ready"}
                ):
                    changes["local_ready"] = True
                    if operation == "start_local":
                        changes["step"] = 1
                if (
                    status.get("client_ready") is True
                    or status.get("client_installed") is True
                    or (
                        operation == "install_client"
                        and state in {"ready", "installed", "client_ready", "client_installed"}
                    )
                ):
                    changes["client_ready"] = True
                if status.get("connected") is True or state in {"connected", "tunnel_ready"}:
                    changes.update(connected=True, local_ready=True, client_ready=True)
                    if operation == "connect":
                        changes["step"] = 2
                elif status.get("tunnel_ready") is False:
                    changes.update(
                        connected=False, verified=False, verification_pending=False, prompt=""
                    )
                if operation == "begin_verification" and status["prompt"]:
                    changes.update(
                        prompt=status["prompt"], verification_pending=True, verified=False, step=2
                    )
                # No local health/status result can turn the final indicator green.
                if operation == "finish_verification":
                    confirmed = (
                        self.state.verification_pending
                        and state == "verified"
                        and status.get("verified") is True
                        and status.get("simulated") is not True
                    )
                    changes.update(verified=confirmed, step=3)
                    if confirmed:
                        changes.update(
                            verification_pending=False,
                            message="Geschafft: ChatGPT hat KiraBridge erreicht.",
                            next_action="Der frische Rückgabecode hat die Verbindung bestätigt.",
                        )
                    elif state == "local_test_verified" or status.get("simulated") is True:
                        changes.update(verification_pending=False, prompt="")
            self._render(**changes)

    def inspect(self):
        return self._dispatch("inspect", self.controller.inspect)

    def start_local(self):
        if not self.state.consent:
            self._render(
                message="Die Zustimmung fehlt noch.",
                next_action="Bestätige zuerst, dass ChatGPT Tasten und Fenster bedienen darf.",
            )
            return False
        return self._dispatch("start_local", self.controller.start_local)

    def consent(self, enabled):
        self._main()
        if not self.state.busy and not self._closed:
            self._render(consent=enabled is True)

    def install_client(self):
        return self._dispatch("install_client", self.controller.install_client)

    def connection_status(self):
        return self._dispatch("connection_status", self.controller.connection_status)

    def connect(self, tunnel_id, runtime_key):
        self._main()
        if self.state.busy or self._closed:
            return False
        if not self.state.consent:
            self._render(
                message="Die Zustimmung fehlt noch.",
                next_action="Bestätige in Schritt 1 zuerst die Steuerung von Tasten und Fenstern.",
            )
            return False
        if (
            not isinstance(tunnel_id, str)
            or not isinstance(runtime_key, str)
            or not tunnel_id.strip()
            or not runtime_key.strip()
        ):
            self._render(
                message="Tunnel-ID und Runtime-Schlüssel fehlen noch.",
                next_action="Trage beides ein. Der Schlüssel gehört nur hierher, nie in den Chat.",
            )
            return False
        return self._dispatch(
            "connect",
            self.controller.connect,
            (tunnel_id.strip(), runtime_key.strip()),
            sensitive=(runtime_key.strip(),),
            clear=self.view.clear_runtime_key,
        )

    def connect_saved(self):
        self._main()
        if self._closed or self.state.busy:
            return False
        if not self.state.consent:
            self._render(
                message="Die Zustimmung fehlt noch.",
                next_action="Bestätige in Schritt 1 zuerst die Steuerung von Tasten und Fenstern.",
            )
            return False
        if not (self.state.local_ready and self.state.client_ready and self.state.connection_saved):
            self._render(
                message="Die gespeicherte Verbindung ist noch nicht startbereit.",
                next_action="Prüfe Windows in Schritt 1 und starte KiraBridge. "
                "Eine fehlende Verbindung kannst du in Schritt 2 neu einrichten.",
            )
            return False
        return self._dispatch(
            "connect", self.controller.connect, ("", ""), clear=self.view.clear_runtime_key
        )

    def begin_verification(self):
        if not self.state.connected:
            self._render(
                message="Die lokale Verbindung ist noch nicht bereit.",
                next_action="Prüfe zuerst den Verbindungsstatus in Schritt 2.",
            )
            return False
        if not self.state.busy:
            self._render(verified=False, verification_pending=False, prompt="")
        return self._dispatch("begin_verification", self.controller.begin_verification)

    def finish_verification(self, response_code):
        self._main()
        if self.state.busy or self._closed:
            return False
        if (
            not self.state.verification_pending
            or not isinstance(response_code, str)
            or not response_code.strip()
        ):
            self._render(
                message="Ein frischer Rückgabecode fehlt noch.",
                next_action="Sende den Prüfauftrag an ChatGPT. Trage danach den frischen Code ein.",
            )
            return False
        return self._dispatch(
            "finish_verification",
            self.controller.finish_verification,
            (response_code.strip(),),
            sensitive=(response_code.strip(),),
            clear=self.view.clear_response_code,
        )

    def go(self, step):
        self._main()
        if self.state.busy or self._closed or type(step) is not int or not 0 <= step < len(STEPS):
            return False
        if self.state.step == 1 and step != 1:
            self.view.clear_runtime_key()
        self._render(step=step)
        return True

    def account_help(self, needed):
        if not self.state.busy:
            self._render(account_help=bool(needed))

    def copy_prompt(self):
        self._main()
        if self._closed or self.state.busy or not self.state.prompt:
            return False
        self.view.copy_public_text(self.state.prompt)
        self._render(
            message="Prüfauftrag kopiert.",
            next_action="Sende nur diesen Text im neuen Chat. Füge dort keinen Schlüssel ein.",
        )
        return True

    def open_page(self, page):
        if page not in OFFICIAL_PAGES:
            return False

        def open_official():
            opened = self.browser_open(OFFICIAL_PAGES[page])
            return {
                "state": "opened" if opened else "error",
                "message": "Die Kontoseite wurde zum Öffnen an deinen Browser übergeben."
                if opened
                else "Der Browser konnte nicht geöffnet werden.",
                "next_action": "Melde dich dort selbst an und kehre dann zum Assistenten zurück.",
            }

        return self._dispatch("browser_" + page, open_official)

    def close(self):
        self._main()
        if self.state.busy:
            return False
        if not self._closed:
            self.view.clear_runtime_key()
            self.view.clear_response_code()
            self._closed = True
            self.view.close()  # Deliberately no controller stop/reset/credential operation.
        return True


class WindowsSetupApp:
    def __init__(self, root, controller):
        import tkinter as tk
        from tkinter import ttk

        self.root, self.tk, self.ttk = root, tk, ttk
        self.controls, self.pages, self.nav = [], [], []
        self._shown_prompt, self._progress_running = None, False
        width = max(680, min(870, root.winfo_screenwidth() - 60))
        height = max(500, min(760, root.winfo_screenheight() - 80))
        self.wrap_width = width - 70
        root.title("KiraBridge einrichten")
        root.geometry(f"{width}x{height}")
        root.minsize(680, 500)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=1)
        intro = ttk.Frame(root, padding=(20, 16, 20, 8))
        intro.grid(row=0, column=0, sticky="ew")
        ttk.Label(
            intro, text="KiraBridge mit ChatGPT verbinden", font=("Segoe UI", 17, "bold")
        ).pack(anchor="w")
        ttk.Label(
            intro,
            text="ChatGPT kann damit Tasten und Fenster auf deinem Windows-PC steuern.\n"
            "Der Assistent nutzt deinen Windows-Benutzer und ändert keine Systemrechte.",
            wraplength=self.wrap_width,
        ).pack(anchor="w", pady=(8, 0))
        navigation = ttk.Frame(root, padding=(16, 4))
        navigation.grid(row=1, column=0, sticky="ew")
        for index, label in enumerate(STEPS):
            navigation.columnconfigure(index, weight=1)
            button = ttk.Button(
                navigation,
                text=f"{index + 1}. {label}",
                command=lambda i=index: self.presenter.go(i),
            )
            button.grid(row=0, column=index, padx=3, sticky="ew")
            self.nav.append(button)
            self.controls.append(button)
        body = ttk.Frame(root, padding=(20, 8))
        body.grid(row=2, column=0, sticky="nsew")
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)
        canvas = tk.Canvas(body, highlightthickness=0)
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        page_holder = ttk.Frame(canvas)
        page_holder.columnconfigure(0, weight=1)
        holder = canvas.create_window((0, 0), window=page_holder, anchor="nw")
        page_holder.bind("<Configure>", lambda _: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(holder, width=event.width))
        self.canvas = canvas
        for _ in STEPS:
            page = ttk.Frame(page_holder)
            page.grid(row=0, column=0, sticky="nsew")
            self.pages.append(page)
        self.tunnel_id, self.runtime_key, self.response_code = (tk.StringVar() for _ in range(3))
        self.consent_value = tk.BooleanVar(value=False)
        self.message, self.next_action = tk.StringVar(), tk.StringVar()
        self.finish_title = tk.StringVar(value="Der Rückweg ist noch nicht bestätigt.")
        self._build_pages()
        footer = ttk.Frame(root, padding=(20, 8, 20, 16))
        footer.grid(row=3, column=0, sticky="ew")
        self.progress = ttk.Progressbar(footer, mode="indeterminate")
        self.progress.pack(fill="x", pady=(0, 8))
        ttk.Label(
            footer,
            textvariable=self.message,
            wraplength=self.wrap_width,
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w")
        ttk.Label(footer, textvariable=self.next_action, wraplength=self.wrap_width).pack(
            anchor="w", pady=(4, 8)
        )
        ttk.Label(
            footer,
            text="Schließen beendet nur den Assistenten. Instanzen und Daten bleiben erhalten.",
            wraplength=self.wrap_width,
        ).pack(anchor="w")
        self._button(footer, "Assistent schließen", lambda: self.presenter.close()).pack(
            anchor="e", pady=(8, 0)
        )
        self.presenter = WindowsSetupPresenter(controller, self)
        root.protocol("WM_DELETE_WINDOW", self._close_request)
        root.after(75, self._poll)

    def _button(self, parent, text, command):
        button = self.ttk.Button(parent, text=text, command=command)
        self.controls.append(button)
        return button

    def _label(self, page, text, *, heading=False):
        label = self.ttk.Label(
            page,
            text=text,
            wraplength=self.wrap_width,
            font=("Segoe UI", 12, "bold") if heading else ("Segoe UI", 10),
        )
        label.pack(anchor="w", pady=(0, 10))
        return label

    def _entry(self, page, variable, *, secret=False):
        entry = self.ttk.Entry(page, textvariable=variable, show="•" if secret else "", width=64)
        entry.pack(anchor="w", fill="x", pady=(0, 10))
        self.controls.append(entry)
        return entry

    def _build_pages(self):
        one, two, three, four = self.pages
        self._label(one, "1. Windows prüfen und KiraBridge starten", heading=True)
        self._label(
            one,
            "Prüfe die Voraussetzungen. Danach startet KiraBridge mit eigenem lokalen Zustand.\n"
            "Vorhandene KiraBridge-Instanzen werden nicht beendet oder überschrieben.",
        )
        self._button(one, "Windows prüfen", lambda: self.presenter.inspect()).pack(
            anchor="w", pady=6
        )
        consent = self.ttk.Checkbutton(
            one,
            text="ChatGPT darf mit dieser Verbindung Tasten drücken und Fenster bedienen.",
            variable=self.consent_value,
            command=lambda: self.presenter.consent(self.consent_value.get()),
        )
        consent.pack(anchor="w", pady=8)
        self.controls.append(consent)
        self.start_button = self._button(
            one, "KiraBridge starten", lambda: self.presenter.start_local()
        )
        self.start_button.pack(anchor="w", pady=6)
        self._label(two, "2. Verbindung vorbereiten", heading=True)
        self._label(
            two,
            "Der offizielle Client verbindet den lokalen Dienst mit deinem Tunnel.\n"
            "Die Kontoanmeldung und die Freigaben in deinem Workspace erledigst du selbst.",
        )
        self._label(two, WINDOWS_CONNECTION_HINT)
        self.install_button = self._button(
            two, "Offiziellen Client installieren", lambda: self.presenter.install_client()
        )
        self.install_button.pack(anchor="w", pady=(0, 8))
        links = self.ttk.Frame(two)
        links.pack(anchor="w", pady=(0, 8))
        self._button(links, "Tunnelseite öffnen", lambda: self.presenter.open_page("tunnels")).pack(
            side="left", padx=(0, 8)
        )
        self._button(links, "Schlüsselseite öffnen", lambda: self.presenter.open_page("keys")).pack(
            side="left"
        )
        choice = self.tk.StringVar(value="available")
        for text, value in (
            ("Ich habe diese Kontofunktionen", "available"),
            ("Ich finde den Menüpunkt nicht", "missing"),
        ):
            radio = self.ttk.Radiobutton(
                two,
                text=text,
                variable=choice,
                value=value,
                command=lambda: self.presenter.account_help(choice.get() == "missing"),
            )
            radio.pack(anchor="w")
            self.controls.append(radio)
        self.account_help_label = self._label(
            two,
            "Prüfe, ob du im richtigen OpenAI-Konto und Workspace angemeldet bist.\n"
            "Fehlt die Funktion, kläre die Freigabe mit der Workspace-Verwaltung.\n"
            "Du kannst den offiziellen Client trotzdem schon installieren.",
        )
        self.account_help_anchor = self._label(two, "Tunnel-ID (beginnt mit tunnel_)")
        self._entry(two, self.tunnel_id)
        self._label(two, "Runtime-Schlüssel – verdeckt, nur hier eingeben, niemals in den Chat")
        self._entry(two, self.runtime_key, secret=True)
        self.connect_button = self._button(
            two,
            "Verbindung vorbereiten",
            lambda: self.presenter.connect(self.tunnel_id.get(), self.runtime_key.get()),
        )
        self.connect_button.pack(anchor="w")
        self.saved_connect_button = self._button(
            two,
            "Gespeicherte Verbindung starten",
            lambda: self.presenter.connect_saved(),
        )
        self.saved_connect_button.pack(anchor="w", pady=(8, 0))
        self._label(three, "3. ChatGPT verbinden", heading=True)
        self._label(three, WINDOWS_CONNECTION_HINT)
        self._label(
            three,
            "1. Öffne die Einstellungen für Apps/Verbindungen in ChatGPT.\n"
            "2. Füge deine eigene MCP-Verbindung hinzu und wähle deinen Tunnel.\n"
            "3. Öffne einen neuen Chat mit dieser Verbindung.\n"
            "4. Fordere hier den Prüfauftrag an und sende nur diesen Text in den Chat.",
        )
        self._button(three, "ChatGPT öffnen", lambda: self.presenter.open_page("chatgpt")).pack(
            anchor="w", pady=4
        )
        self._button(
            three, "Verbindungsstatus prüfen", lambda: self.presenter.connection_status()
        ).pack(anchor="w", pady=4)
        self.begin_button = self._button(
            three, "Frischen Prüfauftrag anfordern", lambda: self.presenter.begin_verification()
        )
        self.begin_button.pack(anchor="w", pady=4)
        self.prompt = self.tk.Text(three, height=6, wrap="word", state="disabled")
        self.prompt.pack(fill="x", pady=8)
        self.copy_button = self._button(
            three, "Nichtgeheimen Prüfauftrag kopieren", lambda: self.presenter.copy_prompt()
        )
        self.copy_button.pack(anchor="w", pady=4)
        self._button(three, "Weiter: Rückgabecode prüfen", lambda: self.presenter.go(3)).pack(
            anchor="w", pady=4
        )
        self._label(four, "4. Rückweg prüfen", heading=True)
        self.ttk.Label(
            four,
            textvariable=self.finish_title,
            wraplength=self.wrap_width,
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w", pady=(0, 12))
        self._label(
            four,
            "Trage den frischen Rückgabecode aus ChatGPT ein.\n"
            "Ein laufender lokaler Dienst allein bestätigt die ChatGPT-Verbindung nicht.",
        )
        self._entry(four, self.response_code)
        self.finish_button = self._button(
            four,
            "Rückgabecode prüfen",
            lambda: self.presenter.finish_verification(self.response_code.get()),
        )
        self.finish_button.pack(anchor="w", pady=6)

    def render(self, state):
        for index, page in enumerate(self.pages):
            if index == state.step:
                page.grid()
            else:
                page.grid_remove()
        self.pages[state.step].tkraise()
        self.message.set(state.message)
        self.next_action.set(state.next_action)
        self.finish_title.set(
            "Geschafft: ChatGPT hat KiraBridge erreicht."
            if state.verified
            else "Der Rückweg ist noch nicht bestätigt."
        )
        for widget in self.controls:
            widget.configure(state="disabled" if state.busy else "normal")
        if not state.busy:
            for widget, disabled in (
                (
                    self.start_button,
                    not state.consent
                    or state.local_ready
                    or "start_local" in state.blocked_operations,
                ),
                (
                    self.install_button,
                    state.client_ready or "install_client" in state.blocked_operations,
                ),
                (
                    self.connect_button,
                    not state.consent
                    or not state.local_ready
                    or not state.client_ready
                    or "connect" in state.blocked_operations,
                ),
                (
                    self.saved_connect_button,
                    not state.consent
                    or not state.local_ready
                    or not state.client_ready
                    or not state.connection_saved
                    or "connect" in state.blocked_operations,
                ),
                (
                    self.begin_button,
                    not state.connected or "begin_verification" in state.blocked_operations,
                ),
                (self.copy_button, not state.prompt),
                (self.finish_button, not state.verification_pending),
            ):
                if disabled:
                    widget.configure(state="disabled")
        if state.account_help:
            self.account_help_label.pack(anchor="w", before=self.account_help_anchor, pady=(4, 10))
        else:
            self.account_help_label.pack_forget()
        if state.prompt != self._shown_prompt:
            self.prompt.configure(state="normal")
            self.prompt.delete("1.0", "end")
            self.prompt.insert("1.0", state.prompt)
            self.prompt.configure(state="disabled")
            self._shown_prompt = state.prompt
        if state.busy and not self._progress_running:
            self.progress.start(15)
        elif not state.busy and self._progress_running:
            self.progress.stop()
        self._progress_running = state.busy

    def clear_runtime_key(self):
        self.runtime_key.set("")

    def clear_response_code(self):
        self.response_code.set("")

    def copy_public_text(self, value):
        self.root.clipboard_clear()
        self.root.clipboard_append(value)

    def _close_request(self):
        if not self.presenter.close():
            self.root.bell()

    def _poll(self):
        self.presenter.poll()
        if not self.presenter._closed:
            self.root.after(75, self._poll)

    def close(self):
        self.root.destroy()


def _show_start_error(message):
    if sys.stderr is not None:
        print(message, file=sys.stderr)
    if sys.platform == "win32":
        try:
            import ctypes

            user = ctypes.WinDLL("user32", use_last_error=True)
            user.MessageBoxW.argtypes = [
                ctypes.c_void_p,
                ctypes.c_wchar_p,
                ctypes.c_wchar_p,
                ctypes.c_uint32,
            ]
            user.MessageBoxW.restype = ctypes.c_int32
            user.MessageBoxW(None, message, "KiraBridge einrichten", 0x10)
        except Exception:
            pass


def main(controller=None):
    if sys.platform != "win32":
        print("Dieser Einrichtungsassistent benötigt Windows.", file=sys.stderr)
        return 2
    outcome, root = 0, None
    try:
        import tkinter as tk

        if controller is None:
            from kirabridge.windows_setup import create_controller

            controller = create_controller()
        root = tk.Tk()
        WindowsSetupApp(root, controller)
        root.mainloop()
    except Exception as error:
        # Never show a traceback containing controller values or account secrets.
        code = getattr(error, "code", None)
        lines = ERROR_MESSAGES.get(code) if type(code) is str else None
        message = (
            " ".join(lines)
            if lines
            else (
                "Der Assistent konnte nicht geöffnet werden. "
                "Bitte verwende das vollständige Windows-Paket."
            )
        )
        _show_start_error(message)
        outcome = 1
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass  # User may already have closed this owned UI normally.
        if controller is not None:
            try:
                controller.close()  # Only the assistant lease; runtimes remain untouched.
            except Exception:
                _show_start_error("Der Assistent konnte seinen lokalen Zugriff nicht freigeben.")
                outcome = 1
    return outcome
