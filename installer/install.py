#!/usr/bin/env python3
"""Pinned, foreground KiraBridge installation. Does not need the checkout's venv."""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import io
import json
import os
import platform
import plistlib
import re
import selectors
import shlex
import shutil
import signal
import sqlite3
import stat
import subprocess
import sys
import tarfile
import time
import tomllib
import types
import uuid
from pathlib import Path

LABEL = "com.kirabridge.bridge"
PRESENTER = None
OUTPUT_TARGET = None


class NonBlockingOutput:
    """A separately opened owned FD; never changes another stream's flags."""

    def __init__(self, fd, encoding="utf-8"):
        self.fd, self.encoding = fd, encoding

    def fileno(self):
        return self.fd

    def isatty(self):
        return os.isatty(self.fd)

    def flush(self):
        pass

    def write(self, text):
        data = text.encode(self.encoding)
        # Decoration never waits for output space, even with a paused terminal.
        if os.write(self.fd, data) != len(data):
            raise BlockingIOError("Decorative output not fully accepted")
        return len(text)

    def write_bytes(self, data):
        """One nonblocking attempt; the presenter retains unaccepted bytes."""
        try:
            return os.write(self.fd, data)
        except BlockingIOError:
            return 0

    def write_child(self, data, deadline, process, timeout):
        view = memoryview(data)
        with selectors.DefaultSelector() as selector:
            selector.register(self.fd, selectors.EVENT_WRITE)
            while view:
                if time.monotonic() >= deadline:
                    raise subprocess.TimeoutExpired(process.args, timeout)
                try:
                    count = os.write(self.fd, view)
                    if count <= 0:
                        raise OSError("Child output stream closed")
                    view = view[count:]
                except BlockingIOError:
                    selector.select(min(0.05, max(0, deadline - time.monotonic())))

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def own_terminal_output(stream):
    fd = None
    try:
        if not stream.isatty():
            return None
        original = os.fstat(stream.fileno())
        fd = os.open(
            os.ttyname(stream.fileno()),
            os.O_WRONLY | os.O_NONBLOCK | os.O_NOCTTY | os.O_CLOEXEC | os.O_NOFOLLOW,
        )
        opened = os.fstat(fd)
        if not stat.S_ISCHR(opened.st_mode) or opened.st_rdev != original.st_rdev:
            raise OSError("TTY identity changed")
        return NonBlockingOutput(fd, getattr(stream, "encoding", None) or "utf-8")
    except (AttributeError, OSError, ValueError):
        if fd is not None:
            os.close(fd)
        return None


def say(message):
    if PRESENTER is not None:
        PRESENTER.say(message)
    else:
        print(message, file=sys.stderr, flush=True)


def presentation_error(message):
    if PRESENTER is not None:
        PRESENTER.error(message)
    else:
        print(message, file=sys.stderr, flush=True)


def begin_presentation(bundle, *, language="de", motion="auto"):
    global PRESENTER, OUTPUT_TARGET
    try:
        root = Path(bundle).resolve(strict=True)
        manifest = json.loads((root / "release.json").read_text())
        path = root / "installer/presentation.py"
        expected = manifest.get("files", {}).get("installer/presentation.py")
        if (
            not isinstance(expected, str)
            or not re.fullmatch(r"[a-f0-9]{64}", expected)
            or path.is_symlink()
            or not path.resolve(strict=True).is_relative_to(root)
        ):
            return
        verified = path.read_bytes()
        if hashlib.sha256(verified).hexdigest() != expected:
            return
        module = types.ModuleType("_kirabridge_installer_presentation")
        module.__file__ = str(path)
        exec(compile(verified, str(path), "exec"), module.__dict__)
        OUTPUT_TARGET = own_terminal_output(sys.stderr)
        PRESENTER = module.create_presentation(
            root, language=language, motion=motion, exclusive_output=OUTPUT_TARGET is not None
        )
        if PRESENTER is not None and OUTPUT_TARGET is not None:
            PRESENTER.graphic_stream = OUTPUT_TARGET
        elif OUTPUT_TARGET is not None:
            OUTPUT_TARGET.close()
            OUTPUT_TARGET = None
    except Exception:
        # Decoration is optional; the full package-integrity gate remains mandatory.
        PRESENTER = None
        if OUTPUT_TARGET is not None:
            OUTPUT_TARGET.close()
            OUTPUT_TARGET = None


def relay_child_output(process, timeout):
    """Own both child pipes; real output releases our frame area before forwarding."""
    deadline = time.monotonic() + timeout
    output_seen = False
    with selectors.DefaultSelector() as selector:
        for stream in (process.stdout, process.stderr):
            selector.register(stream, selectors.EVENT_READ)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(process.args, timeout)
            events = selector.select(min(0.05, remaining))
            if not events and not output_seen and PRESENTER is not None:
                PRESENTER.begin()
                PRESENTER.tick()
            for key, _ in events:
                data = os.read(key.fileobj.fileno(), 65536)
                if not data:
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                    continue
                if PRESENTER is not None:
                    # A partial graphic is discarded, never finalized across logs.
                    PRESENTER.cancel()
                output_seen = True
                prefix = getattr(PRESENTER, "output_prefix", "") if PRESENTER is not None else ""
                OUTPUT_TARGET.write_child(
                    prefix.encode(OUTPUT_TARGET.encoding) + data,
                    deadline,
                    process,
                    timeout,
                )
                if prefix:
                    PRESENTER.acknowledge_output_prefix()
        process.wait(timeout=max(0, deadline - time.monotonic()))


