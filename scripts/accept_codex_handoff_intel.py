"""Reviewable manual acceptance: private HTTP Core, one fresh native Codex window.

Without --execute this prints the review plan and performs no work. Execution
requires exact interpreter/package/source/version, separate package/harness
commit pins and a Codex binary pin.
Root must review this harness before enabling its single owned visible window.
Never pass an existing pane, previous task ID, config file, HOME or CODEX_HOME.

Existing independent turn/protocol helpers come from accept_macos_adapter_intel;
tasks, input, Return and body_only_v1 handoffs use the ordinary product routes.
An unknown result stops the run. No input request is retried, including cleanup.
Private captures must not become public release assets.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import math
import os
import platform
import pwd
import re
import secrets
import shlex
import signal
import socket
import stat
import subprocess
import sys
import time
import tomllib
from pathlib import Path

import httpx
import uvicorn

import kirabridge
from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import (
    AgentConfig,
    Config,
    PrincipalConfig,
    VisibleTerminalBinding,
)
from kirabridge.bridge_core.models import TaskRequest
from kirabridge.literal_session_input import codex_full_row_widths
from kirabridge.mcp_gateway.client import MCPClientPool, Peer
from kirabridge.mcp_gateway.http import create_http_app
from kirabridge.operations_service import installed_source_sha
from kirabridge.platform_adapters.macos.system_identity import (
    installed_native_contract,
    installed_source_commit,
)
from kirabridge.platform_adapters.macos.system_transport import NativeSystemTransport
from kirabridge.platform_adapters.shell_prompt import empty_shell_prompt
from kirabridge.visible_readiness import assess, input_view

TERMINAL = {"completed", "failed", "cancelled", "unknown", "blocked"}
CODEX_CONTEXT_KEYS = (
    "HOME",
    "CODEX_HOME",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "XDG_STATE_HOME",
    "XDG_CACHE_HOME",
    "CODEX_PROFILE",
    "CODEX_CONFIG_PROFILE",
)
BUSY_SOURCE = (
    "CONTEXT_KEYS="
    + repr(CODEX_CONTEXT_KEYS)
    + "\n"
    + """import json,os,sys,time
from pathlib import Path
root=Path(sys.argv[1])
(root/'busy-started.json').write_text(json.dumps({
    'pid':os.getpid(),'tty':os.ttyname(1),
    'config_context':{key:os.environ.get(key) for key in CONTEXT_KEYS}
}))
deadline=time.monotonic()+45
while not (root/'release-busy').exists():
    if time.monotonic()>deadline:sys.exit(99)
    time.sleep(.05)
