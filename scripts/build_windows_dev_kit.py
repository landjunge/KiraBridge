#!/usr/bin/env python3
"""Package a frozen Windows preview only after six matching native reports.

Default is validation/plan only; --build writes one new output directory.
No Windows tests, VM actions, downloads, publication or production installation
are performed here. Guard tests with synthetic reports are not native acceptance.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import stat
import subprocess
import zipfile
from email.parser import BytesParser
from pathlib import Path

VERSION = "0.8.0rc33"
ASSET = f"KiraBridge-{VERSION}-Windows-Dev-Kit.zip"
PHASES = ("core", "keyboard", "mcp", "preview", "shortcuts", "windows")
REUSED_PHASES = ("core", "keyboard", "mcp")
FRESH_PHASES = ("preview", "shortcuts", "windows")
RUNTIME_MODULE_COUNT = 174
REUSED_HARNESSES = (
    "tests/test_windows_core_native.py",
    "scripts/accept_windows_keyboard.py",
    "scripts/accept_windows_mcp.py",
)
REQUIRED_HARNESSES = (
    *REUSED_HARNESSES,
    "scripts/accept_windows_preview.py",
    "scripts/accept_windows_shortcuts.py",
    "scripts/accept_windows_windows.py",
)
ALLOWED_FILE = re.compile(
    r"(?:source\.zip|python-installer\.exe|guest_runner\.ps1|"
    r"wheels/[A-Za-z0-9][A-Za-z0-9._+-]{0,200}\.whl)"
)
PRIVATE_VALUE = re.compile(r"[A-Za-z]:[\\/]|\\\\|/(?:Users|private|tmp|home)/|https?://")
DOCS = (
    "docs/WINDOWS-PREVIEW.md",
    "docs/WINDOWS-DEVELOPMENT-20261103.md",
    "docs/WINDOWS-DESKTOP-20261104.md",
)
# Python.org release reference supplied/verified during the frozen staging run.
# The x64 installer has a bootstrapper, so its outer PE machine alone is not an
# adequate architecture attestation. Anchor the complete vendor installer bytes.
PYTHON_INSTALLERS = {"3.14.10": "92480239264744fe0386a1bd8275786fefa126e3129e56a68e22b52c73329965"}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_path(path: Path) -> Path:
    path = path.expanduser().absolute()
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink():
            raise ValueError("Symlink path component refused")
    return path


def read_owned(path: Path, maximum: int) -> bytes:
    safe_path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as source:
        before = os.fstat(source.fileno())
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid()
            or before.st_size > maximum
        ):
            raise ValueError("Expected a bounded owned regular input")
        data = source.read(maximum + 1)
        after = os.fstat(source.fileno())
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ) or len(data) != before.st_size:
        raise ValueError("Input changed during packaging")
    return data


def no_failure(report):
    if not isinstance(report, dict):
        return False
    if any(report.get(key) for key in ("error", "error_type", "provider_error", "unknown")):
        return False
    return all(
        report.get(key) in (None, "passed", "completed", "success") for key in ("status", "state")
    )


def sanitize(value, key=""):
    """Preserve evidence numbers/structure, remove capability and path strings."""
    if isinstance(value, dict):
        return {
            name: sanitize(item, name)
            for name, item in value.items()
            if name not in ("stdout", "stderr")
        }
    if isinstance(value, list):
        return [sanitize(item, key) for item in value]
    if isinstance(value, str):
        if re.search(r"token|password|secret|authorization|credential", key, re.I):
            return "[redacted]"
        if PRIVATE_VALUE.search(value):
            return "[redacted path or endpoint]"
    return value


def verified_reports(directory: Path, manifest_hash: str, phases=PHASES, *, ignore_preview=False):
    directory = safe_path(directory)
    reports, run_ids = {}, set()
    ignored_preview = None
    for path in sorted(directory.glob("report-*.json")):
        match = re.fullmatch(r"report-([a-f0-9]{32})-(" + "|".join(PHASES) + r")\.json", path.name)
        if not match:
            raise ValueError("Unexpected guest report filename")
        run_id, phase = match.groups()
        if phase not in phases and not (ignore_preview and phase == "preview"):
            raise ValueError("Unexpected phase in the selected evidence directory")
        if phase in reports:
            raise ValueError("Duplicate native phase; explicit reconciliation required")
        raw = read_owned(path, 2 * 1024 * 1024)
        report = json.loads(raw)
        if phase not in phases:
            if (
                ignored_preview is not None
                or report.get("phase") != "preview"
                or report.get("manifest_sha256") != manifest_hash
            ):
                raise ValueError("Ignored old preview is duplicate or belongs to another payload")
            # Reference only. This failed/superseded report never authorizes a
            # phase and is not represented as a successful current execution.
            ignored_preview = {
                "raw_report_sha256": digest(raw),
                "run_id": run_id,
                "accepted_as_passing_phase": False,
            }
            continue
        if (
            report.get("phase") != phase
            or report.get("manifest_sha256") != manifest_hash
            or type(report.get("exit_code")) is not int
            or report["exit_code"] != 0
            or type(report.get("process_id")) is not int
            or report["process_id"] <= 0
            or not no_failure(report)
        ):
            raise ValueError("Native report failed, is uncertain, or belongs to another payload")
        public = {
            "phase": phase,
            "run_id": run_id,
            "exit_code": 0,
            "manifest_sha256": manifest_hash,
            "raw_report_sha256": digest(raw),
            "process_id": report.get("process_id"),
        }
        if phase == "core":
            stdout = report.get("stdout", "")
            if not isinstance(stdout, str) or not re.search(r"(?<!\d)4 passed\b", stdout):
                raise ValueError("Core requires four actually passed tests")
            if re.search(
                r"\b(?:[1-9]\d*\s+(?:skipped|failed|errors?|xfailed|deselected)|SKIPPED)\b", stdout
            ):
                raise ValueError("Skipped or failed core tests cannot authorize a package")
            public["test_counts"] = {"passed": 4, "skipped": 0, "failed": 0}
        else:
            artifact = report.get("artifact")
            if not no_failure(artifact) or artifact.get("passed") is not True:
                raise ValueError("Native artifact did not pass")
            if phase == "keyboard" and artifact.get("platform") != "nt":
                raise ValueError("Keyboard proof must be from native Windows")
            if (
                phase == "preview"
                and artifact.get("independent_original_process_absent") is not True
            ):
                raise ValueError("Preview child cleanup was not independently confirmed")
            public["artifact"] = sanitize(artifact)
            public["raw_artifact_sha256"] = report.get("artifact_sha256")
        reports[phase] = public
        run_ids.add(run_id)
    if set(reports) != set(phases) or len(run_ids) != 1:
        raise ValueError(
            "Exactly six phases of one native guest run are required"
            if phases == PHASES
            else "Exactly the selected phases of one native guest run are required"
        )
    if ignored_preview is not None and ignored_preview["run_id"] not in run_ids:
        raise ValueError("Ignored old preview belongs to a different original run")
    result = {"run_id": next(iter(run_ids)), "phases": [reports[name] for name in phases]}
    if ignored_preview is not None:
        result["ignored_previous_preview"] = ignored_preview
    return result


def normalized(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def public_documentation(archive, source_commit):
    result = {"LICENSE": archive.read("LICENSE")}
    for name in DOCS:
        if name in archive.namelist():
            result[name] = archive.read(name)
        else:
            # Guest archives deliberately omit documentation. Read only these
            # fixed public paths from the same immutable local Git source pin.
            result[name] = subprocess.run(
                ["git", "show", f"{source_commit}:{name}"],
                cwd=Path(__file__).resolve().parents[1],
                check=True,
                capture_output=True,
                timeout=15,
            ).stdout
    return result


def verify_wheels(payload, requirements):
    provided = {}
    for name, data in payload.items():
        if not name.startswith("wheels/"):
            continue
        if not name.endswith(("-win_amd64.whl", "-any.whl")):
            raise ValueError("Only Windows AMD64 or universal wheels may be packaged")
        with zipfile.ZipFile(io.BytesIO(data)) as wheel:
            paths = [p for p in wheel.namelist() if p.endswith(".dist-info/METADATA")]
            if len(paths) != 1:
                raise ValueError("Wheel metadata is ambiguous")
            metadata = BytesParser().parsebytes(wheel.read(paths[0]))
            distribution, version = metadata["Name"], metadata["Version"]
            if not distribution or not version or normalized(distribution) in provided:
                raise ValueError("Invalid or duplicate wheel distribution")
            provided[normalized(distribution)] = version
    pinned = {}
    for item in requirements:
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+!-]+)", item)
        if not match or normalized(match[1]) in pinned:
            raise ValueError("Requirements must uniquely pin every included wheel")
        pinned[normalized(match[1])] = match[2]
    if pinned != provided or pinned.get("kirabridge") != VERSION:
        raise ValueError("Offline wheelhouse does not exactly match all pinned requirements")
    return len(provided)


def frozen_payload(staging: Path, source_commit: str | None = None):
    if source_commit is not None and not re.fullmatch(r"[a-f0-9]{40}", source_commit):
        raise ValueError("Use the full frozen source commit")
    staging = safe_path(staging)
    raw_manifest = read_owned(staging / "manifest.json", 1024 * 1024)
    manifest = json.loads(raw_manifest)
    if (
        set(manifest)
        != {"schema_version", "python_version", "source_commit", "requirements", "files"}
        or manifest["schema_version"] != 1
        or not re.fullmatch(r"[a-f0-9]{40}", manifest["source_commit"])
        or (source_commit is not None and manifest["source_commit"] != source_commit)
        or not re.fullmatch(r"3\.\d+\.\d+", manifest["python_version"])
    ):
        raise ValueError("Manifest schema/source pin is not the frozen preview")
    payload = {}
    for entry in manifest["files"]:
        name = entry.get("path", "")
        if not ALLOWED_FILE.fullmatch(name) or name in payload:
            raise ValueError("Payload is not in the fixed dev-kit allowlist")
        if (
            type(entry.get("bytes")) is not int
            or not 0 < entry["bytes"] <= 512 * 1024 * 1024
            or not re.fullmatch(r"[a-fA-F0-9]{64}", entry.get("sha256", ""))
        ):
            raise ValueError("Invalid payload hash or size")
        data = read_owned(staging / name, entry["bytes"])
        if len(data) != entry["bytes"] or digest(data) != entry["sha256"].lower():
            raise ValueError("Payload differs from native-tested manifest")
        payload[name] = data
    if not {"source.zip", "python-installer.exe", "guest_runner.ps1"} <= payload.keys():
        raise ValueError("Missing a required offline payload")
    if digest(payload["python-installer.exe"]) != PYTHON_INSTALLERS.get(manifest["python_version"]):
        raise ValueError("Python AMD64 installer differs from the verified vendor release")
    wheel_count = verify_wheels(payload, manifest["requirements"])
    with zipfile.ZipFile(io.BytesIO(payload["source.zip"])) as archive:
        if archive.comment != manifest["source_commit"].encode("ascii"):
            raise ValueError("Source archive Git pin differs from native-tested commit")
        files = source_files(payload["source.zip"])
        if any(not files.get(name) for name in REQUIRED_HARNESSES):
            raise ValueError("Source archive is missing a required native acceptance harness")
    return manifest, raw_manifest, payload, wheel_count


def source_files(source_zip):
    with zipfile.ZipFile(io.BytesIO(source_zip)) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate source archive entry")
        return {name: archive.read(name) for name in names if not name.endswith("/")}


def runtime_modules(files, prefix):
    result = {
        name[len(prefix) :]: data
        for name, data in files.items()
        if name.startswith(prefix) and name.endswith(".py")
    }
    if len(result) != RUNTIME_MODULE_COUNT:
        raise ValueError(
            f"Component reuse requires exactly {RUNTIME_MODULE_COUNT} native-tested runtime modules"
        )
    return result


def reuse_components(current, previous):
    manifest, _, payload, _ = current
    old_manifest, _, old_payload, _ = previous
    if (
        manifest["python_version"] != old_manifest["python_version"]
        or manifest["requirements"] != old_manifest["requirements"]
    ):
        raise ValueError("Reused Python version/requirements differ")
    if payload["python-installer.exe"] != old_payload["python-installer.exe"]:
        raise ValueError("Reused Python installer bytes differ")
    wheels = {key: value for key, value in payload.items() if key.startswith("wheels/")}
    old_wheels = {key: value for key, value in old_payload.items() if key.startswith("wheels/")}
    if wheels != old_wheels:
        raise ValueError("Reused offline wheelhouse bytes differ")
    files, old_files = source_files(payload["source.zip"]), source_files(old_payload["source.zip"])
    modules = runtime_modules(files, "src/kirabridge/")
    if modules != runtime_modules(old_files, "src/kirabridge/"):
        raise ValueError("Reused production runtime bytes differ")
    for name in REUSED_HARNESSES:
        if name not in files or files[name] != old_files.get(name):
            raise ValueError("Reused native harness bytes differ")
    runner = "scripts/windows_guest_runner.ps1"
    if (
        payload["guest_runner.ps1"] != old_payload["guest_runner.ps1"]
        or files.get(runner) != payload["guest_runner.ps1"]
        or old_files.get(runner) != old_payload["guest_runner.ps1"]
    ):
        raise ValueError("Reused bootstrap runner bytes differ")
    own = [data for key, data in wheels.items() if key.startswith(f"wheels/kirabridge-{VERSION}-")]
    if len(own) != 1:
        raise ValueError("Expected one native-tested KiraBridge wheel")
    wheel_files = source_files(own[0])
    if runtime_modules(wheel_files, "kirabridge/") != modules:
        raise ValueError("Reused wheel runtime bytes differ from frozen source")
    return {
        "runtime_module_count": RUNTIME_MODULE_COUNT,
        "runtime_module_sha256": {name: digest(body) for name, body in sorted(modules.items())},
        "reused_harness_sha256": {name: digest(files[name]) for name in REUSED_HARNESSES},
        "bootstrap_runner_sha256": digest(payload["guest_runner.ps1"]),
        "python_installer_sha256": digest(payload["python-installer.exe"]),
        "offline_wheelhouse_byte_identical": True,
        "requirements_identical": True,
    }


def prepare(
    staging: Path,
    reports: Path,
    source_commit: str,
    reuse_staging: Path | None = None,
    reuse_reports: Path | None = None,
):
    if (reuse_staging is None) != (reuse_reports is None):
        raise ValueError("Reuse staging and reports must be provided together")
    current = frozen_payload(staging, source_commit)
    manifest, raw_manifest, payload, wheel_count = current
    current_hash = digest(raw_manifest)
    if reuse_staging is None:
        proofs = verified_reports(reports, current_hash)
        for phase in proofs["phases"]:
            phase.update(
                source_commit=source_commit, original_manifest_sha256=current_hash, reused=False
            )
    else:
        previous = frozen_payload(reuse_staging)
        old_manifest, old_raw, _, _ = previous
        # Establish byte provenance BEFORE accepting any reused native phase.
        basis = reuse_components(current, previous)
        old_hash = digest(old_raw)
        old_proofs = verified_reports(reuse_reports, old_hash, REUSED_PHASES, ignore_preview=True)
        new_proofs = verified_reports(reports, current_hash, FRESH_PHASES)
        for phase in old_proofs["phases"]:
            if phase["phase"] != "core" and not re.fullmatch(
                r"[a-f0-9]{64}", phase.get("raw_artifact_sha256") or ""
            ):
                raise ValueError("Reused native phase requires its original artifact hash")
            phase.update(
                source_commit=old_manifest["source_commit"],
                original_manifest_sha256=old_hash,
                reused=True,
            )
        for phase in new_proofs["phases"]:
            if (
                phase["phase"] == "preview"
                and phase["artifact"].get("keyboard_events_requested") != 0
            ):
                raise ValueError("Fresh preview must be read-only with zero requested keys")
            phase.update(
                source_commit=source_commit, original_manifest_sha256=current_hash, reused=False
            )
        proofs = {
            "run_id": new_proofs["run_id"],
            "run_ids": sorted({old_proofs["run_id"], new_proofs["run_id"]}),
            "component_provenance_reuse": True,
            "run_policy": (
                "Three explicitly reused native phases; "
                "preview, shortcuts and windows freshly executed"
            ),
            "reuse_basis": {
                **basis,
                "original_source_commit": old_manifest["source_commit"],
                "original_manifest_sha256": old_hash,
                "current_source_commit": source_commit,
                "ignored_previous_preview": old_proofs.get("ignored_previous_preview"),
            },
            "phases": old_proofs["phases"] + new_proofs["phases"],
        }
    with zipfile.ZipFile(io.BytesIO(payload["source.zip"])) as archive:
        documentation = public_documentation(archive, source_commit)
    proof_bytes = json.dumps(proofs, sort_keys=True, indent=2, ensure_ascii=True).encode() + b"\n"
    package = {
        "name": "KiraBridge Windows Dev Kit",
        "version": VERSION,
        "architecture": "Windows x86_64",
        "source_commit": source_commit,
        "python_version": manifest["python_version"],
        "payload_manifest_sha256": digest(raw_manifest),
        "payload_files": len(payload),
        "offline_wheels": wheel_count,
        "native_guest_phases": list(PHASES),
        "acceptance_reexecuted_by_builder": False,
        "component_provenance_reuse": reuse_staging is not None,
        "acceptance_scope": "Existing matching native guest reports; not remote attestation",
        "supported_preview": [
            "Authenticated local MCP HTTP/stdio",
            "Guarded native keyboard tasks and sequences",
            "Explicit Ctrl/Alt/Shift/Windows shortcuts with owned modifier release",
            "Pinned native window listing, activation, geometry and window-state actions",
            "Regular pinned window close requests without force termination",
            "Fresh target identity and durable no-replay receipts",
        ],
        "unsupported_preview": [
            "Full Windows desktop GUI",
            "General file/process/terminal tools",
            "Windows service installation",
            "External ChatGPT cloud latency acceptance",
        ],
        "windows_os_iso_included": False,
        "mac_production_installation_changed": False,
        "native_proofs_sha256": digest(proof_bytes),
    }
    contents = {
        **payload,
        **documentation,
        "manifest.json": raw_manifest,
        "requirements-win.txt": ("\n".join(manifest["requirements"]) + "\n").encode(),
        "native-acceptance.json": proof_bytes,
        "package.json": json.dumps(package, sort_keys=True, indent=2).encode() + b"\n",
        "README-DE.txt": instructions(manifest["python_version"], source_commit).encode(),
    }
    sums = "".join(f"{digest(data)}  {name}\n" for name, data in sorted(contents.items()))
    contents["SHA256SUMS"] = sums.encode()
    return contents, package


def instructions(python_version: str, source_commit: str):
    compact = "".join(python_version.split(".")[:2])
    return f"""KiraBridge {VERSION} - Windows-Entwicklungspaket (Vorschau)

