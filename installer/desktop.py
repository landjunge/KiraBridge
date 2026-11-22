"""Optional desktop transaction; called only by the manifest-verified installer."""

import hashlib
import json
import os
import plistlib
import re
import signal
import stat
import subprocess
import time
from pathlib import Path

SENDER = "integrations/chat-events/serve.py"


def release_argv(api, args, release, name, argv=None):
    """Service command pinned to this release venv; chat-events keeps its own options."""
    runtime = str(api.python(release))
    if name == "chat-events":
        return [runtime, str(release / "source" / SENDER), *argv[2:]]
    command = {"approvals": ["approval-server"], "grok-app": ["grok-connector", "serve"]}
    return [runtime, "-m", "kirabridge.cli", "--config", str(args.config), *command[name]]


def _run_readiness_probe(api, argv, *, label, timeout):
    """Run a read-only authenticated readiness check with a safe, named failure."""
    try:
        api.run(argv, capture=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"{label} readiness timed out") from None
    except (OSError, RuntimeError):
        raise RuntimeError(f"{label} readiness probe failed") from None


def _private_record_path(path, *, directory):
    """Require an owner-private, non-symlink path before trusting release records."""
    path = Path(path)
    if path.is_symlink() or not path.exists():
        return False
    info = path.lstat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        return False
    if directory and not stat.S_ISDIR(info.st_mode):
        return False
    if not directory and not stat.S_ISREG(info.st_mode):
        return False
    for parent in path.parents:
        if parent.is_symlink():
            return False
    return True


def _verified_previous_approvals(api, args, previous, expected_source):
    """Return a prior plist interpreter path only with static source/record proof."""
    if not isinstance(previous, dict) or not isinstance(expected_source, dict):
        return None
    try:
        version = previous.get("version")
        commit = previous.get("commit")
        source_commit = previous.get("source_commit")
        if (
            not isinstance(version, str)
            or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:(?:a|b|rc)[0-9]+)?", version)
            or not isinstance(commit, str)
            or not re.fullmatch(r"[a-f0-9]{40}", commit)
            or source_commit != commit
        ):
            return None

        prefix = Path(args.prefix).resolve(strict=True)
        release = prefix / "releases" / f"{version}-{commit[:12]}"
        if previous.get("release") != str(release):
            return None
        if not _private_record_path(prefix, directory=True):
            return None
        if not _private_record_path(prefix / "releases", directory=True):
            return None
        if not _private_record_path(release, directory=True):
            return None

        manifest_path = release / "release.json"
        if not _private_record_path(manifest_path, directory=False):
            return None
        manifest = json.loads(manifest_path.read_text())
        files = manifest.get("files")
        modes = manifest.get("file_modes")
        if (
            manifest.get("version") != version
            or manifest.get("commit") != commit
            or manifest.get("source_commit") != source_commit
            or not isinstance(files, dict)
            or not files
            or not isinstance(modes, dict)
            or set(modes) != set(files)
            or previous.get("files") != files
            or previous.get("file_modes") != modes
            or any(
                not isinstance(name, str)
                or not isinstance(checksum, str)
                or not re.fullmatch(r"[a-f0-9]{64}", checksum)
                or type(modes[name]) is not int
                or not 0 <= modes[name] <= 0o777
                for name, checksum in files.items()
            )
        ):
            return None
        for name, checksum in files.items():
            member = api.bundle_member(release, name)
            if (
                api.sha(member) != checksum
                or stat.S_IMODE(member.stat().st_mode) != modes[name]
            ):
                return None

        backup = Path(previous.get("backup", ""))
        if (
            backup.parent != prefix / "backups"
            or not _private_record_path(prefix / "backups", directory=True)
            or not _private_record_path(backup, directory=True)
        ):
            return None
        transaction_path = backup / "transaction.json"
        if not _private_record_path(transaction_path, directory=False):
            return None
        transaction = json.loads(transaction_path.read_text())
        if any(
            transaction.get(key) != value
            for key, value in {
                "release": str(release),
                "backup": str(backup),
                "version": version,
                "commit": commit,
                "source_commit": source_commit,
                "files": files,
                "file_modes": modes,
            }.items()
        ):
            return None

        runtime = Path(api.python(release))
        venv = Path(api.release_venv(release))
        venv_config = venv / "pyvenv.cfg"
        if (
            runtime != release / "source/.venv/bin/python"
            or not runtime.is_symlink()
            or venv.is_symlink()
            or release not in venv.parents
            or not runtime.is_file()
            or not _private_record_path(runtime.parent, directory=True)
            or venv_config.is_symlink()
            or not venv_config.is_file()
        ):
            return None

        venv_metadata = {}
        for line in venv_config.read_text().splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                venv_metadata[key.strip()] = value.strip()
        version = venv_metadata.get("version_info", "")
        if (
            venv_metadata.get("implementation") != "CPython"
            or venv_metadata.get("include-system-site-packages") != "false"
            or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version)
            or not venv_metadata.get("home")
        ):
            return None
        base_home = Path(venv_metadata["home"]).resolve(strict=True)
        base_python = runtime.resolve(strict=True)
        if (
            not base_home.is_dir()
            or base_home.parent not in base_python.parents
            or not stat.S_ISREG(base_python.stat().st_mode)
            or not base_python.stat().st_mode & 0o111
            or not re.fullmatch(
                r"python" + re.escape(".".join(version.split(".")[:2])), base_python.name
            )
        ):
            return None

        package_value = expected_source.get("source_package_path")
        expected_hash = expected_source.get("source_tree_sha256")
        expected_count = expected_source.get("source_file_count")
        if (
            not isinstance(package_value, str)
            or not Path(package_value).is_absolute()
            or not isinstance(expected_hash, str)
            or not re.fullmatch(r"[a-f0-9]{64}", expected_hash)
            or type(expected_count) is not int
            or expected_count <= 0
        ):
            return None
        package = Path(package_value)
        if package.resolve(strict=True) != package or venv not in package.parents:
            return None
        if any(path.is_symlink() for path in package.rglob("*")):
            return None
        observed_source = api.source_tree_identity(package)
        if any(observed_source.get(key) != expected_source.get(key) for key in api.SOURCE_FIELDS):
            return None
        return runtime
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, AttributeError):
        return None


