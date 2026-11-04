"""Pinned official Windows tunnel helper; one existing HTTP executor, no secrets in argv.

Only the Windows setup assistant uses this module. It never changes PATH, runs a
package manager, stops a process, registers autostart, or replaces an existing
installation or profile. Explicit reconnect archives a confirmed exited start;
uncertain process state always preserves the original receipt and blocks replay.
"""

from __future__ import annotations

import functools
import hashlib
import io
import json
import os
import platform
import re
import stat
import struct
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from pathlib import Path

from kirabridge.bridge_core.config import private_directory
from kirabridge.bridge_core.models import BridgeError
from kirabridge.private_files import private_json, write_private
from kirabridge.windows_setup_runtime import listeners, process_identity, same_process

VERSION = "v0.0.19"
SOURCE_COMMIT = "01d67bb4da0d8359b808b4761f8db171ab682cd7"
ASSET = "tunnel-client-v0.0.19-windows-amd64.zip"
RELEASE_URL = "https://github.com/openai/tunnel-client/releases/tag/" + VERSION
ASSET_URL = "https://github.com/openai/tunnel-client/releases/download/" + VERSION + "/" + ASSET
ARCHIVE_SHA256 = "1d0ecc3a54f2a51e27a635ac155f40fbb95df58c52cdeddf6c75532cc0bbeb25"
ARCHIVE_SIZE = 29_539_887
AUTH_ENV = "KIRABRIDGE_WINDOWS_SETUP_AUTHORIZATION"
FILE_SHA256 = {
    "tunnel-client.exe": "7e93a39a567c87154a0aef2091b81100d78f9093c4603412cc2b55bed3dfe5ea",
    "cloudflared.exe": "581ea1df46a9d61ead0916b389bd6cca8a14d5a3090e656c8317aa41a617a6d4",
    "cloudflared-manifest.json": "04073cfbf4d2603f0054f80a4bef0aa5c07ca059fbe013ee4cbb35667a215164",
    "LICENSE": "f4c1d7ba32ef5bcf5cf03e2eefec5825ebafedf50fa330a36700a49c605c1ef4",
    "NOTICE": "1364c020d86ecf948b78b7c655175032068203d13aece70fb0bfe112d7802dc2",
    "tunnel-client-v0.0.19-windows-amd64-licenses.txt": (
        "2b1def83c55dea817579ea1a7206119356c6a97a190c31181fe7817ae60c29ec"
    ),
    "tunnel-client-v0.0.19-windows-amd64.spdx.json": (
        "d3665e98422d1e429fade374f29b2b42127575352fc35153c2abf1091ba7568f"
    ),
}
FILE_SIZES = dict(
    zip(FILE_SHA256, (26_478_592, 40_116_224, 1040, 10_758, 551, 16_542, 274_494), strict=True)
)
TUNNEL_ID = re.compile(r"tunnel_(?:[a-z0-9]{4}_)?[a-z0-9]{32}")


def fail(code):
    return BridgeError(
        code, "Windows connection setup requires local inspection; existing state is preserved"
    )


def boundary(function):
    @functools.wraps(function)
    def guarded(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except BridgeError:
            raise
        except (OSError, ValueError, TypeError, UnicodeError):
            raise fail("setup_client_io") from None

    return guarded


def windows():
    if (
        os.name != "nt"
        or platform.machine().lower() not in {"amd64", "x86_64"}
        or struct.calcsize("P") != 8
    ):
        raise fail("setup_client_platform")


def safe_path(path):
    path = Path(path).absolute()
    if (
        ".." in path.parts
        or str(path).startswith("\\\\")
        or any(c in str(path) for c in "\r\n\x00")
    ):
        raise fail("setup_client_path")
    for item in [*reversed(path.parents), path]:
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise fail("setup_client_path")
    return path


def read_private(path, maximum):
    path = safe_path(path)
    if os.name == "nt":
        from kirabridge.platform_adapters.windows.filesystem_security import private_open

        fd = private_open(path)
    else:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
            raise fail("setup_client_file")
        if os.name == "posix" and (info.st_uid != os.getuid() or info.st_mode & 0o077):
            raise fail("unsafe_credentials")
        data = stream.read(maximum + 1)
    if len(data) > maximum or len(data) != info.st_size:
        raise fail("setup_client_file")
    return data


def write_json(path, value):
    write_private(path, json.dumps(value, sort_keys=True, separators=(",", ":")))


def paths(state_dir):
    state = safe_path(state_dir)
    return state, state / "tools" / ("tunnel-client-" + VERSION), state / "connection"


class ReleaseRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, url):
        target = urllib.parse.urlsplit(url)
        if (
            target.scheme != "https"
            or target.hostname
            not in {
                "github.com",
                "release-assets.githubusercontent.com",
                "objects.githubusercontent.com",
            }
            or target.username
            or target.password
            or target.port not in (None, 443)
            or target.fragment
        ):
            raise fail("setup_client_download_origin")
        return super().redirect_request(request, fp, code, message, headers, url)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise fail("setup_client_health_origin")