def require_visible_terminal(args):
    if not getattr(args, "require_visible_terminal", False):
        return
    path = Path(__file__).with_name("visible_terminal.py")
    if path.is_symlink():
        raise RuntimeError("Visible-terminal verifier symlink refused")
    verified = path.read_bytes()
    if args.bundle:
        manifest = json.loads((args.bundle / "release.json").read_text())
        expected = manifest.get("files", {}).get("installer/visible_terminal.py")
        if not expected or hashlib.sha256(verified).hexdigest() != expected:
            raise RuntimeError("Visible-terminal verifier missing or checksum changed")
    namespace = {"__name__": "kirabridge_visible_installer", "__file__": str(path)}
    exec(compile(verified, str(path), "exec"), namespace)
    args.visible_terminal_proof = namespace["confirm_visible_terminal"](
        getattr(args, "visible_terminal_proof", None)
    )


def run(argv, *, capture=False, timeout=600, **kwargs):
    if "env" not in kwargs:
        kwargs["env"] = {
            k: v
            for k, v in os.environ.items()
            if k not in {"PYTHONPATH", "PYTHONHOME", "UV_PROJECT_ENVIRONMENT", "VIRTUAL_ENV"}
        }
    controlled = not capture and PRESENTER is not None and OUTPUT_TARGET is not None
    process = subprocess.Popen(
        [str(x) for x in argv],
        start_new_session=True,
        stdout=subprocess.PIPE if capture or controlled else None,
        stderr=subprocess.PIPE if capture or controlled else None,
        **kwargs,
    )
    try:
        if controlled:
            relay_child_output(process, timeout)
            stdout = None
        else:
            stdout, _ = process.communicate(timeout=timeout)
        if process.returncode:
            raise RuntimeError(f"command failed ({process.returncode}): {Path(str(argv[0])).name}")
        return stdout if capture else None
    except BaseException:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=3)
        raise
    finally:
        if controlled:
            for stream in (process.stdout, process.stderr):
                stream.close()


def private_dir(path):
    if path.is_symlink():
        raise RuntimeError(f"symlink directory refused: {path}")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError(f"owner-only directory required, permissions not changed: {path}")


def atomic(path, data, mode=0o600, *, exact_mode=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise RuntimeError(f"symlink destination refused: {path}")
    temporary = path.with_name("." + path.name + "-" + uuid.uuid4().hex)
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, mode)
    try:
        if exact_mode:
            # Bootstrap uses umask 077; native archive modes are explicit and pinned.
            os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data.encode() if isinstance(data, str) else data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def jwrite(path, value):
    atomic(path, json.dumps(value, indent=2) + "\n")


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def settings(config):
    return tomllib.loads(config.read_text())


def state_file(config):
    return Path(settings(config)["data_dir"]).expanduser() / "bridge.sqlite3"


@contextlib.contextmanager
def idle_guard(config):
    path = state_file(config)
    if not path.exists():
        yield None
        return
    db = sqlite3.connect(f"file:{path}?mode=rw", uri=True, isolation_level=None, timeout=5)
    try:
        db.execute("BEGIN IMMEDIATE")
        tables = {r[0] for r in db.execute("select name from sqlite_master where type='table'")}
        tasks = (
            db.execute(
                "select count(*) from tasks "
                "where state in ('created','queued','accepted','running')"
            ).fetchone()[0]
            if "tasks" in tables
            else 0
        )
        jobs = (
            db.execute(
                "select count(*) from message_jobs where state in ('queued','running')"
                + (
                    " and (state='running' or not exists (select 1 from queue_holds h "
                    "where h.queue_id='messages' and h.item_id=message_jobs.message_id))"
                    if "queue_holds" in tables
                    else ""
                )
            ).fetchone()[0]
            if "message_jobs" in tables
            else 0
        )
        team_work = (
            db.execute(
                "select count(*) from team_work where state in "
                "('queued','dispatching','created','accepted','running','processing_result')"
            ).fetchone()[0]
            if "team_work" in tables
            else 0
        )
        if tasks or jobs or team_work:
            raise RuntimeError(
                f"BUSY: {tasks} tasks, {jobs} receiver jobs, {team_work} team jobs. "
                "Nothing switched."
            )
        say("Leerlauf unter Schreibsperre: 0 aktive Tasks, 0 Empfängerjobs.")
        yield db
    finally:
        db.rollback()
        db.close()


def python(release):
    return release / "source/.venv/bin/python"


def cli(release, config, *args, timeout=30):
    return json.loads(
        run(
            [python(release), "-m", "kirabridge.cli", "--config", config, *args],
            capture=True,
            timeout=timeout,
        )
    )


def bundle_member(root, name):
    if not isinstance(name, str):
        raise RuntimeError("Unsafe bundle member")
    relative = Path(name)
    if (
        not relative.parts
        or relative.is_absolute()
        or ".." in relative.parts
        or relative.as_posix() != name
    ):
        raise RuntimeError("Unsafe bundle member")
    current = root
    for component in relative.parts:
        current = current / component
        if current.is_symlink():
            raise RuntimeError("Unsafe bundle member symlink")
    if not current.is_file() or not stat.S_ISREG(current.stat().st_mode):
        raise RuntimeError("Unsafe bundle member type")
    return current