def files(root):
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise RuntimeError("Desktop app symlink refused")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return result


def job(api, label, *, path=None, definition=None):
    target = f"gui/{os.getuid()}/{label}"
    result = subprocess.run(
        ["/bin/launchctl", "print", target], capture_output=True, text=True, timeout=10
    )
    if result.returncode not in (0, 113):
        raise RuntimeError("Cannot inspect desktop service: " + label)
    if result.returncode == 0 and path is not None:
        recorded = re.search(r"(?m)^\s*path = (.+)$", result.stdout)
        program = re.search(r"(?m)^\s*program = (.+)$", result.stdout)
        arguments = re.search(r"(?ms)^\s*arguments = \{\n(.*?)^\s*\}", result.stdout)
        expected = (definition or {}).get("ProgramArguments", [])
        if (
            not recorded
            or Path(recorded[1].strip('"')) != path
            or not expected
            or not program
            or program[1].strip() != expected[0]
            or not arguments
            or [line.strip() for line in arguments[1].splitlines() if line.strip()] != expected
        ):
            raise RuntimeError("Loaded desktop service differs from expected definition; preserved")
    return result.returncode == 0


def stop(api, label, *, path=None, definition=None):
    if job(api, label, path=path, definition=definition):
        api.run(
            ["/bin/launchctl", "bootout", f"gui/{os.getuid()}/{label}"], capture=True, timeout=30
        )


def start(api, path):
    # Reuse the existing bounded bootstrap/EIO settling contract.
    from types import SimpleNamespace

    api.start_service(SimpleNamespace(service="launchd", plist=path))


def app_processes(app):
    """Bind executable plus OS process birth observation, not PID alone."""
    output = subprocess.check_output(["/bin/ps", "-axo", "pid=,lstart=,comm="], text=True)
    executable = str(app / "Contents/MacOS/KiraBridge")
    result = []
    for line in output.splitlines():
        parts = line.strip().split(None, 6)
        if len(parts) == 7 and parts[6] == executable:
            result.append({"pid": int(parts[0]), "started": " ".join(parts[1:6])})
    return result