def download():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), ReleaseRedirect())
    began = time.monotonic()
    try:
        request = urllib.request.Request(
            ASSET_URL, headers={"User-Agent": "KiraBridge-Windows-Setup"}
        )
        with opener.open(request, timeout=15) as response:
            parts, size = [], 0
            while chunk := response.read(65536):
                size += len(chunk)
                if size > ARCHIVE_SIZE or time.monotonic() - began > 120:
                    raise fail("setup_client_download_limit")
                parts.append(chunk)
    except (OSError, TimeoutError):
        raise fail("setup_client_download_failed") from None
    data = b"".join(parts)
    if len(data) != ARCHIVE_SIZE or hashlib.sha256(data).hexdigest() != ARCHIVE_SHA256:
        raise fail("setup_client_checksum")
    return data


def archive_files(data):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) != len(FILE_SHA256) or {entry.filename for entry in entries} != set(
                FILE_SHA256
            ):
                raise fail("setup_client_archive")
            result = {}
            for entry in entries:
                if (
                    entry.is_dir()
                    or entry.flag_bits & 1
                    or stat.S_ISLNK(entry.external_attr >> 16)
                    or entry.file_size != FILE_SIZES[entry.filename]
                ):
                    raise fail("setup_client_archive")
                raw = archive.read(entry)
                if hashlib.sha256(raw).hexdigest() != FILE_SHA256[entry.filename]:
                    raise fail("setup_client_archive")
                if entry.filename.endswith(".exe"):
                    if len(raw) < 128 or raw[:2] != b"MZ":
                        raise fail("setup_client_archive")
                    offset = struct.unpack_from("<I", raw, 60)[0]
                    if offset > len(raw) - 6 or raw[offset : offset + 6] != b"PE\0\0\x64\x86":
                        raise fail("setup_client_archive")
                result[entry.filename] = raw
            return result
    except (ValueError, OSError, zipfile.BadZipFile, RuntimeError, struct.error):
        raise fail("setup_client_archive") from None


@boundary
def find_client(state_dir: Path) -> Path | None:
    windows()
    _, folder, _ = paths(state_dir)
    if not os.path.lexists(folder):
        return None
    safe_path(folder)
    private_directory(folder)
    try:
        provenance = private_json(folder / "provenance.json")
        if (
            provenance.get("archive_sha256") != ARCHIVE_SHA256
            or provenance.get("version") != VERSION
            or provenance.get("file_sha256") != FILE_SHA256
        ):
            raise fail("setup_client_existing")
        for name, expected in FILE_SHA256.items():
            if (
                hashlib.sha256(read_private(folder / name, FILE_SIZES[name])).hexdigest()
                != expected
            ):
                raise fail("setup_client_existing")
    except (OSError, ValueError):
        raise fail("setup_client_existing") from None
    return folder / "tunnel-client.exe"


