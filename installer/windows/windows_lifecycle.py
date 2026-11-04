"""Private, offline Windows installer transactions and visible preview launcher.

The application lock is held throughout a preview session. No process is killed.
Persistent pending.json supports recovery after installer interruption. User state
is external to the application and is never removed by rollback or uninstall.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

SCHEMA = 1
RELEASE = re.compile(r"[a-f0-9]{32}")


class SetupError(Exception):
    pass


def safe(path):
    path = Path(path).absolute()
    if ".." in path.parts:
        raise SetupError("Parent traversal refused / Übergeordnete Pfade abgelehnt")
    if os.name == "nt":
        if not re.fullmatch(r"[A-Za-z]:", path.drive):
            raise SetupError("Local Windows drive required / Lokales Windows-Laufwerk erforderlich")
        for part in path.parts[1:]:
            relative(part)
    for item in (*reversed(path.parents), path):
        if item.is_symlink() or (
            item.exists() and getattr(item.lstat(), "st_file_attributes", 0) & 0x400
        ):
            raise SetupError("Linked paths refused / Verknüpfte Pfade abgelehnt")
    return path


def read(path):
    safe(path)
    if path.stat().st_size > 2 * 1024 * 1024:
        raise SetupError("Metadata too large / Metadaten zu groß")
    return json.loads(path.read_text(encoding="utf-8"))


def atomic(path, value, *, private=False):
    safe(path)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    body = json.dumps(value, ensure_ascii=True, sort_keys=True).encode()
    try:
        if private:
            from kirabridge.private_files import write_private

            write_private(temporary, body)
        else:
            with temporary.open("xb") as stream:
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextlib.contextmanager
def locked(root):
    root = safe(root)
    root.mkdir(parents=True, exist_ok=True)
    path = safe(root / ".lifecycle.lock")
    with path.open("a+b") as stream:
        stream.seek(0)
        if not stream.read(1):
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise SetupError(
                "KiraBridge is running. Close its console and retry. / "
                "KiraBridge läuft. Bitte seine Konsole schließen und erneut versuchen."
            ) from None
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def relative(name):
    if (
        not isinstance(name, str)
        or not name
        or "\\" in name
        or ":" in name
        or name.startswith("/")
        or "\x00" in name
        or any(p in {"", ".", ".."} for p in name.split("/"))
        or any(p.endswith((".", " ")) for p in name.split("/"))
        or any(
            p.split(".", 1)[0].upper() in {"CON", "PRN", "AUX", "NUL"}
            or re.fullmatch(r"(?:COM|LPT)[1-9]", p.split(".", 1)[0], re.IGNORECASE)
            for p in name.split("/")
        )
    ):
        raise SetupError("Invalid payload path / Ungültiger Paketpfad")
    return Path(*name.split("/"))


def manifest(runtime, *, verify=True, inventory=None):
    result = read(runtime / "runtime-manifest.json") if inventory is None else inventory
    if (
        not isinstance(result, dict)
        or type(result.get("schema_version")) is not int
        or result["schema_version"] != SCHEMA
        or not isinstance(result.get("release_id"), str)
        or not RELEASE.fullmatch(result["release_id"])
    ):
        raise SetupError("Invalid runtime manifest / Ungültiges Laufzeitmanifest")
    version(result.get("version"))
    files = result.get("files")
    if not isinstance(files, dict) or not files or len(files) > 10000:
        raise SetupError("Invalid file manifest / Ungültige Dateiliste")
    folded = set()
    for name, digest in files.items():
        item = safe(runtime / relative(name))
        if (
            name.casefold() in folded
            or name.casefold() == "runtime-manifest.json"
            or not isinstance(digest, str)
            or not re.fullmatch(r"[a-f0-9]{64}", digest)
        ):
            raise SetupError("Ambiguous manifest / Mehrdeutiges Manifest")
        folded.add(name.casefold())
        if verify and (
            not item.is_file() or hashlib.sha256(item.read_bytes()).hexdigest() != digest
        ):
            raise SetupError("Damaged offline package / Beschädigtes Offlinepaket")
    if verify:
        actual = set()
        for path in runtime.rglob("*"):
            safe(path)  # Reject directory links too, before a later copy could follow them.
            if path.is_file():
                actual.add(path.relative_to(runtime).as_posix())
        if actual != set(files) | {"runtime-manifest.json"}:
            raise SetupError("Unexpected runtime files / Unerwartete Laufzeitdateien")
    return result


def version(value):
    match = (
        re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:rc(\d+))?", value) if isinstance(value, str) else None
    )
    if not match:
        raise SetupError("Unsupported version / Nicht unterstützte Version")
    a, b, c, rc = match.groups()
    return (int(a), int(b), int(c), 0 if rc else 1, int(rc or 0))


def validate_pointer(value):
    if (
        not isinstance(value, dict)
        or type(value.get("schema")) is not int
        or value["schema"] != SCHEMA
        or not isinstance(value.get("release"), str)
        or not RELEASE.fullmatch(value["release"])
        or not isinstance(value.get("data_dir"), str)
        or not Path(value["data_dir"]).is_absolute()
    ):
        raise SetupError("Invalid installation pointer / Ungültige Installationsreferenz")
    version(value.get("version", ""))
    safe(value["data_dir"])
    return value


def pointer(root):
    return validate_pointer(read(root / "current.json"))


def runtime_path(root, release):
    if not RELEASE.fullmatch(str(release)):
        raise SetupError("Invalid release identity / Ungültige Versionsreferenz")
    return safe(root / "releases" / release / "Runtime")


def remove_release(root, release, *, inventory=None):
    """Remove only inventoried files; preserve unexpected user-added files."""
    runtime = runtime_path(root, release)
    if not runtime.exists() and inventory is None:
        return
    info = manifest(runtime, verify=False, inventory=inventory)
    if info["release_id"] != release:
        raise SetupError("Release identity mismatch / Versionsreferenz stimmt nicht überein")
    directories = set()
    for name in info["files"]:
        path = safe(runtime / relative(name))
        directories.update(
            parent for parent in path.parents if parent != runtime and runtime in parent.parents
        )
        if path.is_file():
            path.unlink()
    (runtime / "runtime-manifest.json").unlink(missing_ok=True)
    for path in sorted(directories, key=lambda p: len(p.parts), reverse=True):
        safe(path)
        if path.is_dir():
            with contextlib.suppress(OSError):
                path.rmdir()
    for path in (runtime, runtime.parent, runtime.parent.parent):
        with contextlib.suppress(OSError):
            path.rmdir()


def smoke(runtime):
    completed = subprocess.run(
        [
            str(runtime / "python.exe"),
            "-I",
            "-B",
            "-c",
            "import kirabridge,struct; from kirabridge.windows_preview import prepare; "
            "from kirabridge.mcp_gateway.http import create_http_app; "
            "assert kirabridge.__version__ == '0.8.0rc33'; assert struct.calcsize('P') == 8",
        ],
        cwd=runtime,
        capture_output=True,
        timeout=60,
        check=False,
    )
    if completed.returncode:
        raise SetupError("Runtime validation failed / Laufzeitprüfung fehlgeschlagen")


def journal(root, transaction=None):
    result = read(root / "pending.json")
    if (
        not isinstance(result, dict)
        or type(result.get("schema")) is not int
        or result["schema"] != SCHEMA
        or result.get("kind") not in {"install", "uninstall"}
        or not isinstance(result.get("id"), str)
        or not RELEASE.fullmatch(result["id"])
    ):
        raise SetupError("Invalid pending transaction / Ungültige offene Transaktion")
    if result["kind"] == "install":
        current = validate_pointer(result.get("next"))
        if result.get("previous") is not None:
            validate_pointer(result["previous"])
        if (
            current["release"] != result.get("release")
            or type(result.get("created_release")) is not bool
        ):
            raise SetupError("Invalid pending release / Ungültige offene Versionsreferenz")
        info = manifest(
            runtime_path(root, result["release"]), verify=False, inventory=result.get("inventory")
        )
        if info["release_id"] != current["release"] or info["version"] != current["version"]:
            raise SetupError("Pending inventory mismatch / Offene Dateiliste stimmt nicht überein")
    if transaction is not None and read(transaction).get("id") != result.get("id"):
        raise SetupError("Transaction mismatch / Transaktion stimmt nicht überein")
    return result


def rollback(root, transaction=None):
    if not (root / "pending.json").exists():
        return
    pending = journal(root, transaction)
    if pending["kind"] == "install":
        old = pending.get("previous")
        if old is None:
            (root / "current.json").unlink(missing_ok=True)
        else:
            atomic(root / "current.json", old)
        if pending.get("created_release"):
            remove_release(root, pending["release"], inventory=pending.get("inventory"))
    (root / "pending.json").unlink()


def prepare(root, source, transaction, data_dir=None):
    if (root / "pending.json").exists():
        rollback(root)  # Recover a prior interrupted installer, under the application lock.
    source = safe(source)
    info = manifest(source)
    previous = pointer(root) if (root / "current.json").exists() else None
    if previous and version(previous["version"]) > version(info["version"]):
        raise SetupError("Downgrade refused / Installation einer älteren Version abgelehnt")
    if previous:
        if data_dir and safe(data_dir) != safe(previous["data_dir"]):
            raise SetupError(
                "Existing data location preserved / Vorhandener Datenpfad bleibt erhalten"
            )
        data_dir = previous["data_dir"]
    elif data_dir is None:
        local = os.environ.get("LOCALAPPDATA")
        if not local:
            raise SetupError("LOCALAPPDATA unavailable / LOCALAPPDATA nicht verfügbar")
        data_dir = Path(local) / "KiraBridge" / "Data"
    data = safe(data_dir)
    if data == root or root in data.parents or data in root.parents:
        raise SetupError(
            "Choose separate application/data paths / Programm und Daten separat speichern"
        )
    data_configuration(data)  # Validate ACL/config before touching the current installation.
    destination = runtime_path(root, info["release_id"])
    created = not destination.exists()
    identifier = uuid.uuid4().hex
    atomic(transaction, {"id": identifier})
    pending = {
        "schema": SCHEMA,
        "kind": "install",
        "id": identifier,
        "previous": previous,
        "release": info["release_id"],
        "created_release": created,
        "inventory": info,
        "next": {
            "schema": SCHEMA,
            "release": info["release_id"],
            "version": info["version"],
            "data_dir": str(data),
        },
    }
    atomic(root / "pending.json", pending)
    try:
        if created:
            destination.mkdir(parents=True)
            # Inventory exists in the durable journal before any directory/file is
            # created. Recovery can remove a partial copy even without this file.
            atomic(destination / "runtime-manifest.json", info)
            for name in info["files"]:
                target = safe(destination / relative(name))
                target.parent.mkdir(parents=True, exist_ok=True)
                with (
                    safe(source / relative(name)).open("rb") as original,
                    target.open("xb") as output,
                ):
                    shutil.copyfileobj(original, output)
        manifest(destination)
        smoke(destination)
    except BaseException:
        rollback(root, transaction)
        raise


def commit(root, transaction):
    pending = journal(root, transaction)
    if pending["kind"] != "install":
        raise SetupError("Not an install transaction / Keine Installationstransaktion")
    manifest(runtime_path(root, pending["release"]))
    atomic(root / "current.json", pending["next"])


def finalize(root, transaction):
    pending = journal(root, transaction)
    if pending["kind"] != "install" or pointer(root) != pending["next"]:
        raise SetupError("Installation was not committed / Installation nicht übernommen")
    (root / "pending.json").unlink()


def data_configuration(data):
    from kirabridge.bridge_core.config import private_directory
    from kirabridge.private_files import private_json

    data = safe(data)
    private_directory(data)
    config_path = data / "installer-config.json"
    if not config_path.exists():
        atomic(config_path, {"schema": SCHEMA, "port": 8768}, private=True)
    config = private_json(config_path)
    if (
        not isinstance(config, dict)
        or set(config) != {"schema", "port"}
        or type(config["schema"]) is not int
        or config["schema"] != SCHEMA
        or type(config["port"]) is not int
        or not 1024 <= config["port"] <= 65535
    ):
        raise SetupError(
            "Invalid configuration preserved / Ungültige Konfiguration bleibt erhalten"
        )
    return data, config


def configuration(root):
    current = pointer(root)
    data, config = data_configuration(current["data_dir"])
    return current, data, config


def execute(args):
    root = safe(args.install_dir)
    with locked(root):
        command = args.action
        if command == "prepare":
            prepare(root, args.runtime_dir, safe(args.transaction), args.data_dir)
        elif command == "commit":
            commit(root, safe(args.transaction))
        elif command in {"rollback", "recover"}:
            rollback(root, safe(args.transaction) if args.transaction else None)
        elif command == "finalize":
            finalize(root, safe(args.transaction))
        elif command == "preflight-uninstall":
            if (root / "pending.json").exists():
                rollback(root)
            atomic(
                root / "pending.json",
                {"schema": SCHEMA, "kind": "uninstall", "id": uuid.uuid4().hex},
            )
        elif command == "cancel-uninstall":
            if (root / "pending.json").exists() and journal(root)["kind"] == "uninstall":
                (root / "pending.json").unlink()
        elif command == "uninstall":
            if journal(root)["kind"] != "uninstall":
                raise SetupError("Uninstall preflight required / Deinstallationsprüfung fehlt")
            releases = root / "releases"
            if releases.exists():
                for entry in releases.iterdir():
                    if RELEASE.fullmatch(entry.name):
                        remove_release(root, entry.name)
            (root / "current.json").unlink(missing_ok=True)
            (root / "pending.json").unlink()
        else:
            if (root / "pending.json").exists():
                raise SetupError(
                    "Setup interrupted. Run Setup again. / "
                    "Setup unterbrochen. Setup erneut starten."
                )
            current, data, config = configuration(root)
            if command == "configure":
                if args.port is None or not 1024 <= args.port <= 65535:
                    raise SetupError("Port must be 1024–65535 / Port muss 1024–65535 sein")
                config["port"] = args.port
                atomic(data / "installer-config.json", config, private=True)
            if command in {"configure", "status"}:
                print(
                    json.dumps(
                        {
                            "version": current["version"],
                            "port": config["port"],
                            "data_dir": str(data),
                            "endpoint": f"http://127.0.0.1:{config['port']}/mcp",
                        }
                    )
                )
            elif command == "run":
                import asyncio

                from kirabridge.windows_preview import prepare as preview_prepare
                from kirabridge.windows_preview import serve

                print(
                    f"KiraBridge {current['version']} — http://127.0.0.1:{config['port']}/mcp",
                    flush=True,
                )
                print(
                    "Close this console to stop / Zum Beenden diese Konsole schließen", flush=True
                )
                asyncio.run(serve(preview_prepare(data, port=config["port"]), "http"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=(
            "prepare",
            "commit",
            "rollback",
            "finalize",
            "recover",
            "preflight-uninstall",
            "uninstall",
            "cancel-uninstall",
            "run",
            "status",
            "configure",
        ),
    )
    parser.add_argument("--install-dir", type=Path, required=True)
    parser.add_argument("--runtime-dir", type=Path)
    parser.add_argument("--transaction", type=Path)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--port", type=int)
    args = parser.parse_args(argv)
    if args.action == "prepare" and (args.runtime_dir is None or args.transaction is None):
        parser.error("prepare requires --runtime-dir and --transaction")
    if args.action in {"commit", "finalize"} and args.transaction is None:
        parser.error("commit/finalize requires --transaction")
    try:
        execute(args)
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        # No credentials, subprocess output or unrestricted exception text in setup logs.
        code = getattr(error, "code", None)
        message = (
            str(error)
            if isinstance(error, SetupError)
            else (
                code
                if isinstance(code, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,79}", code)
                else type(error).__name__
            )
        )
        print(f"KiraBridge: {message}. Data preserved / Daten bleiben erhalten.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
