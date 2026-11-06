"""Hermetic temp-scope checks in fresh Python children; no remote/product suite."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parents[1] / "scripts/ci_remote_tests.py"
BOOTSTRAP = r"""
import importlib.util,json,pathlib,sys,tempfile
config=json.loads(sys.argv[1])
spec=importlib.util.spec_from_file_location('temp_scope_under_test',config['script'])
gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)
if config.get('cached_external'):
    tempfile.tempdir=config['cached_external']
try:
    # Observe real contemporaneous OS calls; don't compare dynamic capacity
    # counters from different instants or replace them with fabricated values.
    statvfs=gate.os.statvfs
    samples=[]
    def observe(path):
        value=statvfs(path)
        samples.append({'path':str(path),'raw':list(value)})
        return value
    gate.os.statvfs=observe
    try:
        scope=gate.prepare_temp_scope(pathlib.Path(config['parent']),pathlib.Path(config['report']),config['lane'])
    finally:
        gate.os.statvfs=statvfs
    with tempfile.NamedTemporaryFile() as probe:
        probe.write(b'owned temporary probe');probe.flush()
        actual_probe=str(pathlib.Path(probe.name).resolve().parent)
    result={'accepted':True,'scope':scope,'statvfs_samples':samples,
            'actual_probe_parent':actual_probe,'helper_import':gate.__file__}
    if config.get('pytest_probe'):
        import pytest
        result['pytest_exit']=int(pytest.main([config['pytest_probe'],'-q','--basetemp',scope['pytest_basetemp']]))
    print(json.dumps(result));raise SystemExit(0)
except gate.GateError as exc:
    print(json.dumps({'accepted':False,'error_type':type(exc).__name__,'error':str(exc)}))
    raise SystemExit(1)
