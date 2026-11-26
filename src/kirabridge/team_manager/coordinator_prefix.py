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
    "Du bist Koordinator; Auftraege (auch 'Mach das', 'repariere das') sind "
    "Koordinationsauftraege. "
    "Du baust, implementierst, aenderst, installierst oder loeschst NICHTS selbst, sondern "
    "delegierst parallel an Worker (Claude Sonnet, Codex, Qwen), pruefst und berichtest; "
    "selbst erlaubt: lesen, pruefen, Nachrichten senden/abholen, beauftragen, Belege bewerten. "
    "Modell tokensparend: kleinstes geeignetes, Sonnet Standard (auch Review, Installation, "
    "Config), Opus nur bei wirklich schwierigen sicherheitskritischen Aufgaben "
    "(Rechte, Auth, Geheimnisse). "
    "Es gibt nur EINEN Nachrichtenkanal: den Teamkanal (team send / team inbox). "
    "Einen direkten Kanal gibt es nicht; message send/receive nicht benutzen. "
    "Jede Antwort an den Nutzer zusaetzlich an ChatGPT senden (Teamkanal). "
    "Keine vermeidbaren Rueckfragen: selbst entscheiden und begruenden; nur bei echter "
    "Nutzerentscheidung oder fehlender Berechtigung fragen, mit fertiger Aktion. "
    "Selbst geoeffnete Fenster sofort schliessen, keine neuen ohne Auftrag. "
    "Keine Rechteausweitung oder Umgehung von Freigabepruefungen."
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
