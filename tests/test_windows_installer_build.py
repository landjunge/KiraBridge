"""Offline archive safety checks; these do not claim native Windows acceptance."""

import importlib.util
import io
import json
import stat
import struct
import sys
import zipfile
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "build_windows_installer", Path(__file__).parents[1] / "scripts/build_windows_installer.py"
)
builder = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = builder
spec.loader.exec_module(builder)


def zipped(files):
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w") as output:
        for name, body in files.items():
            output.writestr(name, body)
    return raw.getvalue()


@pytest.mark.parametrize(
    "name", ["../escape", "/absolute", "a/../escape", "C:/drive", "a\\b", "nul.txt", "a./b"]
)
def test_windows_archive_path_hazards_are_rejected(name):
    with pytest.raises(ValueError, match="Unsafe"):
        builder.archive_files(zipped({name: b"bad"}))


def test_case_collisions_and_links_are_rejected():
    with pytest.raises(ValueError, match="Duplicate"):
        builder.archive_files(zipped({"Python.exe": b"one", "python.exe": b"two"}))
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w") as output:
        info = zipfile.ZipInfo("linked")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        output.writestr(info, "target")
    with pytest.raises(ValueError, match="linked"):
        builder.archive_files(raw.getvalue())


def test_expansion_budget_is_enforced(monkeypatch):
    monkeypatch.setattr(builder, "MAX_EXPANDED", 4)
    with pytest.raises(ValueError, match="budget"):
        builder.archive_files(zipped({"large": b"large"}))


def test_wrong_fixed_archive_digest_leaves_output_absent(tmp_path):
    kit = tmp_path / "kit.zip"
    kit.write_bytes(zipped({"untrusted": b"unknown"}))
    output = tmp_path / "out"
    with pytest.raises(ValueError, match="fixed published"):
        builder.stage(kit, tmp_path / "unused-python.zip", output)
    assert not output.exists()


def test_kit_checksum_inventory_rejects_unlisted_payload():
    prefix = "KiraBridge-Windows-Dev-Kit/"
    raw = zipped({prefix + "SHA256SUMS": b"", prefix + "rogue": b"bytes"})
    with pytest.raises(ValueError, match="inventory"):
        builder.verified_kit(raw)


def test_kit_checksum_rejects_changed_payload():
    prefix = "KiraBridge-Windows-Dev-Kit/"
    raw = zipped(
        {
            prefix + "SHA256SUMS": ("0" * 64 + "  file\n").encode(),
            prefix + "file": b"changed",
        }
    )
    with pytest.raises(ValueError, match="digest"):
        builder.verified_kit(raw)


def test_wheel_data_is_remapped_without_global_installation():
    assert builder.wheel_destination("lib.py") == "Lib/site-packages/lib.py"
    assert builder.wheel_destination("a.data/platlib/lib.pyd") == "Lib/site-packages/lib.pyd"
    assert builder.wheel_destination("a.data/purelib/lib.py") == "Lib/site-packages/lib.py"
    assert builder.wheel_destination("a.data/scripts/tool.py") == "Scripts/tool.py"
    assert builder.wheel_destination("a.data/data/LICENSE") == "LICENSE"
    with pytest.raises(ValueError, match="Unsupported"):
        builder.wheel_destination("a.data/unknown/file")


def fake_pe(machine=b"d\x86"):
    raw = bytearray(128)
    raw[:2] = b"MZ"
    struct.pack_into("<I", raw, 0x3C, 64)
    raw[64:70] = b"PE\0\0" + machine
    return bytes(raw)


def test_python_architecture_guard_rejects_x86_and_malformed():
    builder.require_amd64_pe(fake_pe())
    for raw in (b"bad", fake_pe(b"L\x01")):
        with pytest.raises(ValueError, match="AMD64"):
            builder.require_amd64_pe(raw)


def test_runtime_assembly_blocks_wheel_overwrite():
    python = zipped(
        {
            "python.exe": fake_pe(),
            "pythonw.exe": fake_pe(),
            "python314.dll": fake_pe(),
            "python314.zip": b"stdlib fixture",
            "python314._pth": b"original",
        }
    )
    kit = {
        f"wheels/fixture{i}-1-py3-none-any.whl": zipped({"shared.py": b"fixture"})
        for i in range(38)
    }
    with pytest.raises(ValueError, match="overwrite"):
        builder.runtime_files(kit, python)


