"""Explain granted terminal access separately from optional input confirmation."""

from kirabridge.permissions import decision
from kirabridge.platform_adapters import current_platform


def terminal_access(config, principal):
    policy = config.principals[principal]
    caps = set(policy.capabilities)
    inspect = "session.inspect" in caps
    effective = decision(config, principal, "session.input")
    catalog_decision = decision(config, principal, "session.catalog")
    read_decision = decision(config, principal, "session.read")
    send = effective["authorized"]
    buffered = effective["buffer_enabled"]
    host = current_platform().name
    requirements = [
        "interactive macOS desktop",
        "Terminal.app automation",
        "fresh window/TTY/PID identity",
        "confirmed empty shell input",
    ]
    description = (
        "Terminalrechte sind erteilt. Vorhandene Fenster über den Katalog auswählen; "
        "Lesen und Eingabe verwenden Fenster-ID, TTY und PID. "
        "Ein ausgeschalteter Zusatzpuffer deaktiviert den Terminalzugriff nicht."
        if inspect and send
        else "Terminalrechte sind nicht vollständig erteilt."
    )
    alternative = None
    if host == "linux":
        requirements = [
            "bridge-owned PTY for the separate session.open route",
            "explicit session.open authorization",
            "fresh owned session/TTY/PID identity",
            "permitted working directory and executable",
        ]
        description = (
            "Unter Linux ist terminal.visible als Vordergrundpfad nicht unterstützt. "
            "Der vorhandene separate Weg session.open erzeugt eine Bridge-eigene PTY; "
            "er übernimmt keine bestehenden Benutzerterminals. Freigabe, Pfade und "
            "erlaubte Programme müssen getrennt geprüft werden; "
            "die Laufzeitverfügbarkeit wurde nicht geprüft."
        )
        alternative = {"transport": "linux", "operation": "session.open"}
    elif host == "windows":
        requirements = [
            "interactive Windows desktop for the separate windows.console.handoff route",
            "explicit operation authorization",
            "permitted working directory and executable",
        ]
        description = (
            "Unter Windows ist terminal.visible nicht unterstützt. Der vorhandene separate "
            "Weg windows.console.handoff verwendet eine neue sichtbare Windows-Konsole. "
            "Freigabe und Laufzeitverfügbarkeit müssen getrennt geprüft werden."
        )
        alternative = {"transport": "windows.console.v1", "operation": "windows.console.handoff"}
    if alternative is not None:
        alternative.update(availability="not_probed", requires_separate_authorization=True)
    return {
        "host_platform": host,
        "policy_authorized": inspect and send,
        "discovery_allowed": inspect,
        "read_allowed": inspect,
        "catalog_decision": catalog_decision,
        "read_decision": read_decision,
        "read_approval_required": read_decision["approval_required"],
        "input_allowed": send,
        "input_approval_required": effective["approval_required"],
        "input_decision": effective,
        "additional_input_buffer_enabled": buffered,
        "session_input_policy_meaning": "optional_confirmation_buffer_not_terminal_enable_switch",
        "availability": "not_probed",
        "catalog_tool": "session_catalog",
        "read_tool": "session_read",
        "input_operation": "session.input",
        "direct_command_tool": "terminal_control",
        "direct_command_operation": "terminal.visible",
        "direct_command_availability": "not_probed" if host == "macos" else "unsupported_platform",
        "direct_command_decision": decision(config, principal, "terminal.visible"),
        "new_window_decision": decision(config, principal, "session.open"),
        "runtime_requirements": requirements,
        "alternative_terminal_route": alternative,
        "grant_is_not_runtime_readiness": True,
        "cached_client_catalog_query": {"operation": "session.catalog"},
        "cached_client_task_operations": ["session.catalog", "session.read"],
        "cached_client_task_tool": "task_request",
        "cached_client_read_query": {
            "operation": "session.read",
            "pane_id": "FROM_CATALOG",
            "expected_pid": "FROM_CATALOG",
        },
        "description": description,
    }
