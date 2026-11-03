#!/usr/bin/env python3
"""Prepare one new, isolated Windows development VM; never launch it.

Default invocation is a read-only plan. ``--create`` creates a fresh UTM bundle,
private installation seed and a blank QCOW2 disk. Existing targets and symlink
components are refused. The Windows installer can wipe only the sole new disk
declared in that bundle, never a host device. Actual guest acceptance is separate.

Guest bootstrap protocol: GET BASE/guest_runner.ps1, POST BASE/events with JSON.
BASE must be http://10.0.2.2:PORT/TOKEN on the dedicated host staging server.
The runner receives -BootstrapUrl BASE and owns subsequent payload/test steps.
"""

from __future__ import annotations

import argparse
import base64
import ctypes
import errno
import hashlib
import json
import os
import plistlib
import re
import secrets
import shutil
import stat
import struct
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

GIB = 1024**3
CLUSTER = 65536
UNATTEND = "urn:schemas-microsoft-com:unattend"
WCM = "http://schemas.microsoft.com/WMIConfig/2002/State"
ET.register_namespace("", UNATTEND)
ET.register_namespace("wcm", WCM)


@dataclass(frozen=True)
class Plan:
    app: Path
    windows_iso: Path
    destination: Path
    seed_dir: Path
    seed_iso: Path
    bootstrap_url: str = field(repr=False)
    guest_tools: Path | None = None
    disk_gib: int = 80
    image_index: int = 1
    name: str = "KiraBridge Windows Dev"

    def public(self):
        return {
            "action": "plan",
            "destination": str(self.destination),
            "name": self.name,
            "seed_dir": str(self.seed_dir),
            "seed_iso": str(self.seed_iso),
            "architecture": "x86_64",
            "cpu_cores": 2,
            "ram_mib": 8192,
            "disk_gib": self.disk_gib,
            "disk_format": "qcow2",
            "existing_disks_or_vms_touched": False,
            "host_directory_sharing": False,
            "clipboard_sharing": False,
            "network": "emulated NAT; dedicated host staging endpoint",
            "guest_user": "Kiradev",
            "guest_will_be_started": False,
            "guest_acceptance": "not_run",
        }


def checked_path(value: str | Path, *, regular: bool = False) -> Path:
    path = Path(value).expanduser().absolute()
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink():
            raise ValueError("Symlink path component refused")
    if regular and not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("A regular input file is required")
    return path


def bootstrap_url(value: str) -> str:
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError:
        port = None
    if (
        parsed.scheme != "http"
        or parsed.hostname != "10.0.2.2"
        or not port
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or not re.fullmatch(r"/[A-Za-z0-9_-]{16,128}", parsed.path)
    ):
        raise ValueError("Bootstrap URL must use the dedicated NAT host and a private token path")
    return value


def validate(plan: Plan) -> Path:
    first_logon_command()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}", plan.name):
        raise ValueError("VM name needs a bounded plain label")
    checked_path(plan.app)
    info = plistlib.loads(checked_path(plan.app / "Contents/Info.plist", regular=True).read_bytes())
    if info.get("CFBundleIdentifier") != "com.utmapp.UTM":
        raise ValueError("The full UTM application is required")
    firmware = checked_path(
        plan.app / "Contents/Resources/qemu/edk2-i386-secure-vars.fd", regular=True
    )
    checked_path(plan.app / "Contents/Resources/qemu/edk2-x86_64-secure-code.fd", regular=True)
    checked_path(plan.windows_iso, regular=True)
    if plan.guest_tools:
        checked_path(plan.guest_tools, regular=True)
    bootstrap_url(plan.bootstrap_url)
    if not 64 <= plan.disk_gib <= 1024 or not 1 <= plan.image_index <= 32:
        raise ValueError("Disk must be 64–1024 GiB and image index 1–32")
    targets = (plan.destination, plan.seed_dir, plan.seed_iso)
    for target in targets:
        checked_path(target)
        if os.path.lexists(target):
            raise FileExistsError("A provision target already exists; nothing will be overwritten")
        if not target.parent.is_dir():
            raise ValueError("Provision target parents must already exist")
    if any(
        a == b or a in b.parents or b in a.parents
        for i, a in enumerate(targets)
        for b in targets[i + 1 :]
    ):
        raise ValueError("Provision targets must be distinct and non-overlapping")
    if plan.destination.suffix != ".utm" or plan.seed_iso.suffix != ".iso":
        raise ValueError("Destination must end in .utm and seed image in .iso")
    return firmware


