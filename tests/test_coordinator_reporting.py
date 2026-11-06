"""Reporter failures do not kill coordination or silently become successful reports."""

import subprocess
import unittest
from unittest.mock import patch

from kirabridge.coordinator_reporting import run_status_report


class StatusReportingTests(unittest.TestCase):
    def test_success_is_one_bounded_attempt(self):
        with patch("kirabridge.coordinator_reporting.subprocess.run") as run:
            result = run_status_report(["reporter", "private text"], report_id="observed-1")
        run.assert_called_once_with(
            ["reporter", "private text"], check=True, timeout=20, stdout=subprocess.DEVNULL
        )
        self.assertEqual(result["state"], "sent")
        self.assertIsNone(result["error"])

    def test_timeout_keeps_unknown_outcome_without_replay(self):
        with (
            patch("kirabridge.coordinator_reporting.subprocess.run") as run,
            self.assertLogs("kirabridge.coordinator_reporting", level="WARNING") as logs,
        ):
            run.side_effect = subprocess.TimeoutExpired(["reporter", "private text"], 20)
            result = run_status_report(["reporter", "private text"], report_id="observed-2")
        run.assert_called_once()
        self.assertEqual(result["state"], "unknown")
        self.assertEqual(result["error"], "report_timeout")
        self.assertFalse(result["automatic_retry"])
        self.assertIn("observed-2", logs.output[0])
        self.assertNotIn("private text", " ".join(logs.output))

    def test_nonzero_exit_does_not_claim_no_delivery(self):
        with patch("kirabridge.coordinator_reporting.subprocess.run") as run:
            run.side_effect = subprocess.CalledProcessError(7, ["reporter"])
            with self.assertLogs("kirabridge.coordinator_reporting"):
                result = run_status_report(["reporter"], report_id="observed-3")
        run.assert_called_once()
        self.assertEqual(result["state"], "unknown")
        self.assertEqual(result["returncode"], 7)

    def test_start_failure_is_explicit(self):
        with patch("kirabridge.coordinator_reporting.subprocess.run") as run:
            run.side_effect = FileNotFoundError("private path")
            with self.assertLogs("kirabridge.coordinator_reporting"):
                result = run_status_report(["reporter"], report_id="observed-4")
        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["error"], "report_start_failed")

    def test_next_independent_report_can_succeed(self):
        with patch("kirabridge.coordinator_reporting.subprocess.run") as run:
            run.side_effect = [subprocess.TimeoutExpired(["reporter"], 20), None]
            with self.assertLogs("kirabridge.coordinator_reporting"):
                first = run_status_report(["reporter"], report_id="old-observation")
            second = run_status_report(["reporter"], report_id="new-observation")
        self.assertEqual(run.call_count, 2)
        self.assertEqual(first["state"], "unknown")
        self.assertEqual(second["state"], "sent")
        self.assertNotEqual(first["report_id"], second["report_id"])

    def test_programming_errors_and_interrupts_are_not_swallowed(self):
        for failure in (ValueError("bad caller"), KeyboardInterrupt()):
            with (
                self.subTest(error=type(failure).__name__),
                patch("kirabridge.coordinator_reporting.subprocess.run", side_effect=failure),
                self.assertRaises(type(failure)),
            ):
                run_status_report(["reporter"], report_id="bad-call")
