"""Pinned CI test lanes. No worker, provider, installation or status API calls."""

import argparse
import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

LEGACY_TD = "770bbc9f0c0a02699cc93cad47d2e2c3782f7080"
REMOTE_TD = "a0dd4c39478b031e0e31d335c2a15435dfbc52eb"
TOLLGATE = "53fc57cc2e082d022e65e5929cb2a1e186fba852"
REMOTE_MODULES = ("test_remote_relay", "test_remote_os_restart")
PREFLIGHT_MAX_BYTES = 16 * 1024
REMOTE_REQUIREMENTS = (
    "pypdf>=6.19,<7",
    "jsonschema==4.25.1",
    "fastapi>=0.110",
    "uvicorn>=0.54,<1",
    "httpx>=0.28,<1",
)


class GateError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise GateError(message)


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args])


def checkout(repo, expected, paths, *, src_count=None, cache_log=None):
    """Bind actual bytes, including absence of untracked source, to commit blobs."""
    require(bool(re.fullmatch(r"[0-9a-f]{40}", expected)), "Full commit pin required")
    require(git(repo, "rev-parse", "HEAD").decode().strip() == expected, "Wrong checkout pin")
    raw = git(repo, "ls-tree", "-r", "-z", expected, "--", *paths)
    files = {}
    for entry in raw.split(b"\0"):
        if not entry:
            continue
        header, name = entry.split(b"\t", 1)
        mode, kind, blob = header.decode().split()
        name = name.decode()
        path = repo / name
        require(kind == "blob" and mode in {"100644", "100755"}, f"Non-file source: {name}")
        require(path.is_file() and not path.is_symlink(), f"Missing/linked source: {name}")
        require(path.resolve() == path, f"Linked source directory: {name}")
        data = path.read_bytes()
        actual = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        require(actual == blob, f"Modified source: {name}")
        files[name] = hashlib.sha256(data).hexdigest()
    require(bool(files), "Empty pinned source tree")
    untracked = git(repo, "ls-files", "--others", "-z", "--", *paths).split(b"\0")
    caches = []
    for name in filter(None, untracked):
        path = repo / name.decode()
        # Existing fixture children with minimal envs can generate bytecode despite
        # the parent's -B. Prune only caches of pinned .py sources in this checkout.
        try:
            original = Path(importlib.util.source_from_cache(str(path)))
        except ValueError:
            raise GateError(f"Untracked source: {path.relative_to(repo)}") from None
        require(
            cache_log is not None
            and original.relative_to(repo).as_posix() in files
            and path.is_file()
            and not path.is_symlink(),
            "Untracked source",
        )
        require(
            path.parent.resolve() == original.parent.resolve() / "__pycache__",
            "Linked bytecode cache directory",
        )
        caches.append(path)
    for path in caches:
        cache_log.append(
            {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        )
        path.unlink()
    if src_count is not None:
        require(sum(n.startswith("src/") for n in files) == src_count, "Wrong src inventory count")
    manifest = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    return {
        "root": str(repo),
        "commit": expected,
        "paths": paths,
        "src_count": src_count,
        "files": files,
        "manifest_sha256": hashlib.sha256(manifest).hexdigest(),
    }


def bound_import(name, source):
    module = importlib.import_module(name)
    filename = getattr(module, "__file__", None)
    require(filename is not None, f"No concrete import file: {name}")
    resolved = Path(filename).resolve()
    require(resolved.is_relative_to(source), f"Wrong import: {name}: {resolved}")
    return str(resolved)


def imports(kb_src, td_src, lane):
    # Reject a preloaded legacy package rather than deleting/reloading its cache.
    for name, module in tuple(sys.modules.items()):
        root = None
        if name == "threaddesk" or name.startswith("threaddesk."):
            root = td_src
        elif name == "kirabridge" or name.startswith("kirabridge."):
            root = kb_src
        if root is not None:
            filename = getattr(module, "__file__", None)
            require(
                filename is not None and Path(filename).resolve().is_relative_to(root),
                f"Foreign cached {'TD' if root == td_src else 'KB'} module: {name}",
            )
    names = {"kirabridge": kb_src, "threaddesk": td_src}
    if lane == "remote":
        names.update(
            {
                "threaddesk.server_sync.app": td_src,
                "threaddesk.services.commands": td_src,
                "kirabridge.remote_relay": kb_src,
                "kirabridge.bridge_core.bridge": kb_src,
            }
        )
    return {name: bound_import(name, root) for name, root in names.items()}


def dependencies(lane):
    from packaging.requirements import Requirement

    prefix = Path(sys.prefix).resolve()
    require(sys.prefix != sys.base_prefix, "Dedicated locked virtual environment required")
    require(
        sys.flags.no_user_site and sys.dont_write_bytecode,
        "Start Python with PYTHONNOUSERSITE=1/PYTHONDONTWRITEBYTECODE=1",
    )
    for path in sys.path:
        if "site-packages" in Path(path).parts or "dist-packages" in Path(path).parts:
            require(Path(path).resolve().is_relative_to(prefix), "External site-packages overlay")
    result = {}
    for dist in importlib.metadata.distributions():
        origin = Path(dist.locate_file("")).resolve()
        require(origin.is_relative_to(prefix), f"External distribution: {dist.metadata['Name']}")
        result[dist.metadata["Name"]] = {"version": dist.version, "origin": str(origin)}
    if lane == "remote":
        for text in REMOTE_REQUIREMENTS:
            req = Requirement(text)
            require(
                importlib.metadata.version(req.name) in req.specifier,
                f"Unsatisfied M4 server requirement: {text}",
            )
    return result


def validate_junit(path, suite_name, started_ns, pytest_exit):
    require(pytest_exit == 0, f"pytest exit {pytest_exit}")
    require(path.is_file() and not path.is_symlink(), "Missing JUnit report")
    require(path.stat().st_mtime_ns >= started_ns, "Stale JUnit report")
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        raise GateError("Unreadable JUnit report") from exc
    require(root.tag == "testsuites", "Unexpected JUnit root")
    suites = root.findall("testsuite")
    require(len(suites) == 1 and suites[0].get("name") == suite_name, "Wrong run/suite binding")
    suite = suites[0]
    cases = suite.findall("testcase")
    require(bool(cases), "Empty JUnit report")
    require(
        not list(root.iter("skipped"))
        and not list(root.iter("error"))
        and not list(root.iter("failure")),
        "Remote skips/errors/failures",
    )
    require(len(list(root.iter("testcase"))) == len(cases), "Unexpected nested testcases")
    try:
        require(int(suite.attrib["tests"]) == len(cases), "JUnit count mismatch")
        require(
            all(int(suite.attrib[k]) == 0 for k in ("skipped", "errors", "failures")),
            "Remote nonzero JUnit status",
        )
    except (KeyError, ValueError) as exc:
        raise GateError("Missing/invalid JUnit counters") from exc
    # pytest normally leaves root counters absent. Other producers may supply
    # any subset; present aggregates must agree with the actual child cases.
    for counter in ("tests", "skipped", "errors", "failures", "disabled"):
        if counter in root.attrib:
            value = root.attrib[counter]
            require(bool(re.fullmatch(r"[0-9]+", value)), f"Root JUnit invalid counter: {counter}")
            expected = len(cases) if counter == "tests" else 0
            require(int(value) == expected, f"Root JUnit inconsistent counter: {counter}")
    counts = dict.fromkeys(REMOTE_MODULES, 0)
    for case in cases:
        module = case.get("classname", "").removeprefix("tests.")
        require(module in counts and bool(case.get("name")), "Unexpected/unnamed remote testcase")
        counts[module] += 1
    require(all(counts.values()), "A remote module did not execute any cases")
    return {"cases": counts, "total": len(cases), "skipped": 0, "errors": 0, "failures": 0}


def filesystem_snapshot(path):
    stat = path.stat()
    usage = os.statvfs(path)
    return {
        "path": str(path.resolve()),
        "device": stat.st_dev,
        "bytes_total": usage.f_blocks * usage.f_frsize,
        "bytes_free": usage.f_bfree * usage.f_frsize,
        "bytes_available": usage.f_bavail * usage.f_frsize,
        "inodes_total": usage.f_files,
        "inodes_free": usage.f_ffree,
        "inodes_available": usage.f_favail,
    }


def prepare_temp_scope(runner_temp, report_dir, lane):
    """Validate the pre-interpreter job scope; create only a fresh lane report dir."""
    require(lane in {"legacy", "remote"}, "CI temp: unknown lane")
    require(
        runner_temp is not None and runner_temp.is_absolute(),
        "CI temp: absolute runner.temp required",
    )
    try:
        parent = runner_temp.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise GateError("CI temp: runner.temp parent unavailable") from exc
    require(parent.is_dir(), "CI temp: runner.temp parent is not a directory")
    runner_value = os.environ.get("RUNNER_TEMP", "")
    require(
        bool(runner_value) and Path(runner_value).is_absolute(),
        "CI temp: absolute RUNNER_TEMP environment required",
    )
    try:
        declared_parent = Path(runner_value).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise GateError("CI temp: RUNNER_TEMP environment unavailable") from exc
    require(parent == declared_parent, "CI temp: parent differs from RUNNER_TEMP")
    values = {
        key: os.environ.get(key, "") for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "UV_PYTHON")
    }
    require(
        bool(re.fullmatch(r"[0-9]+", values["GITHUB_RUN_ID"]))
        and bool(re.fullmatch(r"[0-9]+", values["GITHUB_RUN_ATTEMPT"]))
        and bool(re.fullmatch(r"[0-9]+\.[0-9]+", values["UV_PYTHON"])),
        "CI temp: explicit run/attempt/Python scope required",
    )
    name = "kb-ci-{GITHUB_RUN_ID}-{GITHUB_RUN_ATTEMPT}-{UV_PYTHON}".format(**values)
    expected_tmp = parent / (name + "-tmp")
    tmp_value = os.environ.get("TMPDIR", "")
    require(bool(tmp_value) and Path(tmp_value).is_absolute(), "CI temp: absolute TMPDIR required")
    try:
        actual_tmp = Path(tmp_value).resolve(strict=True)
        report = report_dir.resolve()
    except (OSError, RuntimeError) as exc:
        raise GateError("CI temp: temporary path unavailable") from exc
    require(
        actual_tmp == expected_tmp and actual_tmp.is_dir(), "CI temp: TMPDIR outside this job scope"
    )
    require(
        report_dir.is_absolute() and report == parent / (name + "-" + lane),
        "CI temp: report outside this job/lane scope",
    )
    # Do not reset tempfile's cache: a fallback or prior external selection is a failure.
    effective = Path(tempfile.gettempdir()).resolve(strict=True)
    require(effective == actual_tmp, "CI temp: effective Python tempfile scope differs")
    require(
        actual_tmp.stat().st_dev == parent.stat().st_dev,
        "CI temp: temporary directory on a different filesystem",
    )
    require(not report.exists() and not report.is_symlink(), "CI temp: report directory reused")
    report.mkdir(mode=0o700)
    basetemp = report / "pytest-basetemp"
    return {
        "identity": values,
        "runner_temp_input": str(runner_temp),
        "runner_temp": str(parent),
        "tmpdir_environment": tmp_value,
        "effective_python_temp": str(effective),
        "report_dir": str(report),
        "pytest_basetemp": str(basetemp),
        "filesystem_before": filesystem_snapshot(effective),
        "report_filesystem": filesystem_snapshot(report),
        "runner_filesystem": filesystem_snapshot(parent),
        "workspace_device": Path.cwd().stat().st_dev,
        "root_device": Path("/").stat().st_dev,
        "capacity_limit": "Observed counters only; no free-space guarantee or threshold.",
    }