def write_private(path: Path, data: bytes):
    with path.open("xb") as output:
        os.chmod(path, 0o600)
        output.write(data)


def copy_exclusive(source: Path, target: Path):
    """APFS clone if possible, otherwise copy, without replacing any file."""
    before = source.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("Copy source changed type")
    cloned = False
    if sys.platform == "darwin":
        libc = ctypes.CDLL(None, use_errno=True)
        clone = getattr(libc, "clonefile", None)
        if clone is not None:
            clone.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int)
            clone.restype = ctypes.c_int
            if clone(os.fsencode(source), os.fsencode(target), 0) == 0:
                cloned = True
            elif ctypes.get_errno() not in (errno.ENOTSUP, errno.EXDEV, errno.ENOSYS):
                raise OSError(ctypes.get_errno(), "Exclusive APFS clone failed")
    if not cloned:
        with source.open("rb") as input_file, target.open("xb") as output:
            os.chmod(target, 0o600)
            shutil.copyfileobj(input_file, output, 1024 * 1024)
    os.chmod(target, 0o600)
    after = source.lstat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ) or target.stat().st_size != before.st_size:
        raise ValueError("Copy source changed during preparation")


def empty_qcow2(path: Path, size: int):
    """Create only an empty v3 image, per QEMU interop/qcow2.html.

    Four 64-KiB clusters: header, refcount table, refcount block, L1 table.
    There are no backing files, snapshots or allocated guest sectors.
    """
    if size % 512 or not 64 * GIB <= size <= 1024 * GIB:
        raise ValueError("Unsupported blank disk size")
    l1_entries = (size + CLUSTER * (CLUSTER // 8) - 1) // (CLUSTER * (CLUSTER // 8))
    header = struct.pack(
        ">IIQIIQIIQQIIQQQQII",
        0x514649FB,
        3,
        0,
        0,
        16,
        size,
        0,
        l1_entries,
        3 * CLUSTER,
        CLUSTER,
        1,
        0,
        0,
        0,
        0,
        0,
        4,
        104,
    )
    with path.open("xb") as output:
        os.chmod(path, 0o600)
        output.truncate(4 * CLUSTER)
        output.write(header)
        output.seek(CLUSTER)
        output.write(struct.pack(">Q", 2 * CLUSTER))
        output.seek(2 * CLUSTER)
        output.write(struct.pack(">4H", 1, 1, 1, 1))


def configuration(plan: Plan, identifier: str):
    def drive(name, kind, readonly):
        return {
            "ImageName": name,
            "ImageType": kind,
            "Interface": "IDE",
            "InterfaceVersion": 1,
            "Identifier": str(uuid.uuid4()).upper(),
            "ReadOnly": readonly,
        }

    drives = [
        drive("windows.qcow2", "Disk", False),
        drive("windows.iso", "CD", True),
        drive("seed.iso", "CD", True),
    ]
    if plan.guest_tools:
        drives.append(drive("guest-tools.iso", "CD", True))
    mac = ":".join(f"{b:02X}" for b in bytes([0x02]) + secrets.token_bytes(5))
    return {
        "Backend": "QEMU",
        "ConfigurationVersion": 4,
        "Information": {
            "Name": plan.name,
            "UUID": identifier,
            "IconCustom": False,
            "Icon": "windows",
            "Notes": "Isolated development VM; not Windows hardware certification",
        },
        "System": {
            "Architecture": "x86_64",
            "Target": "q35",
            "CPU": "default",
            "CPUFlagsAdd": [],
            "CPUFlagsRemove": [],
            "CPUCount": 2,
            "ForceMulticore": False,
            "MemorySize": 8192,
            "JITCacheSize": 0,
        },
        "QEMU": {
            "DebugLog": False,
            "UEFIBoot": True,
            "RNGDevice": True,
            "BalloonDevice": False,
            "TPMDevice": True,
            "Hypervisor": True,
            "TSO": False,
            "RTCLocalTime": True,
            "PS2Controller": True,
            "AdditionalArguments": [],
        },
        "Input": {"UsbBusSupport": "3.0", "UsbSharing": False, "MaximumUsbShare": 0},
        "Sharing": {
            "DirectoryShareMode": "None",
            "DirectoryShareReadOnly": True,
            "ClipboardSharing": False,
        },
        "Display": [
            {
                "Hardware": "VGA",
                "DynamicResolution": False,
                "UpscalingFilter": "Linear",
                "DownscalingFilter": "Linear",
                "NativeResolution": False,
            }
        ],
        "Drive": drives,
        "Network": [
            {
                "Mode": "Emulated",
                "Hardware": "e1000",
                "MacAddress": mac,
                "IsolateFromHost": False,
                "PortForward": [],
            }
        ],
        "Serial": [],
        "Sound": [],
    }


def element(parent, tag, text=None, **attributes):
    child = ET.SubElement(parent, f"{{{UNATTEND}}}{tag}", attributes)
    if text is not None:
        child.text = str(text)
    return child


def first_logon_script() -> bytes:
    # Start only a detached bootstrap; Explorer wait belongs to that child.
    script = r"""$ErrorActionPreference='Stop'
$seed=Get-Volume | Where-Object FileSystemLabel -eq 'KIRASEED' | Select-Object -First 1
if(-not $seed){throw 'Seed unavailable'}
$dest=Join-Path $env:LOCALAPPDATA 'KiraBridgeDev'
New-Item -ItemType Directory -Force $dest | Out-Null
$script=Join-Path $dest 'bootstrap.ps1'
Copy-Item ($seed.DriveLetter+':\bootstrap.ps1') $script
$arguments=@('-NoProfile','-ExecutionPolicy','Bypass','-File',('"'+$script+'"'))
Start-Process powershell.exe -ArgumentList $arguments -WindowStyle Normal
exit 0
"""
    return b"\xef\xbb\xbf" + script.encode("utf-8")


def first_logon_command(script: str | None = None) -> str:
    # Windows-Shell-Setup enforces a 1024-character CommandLine limit.
    entry = (
        script
        if script is not None
        else (
            "$s=Get-Volume|Where-Object FileSystemLabel -eq 'KIRASEED'|"
            "Select-Object -First 1;if(!$s){exit 2};&($s.DriveLetter+':\\first-logon.ps1')"
        )
    )
    encoded = base64.b64encode(entry.encode("utf-16-le")).decode()
    result = "powershell.exe -NoProfile -ExecutionPolicy Bypass -EncodedCommand " + encoded
    if len(result) > 1024:
        raise ValueError("Windows FirstLogon CommandLine exceeds 1024 characters")
    return result


def answer_file(password: str, image_index: int) -> bytes:
    root = ET.Element(f"{{{UNATTEND}}}unattend")

    def component(settings, name):
        return element(
            settings,
            "component",
            name=name,
            processorArchitecture="amd64",
            publicKeyToken="31bf3856ad364e35",
            language="neutral",
            versionScope="nonSxS",
        )

    winpe = element(root, "settings", **{"pass": "windowsPE"})
    intl = component(winpe, "Microsoft-Windows-International-Core-WinPE")
    element(element(intl, "SetupUILanguage"), "UILanguage", "de-DE")
    for key, value in {
        "InputLocale": "0407:00000407",
        "SystemLocale": "de-DE",
        "UILanguage": "de-DE",
        "UserLocale": "de-DE",
    }.items():
        element(intl, key, value)
    setup = component(winpe, "Microsoft-Windows-Setup")
    disk = element(element(setup, "DiskConfiguration"), "Disk", **{f"{{{WCM}}}action": "add"})
    element(disk, "DiskID", 0)
    element(disk, "WillWipeDisk", "true")
    create = element(disk, "CreatePartitions")
    for order, kind, size in [(1, "EFI", 260), (2, "MSR", 16), (3, "Primary", None)]:
        partition = element(create, "CreatePartition", **{f"{{{WCM}}}action": "add"})
        element(partition, "Order", order)
        element(partition, "Type", kind)
        element(partition, "Extend" if size is None else "Size", "true" if size is None else size)
    modify = element(disk, "ModifyPartitions")
    for order, pid, filesystem, label in [(1, 1, "FAT32", "System"), (2, 3, "NTFS", "Windows")]:
        partition = element(modify, "ModifyPartition", **{f"{{{WCM}}}action": "add"})
        for key, value in {
            "Order": order,
            "PartitionID": pid,
            "Format": filesystem,
            "Label": label,
        }.items():
            element(partition, key, value)
        if pid == 3:
            element(partition, "Letter", "C")
    image = element(element(setup, "ImageInstall"), "OSImage")
    meta = element(element(image, "InstallFrom"), "MetaData", **{f"{{{WCM}}}action": "add"})
    element(meta, "Key", "/IMAGE/INDEX")
    element(meta, "Value", image_index)
    install_to = element(image, "InstallTo")
    element(install_to, "DiskID", 0)
    element(install_to, "PartitionID", 3)
    element(image, "WillShowUI", "OnError")
    user_data = element(setup, "UserData")
    element(user_data, "AcceptEula", "true")
    element(user_data, "FullName", "KiraBridge development")

    oobe = element(root, "settings", **{"pass": "oobeSystem"})
    intl = component(oobe, "Microsoft-Windows-International-Core")
    for key, value in {
        "InputLocale": "0407:00000407",
        "SystemLocale": "de-DE",
        "UILanguage": "de-DE",
        "UserLocale": "de-DE",
    }.items():
        element(intl, key, value)
    shell = component(oobe, "Microsoft-Windows-Shell-Setup")
    element(shell, "TimeZone", "W. Europe Standard Time")
    local = element(
        element(element(shell, "UserAccounts"), "LocalAccounts"),
        "LocalAccount",
        **{f"{{{WCM}}}action": "add"},
    )
    element(local, "Name", "Kiradev")
    element(local, "DisplayName", "KiraBridge development")
    element(local, "Group", "Administrators")
    for owner in (local, element(shell, "AutoLogon")):
        pw = element(owner, "Password")
        element(pw, "Value", password)
        element(pw, "PlainText", "true")
        if owner.tag.endswith("AutoLogon"):
            element(owner, "Username", "Kiradev")
            element(owner, "Enabled", "true")
            element(owner, "LogonCount", 2)
    options = element(shell, "OOBE")
    for key in (
        "HideEULAPage",
        "HideOEMRegistrationScreen",
        "HideOnlineAccountScreens",
        "HideWirelessSetupInOOBE",
    ):
        element(options, key, "true")
    element(options, "ProtectYourPC", 3)
    entry_command = first_logon_command()
    command = element(
        element(shell, "FirstLogonCommands"), "SynchronousCommand", **{f"{{{WCM}}}action": "add"}
    )
    element(command, "Order", 1)
    element(command, "Description", "Start isolated KiraBridge development bootstrap")
    element(
        command,
        "CommandLine",
        entry_command,
    )
    ET.indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def bootstrap_script(url: str) -> bytes:
    bootstrap_url(url)
    script = r"""$ErrorActionPreference = 'Stop'
$BaseUrl = '__BASE__'
$Work = Join-Path $env:LOCALAPPDATA 'KiraBridgeDev'
New-Item -ItemType Directory -Force $Work | Out-Null
function Report([string]$State) {
    try {
        $event = @{phase=$State; computer=$env:COMPUTERNAME; user=$env:USERNAME}
        $post = @{Method='Post'; Uri=($BaseUrl+'/events'); Body=($event|ConvertTo-Json -Compress);
            ContentType='application/json'; TimeoutSec=15}
        Invoke-RestMethod @post | Out-Null
    } catch { }
}
try {
    Report 'first_logon_started'
    $deadline = [DateTime]::UtcNow.AddMinutes(3)
    while (-not (Get-Process explorer -ErrorAction SilentlyContinue)) {
        if ([DateTime]::UtcNow -gt $deadline) { throw 'Interactive desktop unavailable' }
        Start-Sleep -Seconds 1
    }
    $Runner = Join-Path $Work 'guest_runner.ps1'
    $get = @{Uri=($BaseUrl+'/guest_runner.ps1'); OutFile=$Runner; TimeoutSec=120}
    Invoke-WebRequest -UseBasicParsing @get
    Report 'runner_downloaded'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Runner -BootstrapUrl $BaseUrl
    if ($LASTEXITCODE -ne 0) { throw 'Guest runner failed' }
    Report 'runner_finished'
} catch {
    # Error messages can contain the private URL, so do not return exception text.
    Report 'first_logon_failed'
    $failure = 'failed: '+$_.Exception.GetType().FullName
    Set-Content -Path (Join-Path $Work 'bootstrap-status.txt') -Value $failure
    exit 1
}
""".replace("__BASE__", url)
    return b"\xef\xbb\xbf" + script.encode("utf-8")


def create(plan: Plan, *, run=subprocess.run):
    firmware = validate(plan)
    run(
        ["/usr/bin/codesign", "--verify", "--deep", "--strict", str(plan.app)],
        check=True,
        capture_output=True,
        timeout=120,
    )
    # Validate every target before the first write and never remove a partial result.
    validate(plan)
    previous_umask = os.umask(0o077)
    try:
        plan.destination.mkdir(mode=0o700)
        data = plan.destination / "Data"
        data.mkdir(mode=0o700)
        plan.seed_dir.mkdir(mode=0o700)
        identifier = str(uuid.uuid4()).upper()
        password = "Kira!" + secrets.token_urlsafe(30)
        write_private(plan.seed_dir / "Autounattend.xml", answer_file(password, plan.image_index))
        write_private(plan.seed_dir / "bootstrap.ps1", bootstrap_script(plan.bootstrap_url))
        write_private(plan.seed_dir / "first-logon.ps1", first_logon_script())
        write_private(
            plan.destination / "private-credentials.json",
            json.dumps({"username": "Kiradev", "password": password}).encode(),
        )
        empty_qcow2(data / "windows.qcow2", plan.disk_gib * GIB)
        copy_exclusive(firmware, data / "efi_vars.fd")
        copy_exclusive(plan.windows_iso, data / "windows.iso")
        if plan.guest_tools:
            copy_exclusive(plan.guest_tools, data / "guest-tools.iso")
        run(
            [
                "/usr/bin/hdiutil",
                "makehybrid",
                "-iso",
                "-joliet",
                "-default-volume-name",
                "KIRASEED",
                "-o",
                str(plan.seed_iso),
                str(plan.seed_dir),
            ],
            check=True,
            capture_output=True,
            timeout=120,
        )
        os.chmod(plan.seed_iso, 0o600)
        copy_exclusive(plan.seed_iso, data / "seed.iso")
        config = configuration(plan, identifier)
        write_private(plan.destination / "config.plist", plistlib.dumps(config))
        result = {
            **plan.public(),
            "action": "created",
            "uuid": identifier,
            "config_sha256": hashlib.sha256(plistlib.dumps(config)).hexdigest(),
            "private_credentials_file": str(plan.destination / "private-credentials.json"),
        }
        write_private(plan.destination / "provisioning.json", json.dumps(result, indent=2).encode())
        return result
    finally:
        os.umask(previous_umask)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--utm-app", type=Path, required=True)
    parser.add_argument("--windows-iso", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--bootstrap-url", required=True)
    parser.add_argument("--seed-dir", type=Path)
    parser.add_argument("--seed-iso", type=Path)
    parser.add_argument("--guest-tools", type=Path)
    parser.add_argument("--disk-gib", type=int, default=80)
    parser.add_argument("--image-index", type=int, default=1)
    parser.add_argument("--name", default="KiraBridge Windows Dev")
    parser.add_argument("--create", action="store_true")
    args = parser.parse_args(argv)
    destination = checked_path(args.destination)
    plan = Plan(
        checked_path(args.utm_app),
        checked_path(args.windows_iso),
        destination,
        checked_path(args.seed_dir or destination.with_name(destination.stem + "-seed")),
        checked_path(args.seed_iso or destination.with_name(destination.stem + "-seed.iso")),
        bootstrap_url(args.bootstrap_url),
        checked_path(args.guest_tools) if args.guest_tools else None,
        args.disk_gib,
        args.image_index,
        args.name,
    )
    validate(plan)
    print(json.dumps(create(plan) if args.create else plan.public(), indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        # Do not print arbitrary child output, guest credentials or bootstrap URLs.
        print(
            f"VM preparation failed: {type(error).__name__}; existing targets were not overwritten",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
