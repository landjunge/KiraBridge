"""Adversarial CI gates; synthetic XML never counts as a remote integration run."""

import importlib.util
import os
import py_compile
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from types import ModuleType

import pytest

SPEC = importlib.util.spec_from_file_location(
    "ci_remote_tests", Path(__file__).resolve().parents[1] / "scripts" / "ci_remote_tests.py"
)
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


@pytest.fixture
def report(tmp_path):
    root = ET.Element("testsuites")
    suite = ET.SubElement(
        root, "testsuite", name="remote-fresh", tests="2", skipped="0", errors="0", failures="0"
    )
    for module in gate.REMOTE_MODULES:
        ET.SubElement(suite, "testcase", classname=f"tests.{module}", name="executed")
    path = tmp_path / "pytest.xml"
    ET.ElementTree(root).write(path)
    return path, root, suite


def check(report, *, exit_code=0, started=0):
    path, root, _ = report
    ET.ElementTree(root).write(path)
    return gate.validate_junit(path, "remote-fresh", started, exit_code)


def test_positive_report_requires_both_real_module_counts(report):
    assert check(report) == {
        "cases": dict.fromkeys(gate.REMOTE_MODULES, 1),
        "total": 2,
        "skipped": 0,
        "errors": 0,
        "failures": 0,
    }


@pytest.mark.parametrize("tag", ["skipped", "failure", "error"])
def test_status_elements_cannot_hide_behind_zero_summary(report, tag):
    ET.SubElement(report[2][0], tag)
    with pytest.raises(gate.GateError, match="skips/errors/failures"):
        check(report)


@pytest.mark.parametrize("counter", ["skipped", "failures", "errors"])
def test_nonzero_summary_is_rejected_even_without_status_child(report, counter):
    report[2].set(counter, "1")
    with pytest.raises(gate.GateError, match="nonzero"):
        check(report)


def fresh_aggregate_report(tmp_path):
    name = "remote-aggregate-" + uuid.uuid4().hex
    root = ET.Element("testsuites")
    suite = ET.SubElement(
        root, "testsuite", name=name, tests="2", skipped="0", errors="0", failures="0"
    )
    for module in gate.REMOTE_MODULES:
        ET.SubElement(suite, "testcase", classname=f"tests.{module}", name="aggregate_probe")
    path = tmp_path / "current-aggregate.xml"
    return path, root, name


def write_fresh_aggregate(path, root):
    started = time.time_ns()
    ET.ElementTree(root).write(path)
    assert path.stat().st_mtime_ns >= started
    assert len(root.findall("testsuite/testcase")) == 2
    assert root[0].attrib["tests"] == "2"
    assert all(root[0].attrib[k] == "0" for k in ("skipped", "errors", "failures"))
    return started


@pytest.mark.parametrize(
    "counter,value",
    [
        ("failures", "1"),
        ("errors", "1"),
        ("skipped", "1"),
        ("disabled", "1"),
        ("tests", "0"),
        ("tests", "3"),
        ("tests", "-1"),
        ("failures", "-1"),
        ("errors", "one"),
        ("skipped", "1.0"),
        ("disabled", ""),
        ("tests", "+2"),
        ("tests", " 2"),
    ],
)
def test_root_aggregate_cannot_contradict_fresh_valid_children(tmp_path, counter, value):
    path, root, name = fresh_aggregate_report(tmp_path)
    # Positive control proves this same fresh suite/modules/exit pass before
    # injecting only the aggregate contradiction. A different gate cannot mask it.
    started = write_fresh_aggregate(path, root)
    assert gate.validate_junit(path, name, started, 0)["total"] == 2
    root.set(counter, value)
    started = write_fresh_aggregate(path, root)
    assert ET.parse(path).getroot().attrib[counter] == value
    with pytest.raises(gate.GateError, match="Root JUnit"):
        gate.validate_junit(path, name, started, 0)


@pytest.mark.parametrize(
    "attributes",
    [
        {},
        {"tests": "2"},
        {"failures": "0"},
        {"tests": "2", "failures": "0", "errors": "0", "skipped": "0", "disabled": "0"},
        {"tests": "002", "skipped": "00"},
    ],
)
def test_optional_consistent_root_aggregate_accepts_fresh_report(tmp_path, attributes):
    path, root, name = fresh_aggregate_report(tmp_path)
    root.attrib.update(attributes)
    started = write_fresh_aggregate(path, root)
    assert gate.validate_junit(path, name, started, 0)["cases"] == dict.fromkeys(
        gate.REMOTE_MODULES, 1
    )


