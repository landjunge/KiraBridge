"""A failed native cleanup must never leave successful acceptance evidence."""

import importlib.util
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


def test_cleanup_failure_marks_json_and_junit_failed():
    path = Path(__file__).parents[1] / "scripts/accept_linux_server.py"
    spec = importlib.util.spec_from_file_location("linux_acceptance", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    evidence = {"result": "passed", "steps": []}
    suite = ET.Element("testsuite")

    def failed_cleanup():
        raise RuntimeError("owned test port remains bound")

    with pytest.raises(RuntimeError, match="port remains bound"):
        module.record_step(evidence, suite, "cleanup", failed_cleanup)
    assert evidence["result"] == "failed"
    assert evidence["steps"][-1]["result"] == "failed"
    assert suite.find("testcase/failure") is not None