def native_contract(root, manifest, commit, version):
    """Manifest-verified regular files only; old release bundles remain rollback inputs."""
    prefix = "native/KiraBridge.app/"
    entries = {
        name: value for name, value in manifest["files"].items() if name.startswith("native/")
    }
    descriptor = manifest.get("native_app")
    if descriptor is None:
        if (
            manifest.get("native_app_required")
            or entries
            or manifest.get("file_modes")
            or "payload/src/kirabridge/platform_adapters/macos/system_transport.py"
            in manifest["files"]
        ):
            raise RuntimeError("Required native app descriptor is missing")
        return None
    if (
        not isinstance(descriptor, dict)
        or descriptor.get("schema") != "kirabridge.native-app.v1"
        or descriptor.get("path") != "native/KiraBridge.app"
        or type(descriptor.get("protocol")) is not int
        or descriptor.get("protocol") != 1
        or descriptor.get("source_commit") != commit
        or descriptor.get("signing") != "ad-hoc"
        or descriptor.get("architecture") not in {"x86_64", "arm64"}
        or not isinstance(descriptor.get("binary_sha256"), str)
        or not re.fullmatch(r"[a-f0-9]{64}", descriptor["binary_sha256"])
        or manifest.get("native_app_required") is not True
        or not entries
        or len(entries) > 1000
        or any(not name.startswith(prefix) for name in entries)
    ):
        raise RuntimeError("Native app descriptor identity is invalid")
    if (
        manifest.get("platforms", ["Darwin-" + descriptor["architecture"]])
        != ["Darwin-" + descriptor["architecture"]]
        or sys.platform == "darwin"
        and descriptor["architecture"] != platform.machine()
    ):
        raise RuntimeError("Native app architecture does not match this host")
    modes = manifest.get("file_modes")
    if not isinstance(modes, dict) or set(modes) != set(entries):
        raise RuntimeError("Native app file modes are incomplete")
    required = {
        prefix + "Contents/Info.plist",
        prefix + "Contents/MacOS/KiraBridge",
        prefix + "Contents/_CodeSignature/CodeResources",
    }
    if not required.issubset(entries):
        raise RuntimeError("Native app files are incomplete")
    actual, total = set(), 0
    native = root / "native"
    if native.is_symlink() or not native.is_dir():
        raise RuntimeError("Unsafe native app directory")
    for path in native.rglob("*"):
        if path.is_symlink():
            raise RuntimeError("Unsafe native app symlink")
        if path.is_dir():
            continue
        actual.add(path.relative_to(root).as_posix())
    if actual != set(entries):
        raise RuntimeError("Native app has unlisted or missing members")
    for name in entries:
        path = bundle_member(root, name)
        mode = modes[name]
        if (
            type(mode) is not int
            or mode not in {0o644, 0o755}
            or stat.S_IMODE(path.stat().st_mode) != mode
        ):
            raise RuntimeError("Native app file mode mismatch")
        size = path.stat().st_size
        total += size
        if size > 32 * 1024 * 1024 or total > 64 * 1024 * 1024:
            raise RuntimeError("Native app exceeds package limits")
        if sha(path) != entries[name]:
            raise RuntimeError("Native app checksum mismatch")
    binary = prefix + "Contents/MacOS/KiraBridge"
    if modes[binary] != 0o755 or entries[binary] != descriptor["binary_sha256"]:
        raise RuntimeError("Native app binary pin mismatch")
    with bundle_member(root, binary).open("rb") as stream:
        header = stream.read(32)
    # The companion builder emits a thin, 64-bit MH_EXECUTE, never a universal
    # wrapper or an archive/script. CPU declarations alone cannot prove that.
    architecture = {0x01000007: "x86_64", 0x0100000C: "arm64"}.get(
        int.from_bytes(header[4:8], "little")
    )
    if (
        len(header) != 32
        or header[:4] != b"\xcf\xfa\xed\xfe"
        or int.from_bytes(header[12:16], "little") != 2
        or architecture != descriptor["architecture"]
    ):
        raise RuntimeError("Native app Mach-O architecture differs from descriptor")
    info = plistlib.loads(bundle_member(root, prefix + "Contents/Info.plist").read_bytes())
    if (
        info.get("CFBundleIdentifier") != "de.netzwerkpunkt.kirabridge"
        or info.get("CFBundleExecutable") != "KiraBridge"
        or info.get("KiraBridgeSourceCommit") != commit
        or info.get("KiraBridgeVersion") != version
        or type(info.get("KiraBridgeSystemProtocol")) is not int
        or info.get("KiraBridgeSystemProtocol") != 1
    ):
        raise RuntimeError("Native app plist identity mismatch")
    return {
        "native_app_required": True,
        "native_app": descriptor,
        "files": entries,
        "file_modes": modes,
    }


def copy_native(root, destination, contract):
    """Copy verified bytes once; never execute the app or modify user Applications."""
    for name, expected in contract["files"].items():
        source = bundle_member(root, name)
        fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_size > 32 * 1024 * 1024:
                raise RuntimeError("Unsafe native app source")
            with os.fdopen(fd, "rb", closefd=False) as stream:
                data = stream.read(32 * 1024 * 1024 + 1)
            after = os.fstat(fd)
            if (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            ) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ) or hashlib.sha256(data).hexdigest() != expected:
                raise RuntimeError("Native app changed during verified copy")
        finally:
            os.close(fd)
        atomic(destination / name, data, contract["file_modes"][name], exact_mode=True)


def prepare_bundle(args):
    bundle = args.bundle.resolve()
    manifest = json.loads((bundle / "release.json").read_text())
    ref, version = manifest["commit"], manifest["version"]
    if not re.fullmatch("[a-f0-9]{40}", ref):
        raise RuntimeError("Invalid bundle commit")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:(?:a|b|rc)[0-9]+)?", version):
        raise RuntimeError("Invalid bundle version")
    if not isinstance(manifest.get("files"), dict):
        raise RuntimeError("Invalid bundle checksum declaration")
    for name, expected in manifest["files"].items():
        path = bundle_member(bundle, name)
        if not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected):
            raise RuntimeError("Invalid bundle checksum declaration")
        if sha(path) != expected:
            raise RuntimeError(f"Bundle checksum mismatch: {name}")
    wheel_name = manifest.get("wheel")
    if (
        not isinstance(wheel_name, str)
        or wheel_name not in manifest["files"]
        or not wheel_name.endswith(".whl")
    ):
        raise RuntimeError("Bundle wheel must be a checksum-pinned member")
    wheel = bundle_member(bundle, wheel_name)
    native = native_contract(bundle, manifest, ref, version)
    releases = args.prefix / "releases"
    private_dir(releases)
    destination = releases / (version + "-" + ref[:12])
    if destination.is_symlink():
        raise RuntimeError("Existing release symlink refused; preserved")
    if destination.exists():
        saved = json.loads((destination / "release.json").read_text())
        if saved["commit"] != ref or cli_version(destination) != version:
            raise RuntimeError("Existing release identity differs; preserved")
        if native is not None:
            if any(saved.get(key) != value for key, value in native.items()):
                raise RuntimeError("Existing native release identity differs; preserved")
            native_contract(destination, saved, ref, version)
        return destination
    uv = shutil.which("uv")
    if not uv or run([uv, "--version"], capture=True).decode().split()[:2] != ["uv", "0.11.6"]:
        raise RuntimeError("uv 0.11.6 is required")
    private_dir(destination)
    try:
        shutil.copytree(bundle / "payload", destination / "source")
        if native is not None:
            copy_native(bundle, destination, native)
            native_contract(destination, {**manifest, **native}, ref, version)
        source = destination / "source"
        run(
            [
                uv,
                "sync",
                "--project",
                source,
                "--locked",
                "--no-dev",
                "--no-install-project",
                "--no-build",
                "--python",
                sys.executable,
                "--cache-dir",
                args.cache_dir,
            ]
        )
        run(
            [
                uv,
                "pip",
                "install",
                "--python",
                python(destination),
                "--no-deps",
                "--cache-dir",
                args.cache_dir,
                wheel,
            ]
        )
        if cli_version(destination) != version:
            raise RuntimeError("Installed wheel version mismatch")
        jwrite(
            destination / "release.json",
            {
                "version": version,
                "commit": ref,
                "source_commit": ref,
                "lock_sha256": sha(source / "uv.lock"),
                **(native or {}),
            },
        )
    except BaseException:
        shutil.rmtree(destination)
        raise
    return destination