@pytest.mark.parametrize(
    "kind",
    [
        "empty",
        "only-r2",
        "only-r3",
        "foreign",
        "wrong-count",
        "wrong-run",
        "missing-count",
        "nested",
        "unnamed",
    ],
)
def test_unexecuted_stale_or_malformed_coverage_cannot_pass(report, kind):
    suite = report[2]
    if kind == "empty":
        suite.remove(suite[0])
        suite.remove(suite[0])
        suite.set("tests", "0")
    elif kind in {"only-r2", "only-r3"}:
        suite.remove(suite[1 if kind == "only-r2" else 0])
        suite.set("tests", "1")
    elif kind == "foreign":
        suite[1].set("classname", "tests.test_unrelated")
    elif kind == "wrong-count":
        suite.set("tests", "100")
    elif kind == "wrong-run":
        suite.set("name", "remote-previous-attempt")
    elif kind == "missing-count":
        del suite.attrib["tests"]
    elif kind == "nested":
        ET.SubElement(suite, "testsuite").append(ET.Element("testcase"))
    elif kind == "unnamed":
        del suite[1].attrib["name"]
    with pytest.raises(gate.GateError):
        check(report)


def test_successful_old_xml_does_not_override_pytest_failure(report):
    with pytest.raises(gate.GateError, match="pytest exit 2"):
        check(report, exit_code=2)


def test_old_file_timestamp_does_not_count_as_new_run(report):
    path = report[0]
    os.utime(path, ns=(1, 1))
    with pytest.raises(gate.GateError, match="Stale"):
        gate.validate_junit(path, "remote-fresh", 2, 0)


@pytest.mark.parametrize("kind", ["missing", "truncated", "symlink"])
def test_missing_truncated_or_linked_reports_fail(tmp_path, kind):
    path = tmp_path / "report.xml"
    if kind == "truncated":
        path.write_text("<testsuites><testsuite")
    elif kind == "symlink":
        target = tmp_path / "previous.xml"
        target.write_text("<testsuites/>")
        path.symlink_to(target)
    with pytest.raises(gate.GateError):
        gate.validate_junit(path, "remote-fresh", 0, 0)