@boundary
def install_client(state_dir: Path) -> Path:
    windows()
    state, folder, _ = paths(state_dir)
    if os.path.lexists(folder):
        found = find_client(state)
        if found:
            return found
        raise fail("setup_client_existing")
    reservation = folder.parent / (folder.name + "-install-reservation.json")
    if os.path.lexists(reservation):
        raise fail("setup_client_existing")
    data = download()
    files = archive_files(data)
    private_directory(state)
    private_directory(folder.parent)
    try:
        write_json(reservation, {"archive_sha256": ARCHIVE_SHA256, "state": "reserved_no_replay"})
    except FileExistsError:
        raise fail("setup_client_existing") from None
    if os.path.lexists(folder):
        raise fail("setup_client_existing")
    # Python3.14 mkdir(0700) adds an Administrators ACE on Windows. Let our
    # native current-user/SYSTEM directory creator create the absent object.
    private_directory(folder)
    write_json(
        folder / "install-attempt.json", {"version": VERSION, "archive_sha256": ARCHIVE_SHA256}
    )
    for name, raw in files.items():
        write_private(folder / name, raw)
    write_json(
        folder / "provenance.json",
        {
            "version": VERSION,
            "source_commit": SOURCE_COMMIT,
            "release_url": RELEASE_URL,
            "asset_url": ASSET_URL,
            "archive_sha256": ARCHIVE_SHA256,
            "checksum_url": ASSET_URL.rsplit("/", 1)[0] + "/SHA256SUMS.txt",
            "file_sha256": FILE_SHA256,
            "verified_at": time.time(),
            "program_executed_by_installer": False,
        },
    )
    return folder / "tunnel-client.exe"


def endpoint(url, path):
    try:
        parsed = urllib.parse.urlsplit(url)
        if (
            parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or parsed.username
            or parsed.password
            or not parsed.port
            or not 1024 <= parsed.port <= 65535
            or parsed.path not in path
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError
    except (TypeError, ValueError):
        raise fail("setup_client_endpoint") from None
    return parsed


def profile_value(state, tunnel_id, runtime_key, mcp_endpoint):
    if not isinstance(tunnel_id, str) or TUNNEL_ID.fullmatch(tunnel_id) is None:
        raise fail("invalid_tunnel")
    endpoint(mcp_endpoint, {"/mcp"})
    key = safe_path(runtime_key)
    if not read_private(key, 8192):
        raise fail("invalid_runtime_key")
    return {
        "config_version": 1,
        "control_plane": {
            "base_url": "https://api.openai.com",
            "tunnel_id": tunnel_id,
            "api_key": "file:" + key.as_posix(),
        },
        "health": {"listen_addr": "127.0.0.1:0"},
        "admin_ui": {"open_browser": False},
        "log": {"level": "info", "format": "json", "http_raw_unsafe": False},
        "mcp": {
            "server_urls": [{"channel": "main", "url": mcp_endpoint}],
            "extra_headers": {"Authorization": "env:" + AUTH_ENV},
            "discovery_extra_headers": {"Authorization": "env:" + AUTH_ENV},
        },
    }


@boundary
def prepare_profile(binary, state_dir, tunnel_id, runtime_key_path, mcp_endpoint) -> Path:
    windows()
    state, _, connection = paths(state_dir)
    if Path(binary) != find_client(state):
        raise fail("setup_client_binary")
    value = profile_value(state, tunnel_id, runtime_key_path, mcp_endpoint)
    private_directory(connection)
    profile = connection / "tunnel-profile.yaml"
    if os.path.lexists(profile):
        try:
            if private_json(profile) != value:
                raise fail("setup_client_profile_mismatch")
        except (OSError, ValueError):
            raise fail("setup_client_profile_mismatch") from None
        return profile
    write_json(profile, value)  # JSON is a YAML document accepted by the pinned Go parser.
    return profile


def child_environment(local_token):
    if (
        not isinstance(local_token, str)
        or re.fullmatch(r"[A-Za-z0-9_-]{32,128}", local_token) is None
    ):
        raise fail("unsafe_credentials")
    prefixes = (
        "CONTROL_PLANE_",
        "MCP_",
        "HARPOON_",
        "TUNNEL_",
        "LOG_",
        "HEALTH_",
        "ADMIN_UI_",
        "CLOUDFLARED_",
        "TRACING_",
        "PROXY_",
        "KIRABRIDGE_",
        "OPENAI_",
    )
    names = {
        "OPENAI_API_KEY",
        "OPENAI_ADMIN_KEY",
        "PID_FILE",
        "FORWARD_REQUEST_ID",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "ALLOW_REMOTE_UI",
        "OPEN_WEB_UI",
        "CA_BUNDLE",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "GODEBUG",
        "GOTRACEBACK",
    }
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith(prefixes) and key.upper() not in names
    }
    env[AUTH_ENV] = "Bearer " + local_token
    return env


