"""Explicit operator-only cache reconciliation; never a remote configuration tool."""

from kirabridge.bridge_core.models import BridgeError


def register(subparsers):
    parser = subparsers.add_parser("file-index", help="Optional configured-project file search")
    parser.add_argument("action", choices=["status", "scan", "search", "poll"])
    parser.add_argument("project", help="Explicit configured project id; does not grant rights")
    parser.add_argument("text", nargs="?")
    parser.add_argument(
        "--batches", type=int, help="Scan batches (scan default 1; poll 10/cycle; total ≤1000)"
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
    parser.add_argument("--cycles", type=int, help="Poll cycles; default 2, total batches ≤1000")
    parser.add_argument("--interval-ms", type=int, help="Poll interval 250–5000 ms; default 1000")
    parser.add_argument(
        "--max-seconds", type=int, help="Cooperative poll duration 1–300 s; default 60"
    )


def execute(index, principal, args, emit):
    batches = args.batches if args.batches is not None else (10 if args.action == "poll" else 1)
    if not 1 <= batches <= 1000 or not 1 <= args.pages <= 1000:
        raise BridgeError("invalid_search_budget", "Use a bounded batch/page count")
    if args.action != "scan" and (args.restart or args.discard_cache):
        raise BridgeError("invalid_search_budget", "Cache reset flags require scan")
    if args.action != "poll" and any(
        v is not None for v in (args.cycles, args.interval_ms, args.max_seconds)
    ):
        raise BridgeError("invalid_search_budget", "Polling flags require poll")
    if args.action == "poll":
        _execute_poll(index, principal, args, batches, emit)
    elif args.action == "status":
        emit(index.status(principal, args.project))
    elif args.action == "scan":
        if args.discard_cache:
            # Validate this operator-selected scope before touching the cache.
            index.context(principal, args.project)
            index.close()
            index.cache.discard()
        for position in range(batches):
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


def _execute_poll(index, principal, args, batches, emit):
    import signal
    from threading import current_thread, main_thread

    from kirabridge.file_index.polling import poll

    def interrupted(*_):
        # The enclosing CLI uses asyncio.run; its cancellation handler cannot
        # interrupt this synchronous operator. Raising also unwinds a pending
        # SQLite transaction and held descriptors. Do not lock an Event here.
        raise KeyboardInterrupt

    previous = {}
    try:
        if current_thread() is main_thread():
            for sig in (signal.SIGINT, signal.SIGTERM):
                previous[sig] = signal.getsignal(sig)
                signal.signal(sig, interrupted)
        for result in poll(
            index,
            principal,
            args.project,
            batches=batches,
            cycles=args.cycles if args.cycles is not None else 2,
            interval_ms=args.interval_ms if args.interval_ms is not None else 1000,
            max_seconds=args.max_seconds if args.max_seconds is not None else 60,
        ):
            emit(result)
    except KeyboardInterrupt:
        # No counters or source data from the interrupted batch are claimed.
        emit(
            {
                "poll_mode": "bounded_poll",
                "poll_status": "stopped",
                "status": "interrupted",
                "complete": False,
                "truncated": True,
                "reasons": ["filesystem_snapshot_unverified", "polling_interrupted"],
            }
        )
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