def test_runtime_assembly_has_private_paths_and_all_pinned_dependencies():
    python = zipped(
        {
            "python.exe": fake_pe(),
            "pythonw.exe": fake_pe(),
            "python314.dll": fake_pe(),
            "python314.zip": b"stdlib fixture",
            "python314._pth": b"original",
        }
    )
    kit = {
        f"wheels/fixture{i}-1-py3-none-any.whl": zipped({f"module{i}.py": b"fixture"})
        for i in range(38)
    }
    files = builder.runtime_files(kit, python)
    assert files["python314._pth"].splitlines() == [
        b"python314.zip",
        b".",
        b"Lib/site-packages",
        b"import site",
    ]
    assert "windows_lifecycle.py" in files
    assert sum(name.startswith("Lib/site-packages/") for name in files) == 38
    assert "python-installer.exe" not in files


def test_inno_uses_precommit_transactions_and_safe_per_user_defaults():
    script = (builder.ROOT / "installer/windows/setup.iss").read_text()
    assert "PrivilegesRequired=lowest" in script
    assert "CloseApplications=no" in script
    assert "AfterInstall: CommitInstall" in script
    assert "Lifecycle('rollback', False)" in script
    assert "Lifecycle('preflight-uninstall', True)" in script
    assert 'Type: files; Name: "{app}\\.lifecycle.lock"' in script
    assert "Type: filesandordirs" not in script
    assert "Flags: shellexec nowait postinstall skipifsilent unchecked" in script
    assert "ExecAndLogOutput" in script
    assert "KiraBridge.Windows" in script
    assert "KiraAppId" in script and "KiraOutputSuffix" in script


def test_manifest_identity_is_deterministic_and_hexadecimal():
    files = {"python.exe": "a" * 64, "module.py": "b" * 64}
    assert builder.digest(builder.canonical(files)) == builder.digest(
        builder.canonical(dict(reversed(list(files.items()))))
    )
    json.loads(builder.canonical(files))


def test_setup_and_uninstall_share_atomic_full_lifetime_maintenance_mutex():
    script = (builder.ROOT / "installer/windows/setup.iss").read_text()
    assert "CreateMutexW@kernel32.dll stdcall" in script
    assert "GetLastError@kernel32.dll stdcall" in script
    assert "CloseHandle@kernel32.dll stdcall" in script
    assert "'Local\\{#KiraAppId}.Maintenance.' + ExpandConstant('{username}')" in script
    assert "KiraCreateMutex(0, False," in script  # NULL security attributes: no inheritance.
    assert "(ErrorCode <> 183)" in script  # ERROR_ALREADY_EXISTS is not success.
    setup = script.split("function InitializeSetup:", 1)[1].split("function PrepareToInstall", 1)[0]
    uninstall = script.split("function InitializeUninstall:", 1)[1].split(
        "procedure CurUninstallStepChanged", 1
    )[0]
    assert "Result := AcquireMaintenance" in setup
    assert "Result := AcquireMaintenance" in uninstall
    assert uninstall.index("AcquireMaintenance") < uninstall.index("preflight-uninstall")
    for hook in ("procedure DeinitializeSetup;", "procedure DeinitializeUninstall;"):
        cleanup = script.split(hook, 1)[1]
        assert "finally\n    ReleaseMaintenance;" in cleanup


def test_installer_stdout_cannot_collide_with_inno_log(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "accept_windows_installer",
        Path(__file__).parents[1] / "scripts/accept_windows_installer.py",
    )
    harness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(harness)
    output = tmp_path / "final-uninstall.log"
    with pytest.raises(ValueError, match="distinct files"):
        harness.guard_log_paths(["unins000.exe", "/LOG=" + str(output)], output)
    with pytest.raises(ValueError, match="distinct files"):
        harness.guard_log_paths(["unins000.exe", "/LOG=" + str(output).upper()], output)
    harness.guard_log_paths(
        ["unins000.exe", "/LOG=" + str(output)], tmp_path / "final-uninstall-stdout.log"
    )
