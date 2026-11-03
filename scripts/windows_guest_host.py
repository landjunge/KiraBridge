#!/usr/bin/env python3
"""Loopback-only fixed-file server for one isolated Windows guest.

Manifest: schema_version=1, python_version=X.Y.Z, files=[{path,sha256,bytes}],
requirements=["package==version",...]. Required paths: guest_runner.ps1,
source.zip, python-installer.exe; additional paths may only be wheels/*.whl.
No host command execution, arbitrary paths, shared directories or token logging.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import stat
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

SAFE_ID = re.compile(r"[A-Za-z0-9_-]{1,120}")
FILE_PATH = re.compile(
    r"(?:guest_runner\.ps1|source\.zip|python-installer\.exe|wheels/[A-Za-z0-9][A-Za-z0-9._+-]{0,200}\.whl)"
)
MAX_REPORT = 2 * 1024 * 1024
MAX_EVENT = 64 * 1024


def safe_path(path: Path) -> Path:
    path = path.expanduser().absolute()
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink():
            raise ValueError("Symlink path components are refused")
    return path


def open_owned(path: Path):
    safe_path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        os.close(fd)
        raise ValueError("Expected an owned regular staging file")
    return os.fdopen(fd, "rb"), info


def identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def read_private_token(path: Path) -> str:
    with open_owned(path)[0] as source:
        info = os.fstat(source.fileno())
        if stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 256:
            raise ValueError("Token file must be private mode0600")
        token = source.read().decode("ascii").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", token):
        raise ValueError("Token file has an invalid token")
    return token


def write_new(path: Path, body: bytes):
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(body)


class GuestState:
    def __init__(self, staging: Path, state: Path, token: str):
        if not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", token):
            raise ValueError("Invalid capability token")
        self.staging, self.state = safe_path(staging), safe_path(state)
        self.token = token
        self.lock = threading.Lock()
        if not self.state.exists():
            self.state.mkdir(mode=0o700)
        info = self.state.stat()
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError("State directory must be private and owned")
        with open_owned(self.staging / "manifest.json")[0] as source:
            self.manifest_bytes = source.read(1024 * 1024 + 1)
        if len(self.manifest_bytes) > 1024 * 1024:
            raise ValueError("Manifest is too large")
        manifest = json.loads(self.manifest_bytes)
        if manifest.get("schema_version") != 1 or not re.fullmatch(
            r"\d+\.\d+\.\d+", manifest.get("python_version", "")
        ):
            raise ValueError("Unsupported manifest schema or Python version")
        requirements = manifest.get("requirements")
        if (
            not isinstance(requirements, list)
            or not requirements
            or not all(
                isinstance(item, str)
                and re.fullmatch(
                    r"[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?==[A-Za-z0-9_.+!-]+", item
                )
                for item in requirements
            )
        ):
            raise ValueError("Every requirement must be exactly pinned")
        self.files = {}
        for row in manifest.get("files", []):
            path = row.get("path", "")
            if not FILE_PATH.fullmatch(path) or path in self.files:
                raise ValueError("Invalid or duplicate manifest path")
            if (
                not re.fullmatch(r"[a-fA-F0-9]{64}", row.get("sha256", ""))
                or type(row.get("bytes")) is not int
                or row["bytes"] <= 0
            ):
                raise ValueError("Invalid file digest or size")
            digest = hashlib.sha256()
            with open_owned(self.staging / path)[0] as source:
                before = os.fstat(source.fileno())
                while chunk := source.read(1024 * 1024):
                    digest.update(chunk)
                after = os.fstat(source.fileno())
            if (
                identity(before) != identity(after)
                or before.st_size != row["bytes"]
                or digest.hexdigest() != row["sha256"].lower()
            ):
                raise ValueError("Staging file does not match manifest")
            self.files[path] = identity(before)
        if not {"guest_runner.ps1", "source.zip", "python-installer.exe"} <= self.files.keys():
            raise ValueError("Manifest lacks a required payload")

    def report(self, report_id: str, body: bytes):
        if not SAFE_ID.fullmatch(report_id):
            raise ValueError("Invalid report identifier")
        path = self.state / f"report-{report_id}.json"
        with self.lock:
            if os.path.lexists(path):
                with open_owned(path)[0] as source:
                    original = source.read(MAX_REPORT + 1)
                if hashlib.sha256(original).digest() != hashlib.sha256(body).digest():
                    return 409, {"error": "report_id_conflict"}
                return 200, {
                    "stored": True,
                    "duplicate": True,
                    "sha256": hashlib.sha256(body).hexdigest(),
                }
            write_new(path, body)
        return 201, {"stored": True, "duplicate": False, "sha256": hashlib.sha256(body).hexdigest()}

    def event(self, body: bytes):
        event = {"received_at": datetime.now(timezone.utc).isoformat(), "event": json.loads(body)}
        line = json.dumps(event, ensure_ascii=False).encode("utf-8") + b"\n"
        with self.lock:
            fd = os.open(
                self.state / "events.jsonl",
                os.O_CREAT | os.O_APPEND | os.O_WRONLY | os.O_NOFOLLOW,
                0o600,
            )
            with os.fdopen(fd, "ab") as output:
                output.write(line)


def handler_for(state: GuestState):
    class Handler(BaseHTTPRequestHandler):
        server_version = "KiraGuestStage/1"

        def log_message(self, *_):
            # BaseHTTPRequestHandler normally includes the capability URL in logs.
            pass

        def send_json(self, status_code, value):
            body = json.dumps(value, separators=(",", ":")).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def route(self):
            parsed = urlsplit(self.path)
            parts = parsed.path.split("/")
            if (
                parsed.query
                or parsed.fragment
                or len(parts) < 3
                or not parts[1].isascii()
                or not hmac.compare_digest(parts[1], state.token)
            ):
                return None
            return "/".join(parts[2:])

        def do_GET(self):
            route = self.route()
            if route == "manifest.json":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(state.manifest_bytes)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(state.manifest_bytes)
                return
            if route not in state.files:
                self.send_json(404, {"error": "not_found"})
                return
            headers_started = False
            try:
                with open_owned(state.staging / route)[0] as source:
                    if identity(os.fstat(source.fileno())) != state.files[route]:
                        self.send_json(409, {"error": "staging_changed"})
                        return
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Content-Length", str(state.files[route][2]))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    headers_started = True
                    while chunk := source.read(1024 * 1024):
                        self.wfile.write(chunk)
            except (OSError, ValueError):
                if not headers_started:
                    self.send_json(409, {"error": "staging_changed"})
                self.close_connection = True

        def do_POST(self):
            route = self.route()
            report_id = (
                route.removeprefix("reports/") if route and route.startswith("reports/") else None
            )
            if route != "events" and (report_id is None or not SAFE_ID.fullmatch(report_id)):
                self.send_json(404, {"error": "not_found"})
                return
            maximum = MAX_EVENT if route == "events" else MAX_REPORT
            lengths = self.headers.get_all("Content-Length", [])
            if (
                self.headers.get("Transfer-Encoding")
                or len(lengths) != 1
                or not lengths[0].isdigit()
            ):
                self.send_json(400, {"error": "content_length_required"})
                return
            if len(lengths[0]) > 10:
                self.send_json(413, {"error": "payload_too_large"})
                return
            length = int(lengths[0])
            if length > maximum:
                self.send_json(413, {"error": "payload_too_large"})
                return
            try:
                self.connection.settimeout(15)
                body = self.rfile.read(length)
                if len(body) != length or not isinstance(json.loads(body), dict):
                    raise ValueError("Expected one complete JSON object")
                if route == "events":
                    state.event(body)
                    self.send_json(201, {"stored": True})
                else:
                    status_code, value = state.report(report_id, body)
                    self.send_json(status_code, value)
            except (ValueError, UnicodeError, OSError):
                self.send_json(400, {"error": "invalid_json_or_storage"})

    return Handler


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staging-dir", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args(argv)
    if not 1024 <= args.port <= 65535:
        parser.error("Choose an explicit unprivileged TCP port")
    state = GuestState(args.staging_dir, args.state_dir, read_private_token(args.token_file))
    with ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(state)) as server:
        server.daemon_threads = True
        ready = {
            "pid": os.getpid(),
            "address": "127.0.0.1",
            "port": args.port,
            "manifest_sha256": hashlib.sha256(state.manifest_bytes).hexdigest(),
        }
        write_new(state.state / "server.json", json.dumps(ready).encode())
        print(json.dumps(ready), flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