Quellstand: {source_commit}
Enthaelt Python {python_version} AMD64, alle exakt gepinnten Offline-Wheels,
Quellarchiv, Lizenz und bereinigte native Testnachweise. Kein Windows-Betriebssystem.

1. ZIP vollstaendig in einen eigenen lokalen Ordner entpacken.
2. python-installer.exe oeffnen und nur fuer den eigenen Windows-Benutzer
   installieren. pip einschliessen; PATH und systemweite Installation nicht aendern.
3. PowerShell im entpackten Paketordner oeffnen. Falls Python an einen anderen
   Ort installiert wurde, den ersten Pfad entsprechend anpassen:

$python = "$env:LOCALAPPDATA\\Programs\\Python\\Python{compact}\\python.exe"
& $python -m venv .venv
$previewPython = ".\\.venv\\Scripts\\python.exe"
& $previewPython -m pip install --no-index --find-links .\\wheels -r .\\requirements-win.txt
$stateDir = "$env:LOCALAPPDATA\\KiraBridgePreviewRC33"
& $previewPython -m kirabridge.windows_preview --state-dir $stateDir --port 8767

Das Fenster fuer die Laufzeit offen lassen. Token und eigene Zustandsdateien
werden erst beim Start lokal angelegt; keine privaten Gast-/Mac-Zugaenge liegen bei.
Details zur Verbindung und Bedienung stehen in docs/WINDOWS-PREVIEW.md.
Das Paket installiert keinen Windows-Dienst und keinen Hintergrund-Autostart.