def test_actual_preloaded_legacy_module_is_not_fixed_by_new_sys_path(tmp_path, monkeypatch):
    legacy, remote = tmp_path / "legacy", tmp_path / "remote"
    for root, value in ((legacy, "old"), (remote, "m4")):
        (root / "threaddesk").mkdir(parents=True)
        (root / "threaddesk" / "__init__.py").write_text(f"identity = {value!r}\n")
    # Preserve the genuine suite cache; load an actual alternate package into this one slot.
    spec = importlib.util.spec_from_file_location("threaddesk", legacy / "threaddesk/__init__.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setitem(sys.modules, "threaddesk", module)
    monkeypatch.syspath_prepend(str(remote))
    assert __import__("threaddesk").identity == "old"
    with pytest.raises(gate.GateError, match="Foreign cached TD module"):
        gate.imports(Path(__file__).resolve().parents[1] / "src", remote, "remote")
    assert sys.modules["threaddesk"] is module  # Gate did not delete or replace the cache.


def test_foreign_cached_kb_submodule_is_rejected(tmp_path, monkeypatch):
    module = ModuleType("kirabridge.ci_foreign_fixture")
    module.__file__ = str(tmp_path / "foreign.py")
    monkeypatch.setitem(sys.modules, module.__name__, module)
    cached_td = sys.modules.get("threaddesk")
    td_src = Path(cached_td.__file__).resolve().parents[1] if cached_td else tmp_path / "td"
    with pytest.raises(gate.GateError, match="Foreign cached KB module"):
        gate.imports(Path(__file__).resolve().parents[1] / "src", td_src, "remote")
    assert sys.modules[module.__name__] is module


def test_resolved_import_outside_requested_source_fails(tmp_path, monkeypatch):
    module = ModuleType("ci_foreign_source")
    module.__file__ = str(tmp_path / "foreign.py")
    monkeypatch.setitem(sys.modules, module.__name__, module)
    with pytest.raises(gate.GateError, match="Wrong import"):
        gate.bound_import(module.__name__, tmp_path / "expected")


@pytest.fixture
def pinned_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    (repo / "src").mkdir()
    (repo / "src" / "module.py").write_text("value = 1\n")
    subprocess.run(["git", "-C", str(repo), "add", "src/module.py"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=CI gate fixture",
            "-c",
            "user.email=fixture@invalid",
            "commit",
            "-m",
            "fixture",
        ],
        check=True,
        capture_output=True,
    )
    pin = gate.git(repo, "rev-parse", "HEAD").decode().strip()
    return repo, pin


def test_actual_blob_content_and_inventory_pin(pinned_repo):
    repo, pin = pinned_repo
    result = gate.checkout(repo, pin, ["src"], src_count=1)
    assert set(result["files"]) == {"src/module.py"}
    assert result["commit"] == pin


def test_only_derived_cache_of_a_pinned_source_can_be_pruned(pinned_repo):
    repo, pin = pinned_repo
    source = repo / "src/module.py"
    cache = Path(py_compile.compile(str(source), doraise=True))
    assert cache.is_file()
    cleanup = []
    result = gate.checkout(repo, pin, ["src"], src_count=1, cache_log=cleanup)
    assert not cache.exists() and len(cleanup) == 1
    assert cleanup[0]["path"] == str(cache) and len(cleanup[0]["sha256"]) == 64
    assert source.read_text() == "value = 1\n" and len(result["files"]) == 1


def test_linked_source_directory_is_rejected_before_cache_cleanup(pinned_repo, tmp_path):
    repo, pin = pinned_repo
    foreign = tmp_path / "foreign-src"
    (repo / "src").rename(foreign)
    (repo / "src").symlink_to(foreign, target_is_directory=True)
    cache = Path(py_compile.compile(str(foreign / "module.py"), doraise=True))
    with pytest.raises(gate.GateError, match="Linked source directory"):
        gate.checkout(repo, pin, ["src"], cache_log=[])
    assert cache.exists()


@pytest.mark.parametrize("kind", ["orphan", "symlink", "linked-directory", "unknown-source"])
def test_cache_cleanup_never_removes_unowned_or_linked_data(pinned_repo, tmp_path, kind):
    repo, pin = pinned_repo
    cache = Path(py_compile.compile(str(repo / "src/module.py"), doraise=True))
    target = cache
    if kind == "orphan":
        target = cache.with_name("untracked.cpython-311.pyc")
        cache.rename(target)
    elif kind == "symlink":
        outside = tmp_path / "outside.pyc"
        outside.write_bytes(cache.read_bytes())
        cache.unlink()
        cache.symlink_to(outside)
    elif kind == "linked-directory":
        outside = tmp_path / "foreign-cache"
        cache.parent.rename(outside)
        cache.parent.symlink_to(outside, target_is_directory=True)
    elif kind == "unknown-source":
        (repo / "src/unknown.py").write_text("value = 'untracked'\n")
    with pytest.raises(gate.GateError):
        gate.checkout(repo, pin, ["src"], cache_log=[])
    assert target.exists()  # Validate the entire candidate list before removing any cache.


@pytest.mark.parametrize(
    "kind", ["wrong-pin", "modified", "untracked", "ignored", "missing", "symlink", "wrong-count"]
)
def test_checkout_rejects_foreign_or_mutated_source(pinned_repo, kind):
    repo, pin = pinned_repo
    path = repo / "src" / "module.py"
    count = 1
    if kind == "wrong-pin":
        pin = "0" * 40
    elif kind == "modified":
        path.write_text("value = 2\n")
    elif kind in {"untracked", "ignored"}:
        if kind == "ignored":
            (repo / ".gitignore").write_text("src/extra.py\n")
        (repo / "src" / "extra.py").write_text("shadow = True\n")
    elif kind == "missing":
        path.unlink()
    elif kind == "symlink":
        path.unlink()
        target = repo / "other.py"
        target.write_text("value = 1\n")
        path.symlink_to(target)
    elif kind == "wrong-count":
        count = 276
    with pytest.raises(gate.GateError):
        gate.checkout(repo, pin, ["src"], src_count=count)
