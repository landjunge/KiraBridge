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
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

LEGACY_TD = "770bbc9f0c0a02699cc93cad47d2e2c3782f7080"
REMOTE_TD = "a0dd4c39478b031e0e31d335c2a15435dfbc52eb"
TOLLGATE = "53fc57cc2e082d022e65e5929cb2a1e186fba852"
REMOTE_MODULES = ("test_remote_relay", "test_remote_os_restart")
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
    counts = dict.fromkeys(REMOTE_MODULES, 0)
    for case in cases:
        module = case.get("classname", "").removeprefix("tests.")
        require(module in counts and bool(case.get("name")), "Unexpected/unnamed remote testcase")
        counts[module] += 1
    require(all(counts.values()), "A remote module did not execute any cases")
    return {"cases": counts, "total": len(cases), "skipped": 0, "errors": 0, "failures": 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lane", choices=("legacy", "remote"))
    parser.add_argument("--expected-kb", required=True)
    parser.add_argument("--td", type=Path, required=True)
    parser.add_argument("--tollgate", type=Path)
    parser.add_argument("--report-dir", type=Path, required=True)
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
    report_dir = args.report_dir.resolve()
    # Reuse is an error: a prior successful XML can never substitute for this invocation.
    report_dir.mkdir(parents=True, exist_ok=False)
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
            )
        },
    }
    evidence_path = report_dir / "provenance.json"
    try:
        evidence["dependencies"] = dependencies(args.lane)
        evidence["imports_before"] = imports(kb_src, td_src, args.lane)
        evidence_path.write_text(json.dumps(evidence, indent=2) + "\n")
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
        evidence["finished_ns"] = time.time_ns()
        evidence_path.write_text(json.dumps(evidence, indent=2) + "\n")
        print(json.dumps(evidence, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