Umfang: lokales authentifiziertes MCP, native Tastatur und Tastenfolgen,
explizite Ctrl-/Alt-/Shift-/Windows-Tastenkombinationen sowie Fenster auflisten,
aktivieren, verschieben, Groesse aendern, minimieren, maximieren,
wiederherstellen und regulaeres Schliessen anfordern. Keine Force-Kills.
Datei-, allgemeine Prozess- und Terminalwerkzeuge sowie eine vollstaendige
Windows-Bedienoberflaeche sind in dieser Vorschau noch nicht freigegeben.
Nur im aktiven eigenen Windows-Desktop benutzen. Ungewisse Eingaben nicht
wiederholen: den bestehenden Task/Receipt lesen. Keine Clipboard-Abkuerzung.

Die beigefuegten Belege stammen aus einem Windows-Entwicklungsgast. Sie ersetzen
keine Abnahme auf jeder Windows-Hardware und keine externe ChatGPT-Cloudmessung.
Pruefsummen pruefen; die Checksummen sind keine unabhaengige Herausgebersignatur.
Python und alle Wheels behalten ihre mitgelieferten Drittanbieterlizenzen.
Fuer KiraBridge gilt die beiliegende LICENSE.
"""


def build(contents, package, out: Path):
    out = safe_path(out)
    if os.path.lexists(out) or not out.parent.is_dir():
        raise ValueError("Output directory must be new with an existing parent")
    out.mkdir(mode=0o700)
    archive = out / ASSET
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        for name, data in sorted(contents.items()):
            info = zipfile.ZipInfo("KiraBridge-Windows-Dev-Kit/" + name, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            output.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)
    os.chmod(archive, 0o600)
    exported = {
        "LICENSE": contents["LICENSE"],
        "native-acceptance.json": contents["native-acceptance.json"],
        "package.json": contents["package.json"],
    }
    for name, data in exported.items():
        with (out / name).open("xb") as file:
            os.chmod(out / name, 0o600)
            file.write(data)
    checksums = {
        ASSET: digest(archive.read_bytes()),
        **{name: digest(data) for name, data in exported.items()},
    }
    with (out / "SHA256SUMS").open("x") as output:
        os.chmod(out / "SHA256SUMS", 0o600)
        output.write("".join(f"{value}  {name}\n" for name, value in sorted(checksums.items())))
    return {
        **package,
        "asset": str(archive),
        "asset_sha256": checksums[ASSET],
        "bytes": archive.stat().st_size,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staging-dir", type=Path, required=True)
    parser.add_argument("--guest-reports-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--reuse-staging-dir", type=Path)
    parser.add_argument("--reuse-reports-dir", type=Path)
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args(argv)
    if (args.reuse_staging_dir is None) != (args.reuse_reports_dir is None):
        parser.error("--reuse-staging-dir and --reuse-reports-dir must be provided together")
    contents, package = prepare(
        args.staging_dir,
        args.guest_reports_dir,
        args.source_commit,
        args.reuse_staging_dir,
        args.reuse_reports_dir,
    )
    print(
        json.dumps(
            build(contents, package, args.out_dir)
            if args.build
            else {**package, "action": "validated_plan_only"},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
