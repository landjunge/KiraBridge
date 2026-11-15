"""Exercise the generated CMD with real CPython, including self-rewriting callers."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from test_windows_standalone import manager

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Native Windows CMD contract")


@pytest.fixture
def native_launcher(tmp_path):
    # Reuse this interpreter's read-only standard library through a private ._pth;
    # this is a small launcher fixture, never a distributable application runtime.
    base = Path(sys.base_prefix)
    payload = tmp_path / "payload"
    runtime = payload / "runtime"
    runtime.mkdir(parents=True)
    shutil.copy2(base / "python.exe", runtime / "python.exe")
    for dll in base.glob("*.dll"):
        shutil.copy2(dll, runtime / dll.name)
    (runtime / f"python{sys.version_info.major}{sys.version_info.minor}._pth").write_text(
        str(base / "Lib") + "\n" + str(base / "DLLs") + "\n", encoding="utf-8"
    )
    (payload / "scripts").mkdir()
    (payload / "scripts/windows_standalone.py").write_text(
        "from pathlib import Path\nimport json,sys\n"
        "root=Path(sys.argv[2])\n"
        "root.joinpath('data','arguments.json').write_text(json.dumps(sys.argv[3:]))\n"
        "if 'rewrite' in sys.argv:\n"
        " root.joinpath('KiraBridge.cmd').write_text('@echo off\\nrem '+('x'*300)"
        "+'\\nexit /b 99\\n')\n"
        "raise SystemExit(int(sys.argv[-1]))\n",
        encoding="utf-8",
    )
    files = {
        p.relative_to(payload).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in payload.rglob("*")
        if p.is_file()
    }
    (payload / "provenance.json").write_text(
        json.dumps({"version": "fixture", "commit": "a" * 40, "files": files})
    )
    root = tmp_path / "fresh ! profile" / "KiraBridge"
    manager.install(root, payload, version="fixture", commit="a" * 40)
    manager.launcher(root)
    return root


@pytest.mark.parametrize(
    "code,inherited_errorlevel",
    [(0, None), (7, None), (260, None), (7, "0"), (260, "0"), (0, "999")],
    ids=[
        "clean-zero",
        "clean-seven",
        "clean-wide",
        "shadow-zero-seven",
        "shadow-zero-wide",
        "shadow999-zero",
    ],
)
@pytest.mark.parametrize("rewrite", [False, True])
def test_native_generated_launcher_preserves_exit_and_arguments(
    native_launcher, code, inherited_errorlevel, rewrite
):
    arguments = ["literal!value & spaces", *(["rewrite"] if rewrite else []), str(code)]
    # CMD requires the complete /c command's outer quotes in addition to the
    # quoted batch path and literal arguments. These are closed test vectors.
    values = [str(native_launcher / "KiraBridge.cmd"), *arguments]
    assert not any('"' in value for value in values)
    line = " ".join('"' + value + '"' for value in values)
    command = '"' + os.environ["COMSPEC"] + '" /d /s /v:off /c "' + line + '"'
    environment = dict(os.environ)
    if inherited_errorlevel is not None:
        environment["ERRORLEVEL"] = inherited_errorlevel
    result = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=20)
    assert result.returncode == code, result.stderr
    assert json.loads((native_launcher / "data/arguments.json").read_text()) == arguments


def test_native_generated_launcher_does_not_clear_callers_errorlevel_variable(native_launcher):
    values = [str(native_launcher / "KiraBridge.cmd"), "7"]
    assert not any('"' in value for value in values)
    line = " ".join('"' + value + '"' for value in values)
    command = (
        '"'
        + os.environ["COMSPEC"]
        + '" /d /s /v:off /c "call '
        + line
        + ' & set ERRORLEVEL & echo KB-CALLER-CONTINUED"'
    )
    result = subprocess.run(
        command,
        env={**os.environ, "ERRORLEVEL": "999"},
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert "ERRORLEVEL=999" in result.stdout.splitlines()
    assert "KB-CALLER-CONTINUED" in result.stdout.splitlines()