def prepare(args):
    if getattr(args, "bundle", None):
        return prepare_bundle(args)
    ref = args.ref
    if not re.fullmatch("[a-f0-9]{40}", ref or ""):
        raise RuntimeError("--ref must be an exact 40-character Git commit SHA")
    actual = (
        run(["git", "-C", args.repo, "rev-parse", ref + "^{commit}"], capture=True).decode().strip()
    )
    if actual != ref:
        raise RuntimeError("Git commit mismatch")
    project = tomllib.loads(
        run(["git", "-C", args.repo, "show", ref + ":pyproject.toml"], capture=True).decode()
    )
    version = project["project"]["version"]
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:(?:a|b|rc)[0-9]+)?", version):
        raise RuntimeError("Unsupported release version")
    if (
        sys.platform == "darwin"
        and run(
            [
                "git",
                "-C",
                args.repo,
                "ls-tree",
                "--name-only",
                ref,
                "src/kirabridge/platform_adapters/macos/system_transport.py",
            ],
            capture=True,
        ).strip()
    ):
        raise RuntimeError(
            "This macOS revision requires its signed native runtime; "
            "use the release --bundle package"
        )
    releases = args.prefix / "releases"
    private_dir(releases)
    destination = releases / (version + "-" + ref[:12])
    if destination.exists():
        manifest = json.loads((destination / "release.json").read_text())
        if manifest["commit"] != ref or cli_version(destination) != version:
            raise RuntimeError("Existing release identity differs")
        say(f"Bereits vorbereitet: {version} @ {ref}")
        return destination
    stage = releases / (".preparing-" + uuid.uuid4().hex)
    private_dir(stage)
    source = stage / "source"
    source.mkdir(mode=0o700)
    say(f"Bereite {version} aus Git-Commit {ref} vor; Arbeitskopie wird nicht kopiert.")
    archive = run(["git", "-C", args.repo, "archive", "--format=tar", ref], capture=True)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(source, filter="data")
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("uv is required; install it explicitly before running this installer")
    run(
        [
            uv,
            "sync",
            "--project",
            source,
            "--frozen",
            "--no-dev",
            "--no-editable",
            "--python",
            sys.executable,
            "--cache-dir",
            args.cache_dir,
        ]
    )
    if cli_version(stage) != version:
        raise RuntimeError("Installed package version differs from release")
    jwrite(
        stage / "release.json",
        {"version": version, "commit": ref, "lock_sha256": sha(source / "uv.lock")},
    )
    # venv Python entry points use absolute paths. Build in the final path instead
    # of renaming a venv; recreate once there with the same frozen lock.
    destination.mkdir(mode=0o700)
    shutil.move(str(source), str(destination / "source"))
    shutil.rmtree(destination / "source/.venv")
    run(
        [
            uv,
            "sync",
            "--project",
            destination / "source",
            "--frozen",
            "--no-dev",
            "--no-editable",
            "--python",
            sys.executable,
            "--cache-dir",
            args.cache_dir,
        ]
    )
    atomic(destination / "release.json", (stage / "release.json").read_bytes())
    shutil.rmtree(stage)
    say(f"Versionspaket geprüft: {version}; bisherige Installation unverändert.")
    return destination


def cli_version(release):
    return (
        run(
            [python(release), "-c", "import kirabridge;print(kirabridge.__version__)"], capture=True
        )
        .decode()
        .strip()
    )


