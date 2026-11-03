"""Presentation of actual actor observations, never an OS or Bridge grant.

CGEvent.h distinguishes synthesis (PostEvent) from monitoring (ListenEvent).
Only synthesis and Accessibility are needed by the existing native keyboard path.
No probe, process start, AppleEvent, permission request or TCC database access here.

https://developer.apple.com/documentation/coregraphics/cgpreflightposteventaccess()
https://developer.apple.com/documentation/coregraphics/cgpreflightlisteneventaccess()
"""

from __future__ import annotations

from copy import deepcopy

_PREFERENCES = "x-apple.systempreferences:com.apple.preference.security?Privacy_"
SETTINGS_URLS = {
    "accessibility": _PREFERENCES + "Accessibility",
    "post_events": _PREFERENCES + "Accessibility",
    "input_monitoring": _PREFERENCES + "ListenEvent",
    "screen_capture": _PREFERENCES + "ScreenCapture",
    "automation": _PREFERENCES + "Automation",
}
DETAILS = (
    (
        "accessibility",
        "Bedienungshilfen",
        True,
        "Erlaubt dem ausführenden KiraBridge-Prozess, das Eingabeziel zu prüfen und zu bedienen.",
        "Datenschutz & Sicherheit → Bedienungshilfen",
    ),
    (
        "post_events",
        "Tastatureingaben senden",
        True,
        "Erlaubt diesem Prozess, Tasten und Tastenkombinationen zu senden.",
        "Datenschutz & Sicherheit → Bedienungshilfen",
    ),
    (
        "input_monitoring",
        "Eingabeüberwachung",
        False,
        "Zum Senden von Tasten nicht erforderlich. Betrifft das Mithören von Eingabegeräten.",
        "Datenschutz & Sicherheit → Eingabeüberwachung",
    ),
    (
        "screen_capture",
        "Bildschirmaufnahme",
        False,
        "Für Tastatureingaben nicht erforderlich. Wird nur für Bildschirmaufnahmen benötigt.",
        "Datenschutz & Sicherheit → Bildschirm- und Systemaudioaufnahme",
    ),
    (
        "automation",
        "Automation",
        False,
        "Für den direkten nativen Tastaturweg nicht erforderlich. AppleScript-Helfer benötigen "
        "eigene, zielbezogene Freigaben, etwa für Terminal.",
        "Datenschutz & Sicherheit → Automation",
    ),
)


def _identity(native):
    helper = native.get("native_helper")
    result = deepcopy(helper) if isinstance(helper, dict) else {}
    # Only fixed identity fields; never echo arbitrary native/user payloads.
    result = {
        key: value
        for key, value in result.items()
        if key in {"pid", "executable", "bundle_id", "generation", "source_commit"}
    }
    pid = native.get("actor_pid")
    if type(pid) is int and pid > 0:
        if result.get("pid", pid) != pid:
            return {}, False
        result["pid"] = pid
    return result, type(result.get("pid")) is int and result["pid"] > 0


def permission_guidance(native: dict | None, platform: dict | None = None) -> dict:
    """Use a fresh trusted system.permissions result, never caller-supplied grants.

    The caller owns freshness and worker-generation verification. Core and finished
    helper observations are displayed separately and cannot satisfy worker checks.
    A missing worker identity or unsupported Boolean stays unknown.
    """
    native = native if isinstance(native, dict) else {}
    identity, bound = _identity(native)
    checks = []
    for resource, label, required, reason, steps in DETAILS:
        value = native.get(resource + "_granted") if bound else None
        state = "granted" if value is True else "not_granted" if value is False else "unknown"
        if resource == "automation":
            state = "not_required"
        checks.append(
            {
                "resource": resource,
                "label": label,
                "state": state,
                "required_for_keyboard": required,
                "reason": reason,
                "settings_url": SETTINGS_URLS[resource],
                "manual_steps": steps,
                "actor": "native_worker",
                "identity": deepcopy(identity),
                "permission_requested": False,
            }
        )
    required = [row for row in checks if row["required_for_keyboard"]]
    ready = (
        False
        if any(row["state"] == "not_granted" for row in required)
        else True
        if all(row["state"] == "granted" for row in required)
        else None
    )
    summary = (
        "Die benötigten macOS-Freigaben des ausführenden Tastaturprozesses sind vorhanden."
        if ready is True
        else "Für Tastatureingaben fehlt eine macOS-Freigabe des ausführenden KiraBridge-Prozesses."
        if ready is False
        else "Die macOS-Freigaben des ausführenden Tastaturprozesses "
        "sind noch nicht vollständig geprüft."
    )
    actors = []
    if isinstance(platform, dict):
        for row in platform.get("permissions", []):
            if isinstance(row, dict) and row.get("actor") == "core":
                actors.append(
                    {
                        "actor": "core",
                        "resource": row.get("resource"),
                        "state": row.get("state", "unknown"),
                        "identity": deepcopy(row.get("identity", {})),
                        "scope": "Nur dieser Core-Prozess; gilt nicht für den Tastaturworker.",
                    }
                )
        helper = platform.get("helper_diagnostics")
        if isinstance(helper, dict):
            for row in helper.get("permissions", []):
                if isinstance(row, dict):
                    actors.append(
                        {
                            "actor": "completed_helper",
                            "resource": row.get("resource"),
                            "target": row.get("target"),
                            "state": row.get("state", "unknown"),
                            "identity": deepcopy(helper.get("identity", {})),
                            "scope": "Abgeschlossener Diagnosehelfer; "
                            "erlaubt keine spätere Eingabe.",
                        }
                    )
    return {
        "schema_version": 1,
        "keyboard_ready": ready,
        "summary": summary,
        "checks": checks,
        "other_actors": actors,
        "scope": "macOS-Freigaben allein bestätigen weder Eingabeziel "
        "noch tatsächliche Zustellung.",
        "permission_requested": False,
        "input_attempted": False,
        "instructions": "Öffne die passende Einstellung und prüfe den angezeigten ausführenden "
        "KiraBridge-Prozess. macOS kann danach einen Neustart dieses Prozesses verlangen. "
        "Ein Wechsel der KiraBridge-Rechtestufe ersetzt keine macOS-Freigabe.",
    }