"""
)


def require(value, message):
    if not value:
        raise RuntimeError(message)


def file_sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def text_sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def endpoint_absent(port):
    with socket.socket() as probe:
        probe.settimeout(1)
        return probe.connect_ex(("127.0.0.1", port)) != 0


def codex_config_context(environment):
    return {key: environment.get(key) for key in CODEX_CONTEXT_KEYS}


def verify_shell_config_context(receipt, expected):
    require(
        isinstance(receipt, dict) and receipt.get("config_context") == expected,
        "Owned shell Codex config context differs; do not start Codex",
    )
    require(
        isinstance(expected.get("HOME"), str)
        and Path(expected["HOME"]).is_absolute()
        and not expected.get("CODEX_HOME"),
        "Unsupported effective Codex reader root",
    )
    return str(Path(expected["HOME"]) / ".codex")


def require_known_managed_absent(paths):
    observed = {str(path): path.exists() or path.is_symlink() for path in paths}
    require(not any(observed.values()), "Observed managed Codex config requires separate review")
    return observed


def known_managed_paths(home):
    username = pwd.getpwuid(os.getuid()).pw_name
    return (
        Path("/etc/codex/requirements.toml"),
        Path("/etc/codex/managed_config.toml"),
        Path("/Library/Managed Preferences/com.openai.codex.plist"),
        Path("/Library/Managed Preferences") / username / "com.openai.codex.plist",
        home / "Library/Preferences/com.openai.codex.plist",
    )


def review_plan():
    return {
        "execute": False,
        "scope": "one new owned Intel Terminal.app window and private loopback Core",
        "steps": [
            "Verify exact package/interpreter/source/version, separate package/harness "
            "commits and local Codex help/hash.",
            "Verify invocation-only MCP entries/features are disabled; retain auth and home.",
            "Record original complete native inventory and exact process identities.",
            "Open exactly one fresh controlled shell; reject adoption or another window.",
            "Exercise real bounded busy shell and stale PID refusal with zero new input.",
            "Start locally verified Codex CLI without shared daemon, inside private workspace.",
            "At 131 columns refuse fresh full-row literal and handoff before any paste.",
            "At 130 columns send one long literal paste and one Return; match own screen/turn.",
            "Send one unchanged body_only_v1 handoff and independently verify its local reply.",
            "Stop private Core; SIGTERM only the unchanged owned Codex; close only idle shell.",
            "Independently prove own window/PIDs absent; record foreign changes read-only.",
        ],
        "forbidden": [
            "production endpoint/config/service changes",
            "existing pane adoption, resume, historical task or uncertain-input replay",
            "HOME/CODEX_HOME/auth changes, extra window, hidden fallback or keyboard cleanup",
        ],
        "review_sources": [
            "scripts/accept_shell_input_intel.py",
            "scripts/accept_macos_adapter_intel.py",
            "scripts/accept_closed_terminal_intel.py",
            "docs/RC24-PREFLIGHT-20261101.md",
        ],
    }


def build_prompts(nonce):
    require(re.fullmatch(r"[a-f0-9]{16}", nonce), "Use a fresh 16-character hex nonce")
    marker = "KB_ACCEPT_" + nonce.upper()
    filler = (
        "Dies ist eine isolierte Eingabeprüfung. Verwende keine Werkzeuge und ändere keine "
        "Dateien. Es gibt keinen Entwicklungsauftrag. Antworte nur mit der verlangten Kennung. "
    )
    raw = f"Antworte ausschließlich mit {marker}_RAW.\n\n" + (filler + "\n\n") * 9
    raw += f"Die einzige Antwort ist {marker}_RAW"
    body = f"Antworte ausschließlich mit {marker}_HANDOFF.\n" + (filler * 3).strip()
    for _ in range(12):
        if not codex_full_row_widths(body, 130):
            break
        body += " Prüfung."
    ambiguous = f"Reply with MARKER_{nonce}.\n" + "abc " * 95 + "abcd"
    require(1000 < len(raw) < 16384 and 300 < len(body) < 1000, "Fixture size changed")
    require(not codex_full_row_widths(body, 130), "Positive fixture is ambiguous")
    require(codex_full_row_widths(ambiguous, 131) == (128,), "Negative fixture changed")
    return marker, raw, body, ambiguous


CODEX_DISABLED_FEATURES = (
    "hooks",
    "plugins",
    "remote_plugin",
    "apps",
    "enable_mcp_apps",
    "skill_mcp_dependency_install",
    "shell_tool",
)


def codex_config_inputs(workspace):
    """Read/hash config sources, without copying their possibly secret values.

    Empty TOML tables merge recursively in pinned Codex; they do not clear MCP
    entries. Disable every discovered server by name and verify the effective
    CLI result before UI. Unexpected managed servers cause refusal, not repair.
    Profiles are deliberately outside this small harness's support boundary.
    """
    paths = {
        Path("/etc/codex/config.toml"),
        Path.home() / ".codex/config.toml",
        workspace / "config.toml",
        *(parent / ".codex/config.toml" for parent in (workspace, *workspace.parents)),
    }
    return read_codex_configs(paths)


def read_codex_configs(paths):
    snapshot, names = {}, set()
    for path in sorted(paths):
        require(not path.is_symlink(), "Config symlinks require separate review")
        if not path.exists():
            snapshot[str(path)] = None
            continue
        data = path.read_bytes()
        require(len(data) <= 1024 * 1024, "Codex config exceeds review budget")
        config = tomllib.loads(data.decode())
        require(not config.get("profile"), "Selected Codex profile requires separate review")
        servers = config.get("mcp_servers", {})
        require(isinstance(servers, dict), "Malformed MCP config")
        for name in servers:
            require(re.fullmatch(r"[a-zA-Z0-9_-]+", name), "Unexpected MCP server identifier")
            names.add(name)
        snapshot[str(path)] = hashlib.sha256(data).hexdigest()
    return snapshot, sorted(names)


def codex_arguments(binary, workspace, server_names=()):
    # These flags are required in the pinned local --help. Overrides apply only
    # to this invocation; the harness never writes the user's Codex config/auth.
    overrides = [
        *("features." + name + "=false" for name in CODEX_DISABLED_FEATURES),
        *("mcp_servers." + name + ".enabled=false" for name in server_names),
        'history.persistence="none"',
        "projects." + json.dumps(str(workspace)) + '.trust_level="trusted"',
    ]
    shared = [part for value in overrides for part in ("-c", value)]
    return [
        str(binary),
        "--no-alt-screen",
        "--no-daemon",
        "--strict-config",
        "-s",
        "read-only",
        "-a",
        "never",
        "-C",
        str(workspace),
        *shared,
    ], shared


def verify_cli_isolation(feature_output, server_output, server_names):
    rows = {parts[0]: parts[-1] for line in feature_output.splitlines() if (parts := line.split())}
    require(
        all(rows.get(name) == "false" for name in CODEX_DISABLED_FEATURES),
        "Effective Codex features are not isolated",
    )
    servers = json.loads(server_output)
    require(isinstance(servers, list), "Unknown Codex MCP listing format")
    require(
        all(isinstance(row, dict) and row.get("enabled") is False for row in servers)
        and sorted(row.get("name", "") for row in servers) == sorted(server_names),
        "Unexpected or enabled Codex MCP server; stop before UI",
    )


async def inspect_cli_isolation(binary, overrides, server_names, workspace):
    feature_listing = await asyncio.to_thread(
        subprocess.run,
        [str(binary), *overrides, "features", "list"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
        cwd=workspace,
    )
    # --strict-config is intentionally absent here: pinned CLI rejects it for
    # the mcp subcommand. mcp list may inspect auth status; it never dispatches
    # tools. Known servers are disabled before this management call.
    listing = await asyncio.to_thread(
        subprocess.run,
        [str(binary), *overrides, "mcp", "list", "--json"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
        cwd=workspace,
    )
    verify_cli_isolation(feature_listing.stdout, listing.stdout, server_names)
    return {
        "features_sha256": text_sha(feature_listing.stdout),
        "mcp_listing_sha256": text_sha(listing.stdout),
        "server_names": list(server_names),
        "known_servers_disabled": True,
    }


def owned_row(rows, owned, original_windows):
    matches = [row for row in rows if row.get("pane_id") == owned["pane_id"]]
    require(len(matches) == 1, "Owned native view is missing or ambiguous")
    row = matches[0]
    require(
        row["expected_pid"] == owned["expected_pid"]
        and row["tty"] == owned["tty"]
        and row["window_id"] not in original_windows
        and row.get("tab_count") == 1
        and row.get("visual_window_id") == row["window_id"]
        and not row.get("identity_ambiguous"),
        "Owned native identity changed; never adopt another view",
    )
    return row


_physical_helper = None


def physical_helper():
    global _physical_helper
    if _physical_helper is None:
        path = Path(__file__).with_name("codex_window_isolation.py")
        require(not path.is_symlink(), "Physical helper must be the tracked regular script")
        spec = importlib.util.spec_from_file_location("codex_physical_acceptance", path)
        _physical_helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_physical_helper)
    return _physical_helper


def remember_created_shell(evidence, opened, nonce, workspace, persist):
    """Keep the creation effect before observing or trusting shell readiness."""
    evidence["creation_receipt"] = {
        "task_id": opened["id"],
        "task_receipt": opened.get("receipt"),
        "nonce": nonce,
        "requested_cwd": str(workspace),
        "task_created_at": opened.get("created"),
        "task_finished_at": opened.get("finished"),
        "result": opened["result"],
        "scope": "creation receipt only; startup and input authority remain unconfirmed",
        "automatic_retry": False,
    }
    evidence["shell_startup"] = {"state": "unconfirmed", "input_permitted": False}
    persist()
    evidence["open_request_nonce_bound"] = opened["id"] == f"codex-accept-{nonce}-open"
    require(evidence["open_request_nonce_bound"], "Open receipt nonce differs")
    created = {key: opened["result"][key] for key in ("pane_id", "expected_pid", "tty")}
    evidence["created_handle"] = created
    persist()
    return created


def startup_generation(identity, created):
    require(isinstance(identity, str), "Detailed created shell identity unavailable")
    fields = identity.split(None, 8)
    require(
        len(fields) == 9
        and fields[0] == str(os.getuid())
        and fields[1] == Path(created["tty"]).name,
        "Created shell UID/TTY identity changed",
    )
    # Only during this read-only startup phase: exec changes comm while retaining
    # the exact PID, UID, TTY, start time and parent. Mutations later pin all fields.
    return tuple(fields[:8])


def require_created_birth(identity, created, receipt):
    generation = startup_generation(identity, created)
    times = [receipt.get(key) for key in ("task_created_at", "task_finished_at")]
    require(
        all(type(value) in {int, float} and math.isfinite(value) and value > 0 for value in times)
        and times[0] <= times[1],
        "Creation task time interval is unavailable",
    )
    started = time.mktime(time.strptime(" ".join(generation[2:7]), "%a %b %d %H:%M:%S %Y"))
    roots = [
        p for p in receipt["result"].get("processes", []) if p["pid"] == created["expected_pid"]
    ]
    require(
        math.floor(times[0]) <= started <= math.floor(times[1])
        and len(roots) == 1
        and int(generation[7]) == roots[0]["ppid"],
        "Created PID birth/parent does not match the original open task receipt",
    )
    return generation


async def wait_created_shell(
    transport,
    created,
    original_windows,
    workspace,
    record,
    *,
    receipt,
    timeout=25,
    poll_interval=0.15,
):
    observation = {"state": "unconfirmed", "input_permitted": False, "observations": 0}
    try:
        initial = await transport.process_identity(created["expected_pid"], detailed=True)
        observation["initial_identity"] = initial
        record(dict(observation))
        generation = require_created_birth(initial, created, receipt)
        observation.update(generation=list(generation))
        record(dict(observation))
        previous = None
        async with asyncio.timeout(timeout):
            while True:  # noqa: ASYNC110 -- bounded observations of one created shell only
                # Read-only logical receipt binding, including startup in a tab
                # group. It grants no input/geometry authority to that group.
                row = physical_helper().created_row(
                    await transport.catalog(), created, original_windows
                )
                identity = await transport.process_identity(created["expected_pid"], detailed=True)
                require(
                    startup_generation(identity, created) == generation,
                    "Created shell birth identity changed; never adopt a replacement",
                )
                raw = await transport.read(created["pane_id"])
                controlled = raw.rstrip("\n").split("\n")[-1].rstrip("\r") == (
                    "KiraBridge visible % "
                )
                pids = [process["pid"] for process in row["processes"]]
                observation.update(
                    observations=observation["observations"] + 1,
                    identity=identity,
                    busy=row["busy"],
                    process_ids=pids,
                    screen_sha256=text_sha(raw),
                    controlled_prompt=controlled,
                    cwd=None,
                )
                record(dict(observation))
                ready = (
                    not row["busy"]
                    and pids == [created["expected_pid"]]
                    and controlled
                    and empty_shell_prompt(raw)
                    and identity.split(None, 8)[8] == "/bin/zsh"
                )
                sample = None
                if ready:
                    cwd = await transport.process_working_directory(
                        created["expected_pid"], expected_identity=identity
                    )
                    observation["cwd"] = cwd
                    record(dict(observation))
                    if cwd == str(workspace):
                        sample = (identity, raw, cwd)
                        if sample == previous:
                            observation.update(
                                state="confirmed", input_permitted=False, shell_ready=True
                            )
                            record(dict(observation))
                            return identity
                previous = sample
                await asyncio.sleep(poll_interval)
    except BaseException as exc:
        observation.update(
            state="unconfirmed",
            input_permitted=False,
            error_type=type(exc).__name__,
            error_code=getattr(exc, "code", None),
            automatic_retry=False,
        )
        record(dict(observation))
        raise


def require_shell_ready_for_cleanup(evidence, shell_identity, persist):
    if shell_identity is None:
        evidence["cleanup_preserved"] = {
            "reason": "created_shell_startup_unconfirmed",
            "created_handle": evidence.get("created_handle"),
            "creation_task_id": evidence.get("creation_receipt", {}).get("task_id"),
            "cleanup_action_attempted": False,
            "automatic_retry": False,
        }
        persist()
        raise RuntimeError(
            "Created shell startup unconfirmed; preserve creation receipt and target"
        )


async def terminate_owned(transport, binding, expected_identity):
    require(
        isinstance(expected_identity, str)
        and len(expected_identity.split(None, 8)) == 9
        and expected_identity.startswith(str(os.getuid()) + " "),
        "Detailed owned Codex identity required before any signal",
    )
    require(
        await transport.process_identity(binding.agent_pid, detailed=True) == expected_identity,
        "Owned Codex identity changed; preserve it",
    )
    os.kill(binding.agent_pid, signal.SIGTERM)


def fresh_request(nonce, label, operation, arguments, submitted):
    require(re.fullmatch(r"[a-f0-9]{16}", nonce), "Invalid fresh run nonce")
    identifier = f"codex-accept-{nonce}-{label}"
    require(identifier not in submitted, "Never replay a submitted or uncertain request")
    submitted.add(identifier)
    return TaskRequest(
        task_id=identifier,
        idempotency_key=identifier,
        operation=operation,
        arguments=arguments,
    )


async def original_deltas(transport, original_windows, original_identities, owned_window=None):
    """Foreign processes may naturally exit/restart; none are cleanup targets."""
    inventory = await transport.window_inventory()
    windows = {row["window_id"] for row in inventory["windows"]}
    pids = await transport.process_ids()
    observed = {"retained": [], "absent": [], "changed_or_unavailable": []}
    for pid, identity in original_identities.items():
        if pid not in pids:
            observed["absent"].append(pid)
            continue
        try:
            current_identity = await transport.process_identity(pid, detailed=True)
            if identity is not None and current_identity == identity:
                observed["retained"].append(pid)
            else:
                observed["changed_or_unavailable"].append(pid)
        except Exception:
            observed["changed_or_unavailable"].append(pid)
    return {
        "foreign_windows_absent": sorted(original_windows - windows),
        "foreign_windows_new": sorted(windows - original_windows - {owned_window}),
        "foreign_processes": observed,
        "read_only": True,
        "foreign_changes_are_not_harness_effect_proof": True,
    }


async def close_owned_idle(transport, owned, shell_identity, raw, workspace):
    require(
        await transport.process_working_directory(
            owned["expected_pid"], expected_identity=shell_identity
        )
        == str(workspace),
        "Owned shell CWD changed before close; preserve window",
    )
    close = (
        transport.native_target(owned["pane_id"])
        + "\nconst otherOwnedIds=app.windows().filter(w=>w.id()!==targetWindow.id())"
        ".map(w=>w.id());"
        + transport.native_identity_guard({owned["expected_pid"]: shell_identity})
        + physical_helper().cwd_guard(owned["expected_pid"], workspace)
        + "\nif(tab.busy() || targetWindow.tabs().length!==1)"
        "throw Error('Owned shell not alone and idle');"
        + transport.native_screen_guard(raw)
        + "targetWindow.close();delay(0.3);"
        "if(otherOwnedIds.some(id=>!app.windows().some(w=>w.id()===id)))"
        "throw Error('Other logical tabs changed during close; reconcile');"
        "JSON.stringify({closed:true});"
    )
    return await transport.native(close, mutation=True)


def controlled_cleanup_prompt(raw):
    """Only own-shell cleanup may accept the observed post-Codex repaint residue."""
    line = raw.rstrip("\n").split("\n")[-1]
    return (
        line.count("KiraBridge visible % ") == 1
        and re.fullmatch(r"[ %]*KiraBridge visible % ", line) is not None
    )


def require_commit_pins(head, installed, package_commit, harness_commit):
    require(
        all(
            re.fullmatch(r"[a-f0-9]{40}", value or "") for value in (package_commit, harness_commit)
        ),
        "Exact package and harness commit pins required",
    )
    require(head == harness_commit, "Harness checkout commit differs")
    require(installed in {None, package_commit}, "Installed release commit differs or is invalid")
    if installed is None:
        require(
            package_commit == harness_commit,
            "Separate harness commit requires an installed package manifest",
        )


def validate_candidate(args):
    require((platform.system(), platform.machine()) == ("Darwin", "x86_64"), "Intel macOS only")
    require(not sys.flags.optimize, "Independent proof assertions must remain enabled")
    require(args.codex_version == "codex-cli 0.167.0", "This harness pins the 0.167 renderer")
    require(Path(sys.executable).absolute() == args.expected_python.absolute(), "Wrong interpreter")
    require(
        Path(kirabridge.__file__).resolve().parent == args.package_root.resolve(), "Wrong package"
    )
    require(kirabridge.__version__ == args.expected_version, "Wrong candidate version")
    require(installed_source_sha() == args.source_sha256, "Wrong Python source manifest")
    source = Path(__file__).resolve().parents[1]
    head = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    installed = installed_source_commit(kirabridge.__file__)
    require_commit_pins(head, installed, args.commit, args.harness_commit)
    subprocess.run(
        ["git", "-C", str(source), "diff", "--quiet", "HEAD", "--", "src", "scripts"],
        check=True,
        timeout=5,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "ls-files",
            "--error-unmatch",
            str(Path(__file__).resolve()),
            str(Path(__file__).with_name("codex_window_isolation.py").resolve()),
        ],
        check=True,
        capture_output=True,
        timeout=5,
    )
    if installed is None:
        require(
            args.package_root.resolve() == source / "src/kirabridge", "Wrong development source"
        )
    require(
        args.codex.is_file() and file_sha(args.codex) == args.codex_sha256, "Wrong Codex binary"
    )
    help_result = subprocess.run(
        [str(args.codex), "--help"], capture_output=True, text=True, timeout=8, check=True
    )
    version = subprocess.check_output([str(args.codex), "--version"], text=True, timeout=8).strip()
    require(version == args.codex_version, "Codex version changed")
    for flag in (
        "--no-alt-screen",
        "--no-daemon",
        "--strict-config",
        "--sandbox",
        "--ask-for-approval",
    ):
        require(flag in help_result.stdout, "Pinned Codex flag unavailable: " + flag)
    spec = importlib.util.spec_from_file_location(
        "owned_acceptance_proofs", source / "scripts/accept_macos_adapter_intel.py"
    )
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    return helpers, {
        "version": version,
        "binary_sha256": file_sha(args.codex),
        "help_sha256": text_sha(help_result.stdout),
    }


async def accept(args):
    helpers, cli = await asyncio.to_thread(validate_candidate, args)
    require(args.allow_one_owned_visible_window, "Explicit one-window execution flag required")
    require(
        not os.environ.get("CODEX_HOME"),
        "Existing CODEX_HOME requires a separately reviewed reader root; do not change it",
    )
    root = args.root.absolute()
    require(
        not root.exists() and not root.is_symlink(), "Use a fresh root; never resume this harness"
    )
    require(
        all(not parent.is_symlink() for parent in root.parents), "Test root has a symlink ancestor"
    )
    root.mkdir(mode=0o700, parents=True)
    os.chmod(root, 0o700)
    workspace = root / "workspace"
    workspace.mkdir(mode=0o700)
    nonce = secrets.token_hex(8)
    marker, raw_prompt, body, ambiguous = build_prompts(nonce)
    parent_context = codex_config_context(os.environ)
    reader_root = verify_shell_config_context({"config_context": parent_context}, parent_context)
    require(Path(reader_root).parent == Path.home(), "Python and Codex reader roots differ")
    managed_absence = require_known_managed_absent(known_managed_paths(Path.home()))
    config_snapshot, server_names = codex_config_inputs(workspace)
    argv, overrides = codex_arguments(args.codex, workspace, server_names)
    initial_isolation = await inspect_cli_isolation(args.codex, overrides, server_names, workspace)
    require(
        codex_config_inputs(workspace) == (config_snapshot, server_names), "Codex config changed"
    )
    (root / "busy.py").write_text(BUSY_SOURCE)
    for name, value in [("raw", raw_prompt), ("handoff", body), ("ambiguous", ambiguous)]:
        (root / (name + "-prompt.private.txt")).write_text(value)
    token_name = "KIRABRIDGE_CODEX_ACCEPT_" + nonce.upper()
    worker_token_name = token_name + "_WORKER"
    require(token_name not in os.environ, "Private token name collision")
    require(worker_token_name not in os.environ, "Private worker token name collision")
    os.environ[token_name] = secrets.token_urlsafe(48)
    os.environ[worker_token_name] = secrets.token_urlsafe(48)
    try:
        config = Config(
            host="127.0.0.1",
            data_dir=str(root / "state"),
            principals={
                "chatgpt": PrincipalConfig(
                    client_type="chatgpt",
                    permission_level="full",
                    approval_mode="automatic",
                    token_env=token_name,
                    roots=[str(root)],
                    terminal_roots=[str(root)],
                    executables=[sys.executable, "/bin/zsh", str(args.codex)],
                    agents=["codex"],
                    message_peers=["codex"],
                    capabilities=[
                        "bridge.health",
                        "session.open",
                        "session.inspect",
                        "session.input",
                        "terminal.execute",
                        "agent.execute",
                        "task.read",
                        "task.cancel",
                        "message.read",
                        "message.send",
                        "message.ack",
                    ],
                ),
                "codex": PrincipalConfig(
                    token_env=worker_token_name,
                    roots=[str(root)],
                    message_peers=["chatgpt"],
                    capabilities=["message.read", "message.send", "message.ack"],
                ),
            },
            agents={"codex": AgentConfig(kind="codex", executable=str(args.codex))},
        )
        bridge = Bridge(config)
        if args.autonext_budget_source:
            require(args.autonext_board_workspace, "Existing coordination board workspace required")
            login = await asyncio.to_thread(
                subprocess.run,
                [str(args.codex), "login", "status"],
                capture_output=True,
                text=True,
                timeout=8,
                check=True,
            )
            require(
                "Logged in using ChatGPT" in login.stdout + login.stderr,
                "Existing subscription login is not confirmed",
            )
            config.principals["chatgpt"].capabilities += [
                "team.manage",
                "team.write",
                "team.read",
                "threaddesk.read",
                "threaddesk.manage",
            ]
            config.principals["codex"].capabilities += [
                "bridge.health",
                "agent.execute",
                "terminal.execute",
                "session.inspect",
                "session.input",
                "task.read",
                "task.cancel",
                "team.read",
                "team.write",
            ]
            config.principals["codex"].approval_mode = "automatic"
            config.principals["codex"].terminal_roots = [str(root)]
            config.principals["codex"].agents = ["codex"]
    except BaseException:
        os.environ.pop(token_name, None)
        os.environ.pop(worker_token_name, None)
        raise
    transport = bridge.sessions.terminal_app
    catalog, native, product_open = transport.catalog, transport.native, transport.open
    original_check = bridge.visible_handoffs.check_target
    owned = binding = shell_identity = agent_identity = None
    product_receipt = None
    baseline_ready = False
    active_label, frames = "startup", []
    original_windows, original_identities = set(), {}
    evidence = {
        "passed": False,
        "executed": True,
        "nonce": nonce,
        "cli": cli,
        "version": kirabridge.__version__,
        "source_sha256": args.source_sha256,
        "commit": args.commit,
        "harness_commit": args.harness_commit,
        "python": sys.executable,
        "package": str(args.package_root),
        "private_root": str(root),
        "checks": [],
        "mutations": [],
        "historical_tasks_replayed": False,
        "production_kirabridge_config_or_endpoint_used": False,
        "codex_config_read_only_sha256": config_snapshot,
        "codex_disabled_mcp_servers": server_names,
        "codex_disabled_features": list(CODEX_DISABLED_FEATURES),
        "codex_config_context": parent_context,
        "codex_reader_root": reader_root,
        "cli_isolation_before_ui": initial_isolation,
        "codex_argv": argv,
        "known_local_managed_files_present": managed_absence,
    }
    server = serving = sock = None
    open_attempts = activation_attempts = 0
    expected_activation_source = None
    submitted = set()

    def save(name, data):
        (root / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")

    def checkpoint():
        save("evidence.private.json", evidence)

    def check(name, **details):
        evidence["checks"].append({"name": name, **details})
        checkpoint()
        print(json.dumps(evidence["checks"][-1]), flush=True)

    async def observe_originals():
        try:
            observation = await original_deltas(
                transport,
                original_windows,
                original_identities,
                int(owned["pane_id"].split(":")[1]) if owned else None,
            )
        except Exception as exc:
            observation = {"observation_unavailable": type(exc).__name__, "read_only": True}
        evidence.setdefault("foreign_observations", []).append(observation)
        checkpoint()

    async def current(*, cleanup=False):
        if cleanup:
            row = physical_helper().created_row(await catalog(), owned, original_windows)
        elif product_receipt is not None:
            await transport.verify_opened(product_receipt, principal="chatgpt")
            row = physical_helper().created_row(await catalog(), owned, original_windows)
        else:
            row = owned_row(await catalog(), owned, original_windows)
        require(
            await transport.process_identity(owned["expected_pid"], detailed=True)
            == shell_identity,
            "Owned shell generation changed",
        )
        return row

    async def wait_shell(*, cleanup=False):
        async with asyncio.timeout(25):
            while True:  # noqa: ASYNC110 -- bounded own native shell observation
                row = await current(cleanup=cleanup)
                raw = await transport.read(owned["pane_id"])
                if (
                    not row["busy"]
                    and [p["pid"] for p in row["processes"]] == [owned["expected_pid"]]
                    and (empty_shell_prompt(raw) or cleanup and controlled_cleanup_prompt(raw))
                ):
                    return raw
                await asyncio.sleep(0.15)

    async def traced_native(source, *, mutation=False):
        nonlocal open_attempts, activation_attempts
        if not mutation:
            return await native(source, mutation=False)
        created = evidence.get("product_creation_receipt")
        activating = expected_activation_source is not None and source == expected_activation_source
        if activating:
            require(
                owned is None and created is None and open_attempts == activation_attempts == 0,
                "Only one exact existing-app activation is permitted before creation",
            )
            activation_attempts += 1
        elif owned is None and created is None:
            require(
                "app.doScript(" in source and open_attempts == 0, "No additional window attempt"
            )
            open_attempts += 1
        else:
            window_id = (
                int(owned["pane_id"].split(":")[1]) if owned is not None else created["window_id"]
            )
            require(
                f"app.windows.byId({window_id})" in source,
                "Native mutation is not bound to owned window",
            )
        receipt = {"source_sha256": text_sha(source), "at": time.time()}
        if activating:
            receipt["existing_app_activation"] = True
        evidence["mutations"].append(receipt)
        checkpoint()
        try:
            value = await native(source, mutation=True)
            receipt["result"] = value
            return value
        except BaseException as exc:
            receipt["error"] = getattr(exc, "code", type(exc).__name__)
            raise
        finally:
            checkpoint()

    async def tracked_product_open(command, *, on_created=None, principal="session_open"):
        async def created(receipt):
            if on_created is not None:
                await on_created(receipt)
            evidence["product_creation_receipt"] = dict(receipt)
            checkpoint()
            require(
                receipt.get("opened") is True
                and receipt.get("tty") not in original_ttys
                and type(receipt.get("window_id")) is int
                and receipt["window_id"] not in original_windows,
                "Product creation receipt is not a fresh owned target",
            )

        return await product_open(command, on_created=created, principal=principal)

    async def forbidden(*args, **kwargs):
        raise RuntimeError("No hidden, raw-send, extra-window or tmux fallback allowed")

    async def traced_check(principal, target, selected, *, ready=False):
        require(
            owned is not None and selected.pane_id == owned["pane_id"],
            "No unrelated input frame may be captured",
        )
        result = await original_check(principal, target, selected, ready=ready)
        require(len(frames) < 512, "Private frame capture budget exceeded")
        frames.append({"label": active_label, "ready": ready, "text": result["text"]})
        save("input-frames.private.json", frames)
        return result

    async def cleanup():
        if owned is None:
            if not baseline_ready:
                require(not evidence["mutations"], "Unknown effect without baseline; preserve")
                evidence["cleanup_complete"] = True
                return
            require(
                open_attempts == 0
                and all(m.get("existing_app_activation") is True for m in evidence["mutations"]),
                "Unestablished open effect; preserve, never adopt",
            )
            evidence["cleanup_scope"] = "No window creation attempted; existing-app activation only"
            await observe_originals()
            evidence["cleanup_complete"] = True
            return
        require_shell_ready_for_cleanup(evidence, shell_identity, checkpoint)
        await observe_originals()
        row = await current(cleanup=True)
        save("cleanup-before-screen.private.json", {"text": await transport.read(owned["pane_id"])})
        if binding is not None and any(p["pid"] == binding.agent_pid for p in row["processes"]):
            require(
                binding.agent_pid not in original_identities, "Never signal an original process"
            )
            await terminate_owned(transport, binding, agent_identity)
            evidence["owned_codex_sigterm"] = binding.agent_pid
        raw = await wait_shell(cleanup=True)
        await observe_originals()
        evidence["close"] = await close_owned_idle(transport, owned, shell_identity, raw, workspace)
        async with asyncio.timeout(25):
            while True:  # noqa: ASYNC110 -- independent full-inventory absence proof
                pids = await transport.process_ids()
                windows = await transport.window_inventory()
                if owned["expected_pid"] not in pids and int(
                    owned["pane_id"].split(":")[1]
                ) not in {r["window_id"] for r in windows["windows"]}:
                    if binding is not None:
                        evidence["absence"] = await bridge.sessions.prove_original_target_gone(
                            "chatgpt", binding.model_dump()
                        )
                    else:
                        require(
                            owned["expected_pid"] not in await transport.process_ids(),
                            "Owned shell absence changed",
                        )
                        evidence["absence"] = {
                            "owned_shell_absent_twice": True,
                            "owned_window_absent": True,
                        }
                    break
                await asyncio.sleep(0.15)
        await observe_originals()
        evidence["cleanup_complete"] = True

    try:
        async with bridge:
            try:
                before = await transport.window_inventory()
                original_windows = {row["window_id"] for row in before["windows"]}
                rows = await catalog()
                require(
                    not transport.last_catalog_incomplete, "Baseline native catalogue incomplete"
                )
                original_ttys = {row["tty"] for row in rows}
                for row in rows:
                    for process in row["processes"]:
                        try:
                            identity = await transport.process_identity(
                                process["pid"], detailed=True
                            )
                        except Exception:
                            identity = None
                        original_identities[process["pid"]] = identity
                save(
                    "baseline.private.json",
                    {"inventory": before, "catalog": rows, "identities": original_identities},
                )
                contract = installed_native_contract(kirabridge.__file__)
                system_transport = bridge.system_modules.transport
                require(
                    isinstance(system_transport, NativeSystemTransport)
                    and contract.get("expected_commit") == args.commit
                    and system_transport.expected_commit == args.commit
                    and system_transport.app_path == contract["app_path"]
                    and system_transport.expected_binary_sha256
                    == contract["expected_binary_sha256"]
                    and transport.system_transport is system_transport,
                    "Physical proof must reuse the exact installed native transport",
                )
                applications = await system_transport.request(
                    "apps.list", {"limit": 1000}, principal="chatgpt"
                )
                terminals = [
                    app
                    for app in applications["applications"]
                    if app.get("bundle_id") == "com.apple.Terminal"
                ]
                require(len(terminals) <= 1, "Existing Terminal app is ambiguous")
                if terminals:
                    pid = terminals[0]["pid"]
                    identity = await transport.process_identity(pid, detailed=True)
                    expected_activation_source = transport.native_existing_app_activation_source(
                        pid, identity
                    )
                    evidence["allowed_existing_app_activation"] = {
                        "pid": pid,
                        "identity_sha256": text_sha(identity),
                        "source_sha256": text_sha(expected_activation_source),
                    }
                    checkpoint()
                baseline_ready = True
                transport.native = traced_native
                transport.open = tracked_product_open
                bridge.visible_handoffs.check_target = traced_check
                sock = socket.socket()
                sock.bind(("127.0.0.1", 0))
                sock.listen(64)
                config.port = sock.getsockname()[1]
                server = uvicorn.Server(
                    uvicorn.Config(create_http_app(bridge), log_level="critical", access_log=False)
                )
                serving = asyncio.create_task(server.serve(sockets=[sock]))
                async with asyncio.timeout(10):
                    while not server.started:
                        if serving.done():
                            await serving
                        await asyncio.sleep(0.02)
                endpoint = f"http://127.0.0.1:{config.port}/mcp"
                evidence["private_endpoint"] = endpoint
                async with httpx.AsyncClient(trust_env=False) as outsider:
                    require(
                        (await outsider.post(endpoint, json={})).status_code == 401,
                        "Private endpoint is not authenticated",
                    )
                async with MCPClientPool(call_timeout=args.response_timeout + 35) as clients:
                    await clients.connect(Peer("owned", url=endpoint, token=os.environ[token_name]))

                    async def call(tool, arguments):
                        result = await clients.call("owned", tool, arguments)
                        require(
                            not result.isError and isinstance(result.structuredContent, dict),
                            "Private MCP call failed",
                        )
                        return result.structuredContent

                    async def submit(
                        label, operation, arguments, *, expected="completed", code=None
                    ):
                        nonlocal active_label
                        active_label = label
                        value = fresh_request(nonce, label, operation, arguments, submitted)
                        admitted = await call("action_request", {"request": value.model_dump()})
                        require(
                            admitted.get("id") == value.task_id,
                            "Request was not persisted; never retry",
                        )
                        async with asyncio.timeout(args.response_timeout + 35):
                            while True:  # noqa: ASYNC110 -- observe own persisted task, never replay
                                task = await call("task_get", {"task_id": value.task_id})
                                if task.get("state") in TERMINAL:
                                    break
                                await asyncio.sleep(0.15)
                        save(label + "-task.private.json", task)
                        require(
                            task["state"] == expected and task["attempt"] == 1,
                            "Unexpected task result; stop without replay",
                        )
                        if code:
                            require(task["error"]["code"] == code, "Wrong typed refusal")
                        return task

                    def input_args(text, **extra):
                        return {
                            "pane_id": owned["pane_id"],
                            "expected_pid": owned["expected_pid"],
                            "text": text,
                            **extra,
                        }

                    async def geometry(columns):
                        row = await current()
                        guards = {
                            p["pid"]: await transport.process_identity(p["pid"], detailed=True)
                            for p in row["processes"]
                        }
                        await observe_originals()
                        await transport.native(
                            transport.native_target(owned["pane_id"])
                            + transport.native_identity_guard(guards)
                            + f"\ntab.numberOfColumns={columns};"
                            "JSON.stringify({columns:tab.numberOfColumns()});",
                            mutation=True,
                        )
                        async with asyncio.timeout(15):
                            previous = None
                            while True:  # noqa: ASYNC110 -- wait for owned width and redraw
                                raw = await transport.read(owned["pane_id"])
                                measured = await transport.input_columns(
                                    owned["pane_id"], identity_guard=guards, expected_screen=raw
                                )
                                if measured == columns and raw == previous:
                                    return raw
                                previous = raw
                                await asyncio.sleep(0.2)

                    health = await call("bridge_health", {})
                    require(
                        health["runtime"]["source_tree_sha256"] == args.source_sha256,
                        "Private runtime source differs",
                    )
                    evidence["runtime"] = health["runtime"]
                    opened = await submit(
                        "open", "session.open", {"cwd": str(workspace), "controlled_shell": True}
                    )
                    owned = remember_created_shell(evidence, opened, nonce, workspace, checkpoint)
                    require(
                        owned["tty"] not in original_ttys
                        and int(owned["pane_id"].split(":")[1]) not in original_windows,
                        "Never adopt an old resource",
                    )

                    def startup_observed(observation):
                        evidence["shell_startup"] = observation
                        checkpoint()

                    shell_identity = await wait_created_shell(
                        transport,
                        owned,
                        original_windows,
                        workspace,
                        startup_observed,
                        receipt=evidence["creation_receipt"],
                    )
                    evidence["owned"] = owned
                    evidence["owned_shell_identity"] = shell_identity
                    checkpoint()
                    product_receipt = opened["result"]["creation_receipt"]
                    require(
                        opened["result"].get("separate_window") is True
                        and product_receipt.get("separate_window") is True
                        and product_receipt["tty"] == owned["tty"]
                        and product_receipt["window_id"] == int(owned["pane_id"].split(":")[1]),
                        "Product did not confirm its own separate window",
                    )
                    await transport.verify_opened(product_receipt, principal="chatgpt")
                    evidence["physical_proof"] = product_receipt["physical_window"]
                    evidence["physical_proof_route"] = "product_session_open_and_verify_opened"
                    checkpoint()
                    await observe_originals()
                    await wait_shell()
                    transport.open = transport.send = bridge.sessions.tmux.send = (
                        bridge.terminal.execute
                    ) = forbidden
                    await geometry(130)
                    await submit(
                        "busy-start",
                        "session.input",
                        input_args(shlex.join([sys.executable, str(root / "busy.py"), str(root)])),
                    )
                    async with asyncio.timeout(10):
                        while not (root / "busy-started.json").exists():  # noqa: ASYNC110 -- own bounded fixture
                            await asyncio.sleep(0.1)
                    busy = json.loads((root / "busy-started.json").read_text())
                    require(busy["tty"] == owned["tty"], "Busy fixture is on another TTY")
                    require(
                        verify_shell_config_context(busy, parent_context) == reader_root,
                        "Shell reader root differs",
                    )
                    evidence["owned_shell_config_context_verified"] = True
                    count = len(evidence["mutations"])
                    await submit(
                        "busy-refused",
                        "session.input",
                        input_args("MUST_NOT_PASTE"),
                        expected="failed",
                        code="session_busy",
                    )
                    require(
                        len(evidence["mutations"]) == count, "Busy refusal attempted native input"
                    )
                    (root / "release-busy").write_text("release this own bounded fixture\n")
                    await wait_shell()
                    check("busy shell refused before any new native mutation")
                    require(
                        file_sha(args.codex) == cli["binary_sha256"],
                        "Codex binary changed before startup",
                    )
                    require(
                        codex_config_inputs(workspace) == (config_snapshot, server_names),
                        "Codex config changed before startup",
                    )
                    require(
                        codex_config_context(os.environ) == parent_context,
                        "Preflight environment changed before Codex startup",
                    )
                    require_known_managed_absent(known_managed_paths(Path.home()))
                    evidence["cli_isolation_before_start"] = await inspect_cli_isolation(
                        args.codex, overrides, server_names, workspace
                    )
                    require(
                        codex_config_inputs(workspace) == (config_snapshot, server_names),
                        "Codex config changed during final isolation check",
                    )
                    require_known_managed_absent(known_managed_paths(Path.home()))
                    checkpoint()
                    await submit(
                        "codex-start",
                        "session.input",
                        input_args(shlex.join(argv)),
                    )
                    async with asyncio.timeout(75):
                        previous = None
                        while True:  # noqa: ASYNC110 -- actual own Codex startup
                            row = await current()
                            agents = [p for p in row["processes"] if p["name"] == "codex"]
                            raw = await transport.read(owned["pane_id"])
                            if len(agents) == 1:
                                candidate = VisibleTerminalBinding(
                                    **{key: owned[key] for key in ("pane_id", "expected_pid")},
                                    agent_pid=agents[0]["pid"],
                                    ready_pattern=(
                                        r"(?m)^[ \t]*›(?: Ask Codex to do anything)?[ \t]*$"
                                    ),
                                )
                                require(
                                    Path(agents[0]["image"]).resolve() == args.codex.resolve(),
                                    "Observed Codex image differs from pinned executable",
                                )
                                if binding is None:
                                    binding = candidate
                                    agent_identity = await transport.process_identity(
                                        binding.agent_pid, detailed=True
                                    )
                                    require(
                                        binding.agent_pid not in original_identities,
                                        "Never adopt an original Codex process",
                                    )
                                    evidence["startup_binding"] = binding.model_dump()
                                    checkpoint()
                                require(
                                    candidate.agent_pid == binding.agent_pid,
                                    "Owned startup generation changed; stop",
                                )
                                if (
                                    assess("codex", raw, candidate)["ready"]
                                    and "\n  GPT-" in input_view("codex", raw)
                                    and raw == previous
                                ):
                                    binding = candidate
                                    break
                            previous = raw
                            await asyncio.sleep(0.3)
                    require(
                        agent_identity
                        == await transport.process_identity(binding.agent_pid, detailed=True),
                        "Owned startup generation changed",
                    )
                    require(
                        binding.agent_pid not in original_identities,
                        "Codex is not a fresh owned process",
                    )
                    config.visible_handoffs.bindings["codex"] = binding
                    evidence["binding"] = binding.model_dump()
                    evidence["owned_identities"] = {
                        str(owned["expected_pid"]): shell_identity,
                        str(binding.agent_pid): agent_identity,
                    }
                    count = len(evidence["mutations"])
                    await submit(
                        "stale",
                        "session.input",
                        input_args("MUST_NOT_PASTE", expected_pid=2147483647),
                        expected="failed",
                        code="session_selection_changed",
                    )
                    require(
                        len(evidence["mutations"]) == count, "Stale refusal attempted native input"
                    )
                    await geometry(131)
                    before_refusal = await transport.read(owned["pane_id"])
                    for label, operation, arguments in [
                        ("ambiguous-literal", "session.input", input_args(ambiguous)),
                        (
                            "ambiguous-handoff",
                            "agent.execute",
                            {
                                "agent": "codex",
                                "prompt": ambiguous,
                                "cwd": str(workspace),
                                "timeout": args.response_timeout,
                            },
                        ),
                    ]:
                        count = len(evidence["mutations"])
                        await submit(
                            label,
                            operation,
                            arguments,
                            expected="failed",
                            code="visible_input_geometry_ambiguous",
                        )
                        require(
                            len(evidence["mutations"]) == count
                            and await transport.read(owned["pane_id"]) == before_refusal,
                            "Ambiguous input was mutated",
                        )
                    check(
                        "131-column ambiguous literal/handoff refused with zero paste "
                        "and unchanged draft"
                    )
                    await geometry(130)

                    async def own_answer(prompt, answer, label):
                        async with asyncio.timeout(args.response_timeout):
                            while True:  # noqa: ASYNC110 -- new exact own turn and stable ready screen
                                identity = await transport.process_identity(
                                    binding.agent_pid, detailed=True
                                )
                                require(
                                    identity == agent_identity, "Owned agent generation changed"
                                )
                                found = await bridge.visible_handoffs.codex_reply.prepare(
                                    binding,
                                    process_identity=transport.process_identity,
                                    expected_identity=agent_identity,
                                    body=prompt,
                                    cwd=str(workspace),
                                )
                                if found["state"] == "ready":
                                    cursor = found["cursor"]
                                    path = Path(cursor["path"])
                                    with os.fdopen(
                                        bridge.visible_handoffs.codex_reply._open_session(path),
                                        "rb",
                                    ) as stream:
                                        info = os.fstat(stream.fileno())
                                        require(
                                            stat.S_ISREG(info.st_mode)
                                            and info.st_uid == os.getuid()
                                            and (info.st_dev, info.st_ino)
                                            == (cursor["device"], cursor["inode"]),
                                            "Own rollout identity changed",
                                        )
                                        data = stream.read(8 * 1024 * 1024 + 1)
                                        after = os.fstat(stream.fileno())
                                    require(
                                        (after.st_dev, after.st_ino) == (info.st_dev, info.st_ino)
                                        and len(data) >= cursor["offset"]
                                        and hashlib.sha256(data[: cursor["offset"]]).hexdigest()
                                        == cursor["prefix_sha256"],
                                        "Own rollout prefix was replaced or rewritten",
                                    )
                                    require(
                                        len(data) <= 8 * 1024 * 1024,
                                        "Own rollout exceeds acceptance budget",
                                    )
                                    complete = data[: data.rfind(b"\n") + 1]
                                    records = [json.loads(line) for line in complete.splitlines()]
                                    proof = helpers.owned_turn_messages(
                                        records, cursor["thread_id"], prompt, answer
                                    )
                                    observed = await call(
                                        "read_query",
                                        {
                                            "query": {
                                                "operation": "session.read",
                                                **{
                                                    key: owned[key]
                                                    for key in ("pane_id", "expected_pid")
                                                },
                                            }
                                        },
                                    )
                                    raw = observed["text"]
                                    if proof and re.search(
                                        r"(?m)^\s*(?:•\s*)?" + re.escape(answer) + r"\s*$", raw
                                    ):
                                        state = await bridge.visible_handoffs.codex_state.read(
                                            str(path), cursor["thread_id"]
                                        )
                                        if assess("codex", raw, binding, state)["ready"]:
                                            save(
                                                label + "-proof.private.json",
                                                {
                                                    **proof,
                                                    "rollout": str(path),
                                                    "device": cursor["device"],
                                                    "inode": cursor["inode"],
                                                    "screen_sha256": text_sha(raw),
                                                    "process_writer_verified": True,
                                                },
                                            )
                                            (root / (label + "-screen.private.txt")).write_text(raw)
                                            return path, data, proof
                                await asyncio.sleep(0.35)

                    count = len(evidence["mutations"])
                    task = await submit("raw", "session.input", input_args(raw_prompt))
                    require(task["result"]["return_sent"] is True, "Raw Return is unconfirmed")
                    receipts = evidence["mutations"][count:]
                    require(
                        sum(r.get("result", {}).get("paste_event_sent") is True for r in receipts)
                        == 1
                        and sum(
                            (
                                r.get("result", {}).get("return_sent")
                                or r.get("result", {}).get("key_sent")
                            )
                            is True
                            for r in receipts
                        )
                        == 1,
                        "Raw did not produce exactly one confirmed paste/Return",
                    )
                    path, _, _ = await own_answer(raw_prompt, marker + "_RAW", "raw")
                    check("long literal exact one paste/Return and own rollout/screen response")
                    count = len(evidence["mutations"])
                    handoff = await submit(
                        "handoff",
                        "agent.execute",
                        {
                            "agent": "codex",
                            "prompt": body,
                            "cwd": str(workspace),
                            "timeout": args.response_timeout,
                        },
                    )
                    result = handoff["result"]
                    protocol = result["evidence"]["protocol_binding"]
                    require(
                        Path(protocol["rollout_path"]).resolve() == path.resolve(),
                        "Handoff switched threads",
                    )
                    own_path, data, _ = await own_answer(body, marker + "_HANDOFF", "handoff")
                    evidence["handoff_proof"] = helpers.local_reply_protocol_proof(
                        result, binding, body, marker + "_HANDOFF", data, workspace
                    )
                    require(own_path.resolve() == path.resolve(), "Own rollout changed")
                    state = bridge.visible_handoffs.status("chatgpt", handoff["id"])
                    require(
                        state["state"] == "completed"
                        and any(
                            event["evidence"].get("prompt_format") == "body_only_v1"
                            for event in state["events"]
                        ),
                        "Handoff contract changed",
                    )
                    receipts = evidence["mutations"][count:]
                    require(
                        sum(r.get("result", {}).get("paste_event_sent") is True for r in receipts)
                        == 1
                        and sum(
                            (
                                r.get("result", {}).get("return_sent")
                                or r.get("result", {}).get("key_sent")
                            )
                            is True
                            for r in receipts
                        )
                        == 1,
                        "Handoff did not produce exactly one paste/Return",
                    )
                    await observe_originals()
                    check("unchanged body_only_v1 handoff and independently bound local answer")
                    if args.autonext_budget_source:
                        from autonext_native_acceptance import accept as accept_autonext

                        await accept_autonext(
                            bridge,
                            args,
                            workspace,
                            binding,
                            protocol,
                            {
                                "task_id": handoff["id"],
                                "protocol": protocol,
                                "source_sha256": args.source_sha256,
                            },
                            nonce,
                            evidence,
                            checkpoint,
                        )
                        check("two pinned real native AutoNext turns completed once in order")
                    evidence["tests_passed"] = True
            except BaseException as exc:
                evidence["error"] = {
                    "type": type(exc).__name__,
                    "code": getattr(exc, "code", None),
                    "message": str(exc),
                }
                raise
            finally:
                if (root / "busy-started.json").exists():
                    (root / "release-busy").write_text("release own fixture during cleanup\n")
                try:
                    if server is not None:
                        server.should_exit = True
                    if serving is not None:
                        await asyncio.wait_for(serving, 10)
                finally:
                    await bridge.tasks.stop()
                    try:
                        await cleanup()
                    except BaseException as exc:
                        evidence["cleanup_error"] = {
                            "type": type(exc).__name__,
                            "message": str(exc),
                        }
                        raise
                    finally:
                        checkpoint()
    finally:
        try:
            if sock is not None:
                sock.close()
                evidence["private_endpoint_absent"] = await asyncio.to_thread(
                    endpoint_absent, config.port
                )
                require(evidence["private_endpoint_absent"], "Private endpoint remains reachable")
        finally:
            os.environ.pop(token_name, None)
            os.environ.pop(worker_token_name, None)
            checkpoint()
    require(
        evidence.get("tests_passed") and evidence.get("cleanup_complete"), "Acceptance incomplete"
    )
    evidence["passed"] = True
    checkpoint()
    print(
        json.dumps({"passed": True, "private_evidence": str(root / "evidence.private.json")}),
        flush=True,
    )


def parser():
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--execute", action="store_true")
    value.add_argument(
        "--autonext-budget-source",
        type=Path,
        help="Opt in to two real read-only continuation turns; actual Codex quota log",
    )
    value.add_argument(
        "--autonext-board-workspace",
        type=Path,
        help="Existing ThreadDesk workspace containing coordination board 482f593429ad",
    )
    value.add_argument("--allow-one-owned-visible-window", action="store_true")
    value.add_argument("--root", type=Path)
    value.add_argument("--expected-python", type=Path)
    value.add_argument("--package-root", type=Path)
    value.add_argument("--expected-version")
    value.add_argument("--source-sha256")
    value.add_argument("--commit")
    value.add_argument("--harness-commit")
    value.add_argument("--codex", type=Path, default=Path.home() / ".local/bin/codex")
    value.add_argument("--codex-sha256")
    value.add_argument("--codex-version", default="codex-cli 0.167.0")
    value.add_argument("--response-timeout", type=int, default=120, choices=range(30, 181))
    return value


if __name__ == "__main__":
    options = parser().parse_args()
    if not options.execute:
        print(json.dumps(review_plan(), indent=2))
    else:
        require(
            all(
                getattr(options, name)
                for name in (
                    "root",
                    "expected_python",
                    "package_root",
                    "expected_version",
                    "source_sha256",
                    "commit",
                    "harness_commit",
                    "codex_sha256",
                )
            ),
            "Execution requires every exact candidate pin",
        )
        os.umask(0o077)
        asyncio.run(accept(options))
