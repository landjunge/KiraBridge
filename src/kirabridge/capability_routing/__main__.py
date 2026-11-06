"""bigplan-delegate: plan by default; --execute admits exactly one new run."""

import argparse
import json
import sys
from pathlib import Path

from .launcher import OutcomeUncertain, launch
from .router import Runtime, Task
from .source import local_source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--matrix-thread", required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        result = launch(
            local_source(args.workspace, args.matrix_thread),
            Runtime.model_validate_json(args.runtime.read_text()),
            Task.model_validate_json(args.task.read_text()),
            execute=args.execute,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["state"] in {"planned", "process_completed"} else 2
    except OutcomeUncertain as exc:
        print(
            json.dumps(
                {
                    "state": "unknown",
                    "error": str(exc),
                    "starts_model": "unknown",
                    "automatic_retry": False,
                }
            )
        )
        return 2
    except (ValueError, OSError, TimeoutError) as exc:
        print(json.dumps({"state": "blocked", "error": str(exc), "starts_model": False}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
