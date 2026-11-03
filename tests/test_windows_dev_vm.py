"""Provisioning safety and generated deployment artifacts; no VM is started."""

import importlib.util
import json
import plistlib
import stat
import struct
import sys
import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "windows_dev_vm", Path(__file__).parents[1] / "scripts/windows_dev_vm.py"
)
vm = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = vm
spec.loader.exec_module(vm)


@pytest.fixture
def plan(tmp_path):
    app = tmp_path / "UTM.app"
    resources = app / "Contents/Resources/qemu"
    resources.mkdir(parents=True)
    (app / "Contents/Info.plist").write_bytes(
        plistlib.dumps({"CFBundleIdentifier": "com.utmapp.UTM"})
    )
    (resources / "edk2-i386-secure-vars.fd").write_bytes(b"secure-vars")
    (resources / "edk2-x86_64-secure-code.fd").write_bytes(b"secure-code")
    image = tmp_path / "windows.iso"
    image.write_bytes(b"own-iso-fixture")
    return vm.Plan(
        app,
        image,
        tmp_path / "dev.utm",
        tmp_path / "seed",
        tmp_path / "seed.iso",
        "http://10.0.2.2:8123/0123456789abcdef0123456789abcdef",
    )


def test_existing_destination_is_refused_before_any_write(plan):
    plan.destination.mkdir()
    original = plan.destination / "important.txt"
    original.write_text("keep")
    with pytest.raises(FileExistsError):
        vm.create(plan, run=lambda *a, **k: pytest.fail("must not execute a tool"))
    assert original.read_text() == "keep"
    assert not plan.seed_dir.exists()


def test_symlink_target_and_parent_are_refused(plan, tmp_path):
    link = tmp_path / "linked"
    actual = tmp_path / "actual"
    actual.mkdir()
    link.symlink_to(actual, target_is_directory=True)
    with pytest.raises(ValueError, match="Symlink"):
        vm.validate(replace(plan, destination=link / "dev.utm"))
    plan.destination.symlink_to(tmp_path / "missing")
    with pytest.raises(ValueError, match="Symlink"):
        vm.validate(plan)
    assert list(actual.iterdir()) == []


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/token0123456789abcdef",
        "http://10.0.2.2:8123/short",
        "http://user:pw@10.0.2.2:8123/token0123456789abcdef",
        "http://10.0.2.2:8123/token0123456789abcdef?injection=1",
        "http://10.0.2.2:99999/token0123456789abcdef",
        "http://10.0.2.2:8123/unsafe'quoted0123456789",
    ],
)
def test_untrusted_bootstrap_destinations_are_refused(url):
    with pytest.raises(ValueError):
        vm.bootstrap_url(url)


def test_plan_is_read_only_and_does_not_expose_token(plan, capsys):
    vm.main(
        [
            "--utm-app",
            str(plan.app),
            "--windows-iso",
            str(plan.windows_iso),
            "--destination",
            str(plan.destination),
            "--bootstrap-url",
            plan.bootstrap_url,
        ]
    )
    output = capsys.readouterr().out
    assert json.loads(output)["action"] == "plan"
    assert "0123456789abcdef" not in output
    assert not plan.destination.exists()
    assert not plan.seed_dir.exists()


def test_creation_only_owns_new_disk_and_private_seed(plan):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        assert kwargs["timeout"] == 120
        assert kwargs["check"] is True
        if "makehybrid" in argv:
            Path(argv[argv.index("-o") + 1]).write_bytes(b"seed-iso-fixture")

    result = vm.create(plan, run=run)
    assert result["action"] == "created"
    assert [Path(c[0]).name for c in calls] == ["codesign", "hdiutil"]
    config = plistlib.loads((plan.destination / "config.plist").read_bytes())
    disks = [d for d in config["Drive"] if d["ImageType"] == "Disk"]
    assert len(disks) == 1 and disks[0]["ImageName"] == "windows.qcow2"
    assert all(d["ReadOnly"] for d in config["Drive"] if d["ImageType"] == "CD")
    assert config["Sharing"]["DirectoryShareMode"] == "None"
    assert config["Sharing"]["ClipboardSharing"] is False
    assert config["Input"]["UsbSharing"] is False
    assert config["Network"][0]["Mode"] == "Emulated"
    assert config["Network"][0]["PortForward"] == []
    assert config["QEMU"]["TPMDevice"] is True
    assert (plan.destination / "Data/efi_vars.fd").read_bytes() == b"secure-vars"
    password = json.loads((plan.destination / "private-credentials.json").read_text())["password"]
    assert password not in json.dumps(result)
    for path in (
        plan.seed_iso,
        plan.seed_dir / "Autounattend.xml",
        plan.destination / "private-credentials.json",
    ):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(plan.destination.stat().st_mode) == 0o700
    # Never retry into even our own existing bundle or rewrite its disk.
    disk_before = (plan.destination / "Data/windows.qcow2").read_bytes()
    with pytest.raises(FileExistsError):
        vm.create(plan, run=run)
    assert (plan.destination / "Data/windows.qcow2").read_bytes() == disk_before


def test_unattended_install_has_one_explicit_guest_disk_and_interactive_launcher():
    root = ET.fromstring(vm.answer_file("Private-test<&password", 1))
    ns = {"u": vm.UNATTEND}
    disks = root.findall(".//u:Disk", ns)
    assert len(disks) == 1
    assert disks[0].findtext("u:DiskID", namespaces=ns) == "0"
    assert disks[0].findtext("u:WillWipeDisk", namespaces=ns) == "true"
    assert root.findtext(".//u:InstallTo/u:DiskID", namespaces=ns) == "0"
    assert root.findtext(".//u:InstallTo/u:PartitionID", namespaces=ns) == "3"
    assert len(root.findall(".//u:FirstLogonCommands/u:SynchronousCommand", ns)) == 1
    assert root.findtext(".//u:AutoLogon/u:Username", namespaces=ns) == "Kiradev"
    assert "BypassTPM" not in vm.answer_file("test", 1).decode()


def test_empty_qcow2_has_consistent_v3_metadata_and_no_backing_file(tmp_path):
    disk = tmp_path / "disk.qcow2"
    vm.empty_qcow2(disk, 80 * vm.GIB)
    raw = disk.read_bytes()
    assert len(raw) == 4 * 65536
    assert raw[:4] == b"QFI\xfb"
    assert struct.unpack_from(">I", raw, 4)[0] == 3
    assert struct.unpack_from(">Q", raw, 8)[0] == 0
    assert struct.unpack_from(">Q", raw, 24)[0] == 80 * 1024**3
    assert struct.unpack_from(">I", raw, 36)[0] == 160
    assert struct.unpack_from(">Q", raw, 40)[0] == 3 * 65536
    assert struct.unpack_from(">Q", raw, 65536)[0] == 2 * 65536
    assert struct.unpack_from(">4H", raw, 2 * 65536) == (1, 1, 1, 1)
    assert not any(raw[3 * 65536 :])
    with pytest.raises(FileExistsError):
        vm.empty_qcow2(disk, 80 * vm.GIB)


def test_copy_never_replaces_existing_target(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.write_bytes(b"new")
    target.write_bytes(b"keep")
    with pytest.raises(OSError):
        vm.copy_exclusive(source, target)
    assert target.read_bytes() == b"keep"
