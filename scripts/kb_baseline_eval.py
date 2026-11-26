#!/usr/bin/env python3
"""KB-S2 Baseline-Auswerter: M1-M5 aus bridge.sqlite3 (rein lesend).

Benutzung: python3 scripts/kb_baseline_eval.py [seit_seq] [out.json] [m5-sonde.jsonl]
Ohne Argumente: seit 107, Ausgabe reports/kb-s1-baseline-<JJJJMMTT>.json.
M3/M5 werden aus persistierten Zeiten bzw. optionaler Sonde-JSONL berechnet.
"""
import json
import sqlite3
import statistics
import sys
from datetime import date

DB = "/Users/landjunge/.local/share/kirabridge/bridge.sqlite3"
TERMINAL = ("completed", "failed", "unknown", "cancelled", "blocked")
MIN_N_FOR_P95 = 5
# Review qwen3 21.11.: team_work_reprocess_history vorhanden -> betroffene seq offen ausweisen
REPROCESS_TABLE = "team_work_reprocess_history"


def pct(values, q):
    vs = sorted(values)
    k = max(0, min(len(vs) - 1, int(round(q * (len(vs) - 1)))))
    return round(vs[k], 2)


def stats(values, note=""):
    if not values:
        return {"n": 0, **({"hinweis": note} if note else {})}
    out = {
        "n": len(values),
        "p50": pct(values, 0.5),
        "max": round(max(values), 2),
        "mean": round(statistics.mean(values), 2),
    }
    if len(values) >= MIN_N_FOR_P95:
        out["p95"] = pct(values, 0.95)
    else:
        out["p95"] = None
        out["hinweis"] = f"n<{MIN_N_FOR_P95}: p95 nicht ausgewiesen (nicht pruefbar)"
    if note:
        out["hinweis"] = out.get("hinweis", "") + " " + note
    return out


def main():
    since = int(sys.argv[1]) if len(sys.argv) > 1 else 107
    out_path = sys.argv[2] if len(sys.argv) > 2 else f"reports/kb-s1-baseline-{date.today():%Y%m%d}.json"
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT w.id,w.seq,w.assignee,w.state,w.error,w.created,w.claimed,w.started,"
        "w.finished,w.core_task_id,t.state t_state,t.started t_started,t.finished t_finished,t.updated t_updated "
        "FROM team_work w LEFT JOIN tasks t ON t.id = w.core_task_id WHERE w.seq >= ?",
        (since,),
    ).fetchall()
    reprocessed = set()
    if con.execute(
        "SELECT 1 FROM sqlite_master WHERE name=?", (REPROCESS_TABLE,)
    ).fetchone():
        reprocessed = {r["work_id"] for r in con.execute(f"SELECT DISTINCT work_id FROM {REPROCESS_TABLE}")}

    m1_claim, m1_start_native, m2_native, m2_coreonly = [], [], [], []
    missing_started = 0
    per_assignee = {}
    m3 = []
    for r in rows:
        if r["claimed"] and r["created"]:
            m1_claim.append(r["claimed"] - r["created"])
        native = bool(r["started"])
        if native:
            m1_start_native.append(r["started"] - r["claimed"])
        else:
            missing_started += 1
        end = r["finished"]
        if native and r["state"] in TERMINAL and end:
            m2_native.append(end - r["started"])
        if r["t_started"] and r["t_finished"]:
            m2_coreonly.append(r["t_finished"] - r["t_started"])
        a = per_assignee.setdefault(
            r["assignee"] or "?",
            {"total": 0, "completed": 0, "failed": 0, "unknown": 0, "cancelled": 0,
             "agent_timeout": 0, "reprocess_betroffen": 0, "errors": {}},
        )
        a["total"] += 1
        if r["state"] in a:
            a[r["state"]] += 1
        if r["error"] == "agent_timeout":
            a["agent_timeout"] += 1
        if r["id"] in reprocessed:
            a["reprocess_betroffen"] += 1
        if r["error"]:
            a["errors"][r["error"]] = a["errors"].get(r["error"], 0) + 1
        if r["state"] == "unknown" and r["error"] == "agent_timeout" and end is None:
            if r["t_finished"]:
                anchor, quelle = r["t_finished"], "tasks.finished"
            elif r["t_updated"]:
                anchor, quelle = r["t_updated"], "tasks.updated"
            else:
                anchor, quelle = None, "keine"
            over = round(anchor - (r["started"] or r["claimed"]) - 240, 1) if anchor else None
            route = "cli_opencode" if r["seq"] == 115 else "acp_opencode"
            m3.append({"seq": r["seq"], "route": route, "ueberschuss_s": over, "endquelle": quelle})

    m4 = {}
    for name, v in per_assignee.items():
        term = sum(v[s] for s in ("completed", "failed", "unknown", "cancelled"))
        m4[name] = {
            **v,
            "fehlerquote_design": round((v["failed"] + v["unknown"]) / v["completed"], 3)
            if v["completed"] else None,
            "timeout_quote": round(v["agent_timeout"] / term, 3) if term else None,
        }

    result = {
        "seit_seq": since,
        "auftraege": len(rows),
        "M1_dispatch_to_claim_s": stats(m1_claim),
        "M1_claim_to_start_native_s": stats(m1_start_native, "nur Auftraege mit gesetztem team_work.started"),
        "M2_start_to_finish_native_s": stats(m2_native, "team_work.started->team_work.finished, terminale Auftraege"),
        "M2_core_task_s": stats(m2_coreonly, "tasks.started->tasks.finished als unabhaengiger Zweig"),
        "fehlende_startstempel": missing_started,
        "M3_timeout_ueberschuss_acp": m3,
        "M4_fehlerquote": m4,
        "reprocess_hinweis": "reprocessierte Auftraege koennen started/finished verwischen",
    }
    if len(sys.argv) > 3:
        try:
            samples = [json.loads(l) for l in open(sys.argv[3]) if l.strip()]
            blocks = [x for x in samples if x["code"] == "000"]
            result["M5_daemon_sonde"] = {
                "sonden": len(samples),
                "blockaden_000": len(blocks),
                "max_antwort_s": max((x["dur_s"] for x in samples if x["code"] != "000"), default=None),
                "quelle": sys.argv[3],
            }
        except OSError as e:
            result["M5_daemon_sonde"] = {"fehler": str(e)}
    else:
        result["M5_daemon_sonde"] = {"hinweis": "keine JSONL uebergeben"}
    with open(out_path, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: result[k] for k in ("auftraege", "fehlende_startstempel")}, ensure_ascii=False))
    print("geschrieben:", out_path)


if __name__ == "__main__":
    main()