def emit_preflight(evidence):
    """Flush bounded observed bindings before pytest; this cannot grant acceptance."""
    required = {
        "run_id",
        "lane",
        "python",
        "version",
        "platform",
        "sources",
        "imports_before",
        "temp_scope",
        "environment",
    }
    require(required <= evidence.keys(), "Preflight bindings missing")
    require(
        not {"gate", "pytest_exit", "junit", "finished_ns"} & evidence.keys(),
        "Preflight must precede pytest completion",
    )
    scope_keys = (
        "identity",
        "runner_temp",
        "effective_python_temp",
        "report_dir",
        "pytest_basetemp",
        "filesystem_before",
        "report_filesystem",
        "runner_filesystem",
        "workspace_device",
        "root_device",
    )
    require(
        {"kb", "td"} <= evidence["sources"].keys()
        and {"kirabridge", "threaddesk"} <= evidence["imports_before"].keys()
        and set(scope_keys) <= evidence["temp_scope"].keys(),
        "Preflight bindings missing",
    )
    record = {
        "schema": "kirabridge.ci-preflight.v1",
        "phase": "PREFLIGHT",
        "acceptance": "not_evaluated",
        "pytest_started": False,
        "at_ns": time.time_ns(),
        **{key: evidence[key] for key in ("run_id", "lane", "python", "version", "platform")},
        "job": {
            key: evidence["environment"].get(key)
            for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB", "GITHUB_SHA")
        },
        "sources": {
            name: {
                **{key: source[key] for key in ("root", "commit", "manifest_sha256")},
                "file_count": len(source["files"]),
            }
            for name in ("kb", "td", "tollgate")
            if (source := evidence["sources"].get(name)) is not None
        },
        "imports": dict(evidence["imports_before"]),
        "temp_scope": {key: evidence["temp_scope"][key] for key in scope_keys},
    }
    payload = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    require(len(payload.encode("utf-8")) + 1 <= PREFLIGHT_MAX_BYTES, "Preflight record too large")
    print(payload, flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lane", choices=("legacy", "remote"))
    parser.add_argument("--expected-kb", required=True)
    parser.add_argument("--td", type=Path, required=True)
    parser.add_argument("--tollgate", type=Path)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--runner-temp", type=Path, required=True)
    args = parser.parse_args(argv)
    kb = Path(__file__).resolve().parents[1]
    require(Path.cwd().resolve() == kb, "Run from the pinned KB checkout")
    td = args.td.resolve()
    cache_log = []
    sources = {
        "kb": checkout(
            kb,
            args.expected_kb,
            ["src", "tests", "scripts/ci_remote_tests.py", "pyproject.toml", "uv.lock"],
            cache_log=cache_log,
        ),
        "td": checkout(
            td,
            REMOTE_TD if args.lane == "remote" else LEGACY_TD,
            ["src", "pyproject.toml"],
            src_count=276 if args.lane == "remote" else None,
            cache_log=cache_log,
        ),
    }
    kb_src, td_src = kb / "src", td / "src"
    expected_path = [str(kb_src), str(td_src)]
    require(
        os.environ.get("PYTHONPATH", "").split(os.pathsep) == expected_path,
        "Explicit lane-specific KB/TD PYTHONPATH required",
    )
    require(os.environ.get("KIRABRIDGE_TEST_THREADDESK_SOURCE") == str(td_src), "Wrong TD env")
    remote = os.environ.get("KIRABRIDGE_TEST_REMOTE_THREADDESK_SOURCE", "")
    require(remote == (str(td_src) if args.lane == "remote" else ""), "Wrong paired TD env")
    require(
        not os.environ.get("PYTEST_ADDOPTS") and not os.environ.get("PYTEST_PLUGINS"),
        "External pytest options/plugins are not part of the pinned lane",
    )
    if args.lane == "remote":
        require(os.name == "posix", "R3 requires actual POSIX signal/process support")
    else:
        require(args.tollgate is not None, "Legacy TollGate checkout required")
        tg = args.tollgate.resolve()
        sources["tollgate"] = checkout(tg, TOLLGATE, ["."], cache_log=cache_log)
        require(os.environ.get("KIRABRIDGE_TEST_TOLLGATE_SOURCE") == str(tg), "Wrong TollGate env")
    temp_scope = prepare_temp_scope(args.runner_temp, args.report_dir, args.lane)
    report_dir = Path(temp_scope["report_dir"])
    run_id = uuid.uuid4().hex
    suite = f"{args.lane}-{run_id}"
    xml = report_dir / "pytest.xml"
    selection = (
        [f"tests/{name}.py" for name in REMOTE_MODULES]
        if args.lane == "remote"
        else [f"--ignore=tests/{name}.py" for name in REMOTE_MODULES]
    )
    pytest_args = [
        "-q",
        "-W",
        "error::pytest.PytestUnraisableExceptionWarning",
        "--junitxml",
        str(xml),
        "--basetemp",
        temp_scope["pytest_basetemp"],
        "-o",
        f"junit_suite_name={suite}",
        *selection,
    ]
    evidence = {
        "schema": "kirabridge.ci-test-lane.v1",
        "run_id": run_id,
        "lane": args.lane,
        "python": sys.executable,
        "version": sys.version,
        "platform": platform.platform(),
        "argv": [sys.executable, *sys.argv],
        "pytest_args": pytest_args,
        "cwd": str(kb),
        "sys_path": sys.path[:],
        "sources": sources,
        "temp_scope": temp_scope,
        "removed_derived_bytecode": cache_log,
        "environment": {
            key: os.environ.get(key)
            for key in (
                "PYTHONPATH",
                "PYTHONNOUSERSITE",
                "PYTHONDONTWRITEBYTECODE",
                "UV_PYTHON",
                "UV_PYTHON_DOWNLOADS",
                "KIRABRIDGE_TEST_THREADDESK_SOURCE",
                "KIRABRIDGE_TEST_REMOTE_THREADDESK_SOURCE",
                "KIRABRIDGE_TEST_TOLLGATE_SOURCE",
                "GITHUB_RUN_ID",
                "GITHUB_RUN_ATTEMPT",
                "GITHUB_JOB",
                "GITHUB_SHA",
                "RUNNER_TEMP",
                "TMPDIR",
            )
        },
    }
    evidence_path = report_dir / "provenance.json"
    try:
        evidence["dependencies"] = dependencies(args.lane)
        evidence["imports_before"] = imports(kb_src, td_src, args.lane)
        evidence_path.write_text(json.dumps(evidence, indent=2) + "\n")
        emit_preflight(evidence)
        import pytest

        started = time.time_ns()
        evidence["started_ns"] = started
        exit_code = int(pytest.main(pytest_args))
        evidence["pytest_exit"] = exit_code
        evidence["imports_after"] = imports(kb_src, td_src, args.lane)
        # Detect source mutation during the test run as well as incorrect initial bytes.
        for name, source in sources.items():
            root = Path(source["root"])
            after = checkout(
                root,
                source["commit"],
                source["paths"],
                src_count=source["src_count"],
                cache_log=cache_log,
            )
            require(after == source, f"Source changed during pytest: {name}")
        if args.lane == "remote":
            evidence["junit"] = validate_junit(xml, suite, started, exit_code)
        else:
            require(exit_code == 0, f"Legacy pytest exit {exit_code}")
        evidence["gate"] = "PASS"
    except Exception as exc:
        evidence["gate"] = "FAIL"
        evidence["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        try:
            temp_scope["filesystem_after"] = filesystem_snapshot(
                Path(temp_scope["effective_python_temp"])
            )
        except OSError as exc:
            # Retain the actual test/gate outcome if post-run telemetry is unavailable.
            temp_scope["filesystem_after_error"] = f"{type(exc).__name__}: {exc}"
        evidence["finished_ns"] = time.time_ns()
        evidence_path.write_text(json.dumps(evidence, indent=2) + "\n")
        print(json.dumps(evidence, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