def verified_existing_app_commit(app):
    """Return the recorded source commit for a valid, signed KiraBridge app."""
    info = app / "Contents/Info.plist"
    if app.is_symlink() or info.is_symlink() or not info.is_file():
        return None
    try:
        metadata = plistlib.loads(info.read_bytes())
    except (OSError, ValueError, plistlib.InvalidFileException):
        return None
    commit = metadata.get("KiraBridgeSourceCommit")
    if (
        metadata.get("CFBundleIdentifier") != "de.netzwerkpunkt.kirabridge"
        or not isinstance(commit, str)
        or not re.fullmatch(r"[a-f0-9]{40}", commit)
    ):
        return None
    verified = subprocess.run(
        ["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)],
        capture_output=True,
        timeout=30,
    )
    return commit if verified.returncode == 0 else None


def stop_app(app):
    for process in app_processes(app):
        pid = process["pid"]
        if process not in app_processes(app):
            raise RuntimeError("Desktop app process identity changed")
        os.kill(pid, signal.SIGTERM)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if process not in app_processes(app):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("Desktop app did not close; no replacement")


def start_app(api, app):
    api.run(["/usr/bin/open", str(app)], capture=True, timeout=15)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        observed = app_processes(app)
        if observed:
            return observed
        time.sleep(0.2)
    raise RuntimeError("Desktop application startup not observed")


def snapshot(api, args, release, old, backup):
    home = Path.home()
    if args.service != "launchd" or api.LABEL != "com.kirabridge.bridge":
        raise RuntimeError("Desktop installation requires the standard macOS user service")
    manifest = json.loads((release / "release.json").read_text())
    if not manifest.get("native_app_required"):
        raise RuntimeError("Desktop installation requires the exact native app package")
    app = home / "Applications/KiraBridge.app"
    api.validate_destination(app)
    app_before = files(app) if app.exists() else None
    app_before_commit = None
    app_before_drift = False
    if app_before is not None:
        expected = {
            k.removeprefix("native/KiraBridge.app/"): v
            for k, v in (old or {}).get("files", {}).items()
            if k.startswith("native/KiraBridge.app/")
        }
        if not expected or app_before != expected:
            app_before_commit = verified_existing_app_commit(app)
            if app_before_commit is None:
                raise RuntimeError(
                    "Existing desktop app differs from recorded installation; preserved"
                )
            app_before_drift = True
    state = {
        "app": str(app),
        "app_before": app_before,
        "app_before_source_commit": app_before_commit,
        "app_before_manifest_drift": app_before_drift,
        "app_was_running": bool(app_processes(app)),
        "services": [],
    }
    for name in ("approvals", "chatgpt", "grok-app", "chat-events"):
        label = "com.kirabridge." + name
        path = home / "Library/LaunchAgents" / (label + ".plist")
        api.validate_destination(path)
        exists = path.exists()
        if name != "approvals" and not exists:
            continue  # Never create an account/profile or optional service during an upgrade.
        definition = plistlib.loads(path.read_bytes()) if exists else None
        if definition:
            argv = definition.get("ProgramArguments")
            if definition.get("Label") != label:
                raise RuntimeError("Unexpected desktop service label; preserved")
            if name == "approvals":
                allowed = {str(api.python(release))}
                if old:
                    allowed.add(str(api.python(Path(old["release"]))))
                if (
                    not isinstance(argv, list)
                    or not argv
                    or argv[1:] != release_argv(api, args, release, name)[1:]
                ):
                    raise RuntimeError("Existing console service differs; preserved")
                if argv[0] not in allowed and old:
                    previous_runtime = _verified_previous_approvals(
                        api, args, old.get("previous"), old.get("previous_source")
                    )
                    if previous_runtime is not None:
                        allowed.add(str(previous_runtime))
                if argv[0] not in allowed:
                    raise RuntimeError("Existing console service differs; preserved")
            elif name != "chatgpt":
                # Older setups ran these from a development checkout; any absolute
                # interpreter is moved to the release venv, the command must match.
                if (
                    not isinstance(argv, list)
                    or len(argv) < 2
                    or not all(isinstance(value, str) for value in argv)
                    or not argv[0].startswith("/")
                    or (
                        name == "grok-app"
                        and argv[1:] != release_argv(api, args, release, name)[1:]
                    )
                    or (
                        name == "chat-events"
                        and (
                            Path(argv[1]).parts[-3:] != Path(SENDER).parts
                            or argv[2:4] != ["--config", str(args.config)]
                            or "--sender-only" not in argv
                        )
                    )
                ):
                    raise RuntimeError(f"Existing {name} service differs; preserved")
                if name == "chat-events" and not (release / "source" / SENDER).is_file():
                    raise RuntimeError("Release lacks the completion sender; preserved")
            else:
                api.run(
                    [
                        api.python(release),
                        "-c",
                        "from kirabridge.chatgpt_service import ensure_chatgpt_service; "
                        "from kirabridge.setup_dependencies import local_client; "
                        "import pathlib,sys; p=pathlib.Path(sys.argv[1]); "
                        "b=local_client(p); "
                        "assert b, 'Existing ChatGPT tunnel client missing'; "
                        "ensure_chatgpt_service(p, b, dry_run=True)",
                        str(args.config),
                    ],
                    capture=True,
                    timeout=15,
                )
        was_loaded = job(api, label, path=path, definition=definition)
        if was_loaded and not exists:
            raise RuntimeError("Loaded desktop service has no expected definition; preserved")
        if exists:
            api.snapshot_file(path, backup, name + ".before.plist")
        state["services"].append(
            {
                "name": name,
                "label": label,
                "path": str(path),
                "existed": exists,
                "before_sha256": api.sha(path) if exists else None,
                "was_loaded": was_loaded,
                "changed": False,
            }
        )
    return state


def save(api, current, active):
    api.jwrite(Path(active["backup"]) / "transaction.json", active)
    api.jwrite(current, active)


def activate(api, args, release, active, current):
    state = active["desktop"]
    backup = Path(active["backup"])
    app = Path(state["app"])
    if (files(app) if app.exists() else None) != state["app_before"]:
        raise RuntimeError("Desktop app changed during installation; preserved")
    for row in state["services"]:
        path = Path(row["path"])
        if (api.sha(path) if path.exists() else None) != row["before_sha256"]:
            raise RuntimeError("Desktop service changed during installation; preserved")
    # Stage and verify before stopping anything. copy_native rechecks every byte.
    staged = backup / "app-stage"
    api.copy_native(release, staged, active)
    source = staged / "native/KiraBridge.app"
    api.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(source)], capture=True)
    state["app_expected"] = files(source)
    state["app_stopping"] = True
    save(api, current, active)
    stop_app(app)
    app.parent.mkdir(parents=True, exist_ok=True)
    state["app_mutating"] = True
    save(api, current, active)
    if app.exists():
        app.rename(backup / "desktop.before.app")
    source.rename(app)
    state["app_installed"] = files(app)
    save(api, current, active)
    for row in state["services"]:
        path = Path(row["path"])
        api.validate_destination(path)
        if (api.sha(path) if path.exists() else None) != row["before_sha256"]:
            raise RuntimeError("Desktop service changed during installation; preserved")
        row["changed"] = True
        save(api, current, active)
        current_definition = plistlib.loads(path.read_bytes()) if path.exists() else None
        stop(api, row["label"], path=path, definition=current_definition)
        if row["name"] != "chatgpt":
            definition = (
                plistlib.loads((backup / (row["name"] + ".before.plist")).read_bytes())
                if row["existed"]
                else {
                    "Label": row["label"],
                    "RunAtLoad": True,
                    "KeepAlive": {"SuccessfulExit": False},
                    "ThrottleInterval": 3,
                    "Umask": 0o077,
                    "ProcessType": "Background",
                    "EnvironmentVariables": {
                        "HOME": str(Path.home()),
                        "PATH": "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
                    },
                }
            )
            definition["ProgramArguments"] = release_argv(
                api, args, release, row["name"], definition.get("ProgramArguments")
            )
            if "WorkingDirectory" in definition:
                definition["WorkingDirectory"] = str(release / "source")
            api.atomic(path, plistlib.dumps(definition))
        else:
            definition = plistlib.loads(path.read_bytes())
            api.run(
                [
                    api.python(release),
                    "-c",
                    "from kirabridge.chatgpt_service import ensure_chatgpt_service; "
                    "import pathlib,sys; "
                    "ensure_chatgpt_service(pathlib.Path(sys.argv[1]), sys.argv[2])",
                    str(args.config),
                    definition["ProgramArguments"][0],
                ],
                capture=True,
                timeout=15,
            )
        row["installed_sha256"] = api.sha(path)
        save(api, current, active)
        start(api, path)
    # Authenticated console probe; does not print a login ticket or open a browser.
    _run_readiness_probe(
        api,
        [
            api.python(release),
            "-c",
            "from kirabridge.console_runtime import console_key,probe; "
            "import pathlib,httpx,sys,time; "
            "key=console_key(pathlib.Path(sys.argv[1])); deadline=time.monotonic()+30\n"
            "with httpx.Client(trust_env=False,timeout=2) as c:\n"
            " while probe(c,key) is None:\n"
            "  if time.monotonic()>=deadline: raise RuntimeError('Console readiness timeout')\n"
            "  time.sleep(.2)\n",
            str(args.config),
        ],
        label="approval console",
        timeout=35,
    )
    if any(row["name"] == "chatgpt" for row in state["services"]):
        _run_readiness_probe(
            api,
            [
                api.python(release),
                "-c",
                "from kirabridge.chatgpt_setup import wait_for_tunnel_readiness; "
                "from kirabridge.setup_dependencies import local_client; "
                "import pathlib,sys; p=pathlib.Path(sys.argv[1]); "
                "b=local_client(p); wait_for_tunnel_readiness(b,p,timeout=75)\n",
                str(args.config),
            ],
            label="ChatGPT tunnel",
            timeout=95,
        )
    state["app_started"] = start_app(api, app)
    save(api, current, active)


