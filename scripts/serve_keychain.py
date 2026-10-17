"""Optional macOS launchd entrypoint. Reads an existing Keychain item; never logs its value."""

import os
import subprocess
import sys


def main():
    if sys.platform != "darwin" or len(sys.argv) != 2:
        raise SystemExit("Usage on macOS: serve_keychain.py /absolute/config.toml")
    try:
        result = subprocess.run(
            ["/usr/bin/security", "find-generic-password", "-s", "KiraBridge", "-a", "local", "-w"],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise SystemExit("KiraBridge Keychain request timed out") from None
    if result.returncode:
        raise SystemExit("KiraBridge Keychain item is unavailable")
    try:
        token = result.stdout.decode("utf-8").rstrip("\n")
    except UnicodeError:
        raise SystemExit("KiraBridge Keychain token must be UTF-8") from None
    if len(token) < 32:
        raise SystemExit("KiraBridge Keychain token must have at least 32 characters")
    env = os.environ.copy()
    env["KIRABRIDGE_TOKEN"] = token
    os.execve(
        sys.executable,
        [
            sys.executable,
            "-m",
            "kirabridge.cli",
            "--config",
            sys.argv[1],
            "serve",
            "--transport",
            "http",
        ],
        env,
    )


if __name__ == "__main__":
    main()
