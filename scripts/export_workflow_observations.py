#!/usr/bin/env python3
"""Bounded local metadata export; deliberately never constructs Bridge or Store."""

from __future__ import annotations

import argparse
import json
import sys

from kirabridge.bridge_core.config import load_config
from kirabridge.bridge_core.models import BridgeError, canonical
from kirabridge.observation_export import export_configured_observations


class Arguments(argparse.ArgumentParser):
    def error(self, message):
        # Never echo arbitrary arguments, config paths or exception strings.
        self.exit(2, '{"status":"error","code":"invalid_cli_arguments"}\n')


def main(argv=None):
    parser = Arguments(
        description="Read selected owned existing task audit metadata / Metadaten lesen"
    )
    parser.add_argument(
        "--config", required=True, help="Existing operator configuration / vorhandene Konfiguration"
    )
    parser.add_argument(
        "--principal",
        required=True,
        help="Configured identity with task.read / konfigurierte Identität",
    )
    parser.add_argument(
        "--task-id",
        action="append",
        required=True,
        help="Select 1–16 owned task IDs / eigene Aufgaben",
    )
    parser.add_argument("--cursor", type=int, default=0)
    parser.add_argument("--through-seq", type=int)
    parser.add_argument(
        "--limit", type=int, default=100, help="Audit rows, max500 / Auditzeilen, maximal500"
    )
    parser.add_argument("--format", choices=("jsonl", "json"), default="jsonl")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        result = export_configured_observations(
            config,
            args.principal,
            task_ids=args.task_id,
            cursor=args.cursor,
            limit=args.limit,
            through_seq=args.through_seq,
        )
    except BridgeError as exc:
        print(json.dumps({"status": "error", "code": exc.code}), file=sys.stderr)
        return 2
    except (OSError, ValueError, TypeError):
        print('{"status":"error","code":"observation_config_unavailable"}', file=sys.stderr)
        return 2
    if args.format == "json":
        print(canonical(result))
    else:
        for event in result["events"]:
            print(canonical(event))
        print(
            canonical(
                {
                    key: result[key]
                    for key in (
                        "next_cursor",
                        "through_seq",
                        "has_more",
                        "audit_rows_examined",
                        "page_event_bytes",
                        "coverage",
                        "diagnostics",
                    )
                }
            ),
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