def restore(api, active, current=None):
    state = active.get("desktop")
    if not state:
        return
    backup = Path(active["backup"])
    for row in reversed(state["services"]):
        if not row["changed"]:
            continue
        path = Path(row["path"])
        expected = (
            row["before_sha256"]
            if row.get("restored")
            else row.get("installed_sha256", row["before_sha256"])
        )
        if (api.sha(path) if path.exists() else None) != expected:
            raise RuntimeError("Desktop service changed after activation; recovery preserved")
        definition = plistlib.loads(path.read_bytes()) if path.exists() else None
        if not row.get("restored"):
            stop(api, row["label"], path=path, definition=definition)
            if row["existed"]:
                saved = backup / (row["name"] + ".before.plist")
                api.atomic(path, saved.read_bytes(), saved.stat().st_mode & 0o777)
            else:
                path.unlink(missing_ok=True)
            row["restored"] = True
            if current is not None:
                save(api, current, active)
        if row["was_loaded"] and not job(
            api,
            row["label"],
            path=path,
            definition=(plistlib.loads(path.read_bytes()) if path.exists() else None),
        ):
            start(api, path)
    if state.get("app_mutating"):
        app = Path(state["app"])
        previous = backup / "desktop.before.app"
        observed = files(app) if app.exists() else None
        before = state.get("app_before")
        # An interruption just after the intent checkpoint can precede the
        # first rename. The untouched old app is already the desired state.
        if not previous.exists() and observed == before:
            if state.get("app_was_running") and not app_processes(app):
                start_app(api, app)
            return
        if before is not None and not previous.exists():
            raise RuntimeError("Desktop app backup missing; recovery preserved")
        if previous.exists() and files(previous) != before:
            raise RuntimeError("Desktop app backup changed; recovery preserved")
        if app.exists():
            if observed != state.get("app_installed", state.get("app_expected")):
                raise RuntimeError("Desktop app changed after activation; recovery preserved")
            stop_app(app)
            app.rename(backup / "desktop.failed.app")
        if previous.exists():
            previous.rename(app)
        elif before is not None:
            raise RuntimeError("Desktop app backup missing; recovery preserved")
        if state.get("app_was_running"):
            start_app(api, app)
    elif state.get("app_stopping") and state.get("app_was_running"):
        app = Path(state["app"])
        if not app_processes(app):
            start_app(api, app)