def saved_process(connection):
    try:
        record = private_json(connection / "tunnel-process.json")
    except FileNotFoundError:
        return None
    if (
        not isinstance(record, dict)
        or type(record.get("pid")) is not int
        or record["pid"] <= 0
        or not isinstance(record.get("created_100ns"), str)
        or re.fullmatch(r"[1-9][0-9]{1,19}", record["created_100ns"]) is None
        or not isinstance(record.get("image"), str)
        or not record["image"]
        or record.get("running") is not True
    ):
        raise fail("setup_client_start_unknown")
    return record


START_FILES = (
    "tunnel-start-attempt.json",
    "tunnel-process.json",
    "tunnel-spawned.json",
    "tunnel-health.url",
    "tunnel.pid",
)


def history_complete(connection):
    if os.path.lexists(connection / "tunnel-archive-in-progress.json"):
        raise fail("setup_client_start_unknown")
    history = connection / "history"
    if not os.path.lexists(history):
        return
    safe_path(history)
    private_directory(history)
    entries = list(history.iterdir())
    if len(entries) > 128:
        raise fail("setup_client_start_unknown")
    for folder in entries:
        safe_path(folder)
        private_directory(folder)
        try:
            complete = private_json(folder / "completed.json")
        except (OSError, ValueError):
            raise fail("setup_client_start_unknown") from None
        if not isinstance(complete, dict) or complete.get("completed") is not True:
            raise fail("setup_client_start_unknown")


def original_absent(record):
    current = process_identity(record["pid"])
    if current is None:
        return True
    if (
        not isinstance(current, dict)
        or current.get("pid") != record["pid"]
        or type(current.get("running")) is not bool
        or not isinstance(current.get("created_100ns"), str)
        or re.fullmatch(r"[1-9][0-9]{1,19}", current["created_100ns"]) is None
    ):
        raise fail("setup_client_start_unknown")
    return current["created_100ns"] != record["created_100ns"] or not current["running"]


def archive_exited(connection, record, profile_hash):
    """Only the explicit Connect action calls this, after proving the old generation gone."""
    if not original_absent(record):
        raise fail("setup_client_start_unknown")
    required = set(START_FILES[:3])
    held = []
    try:
        for name in START_FILES:
            source = connection / name
            if not os.path.lexists(source):
                if name in required:
                    raise fail("setup_client_start_unknown")
                continue
            safe_path(source)
            if os.name == "nt":
                from kirabridge.platform_adapters.windows.filesystem_security import private_open

                descriptor = private_open(
                    source
                )  # Owner/SYSTEM, no reparse/hardlink, final handle path.
            else:
                descriptor = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            stream = os.fdopen(descriptor, "rb")
            info = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or info.st_size > 65536
                or (os.name == "posix" and (info.st_uid != os.getuid() or info.st_mode & 0o077))
            ):
                stream.close()
                raise fail("setup_client_start_unknown")
            try:
                raw = stream.read(65537)
                if len(raw) != info.st_size:
                    raise fail("setup_client_start_unknown")
                if name == "tunnel.pid" and raw.decode("ascii").strip() != str(record["pid"]):
                    raise fail("setup_client_start_unknown")
                if name == "tunnel-health.url":
                    endpoint(raw.decode("ascii").strip(), {"", "/"})
            except BaseException:
                stream.close()
                raise
            held.append((name, source, stream, info, raw))
        if not original_absent(record):
            raise fail("setup_client_start_unknown")
        marker = connection / "tunnel-archive-in-progress.json"
        write_json(
            marker,
            {
                "pid": record["pid"],
                "created_100ns": record["created_100ns"],
                "profile_sha256": profile_hash,
                "original_generation_absent": True,
            },
        )
        private_directory(connection / "history")
        history = connection / "history" / uuid.uuid4().hex
        private_directory(history)  # Native creator; no Python3.14 mkdir(0700).
        write_json(
            history / "archive-attempt.json",
            {
                "files": {name: hashlib.sha256(raw).hexdigest() for name, _, _, _, raw in held},
                "profile_sha256": profile_hash,
            },
        )
        for name, source, _stream, info, raw in held:
            current = os.stat(source, follow_symlinks=False)
            if (current.st_dev, current.st_ino, current.st_size) != (
                info.st_dev,
                info.st_ino,
                info.st_size,
            ):
                raise fail("setup_client_start_unknown")
            destination = history / name
            if os.path.lexists(destination):
                raise fail("setup_client_start_unknown")
            os.rename(source, destination)
            if read_private(destination, 65536) != raw:
                raise fail("setup_client_start_unknown")
        write_json(
            history / "completed.json",
            {
                "completed": True,
                "original_generation_absent": True,
                "pid": record["pid"],
                "created_100ns": record["created_100ns"],
            },
        )
        # Marker was exclusively created by this call in the private connection
        # directory. Keep it in history instead of deleting any original evidence.
        if os.path.lexists(history / "reservation.json"):
            raise fail("setup_client_start_unknown")
        os.rename(marker, history / "reservation.json")
    finally:
        for _, _, stream, _, _ in held:
            stream.close()


