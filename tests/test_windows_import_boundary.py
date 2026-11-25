"""Unused Linux terminal support must not require POSIX-only modules on Windows."""

import subprocess
import sys
from pathlib import Path


def test_cli_import_and_unused_linux_adapter_do_not_load_posix_pty_modules():
    source = Path(__file__).resolve().parents[1] / "src"
    code = r"""
import importlib.abc
import sys

sys.path.insert(0, sys.argv[1])
blocked = {"pty", "tty", "termios"}

class MissingWindowsModules(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in blocked:
            raise ModuleNotFoundError("POSIX-only module unavailable: " + fullname)

sys.meta_path.insert(0, MissingWindowsModules())
from kirabridge.cli import main
from kirabridge.platform_adapters.linux.owned_terminal import LinuxOwnedTerminal

assert callable(main)
LinuxOwnedTerminal()
assert not blocked.intersection(sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", code, str(source)],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