def fresh_config(args, release):
    if args.config.exists():
        # Never rewrite an existing policy, even if its permissions differ.
        return
    private_dir(args.config.parent)
    data = args.prefix / "data"
    private_dir(data)
    credentials = args.config.parent / "credentials.json"
    if credentials.exists():
        raise RuntimeError("Credentials exist without config; refusing to overwrite")
    code = (
        "import json;from kirabridge.bridge_core.bridge import INPUTS;"
        "from kirabridge.operations import capability_for;"
        "print(json.dumps(sorted({capability_for(op) for op in INPUTS})))"
    )
    capabilities = json.loads(run([python(release), "-c", code], capture=True))
    capabilities += [
        "bridge.health",
        "task.read",
        "task.cancel",
        "agent.inspect",
        "message.send",
        "message.read",
        "message.ack",
        "session.inspect",
    ]
    import secrets

    tokens = {name: secrets.token_urlsafe(48) for name in ("local", "chatgpt")}
    text = (
        f"data_dir = {json.dumps(str(data))}\n"
        f"credentials_file = {json.dumps(str(credentials))}\n"
        'host = "127.0.0.1"\nport = 8765\nallow_remote = false\n'
    )
    full = args.full_access
    workspace = getattr(args, "workspace", Path.home() / "workspace/KiraBridge").resolve()
    if not full:
        if workspace == Path("/"):
            raise RuntimeError("A scoped workspace cannot be the filesystem root")
        workspace.mkdir(mode=0o700, parents=True, exist_ok=True)
    roots = ["/"] if full else [str(workspace)]
    for name in tokens:
        text += (
            f'\n[principals.{name}]\napproval_mode = "{"automatic" if full else "manual"}"\n'
            + f'permission_level = "{"full" if full else "ask"}"\n'
            + ('automatic_operations = ["session.input"]\n' if full and name == "chatgpt" else "")
            + f"capabilities = {json.dumps(capabilities)}\n"
            f"roots = {json.dumps(roots)}\nread_roots = {json.dumps(roots)}\n"
            f"terminal_roots = {json.dumps(roots)}\n"
            f"allow_any_executable = {str(full).lower()}\nexecutables = []\nagents = []\n"
            f'token_env = "KIRABRIDGE_{name.upper()}_TOKEN"\n'
        )
    text += (
        "\n[terminal]\nsearch_path = "
        + json.dumps(
            [
                str(Path.home() / ".local/bin"),
                "/usr/local/bin",
                "/opt/homebrew/bin",
                "/usr/bin",
                "/bin",
                "/usr/sbin",
                "/sbin",
            ]
        )
        + "\nhome = "
        + json.dumps(str(Path.home()))
        + "\n"
    )
    jwrite(credentials, tokens)
    atomic(args.config, text)
    say(
        "Neue lokale Konfiguration erstellt; Zugangsdaten nicht ausgegeben. "
        "ChatGPT-Kontoverbindung separat erforderlich."
    )


def loaded(args):
    if args.service == "none":
        return False
    result = subprocess.run(
        ["launchctl", "print", f"gui/{os.getuid()}/{LABEL}"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode:
        return False
    match = re.search(r"^\s*path = (.+)$", result.stdout, re.MULTILINE)
    if not match or Path(match.group(1).strip('"')) != args.plist:
        raise RuntimeError("Loaded service comes from another plist; preserved")
    return True


def stop_service(args):
    if loaded(args):
        run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], capture=True, timeout=20)


def start_service(args):
    if args.service != "none" and args.plist.exists():
        command = ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(args.plist)]
        # Bootstrap exit code 5 is a generic Input/output error (EIO), not
        # proof of pending removal. Delayed teardown after bootout is one
        # possible cause. Retry only code 5 within a fixed bound, then fail
        # through activate()'s existing rollback path; other errors fail immediately.
        # Production HTTP long-polls can outlive the old four-second retry
        # window. Keep both elapsed time and command count bounded; do not change
        # the operator's launchd exit/KeepAlive options or require root.
        deadline = time.monotonic() + 30
        for attempt in range(30):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("launchctl bootstrap did not settle within 30 seconds")
            completed = subprocess.run(
                command, capture_output=True, text=True, timeout=min(20, remaining), check=False
            )
            if completed.returncode == 0:
                return
            if completed.returncode != 5 or attempt == 29:
                detail = completed.stderr.strip() or completed.stdout.strip()
                raise RuntimeError(
                    f"launchctl bootstrap failed ({completed.returncode}): {detail[:500]}"
                )
            time.sleep(min(1, max(0, deadline - time.monotonic())))


SOURCE_FIELDS = ("source_package_path", "source_tree_sha256", "source_file_count")


def release_source(release):
    # Version strings can be shared by distinct builds. Resolve the installed
    # package with the target venv, ignoring the caller's PYTHONPATH/user site.
    package = Path(
        json.loads(
            run(
                [
                    python(release),
                    "-I",
                    "-c",
                    "import json,pathlib,kirabridge; "
                    "print(json.dumps(str(pathlib.Path(kirabridge.__file__).resolve().parent)))",
                ],
                capture=True,
                timeout=8,
            )
        )
    ).resolve(strict=True)
    if not package.is_relative_to((release / "source/.venv").resolve(strict=True)):
        raise RuntimeError("Target runtime imports a package outside its release")
    manifest = {str(p.relative_to(package)): sha(p) for p in sorted(package.rglob("*.py"))}
    if not manifest:
        raise RuntimeError("Target runtime source is unavailable")
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return {
        "source_package_path": str(package),
        "source_tree_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
        "source_file_count": len(manifest),
    }


def wait_health(args, release, version, *, expected_source=None):
    expected = release_source(release) if expected_source is None else expected_source
    if (
        not isinstance(expected.get("source_package_path"), str)
        or not Path(expected["source_package_path"]).is_absolute()
        or not isinstance(expected.get("source_tree_sha256"), str)
        or not re.fullmatch(r"[a-f0-9]{64}", expected.get("source_tree_sha256", ""))
        or type(expected.get("source_file_count")) is not int
        or expected["source_file_count"] <= 0
    ):
        raise RuntimeError("Expected daemon source identity is unavailable")
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            health = cli(release, args.config, "status", timeout=8)
            if (
                health.get("version") == version
                and health.get("dispatcher_active")
                and health.get("runtime", {}).get("config_sha256") == sha(args.config)
                and all(
                    health.get("runtime", {}).get(key) == expected[key] for key in SOURCE_FIELDS
                )
            ):
                return health
        except (RuntimeError, subprocess.TimeoutExpired, ValueError):
            pass
        time.sleep(0.5)
    raise RuntimeError("New daemon readiness not proven within 30 seconds")


def validate_service_owner(args):
    if args.service == "none" or not args.plist.exists():
        return
    previous = plistlib.loads(args.plist.read_bytes())
    argv = previous.get("ProgramArguments", [])
    if (
        previous.get("Label") != LABEL
        or str(args.config) not in argv
        or "serve" not in argv
        or "kirabridge.cli" not in argv
    ):
        raise RuntimeError("Existing service is not the expected KiraBridge config; left untouched")


