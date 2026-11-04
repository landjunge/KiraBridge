"""Native official-client configuration check; no tunnel runtime or account contact.

Used by the guest setup acceptance harness, never on the development host. The
only CLI commands are version, static help, offline profile validation and doctor
against the caller's owned loopback server. No run/connect/admin command exists.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
import threading
import uuid
from pathlib import Path

from kirabridge import windows_setup_client as client
from kirabridge.bridge_core.config import private_directory
from kirabridge.bridge_core.models import BridgeError
from kirabridge.private_files import write_private
from kirabridge.windows_setup_runtime import process_identity

MAX_OUTPUT = 65536
REQUIRED_DOCTOR = {
    "config_source",
    "profile_load",
    "tunnel_id",
    "control_plane_api_key",
    "mcp_target",
    "mcp_server_reachable",
    "health_listener",
    "ui",
}


def failed(code):
    return BridgeError(
        code, "Native tunnel-client configuration check failed; preserve its receipt"
    )


def _run(binary, arguments, env, folder, name):
    """Bounded in-memory diagnostics; never signal/retry an uncertain child."""
    write_private(
        folder / (name + "-attempt.json"),
        json.dumps(
            {
                "state": "attempted_no_retry",
                "command_kind": name,
                "runtime_start_requested": False,
            }
        ),
    )
    child = subprocess.Popen(
        [str(binary), *arguments],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NEW_CONSOLE,
        close_fds=True,
    )
    try:
        identity = process_identity(child.pid)
    except BridgeError:
        identity = None  # Fast-exited readonly child; retained Popen exit is still authoritative.
    write_private(
        folder / (name + "-spawned.json"), json.dumps({"pid": child.pid, "identity": identity})
    )
    outputs, oversized = [bytearray(), bytearray()], [False, False]

    def drain(stream, index):
        while chunk := stream.read(4096):
            remaining = MAX_OUTPUT - len(outputs[index])
            outputs[index].extend(chunk[:remaining])
            if len(chunk) > remaining:
                oversized[index] = True
        stream.close()

    threads = [
        threading.Thread(target=drain, args=(stream, index), daemon=True)
        for index, stream in enumerate((child.stdout, child.stderr))
    ]
    for thread in threads:
        thread.start()
    try:
        code = child.wait(timeout=45)
    except subprocess.TimeoutExpired:
        raise failed("setup_client_native_unknown") from None  # Original child is preserved.
    for thread in threads:
        thread.join(timeout=2)
    if any(thread.is_alive() for thread in threads) or any(oversized):
        raise failed("setup_client_native_output_limit")
    stdout, stderr = map(bytes, outputs)
    write_private(
        folder / (name + "-result.json"),
        json.dumps(
            {
                "exit_code": code,
                "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
                "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
                "raw_output_saved": False,
            }
        ),
    )
    return code, stdout, stderr


@client.boundary
def verify_client(binary, state_dir, endpoint, bearer_token) -> dict:
    client.windows()
    state = client.safe_path(state_dir)
    if Path(binary) != client.find_client(state):
        raise failed("setup_client_native_binary")
    client.endpoint(endpoint, {"/mcp"})
    env = client.child_environment(bearer_token)
    folder = state / ("native-client-check-" + uuid.uuid4().hex)
    if os.path.lexists(folder):
        raise failed("setup_client_native_existing")
    private_directory(folder)
    key, profile = folder / "dummy-runtime.key", folder / "dummy-profile.yaml"
    # This value is deliberately not an account credential and is never sent
    # to OpenAI. doctor only loads it and probes the configured local MCP URL.
    write_private(key, "sk-native-configuration-check-" + secrets.token_hex(24))
    value = client.profile_value(state, "tunnel_" + "a" * 32, key, endpoint)
    write_private(profile, json.dumps(value, sort_keys=True))
    code, version, _ = _run(binary, ["--version"], env, folder, "version")
    if code != 0 or version.decode("utf-8").strip() not in {"0.0.19", "v0.0.19"}:
        raise failed("setup_client_native_version")
    code, help_text, _ = _run(binary, ["help", "quickstart"], env, folder, "quickstart")
    if code != 0 or any(
        word not in help_text.lower() for word in (b"tunnel-client", b"init", b"run")
    ):
        raise failed("setup_client_native_help")
    profiles = folder / "validated-profiles"
    code, _, _ = _run(
        binary,
        [
            "profiles",
            "add",
            "parser-check",
            "--profile-dir",
            str(profiles),
            "--from-file",
            str(profile),
        ],
        env,
        folder,
        "parser",
    )
    if code != 0 or (profiles / "parser-check.yaml").read_bytes() != profile.read_bytes():
        raise failed("setup_client_native_parser")
    code, raw, _ = _run(
        binary, ["doctor", "--profile-file", str(profile), "--json"], env, folder, "doctor"
    )
    try:
        doctor = json.loads(raw)
        rows = doctor["checks"]
        if not isinstance(rows, list) or len(rows) > 32:
            raise ValueError
        checks = {item["id"]: item["status"] for item in rows}
        if len(checks) != len(rows) or any(
            status not in {"PASS", "FAIL", "SKIP"} for status in checks.values()
        ):
            raise ValueError
        if any(checks.get(name) != "PASS" for name in REQUIRED_DOCTOR):
            raise ValueError
        # The official doctor's OAuth metadata probe deliberately does not use
        # runtime extra headers. A protected localhost MCP may therefore fail
        # only this diagnostic; it is not reported as successful authentication.
        failures = {name for name, status in checks.items() if status == "FAIL"}
        if failures - {"oauth_metadata"} or code not in (0, 2):
            raise ValueError
        if doctor["result"] not in {"ok", "fail"}:
            raise ValueError
        if (doctor["result"] == "ok") != (code == 0) or (code == 0) != (not failures):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        raise failed("setup_client_native_doctor") from None
    result = {
        "passed": True,
        "scope": "Official CLI Windows parser and local-only doctor",
        "official_client_version": "0.0.19",
        "profile_parser_passed": True,
        "doctor_exit_code": code,
        "doctor_passed": code == 0,
        "doctor_checks": {
            name: checks[name]
            for name in REQUIRED_DOCTOR | {"oauth_metadata", "codex_plugin"}
            if name in checks
        },
        "local_oauth_diagnostic_limited": bool(failures),
        "no_tunnel_runtime_started": True,
        "no_account_contact_performed": True,
        "account_access_verified": False,
        "secrets_returned": False,
        "profile_sha256": hashlib.sha256(profile.read_bytes()).hexdigest(),
    }
    write_private(folder / "completed.json", json.dumps(result, sort_keys=True))
    return result
