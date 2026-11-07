"""A failed native cleanup must never leave successful acceptance evidence."""

import importlib.util
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "error", [RuntimeError("owned test port remains bound"), KeyboardInterrupt()]
)
def test_cleanup_failure_marks_json_and_junit_failed(error):
    path = Path(__file__).parents[1] / "scripts/accept_linux_server.py"
    spec = importlib.util.spec_from_file_location("linux_acceptance", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    evidence = {"result": "passed", "steps": []}
    suite = ET.Element("testsuite")

    def failed_cleanup():
        raise error

    with pytest.raises(type(error)):
        module.record_step(evidence, suite, "cleanup", failed_cleanup)
    assert evidence["result"] == "failed"
    assert evidence["steps"][-1]["result"] == "failed"
    assert suite.find("testcase/failure") is not None


@pytest.mark.parametrize("cleanup_ok", [True, False])
def test_resume_finds_failed_baseline_before_cleanup_and_rejects_failed_cleanup(cleanup_ok):
    path = Path(__file__).parents[1] / "scripts/accept_linux_server.py"
    spec = importlib.util.spec_from_file_location("linux_acceptance", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    prior = {
        "result": "failed",
        "cleanup": {"unit_absent": True, "port_unbound": True},
        "steps": [
            {"name": "previous-runtime-baseline", "result": "failed"},
            {"name": "cleanup", "result": "passed" if cleanup_ok else "failed"},
        ],
    }
    if cleanup_ok:
        module.validate_update_resume(prior)
    else:
        with pytest.raises(RuntimeError, match="confirmed cleanup"):
            module.validate_update_resume(prior)
