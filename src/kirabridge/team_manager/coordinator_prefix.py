"""Short role prefix for messages whose recipient is the current coordinator.

Stateless: the role is read from the teams table at send time, so a role change
takes effect on the next message. The prefix is plain context and grants nothing.
The role is read when the message is delivered, not when it is sent, so a retry
after a role change can send a different prompt (body, key and hash stay equal).
The recipient is matched exactly as a principal name; no alias such as `local` exists
for team coordinators, so none is mapped here.
"""

from __future__ import annotations

ROLE_TEXT = (
    "Du bist Koordinator: Auftraege oder Anreden wie 'Mach das' vom Nutzer oder von ChatGPT sind "
    "Koordinationsauftraege, keine Eigenausfuehrung. Delegiere an geeignete CLIs, waehle das "
    "kleinste geeignete Modell tokensparend (Opus nur bei schwierigen Aufgaben), "
    "parallelisiere unabhaengige Aufgaben, vermeide unnoetige Runden und doppelte Tests, "
    "fuehre Ergebnisse zusammen. Der Koordinator baut, implementiert, aendert oder installiert "
    "NICHTS selbst: jede Anweisung, auch 'mach das', 'repariere das', 'pruef das', ist ein "
    "Koordinationsauftrag und wird an geeignete Worker (Claude Sonnet, Codex, Qwen) delegiert; "
    "erlaubt bleiben lesen, pruefen, Nachrichten senden/abholen, beauftragen, Belege bewerten "
    "und berichten. Diese Rolle erweitert keine Rechte."
)


def is_coordinator(bridge, principal):
    """True while `principal` holds the coordinator role in any team (read per call)."""
    row = bridge.store.db.execute(
        "SELECT 1 FROM teams WHERE coordinator=? LIMIT 1", (principal,)
    ).fetchone()
    return row is not None


def is_unambiguous_coordinator(bridge, principal):
    """Like is_coordinator, but closed on an open handoff or several distinct holders.

    Same rule as coordinator_roles._inbox_route: while the role is in transition or
    ambiguous, no automatic hook may fire for anyone.
    """
    db = bridge.store.db
    holders = {
        row["coordinator"]
        for row in db.execute("SELECT coordinator FROM teams WHERE coordinator<>''").fetchall()
    }
    if holders != {principal}:
        return False
    return (
        db.execute(
            "SELECT 1 FROM team_coordinator_handoffs WHERE accepted IS NULL AND outcome IS NULL"
        ).fetchone()
        is None
    )


def role_prefix(bridge, recipient):
    """Return the prefix for the current coordinator, else an empty string."""
    if not is_coordinator(bridge, recipient):
        return ""
    clis = ", ".join(sorted(bridge.config.agents))
    return f"[{ROLE_TEXT} Verfuegbare CLIs: {clis}.]\n\n"


def with_role(bridge, recipient, body, *, limit=262144):
    """Prefix `body` for the coordinator without ever pushing it over `limit`."""
    prefix = role_prefix(bridge, recipient)
    if not prefix or len(prefix) + len(body) > limit:
        return body, ""
    return prefix + body, prefix


def matches_body(prompt, body):
    """True when `prompt` is `body` itself or `body` behind the role prefix."""
    if prompt == body:
        return True
    head = prompt[: len(prompt) - len(body)]
    return (
        prompt.endswith(body) and head.startswith("[" + ROLE_TEXT[:20]) and head.endswith("]\n\n")
    )