def complete_start_record(connection, attempt, record, binary, profile_hash):
    if (
        not isinstance(attempt, dict)
        or re.fullmatch(r"[0-9a-f]{32}", str(attempt.get("attempt_id", ""))) is None
        or attempt.get("state") != "attempted_no_automatic_restart"
        or attempt.get("profile_sha256") != profile_hash
        or not record
        or Path(record.get("image", "")) != Path(binary)
    ):
        raise fail("setup_client_start_unknown")
    try:
        spawned = private_json(connection / "tunnel-spawned.json")
    except (OSError, ValueError):
        raise fail("setup_client_start_unknown") from None
    if (
        not isinstance(spawned, dict)
        or spawned.get("pid") != record["pid"]
        or spawned.get("attempt_id") != attempt.get("attempt_id")
        or record.get("attempt_id") != attempt.get("attempt_id")
    ):
        raise fail("setup_client_start_unknown")


@boundary
def start_client(binary, profile_path, state_dir, local_token) -> subprocess.Popen | None:
    windows()
    state, _, connection = paths(state_dir)
    if (
        Path(binary) != find_client(state)
        or Path(profile_path) != connection / "tunnel-profile.yaml"
    ):
        raise fail("setup_client_binary")
    profile = private_json(profile_path)
    try:
        key = profile["control_plane"]["api_key"]
        if not isinstance(key, str) or not key.startswith("file:"):
            raise ValueError
        expected = profile_value(
            state,
            profile["control_plane"]["tunnel_id"],
            Path(key[5:]),
            profile["mcp"]["server_urls"][0]["url"],
        )
        if profile != expected:
            raise ValueError
    except (ValueError, KeyError, TypeError, IndexError):
        raise fail("setup_client_profile_mismatch") from None
    env = child_environment(local_token)
    profile_hash = hashlib.sha256(read_private(profile_path, 65536)).hexdigest()
    attempt_path, health = (
        connection / "tunnel-start-attempt.json",
        connection / "tunnel-health.url",
    )
    history_complete(connection)
    if os.path.lexists(attempt_path):
        attempt, record = private_json(attempt_path), saved_process(connection)
        complete_start_record(connection, attempt, record, binary, profile_hash)
        if same_process(record):
            return None  # Reuse this original live process; no second executable is started.
        archive_exited(connection, record, profile_hash)
    if any(
        os.path.lexists(connection / name)
        for name in (
            "tunnel-health.url",
            "tunnel-process.json",
            "tunnel-spawned.json",
            "tunnel.pid",
        )
    ):
        raise fail("setup_client_start_unknown")
    try:
        attempt_id = uuid.uuid4().hex
        write_json(
            attempt_path,
            {
                "attempt_id": attempt_id,
                "profile_sha256": profile_hash,
                "started_at": time.time(),
                "state": "attempted_no_automatic_restart",
            },
        )
    except FileExistsError:
        raise fail("setup_client_start_unknown") from None
    try:
        child = subprocess.Popen(
            [
                str(binary),
                "run",
                "--profile-file",
                str(profile_path),
                "--health.url-file",
                str(health),
                "--pid.file",
                str(connection / "tunnel.pid"),
            ],
            env=env,
            creationflags=subprocess.CREATE_NEW_CONSOLE,
            close_fds=True,
        )
        write_json(connection / "tunnel-spawned.json", {"pid": child.pid, "attempt_id": attempt_id})
        record = process_identity(child.pid)
        if not record or not record["running"] or Path(record["image"]) != Path(binary):
            raise fail("setup_client_start_unknown")
        record["attempt_id"] = attempt_id
        write_json(connection / "tunnel-process.json", record)
        return child
    except (OSError, ValueError):
        raise fail("setup_client_start_unknown") from None