def snapshot_file(path, backup, name):
    if path.is_symlink():
        raise RuntimeError(f"Symlink file refused: {path}")
    if path.exists():
        atomic(backup / name, path.read_bytes(), path.stat().st_mode & 0o777)
        return True
    return False


def validate_destination(path, *, private=False):
    # Validate without chmod/chown. Standard macOS /var aliases are resolved by callers.
    if path.is_symlink():
        raise RuntimeError(f"Symlink destination refused: {path}")
    if path.exists():
        info = path.stat()
        if info.st_uid != os.getuid() or info.st_mode & (0o077 if private else 0o022):
            raise RuntimeError(f"Unsafe ownership/permissions, left unchanged: {path}")
    for parent in path.parents:
        if parent.is_symlink():
            raise RuntimeError(f"Symlink parent refused: {parent}")
        if not parent.exists():
            continue
        info = parent.stat()
        if info.st_uid not in (0, os.getuid()) or (
            info.st_mode & 0o022 and not info.st_mode & 0o1000
        ):
            raise RuntimeError(f"Unsafe parent directory: {parent}")


def validate_launcher_owner(args):
    if args.launcher.is_symlink():
        raise RuntimeError("Symlink launcher refused")
    if not args.launcher.exists():
        return
    current = args.prefix / "current.json"
    if current.exists():
        recorded = json.loads(current.read_text()).get("installed_wrapper_sha256")
        if recorded and sha(args.launcher) == recorded:
            return
    # Recognize only the established plain KiraBridge launcher, never arbitrary shell code.
    text = ""
    try:
        text = args.launcher.read_text()
        tokens = shlex.split(text.split("\n", 1)[1])
    except (ValueError, IndexError, UnicodeError):
        tokens = []
    valid = (
        text.startswith("#!/bin/sh\n")
        and len(text.splitlines()) == 2
        and len(tokens) == 7
        and tokens[:1] == ["exec"]
        and tokens[2:5] == ["-m", "kirabridge.cli", "--config"]
        and tokens[5:6] == [str(args.config)]
        and tokens[6:] == ["$@"]
    )
    if not valid:
        raise RuntimeError("Unrecognized existing launcher preserved; manual migration required")


def require_queue_compatibility(config, release):
    """Old runtimes ignore delivery holds: never resume their worker on such a store."""
    path = state_file(config)
    if release is None or not path.exists():
        return
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
        exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='queue_holds' AND type='table'"
        ).fetchone()
        held = exists and db.execute("SELECT 1 FROM queue_holds LIMIT 1").fetchone()
    if not held:
        return
    try:
        run(
            [python(release), "-c", "from kirabridge.queue_management import QueueManager"],
            capture=True,
            timeout=10,
        )
    except (RuntimeError, subprocess.TimeoutExpired):
        raise RuntimeError(
            "QUEUE COMPATIBILITY: target runtime ignores delivery withdrawals. "
            "No service switch; preserve queue/audit and use a queue-aware runtime. "
            "Never delete holds or restore a database backup to force rollback."
        ) from None


def desktop_module(args):
    path = Path(__file__).with_name("desktop.py")
    if path.is_symlink():
        raise RuntimeError("Desktop installer symlink refused")
    manifest = json.loads((args.bundle / "release.json").read_text())
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != manifest.get("files", {}).get("installer/desktop.py"):
        raise RuntimeError("Desktop installer checksum mismatch")
    module = types.ModuleType("_kirabridge_desktop_installer")
    exec(compile(data, str(path), "exec"), module.__dict__)
    return module


