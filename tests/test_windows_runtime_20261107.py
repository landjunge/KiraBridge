"""Fixtures for the bundled Windows CPython runtime check. No installer run."""

import hashlib
import os
from pathlib import Path

import pytest

from kirabridge.windows_package import PackageError
from kirabridge.windows_runtime import validate_bundled_runtime


def _runtime(path: Path, exe=b"MZ-python", dll=b"MZ-python314", dll_name="python314.dll"):
    path.mkdir(parents=True, exist_ok=True)
    if exe is not None:
        (path / "python.exe").write_bytes(exe)
    if dll is not None:
        (path / dll_name).write_bytes(dll)
    return path


def test_valid_runtime_returns_sha256_for_exe_and_matching_dll(tmp_path):
    exe = b"MZ-python-3.14"
    dll = b"MZ-python314-dll"
    root = _runtime(tmp_path / "runtime", exe=exe, dll=dll)
    (root / "python3.dll").write_bytes(b"stable-abi-stub")
    (root / "LICENSE.txt").write_bytes(b"license")
    found = validate_bundled_runtime(root)
    assert found["python_dll"] == "python314.dll"
    assert found["files"] == {
        "python.exe": hashlib.sha256(exe).hexdigest(),
        "python314.dll": hashlib.sha256(dll).hexdigest(),
    }


def test_rejects_missing_python_exe(tmp_path):
    root = _runtime(tmp_path / "runtime", exe=None)
    with pytest.raises(PackageError, match="python.exe"):
        validate_bundled_runtime(root)


def test_rejects_missing_python_dll(tmp_path):
    root = _runtime(tmp_path / "runtime", dll=None)
    with pytest.raises(PackageError, match="Python DLL"):
        validate_bundled_runtime(root)


def test_rejects_stable_abi_dll_without_versioned_dll(tmp_path):
    root = _runtime(tmp_path / "runtime", dll=None)
    (root / "python3.dll").write_bytes(b"stable-abi-stub")
    with pytest.raises(PackageError, match="Python DLL"):
        validate_bundled_runtime(root)


def test_rejects_empty_python_exe(tmp_path):
    root = _runtime(tmp_path / "runtime", exe=b"")
    with pytest.raises(PackageError, match="empty"):
        validate_bundled_runtime(root)


def test_rejects_empty_python_dll(tmp_path):
    root = _runtime(tmp_path / "runtime", dll=b"")
    with pytest.raises(PackageError, match="empty"):
        validate_bundled_runtime(root)


def test_rejects_symlink_python_exe(tmp_path):
    root = tmp_path / "runtime"
    root.mkdir()
    outside = tmp_path / "outside.exe"
    outside.write_bytes(b"MZ-secret")
    (root / "python.exe").symlink_to(outside)
    (root / "python314.dll").write_bytes(b"MZ-python314")
    with pytest.raises(PackageError):
        validate_bundled_runtime(root)


def test_rejects_symlink_python_dll(tmp_path):
    root = tmp_path / "runtime"
    root.mkdir()
    (root / "python.exe").write_bytes(b"MZ-python")
    outside = tmp_path / "outside.dll"
    outside.write_bytes(b"MZ-secret-dll")
    (root / "python314.dll").symlink_to(outside)
    with pytest.raises(PackageError):
        validate_bundled_runtime(root)


def test_rejects_symlink_runtime_root(tmp_path):
    real = _runtime(tmp_path / "real")
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(PackageError):
        validate_bundled_runtime(link)


def test_rejects_parent_segment_in_root(tmp_path):
    outside = _runtime(tmp_path / "outside")
    escaped = outside.parent / outside.name / ".." / "outside"
    assert ".." in escaped.parts
    with pytest.raises(PackageError, match="traversal"):
        validate_bundled_runtime(escaped)


def test_rejects_hardlinked_python_exe(tmp_path):
    root = tmp_path / "runtime"
    root.mkdir()
    source = tmp_path / "source.exe"
    source.write_bytes(b"MZ-python")
    os.link(source, root / "python.exe")
    (root / "python314.dll").write_bytes(b"MZ-python314")
    with pytest.raises(PackageError):
        validate_bundled_runtime(root)


def test_rejects_two_python_dlls(tmp_path):
    root = _runtime(tmp_path / "runtime")
    (root / "python311.dll").write_bytes(b"MZ-python311")
    with pytest.raises(PackageError, match="exactly one"):
        validate_bundled_runtime(root)


def test_rejects_directory_named_python_exe(tmp_path):
    root = tmp_path / "runtime"
    root.mkdir()
    (root / "python.exe").mkdir()
    (root / "python314.dll").write_bytes(b"MZ-python314")
    with pytest.raises(PackageError):
        validate_bundled_runtime(root)


def test_rejects_file_as_runtime_root(tmp_path):
    root = tmp_path / "runtime"
    root.write_bytes(b"not-a-directory")
    with pytest.raises(PackageError):
        validate_bundled_runtime(root)