"""


@pytest.fixture
def context(tmp_path):
    root = tmp_path.resolve()
    parent = root / "runner-temp"
    parent.mkdir()
    python = f"{sys.version_info.major}.{sys.version_info.minor}"
    prefix = f"kb-ci-42-1-{python}"
    job_tmp = parent / (prefix + "-tmp")
    job_tmp.mkdir()
    outside = root / "other-owned-test-data"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_bytes(b"preserve owned test sentinel")
    return {
        "script": str(HARNESS),
        "parent": str(parent),
        "report": str(parent / (prefix + "-legacy")),
        "lane": "legacy",
        "job_tmp": str(job_tmp),
        "outside": str(outside),
        "sentinel": str(sentinel),
        "python": python,
        "root": str(root),
    }


def run_child(config, *, changes=None):
    environment = {
        **os.environ,
        "TMPDIR": config["job_tmp"],
        "RUNNER_TEMP": config["parent"],
        "GITHUB_RUN_ID": "42",
        "GITHUB_RUN_ATTEMPT": "1",
        "UV_PYTHON": config["python"],
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTEST_ADDOPTS": "",
        "PYTEST_PLUGINS": "",
    }
    for key, value in (changes or {}).items():
        if value is None:
            environment.pop(key, None)
        else:
            environment[key] = value
    completed = subprocess.run(
        [sys.executable, "-c", BOOTSTRAP, json.dumps(config)],
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
    )
    records = [json.loads(line) for line in completed.stdout.splitlines() if line.startswith("{")]
    assert len(records) == 1, completed.stdout + completed.stderr
    return completed, records[0]


def test_actual_tempfile_and_pytest_use_fresh_job_and_lane_scope(context):
    probe = Path(context["root"]) / "test_actual_basetemp.py"
    path_record = Path(context["root"]) / "pytest-path.json"
    probe.write_text(
        "import json\nfrom pathlib import Path\n"
        "def test_owned_path(tmp_path):\n"
        f"    Path({str(path_record)!r}).write_text(json.dumps(str(tmp_path)))\n"
    )
    context["pytest_probe"] = str(probe)
    completed, result = run_child(context)
    assert completed.returncode == 0 and result["accepted"] and result["pytest_exit"] == 0
    scope = result["scope"]
    assert result["helper_import"] == str(HARNESS)
    assert result["actual_probe_parent"] == context["job_tmp"] == scope["effective_python_temp"]
    assert Path(json.loads(path_record.read_text())).is_relative_to(Path(scope["pytest_basetemp"]))
    assert Path(scope["pytest_basetemp"]).parent == Path(context["report"])
    assert scope["filesystem_before"]["device"] == Path(context["parent"]).stat().st_dev
    assert scope["report_filesystem"]["device"] == scope["runner_filesystem"]["device"]
    usage = os.statvfs_result(
        next(
            s["raw"]
            for s in result["statvfs_samples"]
            if s["path"] == scope["effective_python_temp"]
        )
    )
    assert scope["filesystem_before"]["bytes_total"] == usage.f_blocks * usage.f_frsize
    assert scope["filesystem_before"]["inodes_total"] == usage.f_files
    assert scope["filesystem_before"]["inodes_free"] == usage.f_ffree
    assert Path(context["sentinel"]).read_bytes() == b"preserve owned test sentinel"


def test_legacy_and_remote_report_dirs_are_separate_and_reuse_is_refused(context):
    legacy, first = run_child(context)
    assert legacy.returncode == 0
    context["lane"] = "remote"
    context["report"] = context["report"].removesuffix("legacy") + "remote"
    remote, second = run_child(context)
    assert remote.returncode == 0
    assert first["scope"]["pytest_basetemp"] != second["scope"]["pytest_basetemp"]
    marker = Path(context["report"]) / "keep"
    marker.write_bytes(b"do not clear an old report directory")
    duplicate, failure = run_child(context)
    assert duplicate.returncode == 1 and failure["error"] == "CI temp: report directory reused"
    assert marker.read_bytes() == b"do not clear an old report directory"


def test_runner_parent_alias_resolves_to_actual_runner_storage(context):
    actual = context["parent"]
    alias = Path(context["root"]) / "runner-parent-alias"
    alias.symlink_to(actual, target_is_directory=True)
    context["parent"] = str(alias)
    completed, result = run_child(context)
    assert completed.returncode == 0
    assert result["scope"]["runner_temp_input"] == str(alias)
    assert result["scope"]["runner_temp"] == actual


@pytest.mark.parametrize(
    "kind",
    [
        "parent-missing",
        "parent-file",
        "parent-relative",
        "parent-other-existing",
        "runner-env-missing",
        "runner-env-relative",
        "runner-env-unavailable",
        "tmp-unset",
        "tmp-missing",
        "tmp-file",
        "tmp-external",
        "tmp-other-job",
        "tmp-symlink-external",
        "report-external",
        "report-wrong-lane",
        "cached-external",
        "run-missing",
        "attempt-invalid",
        "python-invalid",
    ],
)
def test_wrong_missing_or_external_scope_fails_without_touching_other_data(context, kind):
    changes = {}
    report = Path(context["report"])
    if kind == "parent-missing":
        context["parent"] = str(Path(context["root"]) / "missing-parent")
    elif kind == "parent-file":
        parent = Path(context["root"]) / "file-parent"
        parent.write_text("not a directory")
        context["parent"] = str(parent)
    elif kind == "parent-relative":
        context["parent"] = "relative-parent"
    elif kind == "parent-other-existing":
        changes["RUNNER_TEMP"] = context["parent"]
        context["parent"] = context["outside"]
    elif kind == "runner-env-missing":
        changes["RUNNER_TEMP"] = None
    elif kind == "runner-env-relative":
        changes["RUNNER_TEMP"] = "relative-parent"
    elif kind == "runner-env-unavailable":
        changes["RUNNER_TEMP"] = str(Path(context["root"]) / "missing-parent")
    elif kind == "tmp-unset":
        changes["TMPDIR"] = None
    elif kind == "tmp-missing":
        Path(context["job_tmp"]).rmdir()
    elif kind == "tmp-file":
        Path(context["job_tmp"]).rmdir()
        Path(context["job_tmp"]).write_text("not a directory")
    elif kind == "tmp-external":
        changes["TMPDIR"] = context["outside"]
    elif kind == "tmp-other-job":
        other = Path(context["job_tmp"].replace("kb-ci-42-", "kb-ci-43-"))
        other.mkdir()
        changes["TMPDIR"] = str(other)
    elif kind == "tmp-symlink-external":
        Path(context["job_tmp"]).rmdir()
        Path(context["job_tmp"]).symlink_to(context["outside"], target_is_directory=True)
    elif kind == "report-external":
        context["report"] = str(Path(context["outside"]) / report.name)
    elif kind == "report-wrong-lane":
        context["report"] += "-different"
    elif kind == "cached-external":
        context["cached_external"] = context["outside"]
    elif kind == "run-missing":
        changes["GITHUB_RUN_ID"] = None
    elif kind == "attempt-invalid":
        changes["GITHUB_RUN_ATTEMPT"] = "../other"
    elif kind == "python-invalid":
        changes["UV_PYTHON"] = "/outside/python"
    completed, failure = run_child(context, changes=changes)
    assert completed.returncode == 1 and failure["accepted"] is False
    assert failure["error_type"] == "GateError" and failure["error"].startswith("CI temp:")
    assert not Path(context["report"]).exists() and not report.exists()
    assert Path(context["sentinel"]).read_bytes() == b"preserve owned test sentinel"
