"""Opt-in latency measurement for the terminal and session path.

Set ``KIRABRIDGE_TIMING=1`` to log one line per measured phase to stderr, for example
``timing phase=terminal_native ms=412.3 outcome=ok``. Disabled by default: no handler is
installed and the wrappers only add one environment lookup per call.

Only the phase name, the elapsed milliseconds, the outcome (``ok`` or the exception class
name) and numeric or boolean counters are ever written. Scripts, commands, paths, window
titles and all other strings are dropped, so enabling it cannot leak task content.
"""

from __future__ import annotations

import functools
import logging
import os
import sys
import time
from collections.abc import Callable
from contextlib import contextmanager
from typing import Any

LOGGER = logging.getLogger("kirabridge.timing")
ENV = "KIRABRIDGE_TIMING"


def enabled() -> bool:
    return os.environ.get(ENV) == "1"


def _ensure_handler() -> None:
    # Own logger and handler: the CLI sets the root logger to CRITICAL, which must not
    # silence an explicitly requested measurement.
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False
    if not LOGGER.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        LOGGER.addHandler(handler)


def _emit(phase: str, started: float, outcome: str, fields: dict[str, Any]) -> None:
    extra = "".join(
        f" {key}={int(value) if isinstance(value, bool) else value}"
        for key, value in fields.items()
        if isinstance(value, bool | int | float)
    )
    elapsed = (time.perf_counter() - started) * 1000
    LOGGER.info("timing phase=%s ms=%.1f outcome=%s%s", phase, elapsed, outcome, extra)


@contextmanager
def timed(phase: str):
    """Measure a block. Yields a dict for numeric counters to attach to the log line."""
    fields: dict[str, Any] = {}
    if not enabled():
        yield fields
        return
    _ensure_handler()
    started, outcome = time.perf_counter(), "ok"
    try:
        yield fields
    except BaseException as exc:
        outcome = type(exc).__name__
        raise
    finally:
        _emit(phase, started, outcome, fields)


def _count(result: Any) -> int | None:
    if isinstance(result, dict) and isinstance(result.get("sessions"), list):
        return len(result["sessions"])
    if isinstance(result, list):
        return len(result)
    return None


def timed_async(phase: str, **static: bool | int | float) -> Callable:
    """Decorate a coroutine function; logs ``sessions=<n>`` for list/catalog results."""

    def decorate(function: Callable) -> Callable:
        @functools.wraps(function)
        async def wrapper(*args, **kwargs):
            if not enabled():
                return await function(*args, **kwargs)
            with timed(phase) as fields:
                fields.update(static)
                if isinstance(kwargs.get("mutation"), bool):
                    fields["mutation"] = kwargs["mutation"]
                result = await function(*args, **kwargs)
                count = _count(result)
                if count is not None:
                    fields["sessions"] = count
                return result

        return wrapper

    return decorate
