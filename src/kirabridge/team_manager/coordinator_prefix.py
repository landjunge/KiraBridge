"""Short role prefix for messages whose recipient is the current coordinator.

Stateless: the role is read from the teams table at send time, so a role change
takes effect on the next message. The prefix is plain context and grants nothing.
"""

from __future__ import annotations

ROLE_TEXT = (
    "Du bist Koordinator: Auftraege oder Anreden wie 'Mach das' von Kira oder Daniel sind "
    "Koordinationsauftraege, keine Eigenausfuehrung. Delegiere an geeignete CLIs, waehle das "
    "kleinste geeignete Modell tokensparend (Opus nur bei schwierigen Aufgaben), "
    "parallelisiere unabhaengige Aufgaben, vermeide unnoetige Runden und doppelte Tests, "
    "fuehre Ergebnisse zusammen. Der Koordinator baut, implementiert, aendert oder installiert "
    "NICHTS selbst: jede Anweisung, auch 'mach das', 'repariere das', 'pruef das', ist ein "
    "Koordinationsauftrag und wird an geeignete Worker (Claude Sonnet, Codex, Qwen) delegiert; "
    "erlaubt bleiben lesen, pruefen, Nachrichten senden/abholen, beauftragen, Belege bewerten "
    "und berichten. Diese Rolle erweitert keine Rechte."
)


def role_prefix(bridge, recipient):
    """Return the prefix for the current coordinator, else an empty string."""
    row = bridge.store.db.execute(
        "SELECT 1 FROM teams WHERE coordinator=? LIMIT 1", (recipient,)
    ).fetchone()
    if row is None:
        return ""
    clis = ", ".join(sorted(bridge.config.agents))
    return f"[{ROLE_TEXT} Verfuegbare CLIs: {clis}.]\n\n"


def with_role(bridge, recipient, body, *, limit=262144):
    """Prefix `body` for the coordinator without ever pushing it over `limit`."""
    prefix = role_prefix(bridge, recipient)
    if not prefix or (len(body) <= limit < len(prefix) + len(body)):
        return body, ""
    return prefix + body, prefix