def activate(args, release):
    require_visible_terminal(args)
    validate_service_owner(args)
    validate_launcher_owner(args)
    fresh_config(args, release)
    validate_service_owner(args)
    config_before = args.config.read_bytes()
    config = settings(args.config)
    credentials = Path(config["credentials_file"]) if config.get("credentials_file") else None
    credential_hash = sha(credentials) if credentials else None
    current = args.prefix / "current.json"
    old = json.loads(current.read_text()) if current.exists() else None
    manifest = json.loads((release / "release.json").read_text())
    if old and old["release"] == str(release) and not getattr(args, "desktop", False):
        if args.service != "none":
            if not loaded(args):
                start_service(args)
            wait_health(args, release, manifest["version"])
        say("Diese Version ist bereits aktiviert und geprüft.")
        return
    backup = args.prefix / "backups" / (time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8])
    private_dir(backup)
    had_wrapper = snapshot_file(args.launcher, backup, "launcher.before")
    had_plist = (
        snapshot_file(args.plist, backup, "service.before.plist")
        if args.service != "none"
        else False
    )
    atomic(backup / "config.before.toml", config_before)
    if credentials:
        snapshot_file(credentials, backup, "credentials.before.json")
    was_loaded = loaded(args)
    previous_health = None
    if args.service != "none":
        try:
            previous_health = cli(release, args.config, "status", timeout=8)
        except (RuntimeError, subprocess.TimeoutExpired, ValueError):
            if was_loaded:
                raise RuntimeError("Existing service health unavailable; no switch") from None
        if previous_health and not was_loaded:
            raise RuntimeError("Backend runs outside expected launchd service; no switch")
    before = {
        "previous": old,
        "release": str(release),
        "backup": str(backup),
        "had_wrapper": had_wrapper,
        "had_plist": had_plist,
        "was_loaded": was_loaded,
        "previous_version": (previous_health or {}).get("version"),
        "previous_source": {
            key: (previous_health or {}).get("runtime", {}).get(key) for key in SOURCE_FIELDS
        },
        "config": str(args.config),
        "launcher": str(args.launcher),
        "plist": str(args.plist),
        "service": args.service,
        **manifest,
    }
    jwrite(backup / "transaction.json", before)
    if getattr(args, "desktop", False):
        before["desktop"] = desktop_module(args).snapshot(
            types.SimpleNamespace(**globals()), args, release, old, backup
        )
        jwrite(backup / "transaction.json", before)
    say(f"Rückweg gesichert: {backup}. Konfiguration und Zugangsdaten bleiben erhalten.")
    try:
        with idle_guard(args.config):
            require_queue_compatibility(args.config, release)
            dbpath = state_file(args.config)
            if dbpath.exists():
                with (
                    sqlite3.connect(f"file:{dbpath}?mode=ro", uri=True) as reader,
                    sqlite3.connect(backup / "bridge.before.sqlite3") as writer,
                ):
                    reader.backup(writer)
            if args.config.read_bytes() != config_before or (
                credentials and sha(credentials) != credential_hash
            ):
                raise RuntimeError(
                    "Configuration/credentials changed during preparation; no switch"
                )
            require_visible_terminal(args)
            jwrite(current, before)  # Durable recovery record before any switch.
            stop_service(args)
            wrapper = (
                "#!/bin/sh\nexec "
                + shlex.quote(str(python(release)))
                + " -m kirabridge.cli --config "
                + shlex.quote(str(args.config))
                + ' "$@"\n'
            )
            atomic(args.launcher, wrapper, 0o700)
            if args.service != "none":
                plist = (
                    plistlib.loads((backup / "service.before.plist").read_bytes())
                    if had_plist
                    else {
                        "Label": LABEL,
                        "ProcessType": "Background",
                        "RunAtLoad": True,
                        "KeepAlive": {"SuccessfulExit": False},
                        "ThrottleInterval": 3,
                        "Umask": 0o077,
                        "EnvironmentVariables": {"HOME": str(Path.home()), "PATH": os.defpath},
                    }
                )
                plist["ProgramArguments"] = [
                    str(python(release)),
                    "-m",
                    "kirabridge.cli",
                    "--config",
                    str(args.config),
                    "serve",
                    "--transport",
                    "http",
                ]
                logs = args.prefix / "logs"
                private_dir(logs)
                plist.setdefault("StandardOutPath", str(logs / "service.stdout.log"))
                plist.setdefault("StandardErrorPath", str(logs / "service.stderr.log"))
                atomic(args.plist, plistlib.dumps(plist))
            before["installed_wrapper_sha256"] = sha(args.launcher)
            if args.service != "none":
                before["installed_plist_sha256"] = sha(args.plist)
            jwrite(current, before)
        # Shutdown may need SQLite writes. Do not wait for launchd to replace a
        # stopping process while our idle guard still holds its writer reservation.
        start_service(args)
        if args.service != "none":
            health = wait_health(args, release, manifest["version"])
            say(f"Dienst gestartet: Version {health['version']}, PID {health['runtime']['pid']}.")
        if before.get("desktop"):
            desktop_module(args).activate(
                types.SimpleNamespace(**globals()), args, release, before, current
            )
    except Exception:
        if current.exists() and json.loads(current.read_text()).get("backup") == str(backup):
            say("Umschaltung fehlgeschlagen. Rückweg wird unter erneuter Leerlaufprüfung versucht.")
            rollback(args, _compensating=True)
        raise
    assert args.config.read_bytes() == config_before, "Configuration changed"
    assert not credentials or sha(credentials) == credential_hash, "Credentials changed"
    say(
        f"INSTALLIERT: {manifest['version']} @ {manifest['commit']}. "
        "Rechte und Zugangsdaten erhalten."
    )


def rollback(args, *, _compensating=False):
    # Recovery restores only the already recorded old definitions. Loss of UI
    # after a failed switch must not prevent this guarded compensation.
    if not _compensating:
        require_visible_terminal(args)
    current = args.prefix / "current.json"
    if not current.exists():
        raise RuntimeError("No activated version/recovery record")
    active = json.loads(current.read_text())
    core_already_restored = active.get("rollback_core_restored", False)
    for key in ("config", "launcher", "plist", "service"):
        if str(getattr(args, key)) != active[key]:
            raise RuntimeError("Rollback arguments differ from activation; no switch")
    validate_service_owner(args)
    backup = Path(active["backup"])
    for path, key in [
        (args.launcher, "installed_wrapper_sha256"),
        (args.plist, "installed_plist_sha256"),
    ]:
        expected_key = "restored_" + key if active.get("rollback_core_restored") else key
        if expected_key in active and (
            (sha(path) if path.exists() else None) != active[expected_key]
        ):
            raise RuntimeError(
                "Installed definition changed since activation; preserve and review first"
            )
    with idle_guard(args.config):
        previous_release = (active.get("previous") or {}).get("release")
        require_queue_compatibility(
            args.config, Path(previous_release) if previous_release else None
        )
        if not _compensating:
            require_visible_terminal(args)
        if not active.get("rollback_core_restored"):
            stop_service(args)
            for path, flag, name in [
                (args.launcher, "had_wrapper", "launcher.before"),
                (args.plist, "had_plist", "service.before.plist"),
            ]:
                if path == args.plist and args.service == "none":
                    continue
                if active[flag]:
                    saved = backup / name
                    atomic(path, saved.read_bytes(), saved.stat().st_mode & 0o777)
                else:
                    path.unlink(missing_ok=True)
            if active.get("desktop"):
                active["rollback_core_restored"] = True
                active["restored_installed_wrapper_sha256"] = (
                    sha(args.launcher) if args.launcher.exists() else None
                )
                active["restored_installed_plist_sha256"] = (
                    sha(args.plist) if args.plist.exists() else None
                )
                jwrite(backup / "transaction.json", active)
                jwrite(current, active)
    if active["was_loaded"] and (not core_already_restored or not loaded(args)):
        start_service(args)
    if active.get("desktop"):
        desktop_module(args).restore(types.SimpleNamespace(**globals()), active, current)
    if active["was_loaded"] and active.get("previous_version"):
        previous_release = (active.get("previous") or {}).get("release")
        if previous_release:
            wait_health(args, Path(previous_release), active["previous_version"])
        else:
            # An existing manually installed service may have no versioned
            # release record. Its authenticated pre-switch source is the target.
            wait_health(
                args,
                Path(active["release"]),
                active["previous_version"],
                expected_source=active.get("previous_source", {}),
            )
    # Keep the complete active recovery record until every affected component
    # is restored. Desktop failure must not erase its transaction checkpoint.
    if active["previous"]:
        jwrite(current, active["previous"])
    else:
        current.unlink()
    say(
        "ZURÜCKGEROLLT: vorheriger Launcher/Dienst wiederhergestellt. "
        "Konfiguration, Zugangsdaten und neue Ergebnisdaten bleiben erhalten."
    )


