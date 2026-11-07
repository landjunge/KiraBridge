import json
from pathlib import Path

p = Path(__file__).parent
d = json.loads((p / "status.json").read_text())
rows = [
    "# Baufortschritt · seven-tools-build-20261018-1833",
    "",
    "Maßgeblich: status.json; diese Ansicht wird daraus erzeugt. "
    "Keine zweite Ausführungswarteschlange.",
    "",
    "Koordinator: /root. Originalauftrag und acht Pläne: SOURCE.md, "
    "unverändert und per SHA-256 gebunden.",
    "",
    "| Paket | Verantwortlich | Status | Abhängigkeiten | Commit / PR / Grenze |",
    "|---|---|---|---|---|",
]
for key, r in d["packages"].items():
    rows.append(
        f"| {key} | {r['owner']} | {r['state']} | {', '.join(r['dependencies'])} | "
        f"{r.get('commit') or r.get('blocker') or ''} |"
    )
(p / "MASTERPLAN.md").write_text("\n".join(rows) + "\n")
