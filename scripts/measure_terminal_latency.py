#!/usr/bin/env python3
"""Measure how long KiraBridge needs to find the open Terminal.app windows.

One command, no questions, read-only: it only asks Terminal.app for its windows and
tabs (exactly what KiraBridge does itself), several times in a row, and prints a short
table in plain German. It opens, moves, focuses and closes nothing. The result is copied
to the clipboard on macOS so it can simply be pasted into the chat.

    uv run python scripts/measure_terminal_latency.py [--runs 10]

Only phase names, milliseconds and counters are collected; no window titles or paths.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

os.environ["KIRABRIDGE_TIMING"] = "1"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kirabridge import timing  # noqa: E402

LINE = re.compile(r"timing phase=(\w+) ms=([0-9.]+) outcome=(\w+)")
PHASES = ("terminal_catalog", "terminal_native", "ps_catalog", "ioreg_probe")
LABEL = {
    "terminal_catalog": "Fenster finden (gesamt)",
    "terminal_native": "Terminal.app fragen (osascript)",
    "ps_catalog": "Prozesse lesen (ps)",
    "ioreg_probe": "Bildschirm-Check (ioreg)",
}


class Collector(logging.Handler):
    def __init__(self):
        super().__init__()
        self.rows: list[tuple[str, float, str]] = []

    def emit(self, record):
        match = LINE.search(record.getMessage())
        if match:
            self.rows.append((match[1], float(match[2]), match[3]))


def install_collector() -> Collector:
    collector = Collector()
    timing._ensure_handler()
    timing.LOGGER.handlers[:] = [collector]  # keep stderr quiet; we print the summary
    return collector


async def measure(transport, runs: int, collector: Collector) -> dict:
    """Run the catalog `runs` times. Returns wall times, errors and what was found."""
    walls, errors, found = [], [], None
    for _ in range(runs):
        started = time.perf_counter()
        try:
            rows = await transport.catalog()
            found = len(rows) if found is None else found
        except Exception as error:  # report, never crash a measurement run
            errors.append(getattr(error, "code", type(error).__name__))
        walls.append((time.perf_counter() - started) * 1000)
        await asyncio.sleep(0.2)
    return {"walls": walls, "errors": errors, "found": found, "rows": list(collector.rows)}


def _stats(values: list[float]) -> str:
    if not values:
        return "-"
    return f"{statistics.mean(values):7.0f} ms  (max {max(values):.0f} ms)"


def summary(result: dict, runs: int) -> str:
    by_phase: dict[str, list[float]] = {}
    for phase, ms, _outcome in result["rows"]:
        by_phase.setdefault(phase, []).append(ms)
    lines = [f"KiraBridge Zeitmessung ({runs} Durchläufe, nur lesen)"]
    lines.append(f"Gefundene Terminal-Sitzungen: {result['found']}")
    if result["errors"]:
        lines.append(f"Fehler: {len(result['errors'])}x, Codes: {sorted(set(result['errors']))}")
    lines.append("")
    lines.append("Was                                  Durchschnitt")
    for phase in PHASES:
        lines.append(f"{LABEL[phase]:<36} {_stats(by_phase.get(phase, []))}")
    lines.append(f"{'Ein Durchlauf insgesamt':<36} {_stats(result['walls'])}")
    catalog = by_phase.get("terminal_catalog", [])
    native = by_phase.get("terminal_native", [])
    if catalog and native and statistics.mean(catalog) > 0:
        share = 100 * statistics.mean(native) / statistics.mean(catalog)
        lines.append("")
        lines.append(f"Davon wartet KiraBridge auf Terminal.app: {share:.0f} %")
    return "\n".join(lines)


def to_clipboard(text: str) -> bool:
    try:
        subprocess.run(["/usr/bin/pbcopy"], input=text.encode(), check=True, timeout=5)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=10)
    args = parser.parse_args()
    if sys.platform != "darwin":
        print("Dieses Skript misst Terminal.app und muss auf dem Mac laufen.")
        return 1
    from kirabridge.platform_adapters.terminal_app import TerminalAppTransport

    collector = install_collector()
    transport = TerminalAppTransport(asyncio.Lock())
    result = asyncio.run(measure(transport, max(1, args.runs), collector))
    text = summary(result, max(1, args.runs))
    print(text)
    if "session_automation_denied" in result["errors"]:
        print(
            "\nmacOS hat den Zugriff auf Terminal.app abgelehnt. Erlaube ihn unter "
            "Systemeinstellungen > Datenschutz & Sicherheit > Automation und starte neu."
        )
    if to_clipboard(text):
        print("\nDas Ergebnis ist in der Zwischenablage. Füge es im Chat ein (Cmd+V).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