def health_get(base, route):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(base + route, timeout=3) as response:
            raw = response.read(65537)
            if len(raw) > 65536:
                raise fail("setup_client_health_limit")
            return response.status, raw
    except urllib.error.HTTPError as error:
        status = error.code
        error.close()
        if status == 503:
            return 503, b""
        raise fail("setup_client_health_unavailable") from None
    except (OSError, TimeoutError):
        raise fail("setup_client_health_unavailable") from None


@boundary
def client_status(state_dir) -> dict:
    windows()
    _, folder, connection = paths(state_dir)
    history_complete(connection)
    if not os.path.lexists(connection / "tunnel-start-attempt.json"):
        if any(
            os.path.lexists(connection / name)
            for name in (
                "tunnel-health.url",
                "tunnel-process.json",
                "tunnel-spawned.json",
                "tunnel.pid",
            )
        ):
            return {
                "started": None,
                "ready": False,
                "state": "unknown",
                "chatgpt_tool_call": "unverified",
            }
        return {
            "started": False,
            "ready": False,
            "state": "not_started",
            "chatgpt_tool_call": "unverified",
        }
    private_json(connection / "tunnel-start-attempt.json")
    record = saved_process(connection)
    result = {
        "started": True,
        "ready": False,
        "state": "unknown",
        "chatgpt_tool_call": "unverified",
    }
    if (
        not record
        or not same_process(record)
        or Path(record.get("image", "")) != folder / "tunnel-client.exe"
    ):
        return result
    result.update(pid=record["pid"], created_100ns=record["created_100ns"], state="starting")
    try:
        base = read_private(connection / "tunnel-health.url", 2048).decode("ascii").strip()
    except FileNotFoundError:
        return result
    parsed = endpoint(base, {"", "/"})
    rows = listeners(parsed.port)
    if rows != [{"pid": record["pid"], "host": "127.0.0.1"}]:
        raise fail("setup_client_health_owner")
    live_code, live = health_get(base.rstrip("/"), "/healthz")
    ready_code, ready = health_get(base.rstrip("/"), "/readyz")
    code, raw = health_get(base.rstrip("/"), "/health?details=true")
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError):
        raise fail("setup_client_health_schema") from None
    if not isinstance(data, dict) or not isinstance(data.get("components"), dict):
        raise fail("setup_client_health_schema")
    control = data["components"].get("control-plane", {})
    if not isinstance(control, dict) or not isinstance(control.get("details", {}), dict):
        raise fail("setup_client_health_schema")
    details = control.get("details", {})
    success = details.get("last_success")
    polling = (
        control.get("status") == "ok"
        and isinstance(success, str)
        and bool(success)
        and details.get("consecutive_failures") == 0
    )
    healthy = (
        live_code == 200
        and live == b"live"
        and code == 200
        and data.get("schema_version") == 1
        and data.get("live") is True
    )
    is_ready = (
        healthy
        and ready_code == 200
        and ready == b"ready"
        and data.get("ready") is True
        and polling
        and same_process(record)
    )
    result.update(
        healthy=healthy,
        ready=is_ready,
        active_polling=polling,
        state="ready" if is_ready else "pending",
    )
    return result
