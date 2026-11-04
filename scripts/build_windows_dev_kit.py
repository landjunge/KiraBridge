#!/usr/bin/env python3
"""Package a frozen Windows preview only after four matching native reports.

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

VERSION = "0.8.0rc31.dev2"
ASSET = f"KiraBridge-{VERSION}-Windows-Dev-Kit.zip"
PHASES = ("core", "keyboard", "mcp", "preview")
ALLOWED_FILE = re.compile(
    r"(?:source\.zip|python-installer\.exe|guest_runner\.ps1|"
    r"wheels/[A-Za-z0-9][A-Za-z0-9._+-]{0,200}\.whl)"
)
PRIVATE_VALUE = re.compile(r"[A-Za-z]:[\\/]|\\\\|/(?:Users|private|tmp|home)/|https?://")
DOCS = ("docs/WINDOWS-PREVIEW.md", "docs/WINDOWS-DEVELOPMENT-20261103.md")
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
    return report.get("status") in (None, "passed", "completed", "success") and report.get(
        "state"
    ) not in ("started", "unknown", "failed", "error")


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


def verified_reports(directory: Path, manifest_hash: str):
    directory = safe_path(directory)
    reports, run_ids = {}, set()
    for path in sorted(directory.glob("report-*.json")):
        match = re.fullmatch(r"report-([a-f0-9]{32})-(core|keyboard|mcp|preview)\.json", path.name)
        if not match:
            raise ValueError("Unexpected guest report filename")
        run_id, phase = match.groups()
        if phase in reports:
            raise ValueError("Duplicate native phase; explicit reconciliation required")
        raw = read_owned(path, 2 * 1024 * 1024)
        report = json.loads(raw)
        if (
            report.get("phase") != phase
            or report.get("manifest_sha256") != manifest_hash
            or type(report.get("exit_code")) is not int
            or report["exit_code"] != 0
            or not no_failure(report)
        ):
            raise ValueError("Native report failed, is uncertain, or belongs to another payload")
        public = {
            "phase": phase,
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
    if set(reports) != set(PHASES) or len(run_ids) != 1:
        raise ValueError("Exactly four phases of one native guest run are required")
    return {"run_id": next(iter(run_ids)), "phases": [reports[name] for name in PHASES]}


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


def prepare(staging: Path, reports: Path, source_commit: str):
    if not re.fullmatch(r"[a-f0-9]{40}", source_commit):
        raise ValueError("Use the full frozen source commit")
    staging = safe_path(staging)
    raw_manifest = read_owned(staging / "manifest.json", 1024 * 1024)
    manifest = json.loads(raw_manifest)
    if (
        set(manifest)
        != {"schema_version", "python_version", "source_commit", "requirements", "files"}
        or manifest["schema_version"] != 1
        or manifest["source_commit"] != source_commit
        or not re.fullmatch(r"3\.\d+\.\d+", manifest["python_version"])
    ):
        raise ValueError("Manifest schema/source pin is not the frozen preview")
    proofs = verified_reports(reports, digest(raw_manifest))
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
        if archive.comment != source_commit.encode("ascii"):
            raise ValueError("Source archive Git pin differs from native-tested commit")
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
        "acceptance_scope": "Existing matching native guest reports; not remote attestation",
        "supported_preview": [
            "Authenticated local MCP HTTP/stdio",
            "Guarded native keyboard tasks and sequences",
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
$stateDir = "$env:LOCALAPPDATA\\KiraBridgeWindowsPreview"
& $previewPython -m kirabridge.windows_preview --state-dir $stateDir --port 8765

Das Fenster fuer die Laufzeit offen lassen. Token und eigene Zustandsdateien
werden erst beim Start lokal angelegt; keine privaten Gast-/Mac-Zugaenge liegen bei.
Details zur Verbindung und Bedienung stehen in docs/WINDOWS-PREVIEW.md.
Das Paket installiert keinen Windows-Dienst und keinen Hintergrund-Autostart.

Umfang: lokales authentifiziertes MCP sowie native Tastatur und Tastenfolgen.
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
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args(argv)
    contents, package = prepare(args.staging_dir, args.guest_reports_dir, args.source_commit)
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
