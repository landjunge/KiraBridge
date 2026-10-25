"""Fail closed unless an Intel job uses the dedicated, isolated macOS account.

This is a deployment sanity check, not a sandbox against malicious repository code.
Repository-level fork workflow restrictions remain mandatory.
"""

from __future__ import annotations

import grp
import os
import platform
import pwd
import stat
import subprocess
from pathlib import Path


def check_host() -> None:
    if platform.system() != "Darwin" or platform.machine() != "x86_64":
        raise RuntimeError("Intel macOS required; this is not ARM acceptance")
    user = pwd.getpwuid(os.getuid())
    home = Path(user.pw_dir)
    if user.pw_name != "kirabridge-ci" or user.pw_uid < 502:
        raise RuntimeError("Use the dedicated kirabridge-ci account, never the production user")
    if home != Path("/Users/kirabridge-ci") or Path.home() != home:
        raise RuntimeError("Use the account's real NSS home; no HOME override")
    groups = {*os.getgroups(), os.getgid(), user.pw_gid}
    if grp.getgrnam("admin").gr_gid in groups:
        raise RuntimeError("The CI account must not be an administrator")
    info = home.stat()
    if info.st_uid != user.pw_uid or stat.S_IMODE(info.st_mode) != 0o700:
        raise RuntimeError("The dedicated CI home must be owned by its UID and mode 0700")
    if not Path("/Users/landjunge").is_dir():
        raise RuntimeError("Expected production home missing; isolation has not been verified")
    if any(os.access("/Users/landjunge", mode) for mode in (os.R_OK, os.W_OK, os.X_OK)):
        raise RuntimeError("Production home is accessible; do not run repository code")
    workspace = Path(os.environ.get("GITHUB_WORKSPACE", ".")).resolve()
    if not workspace.is_relative_to(home):
        raise RuntimeError("The workflow workspace must be inside the dedicated account home")
    result = subprocess.run(
        ["/bin/launchctl", "print", f"gui/{user.pw_uid}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("A separate GUI login is required for the real launchd acceptance")
    print("Isolated Intel macOS account, private workspace and GUI domain verified")


if __name__ == "__main__":
    check_host()
