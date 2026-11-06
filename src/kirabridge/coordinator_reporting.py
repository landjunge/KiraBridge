"""Bounded status reporting must not terminate the coordinator's task loop."""

import logging
import subprocess

LOGGER = logging.getLogger(__name__)


def run_status_report(command, *, report_id):
    """Attempt once; a reporting failure is not a task failure or permission to replay."""
    result = {"report_id": report_id, "state": "sent", "error": None, "automatic_retry": False}
    try:
        subprocess.run(command, check=True, timeout=20, stdout=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        result.update(state="unknown", error="report_timeout")
    except subprocess.CalledProcessError as error:
        result.update(state="unknown", error="report_exit", returncode=error.returncode)
    except OSError:
        result.update(state="failed", error="report_start_failed")
    if result["error"]:
        # Command arguments contain report text; only log the correlation ID and code.
        LOGGER.warning("Status report %s: %s", report_id, result["error"])
    return result
