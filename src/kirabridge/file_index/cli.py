"""Explicit operator-only cache reconciliation; never a remote configuration tool."""

from kirabridge.bridge_core.models import BridgeError


def register(subparsers):
    parser = subparsers.add_parser("file-index", help="Optional configured-project file search")
    parser.add_argument("action", choices=["status", "scan", "search"])
    parser.add_argument("project", help="Explicit configured project id; does not grant rights")
    parser.add_argument("text", nargs="?")
    parser.add_argument(
        "--batches", type=int, default=1, help="Scan batches in this process,1–1000"
    )
    parser.add_argument("--restart", action="store_true", help="Begin a new bounded observation")
    parser.add_argument(
        "--discard-cache",
        action="store_true",
        help="Operator-only: discard all derived cache before scan",
    )
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument(
        "--pages", type=int, default=1, help="Search pages in this live process,1–1000"
    )


def execute(index, principal, args, emit):
    if not 1 <= args.batches <= 1000 or not 1 <= args.pages <= 1000:
        raise BridgeError("invalid_search_budget", "Use a bounded batch/page count")
    if args.action != "scan" and (args.restart or args.discard_cache):
        raise BridgeError("invalid_search_budget", "Cache reset flags require scan")
    if args.action == "status":
        emit(index.status(principal, args.project))
    elif args.action == "scan":
        if args.discard_cache:
            # Validate this operator-selected scope before touching the cache.
            index.context(principal, args.project)
            index.close()
            index.cache.discard()
        for position in range(args.batches):
            result = index.scan(principal, args.project, restart=args.restart and position == 0)
            if result["status"] != "building":
                break
        emit(result)
    else:
        cursor = None
        for _ in range(args.pages):
            result = index.query(
                principal, args.project, args.text, limit=args.limit, cursor=cursor
            )
            emit(result)
            cursor = result["next_cursor"]
            if cursor is None:
                break