def status(args):
    current = args.prefix / "current.json"
    if not current.exists():
        print(json.dumps({"installed_by_versioned_installer": False}), flush=True)
        return
    active = json.loads(current.read_text())
    result = {k: active[k] for k in ("version", "commit", "release")}
    result["config_sha256"] = sha(args.config)
    result["service_managed"] = args.service != "none"
    if args.service != "none":
        result["daemon"] = cli(Path(active["release"]), args.config, "status")
    print(json.dumps(result, indent=2), flush=True)


def _main():
    global LABEL
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "install", "status", "rollback"])
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--ref")
    parser.add_argument("--language", choices=("de", "en"), default="de")
    parser.add_argument("--motion", choices=("auto", "full", "reduced"), default="auto")
    parser.add_argument("--bundle", type=Path, help="Verified extracted release bundle")
    parser.add_argument("--workspace", type=Path, default=Path.home() / "workspace/KiraBridge")
    parser.add_argument(
        "--prefix", type=Path, default=Path.home() / ".local/share/kirabridge/install"
    )
    parser.add_argument(
        "--config", type=Path, default=Path.home() / ".config/kirabridge/config.toml"
    )
    parser.add_argument("--launcher", type=Path, default=Path.home() / ".local/bin/kirabridge")
    parser.add_argument(
        "--plist", type=Path, default=Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"
    )
    parser.add_argument(
        "--service",
        choices=["launchd", "none"],
        default="launchd" if sys.platform == "darwin" else "none",
    )
    parser.add_argument(
        "--cache-dir", type=Path, default=Path.home() / ".cache/kirabridge-installer"
    )
    parser.add_argument(
        "--full-access",
        action="store_true",
        help="Explicit operator grant for fresh config only; never modifies an existing policy",
    )
    parser.add_argument(
        "--test-label", help="Isolated launchd test label; com.kirabridge.test.* only"
    )
    parser.add_argument(
        "--require-visible-terminal",
        action="store_true",
        help="Require a fresh confirmed visible macOS Terminal window before activation",
    )
    parser.add_argument(
        "--desktop",
        action="store_true",
        help="Upgrade the matched desktop app, console and linked ChatGPT service transactionally",
    )
    args = parser.parse_args()
    if args.desktop and (sys.platform != "darwin" or not args.bundle or args.test_label):
        parser.error("--desktop requires a native macOS bundle and the standard user service")
    if args.desktop and args.action == "install" and not args.require_visible_terminal:
        parser.error("--desktop installation requires --require-visible-terminal")
    if args.test_label:
        if not re.fullmatch(r"com\.kirabridge\.test\.[a-z0-9-]{8,64}", args.test_label):
            parser.error("Invalid isolated test label")
        required = ("--prefix", "--config", "--launcher", "--plist", "--cache-dir", "--workspace")
        if not all(flag in sys.argv for flag in required):
            parser.error("--test-label requires explicit isolated paths for all destinations")
        LABEL = args.test_label
    if os.getuid() == 0:
        parser.error("Run as your normal user without sudo")
    if args.require_visible_terminal:
        if args.action not in {"install", "rollback"}:
            parser.error("Visible-terminal verification applies to install or rollback")
        require_visible_terminal(args)
    for name in ("repo", "prefix", "config", "launcher", "plist", "cache_dir"):
        setattr(args, name, getattr(args, name).expanduser().absolute())
    if sys.version_info < (3, 11):
        parser.error("Python 3.11+ is required")

    def interrupted(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    os.umask(0o077)
    if args.action != "status":
        begin_presentation(
            args.bundle or Path(__file__).resolve().parents[1],
            language=args.language,
            motion=args.motion,
        )
        say("KiraBridge · Installation/Update")
    for path in (args.config, args.launcher, args.plist, args.prefix, args.cache_dir):
        validate_destination(path, private=path == args.config)
    private_dir(args.prefix)
    fd = os.open(args.prefix / "install.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action in ("prepare", "install"):
            release = prepare(args)
            if args.action == "install":
                activate(args, release)
        elif args.action == "rollback":
            rollback(args)
        else:
            status(args)
        if PRESENTER is not None:
            # Do not begin a late frame and immediately discard its tail on exit.
            # Real completion is already reported by activate/rollback/prepare.
            PRESENTER.cancel()
            prefix = getattr(PRESENTER, "output_prefix", "")
            if prefix:
                written = sys.stderr.write(prefix)
                if written is not None and written != len(prefix):
                    raise BlockingIOError("Final terminal cleanup not fully accepted")
                sys.stderr.flush()
                PRESENTER.acknowledge_output_prefix()
    finally:
        os.close(fd)


def close_presentation():
    global PRESENTER, OUTPUT_TARGET
    presenter, target = PRESENTER, OUTPUT_TARGET
    PRESENTER, OUTPUT_TARGET = None, None
    try:
        if presenter is not None:
            presenter.cancel()
    finally:
        if target is not None:
            target.close()


def main():
    try:
        _main()
        return 0
    except KeyboardInterrupt:
        presentation_error(
            "ABGEBROCHEN: eigene Build-Unterprozesse gestoppt; Rückweg steht im Transaktionsbackup."
        )
        return 130
    except Exception as exc:
        presentation_error(f"FEHLER: {exc}")
        return 1
    finally:
        close_presentation()


if __name__ == "__main__":
    sys.exit(main())
