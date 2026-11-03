"""Owner/DACL-verified Windows state files, without POSIX-mode assumptions.

New objects receive a protected DACL for the current user and LocalSystem.
Existing objects are inspected through opened handles, never silently re-ACL'd.
Administrators are accepted as privileged trustees on existing private objects.
See https://learn.microsoft.com/windows/win32/fileio/file-security-and-access-rights
"""

from __future__ import annotations

import ctypes
import ntpath
import os
from contextlib import contextmanager
from pathlib import Path, PureWindowsPath

from kirabridge.bridge_core.models import BridgeError

DWORD = ctypes.c_uint32
WORD = ctypes.c_uint16
BYTE = ctypes.c_ubyte
HANDLE = ctypes.c_void_p
BOOL = ctypes.c_int32
PRIVILEGED_SIDS = frozenset({"S-1-5-18", "S-1-5-32-544"})
REPARSE_POINT = 0x400
DIRECTORY = 0x10


class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("length", DWORD), ("descriptor", HANDLE), ("inherit", BOOL)]


class ACL(ctypes.Structure):
    _fields_ = [
        ("revision", BYTE),
        ("reserved", BYTE),
        ("size", WORD),
        ("count", WORD),
        ("reserved2", WORD),
    ]


class ACE_HEADER(ctypes.Structure):
    _fields_ = [("type", BYTE), ("flags", BYTE), ("size", WORD)]


class FILE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("attributes", DWORD),
        ("creation", DWORD * 2),
        ("access", DWORD * 2),
        ("write", DWORD * 2),
        ("volume", DWORD),
        ("size_high", DWORD),
        ("size_low", DWORD),
        ("links", DWORD),
        ("index_high", DWORD),
        ("index_low", DWORD),
    ]


def validate_security(owner_sid, allowed_sids, current_sid):
    """Conservative ACL policy, also used by platform-independent policy tests."""
    if owner_sid != current_sid or not allowed_sids:
        raise BridgeError("unsafe_state", "Windows state must be owned by the current user")
    if any(sid not in PRIVILEGED_SIDS | {current_sid} for sid in allowed_sids):
        raise BridgeError("unsafe_state", "Windows state grants access to another trustee")


def validate_local_path(value):
    path = PureWindowsPath(value)
    if (
        not path.is_absolute()
        or not path.drive
        or path.drive.startswith("\\")
        or ".." in path.parts
        or "\x00" in value
        or len(value) > 32760
        or any(":" in part for part in path.parts[1:])
    ):
        raise BridgeError("unsafe_state", "Windows private state requires a local absolute path")
    return str(path)


class WindowsFiles:
    def __init__(self):
        if os.name != "nt":
            raise BridgeError("unsupported_platform", "Windows file APIs require Windows")
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.security = ctypes.WinDLL("advapi32", use_last_error=True)
        self._bind()
        self.sid = self._current_sid()

    def _bind(self):
        def function(library, name, result, *arguments):
            method = getattr(library, name)
            method.argtypes, method.restype = list(arguments), result

        pointer = ctypes.POINTER
        function(self.kernel, "GetCurrentProcess", HANDLE)
        function(self.kernel, "CloseHandle", BOOL, HANDLE)
        function(self.kernel, "LocalFree", HANDLE, HANDLE)
        function(self.kernel, "GetFileAttributesW", DWORD, ctypes.c_wchar_p)
        function(
            self.kernel, "CreateDirectoryW", BOOL, ctypes.c_wchar_p, pointer(SECURITY_ATTRIBUTES)
        )
        function(
            self.kernel,
            "CreateFileW",
            HANDLE,
            ctypes.c_wchar_p,
            DWORD,
            DWORD,
            pointer(SECURITY_ATTRIBUTES),
            DWORD,
            DWORD,
            HANDLE,
        )
        function(self.kernel, "GetFileInformationByHandle", BOOL, HANDLE, pointer(FILE_INFORMATION))
        function(
            self.kernel, "GetFinalPathNameByHandleW", DWORD, HANDLE, ctypes.c_wchar_p, DWORD, DWORD
        )
        function(self.security, "OpenProcessToken", BOOL, HANDLE, DWORD, pointer(HANDLE))
        function(
            self.security, "GetTokenInformation", BOOL, HANDLE, DWORD, HANDLE, DWORD, pointer(DWORD)
        )
        function(self.security, "ConvertSidToStringSidW", BOOL, HANDLE, pointer(ctypes.c_wchar_p))
        function(
            self.security,
            "ConvertStringSecurityDescriptorToSecurityDescriptorW",
            BOOL,
            ctypes.c_wchar_p,
            DWORD,
            pointer(HANDLE),
            pointer(DWORD),
        )
        function(
            self.security,
            "GetSecurityInfo",
            DWORD,
            HANDLE,
            DWORD,
            DWORD,
            pointer(HANDLE),
            pointer(HANDLE),
            pointer(HANDLE),
            pointer(HANDLE),
            pointer(HANDLE),
        )
        function(self.security, "GetAce", BOOL, HANDLE, DWORD, pointer(HANDLE))

    @staticmethod
    def _error():
        return ctypes.WinError(ctypes.get_last_error())

    def close(self, handle):
        if not self.kernel.CloseHandle(handle):
            raise self._error()

    def _sid_string(self, sid):
        result = ctypes.c_wchar_p()
        if not sid or not self.security.ConvertSidToStringSidW(sid, ctypes.byref(result)):
            raise self._error()
        try:
            return result.value
        finally:
            self.kernel.LocalFree(ctypes.cast(result, HANDLE))

    def _current_sid(self):
        token = HANDLE()
        if not self.security.OpenProcessToken(
            self.kernel.GetCurrentProcess(), 8, ctypes.byref(token)
        ):
            raise self._error()
        try:
            size = DWORD()
            self.security.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
            if not 0 < size.value <= 65536:
                raise BridgeError("unsafe_state", "Cannot determine Windows user identity")
            data = ctypes.create_string_buffer(size.value)
            if not self.security.GetTokenInformation(token, 1, data, size, ctypes.byref(size)):
                raise self._error()
            return self._sid_string(ctypes.cast(data, ctypes.POINTER(HANDLE)).contents.value)
        finally:
            self.close(token)

    @contextmanager
    def _attributes(self):
        descriptor = HANDLE()
        sddl = f"O:{self.sid}D:P(A;OICI;FA;;;{self.sid})(A;OICI;FA;;;SY)"
        if not self.security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, 1, ctypes.byref(descriptor), None
        ):
            raise self._error()
        try:
            yield SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES), descriptor, 0)
        finally:
            self.kernel.LocalFree(descriptor)

    def _inspect_security(self, handle):
        owner, dacl, descriptor = HANDLE(), HANDLE(), HANDLE()
        error = self.security.GetSecurityInfo(
            handle,
            1,
            1 | 4,
            ctypes.byref(owner),
            None,
            ctypes.byref(dacl),
            None,
            ctypes.byref(descriptor),
        )
        if error:
            raise ctypes.WinError(error)
        try:
            if not dacl:
                raise BridgeError("unsafe_state", "A null Windows DACL is not private")
            acl = ctypes.cast(dacl, ctypes.POINTER(ACL)).contents
            if not 0 < acl.count <= 256:
                raise BridgeError("unsafe_state", "Windows state ACL cannot be verified")
            allowed = []
            for index in range(acl.count):
                ace = HANDLE()
                if not self.security.GetAce(dacl, index, ctypes.byref(ace)):
                    raise self._error()
                header = ctypes.cast(ace, ctypes.POINTER(ACE_HEADER)).contents
                if header.type == 1:  # ACCESS_DENIED_ACE cannot grant access.
                    continue
                if header.type != 0 or header.size < 12:
                    raise BridgeError("unsafe_state", "Unsupported Windows state ACL entry")
                # ACCESS_ALLOWED_ACE: 4-byte header + 4-byte mask, then SID.
                allowed.append(self._sid_string(ace.value + 8))
            validate_security(self._sid_string(owner), allowed, self.sid)
        finally:
            self.kernel.LocalFree(descriptor)

    def _inspect(self, handle, expected_path, *, directory):
        info = FILE_INFORMATION()
        if not self.kernel.GetFileInformationByHandle(handle, ctypes.byref(info)):
            raise self._error()
        if info.attributes & REPARSE_POINT or bool(info.attributes & DIRECTORY) != directory:
            raise BridgeError("unsafe_state", "Windows state reparse points/types are forbidden")
        if not directory and info.links != 1:
            raise BridgeError("unsafe_state", "Windows private files cannot have hard links")
        buffer = ctypes.create_unicode_buffer(32768)
        size = self.kernel.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0)
        if not 0 < size < len(buffer):
            raise BridgeError("unsafe_state", "Cannot resolve Windows state handle")
        resolved = buffer.value.removeprefix("\\\\?\\")
        if ntpath.normcase(ntpath.normpath(resolved)) != ntpath.normcase(expected_path):
            raise BridgeError("unsafe_state", "Windows state path resolves through another object")
        self._inspect_security(handle)

    def _path(self, value):
        raw = str(value)
        if ".." in PureWindowsPath(raw).parts:
            raise BridgeError("unsafe_state", "Relative traversal is forbidden")
        path = validate_local_path(str(Path(value).absolute()))
        # Reject junctions in existing ancestors as well as at the final handle.
        for ancestor in reversed(Path(path).parents):
            attributes = self.kernel.GetFileAttributesW(str(ancestor))
            if attributes == 0xFFFFFFFF:
                if ctypes.get_last_error() not in {2, 3}:
                    raise self._error()
            elif attributes & REPARSE_POINT:
                raise BridgeError("unsafe_state", "Windows state cannot traverse a reparse point")
        return path

    def open(
        self, path, *, directory=False, create=False, create_new=False, exclusive=False, write=False
    ):
        path = self._path(path)
        access = 0x20000 | (0x80 if directory else 0x80000000)  # READ_CONTROL + attributes/read
        if write:
            access |= 0x40000000
        flags = 0x00200000 | (0x02000000 if directory else 0)  # no-follow + directory handle
        with self._attributes() as attributes:
            handle = self.kernel.CreateFileW(
                path,
                access,
                0 if exclusive else 1 | 2 | 4,
                ctypes.byref(attributes),
                1 if create_new else 4 if create else 3,
                flags,
                None,
            )
            error = ctypes.get_last_error()
        if handle == HANDLE(-1).value:
            # LocalFree in _attributes.__exit__ may change this thread's last error.
            raise ctypes.WinError(error)
        try:
            self._inspect(handle, path, directory=directory)
            return handle
        except BaseException:
            self.close(handle)
            raise

    def ensure_directory(self, value):
        path = Path(self._path(value))
        with self._attributes() as attributes:
            for candidate in [*reversed(path.parents), path]:
                existing = self.kernel.GetFileAttributesW(str(candidate))
                if existing != 0xFFFFFFFF:
                    if existing & REPARSE_POINT or not existing & DIRECTORY:
                        raise BridgeError("unsafe_state", "Unsafe Windows directory ancestor")
                    continue
                if ctypes.get_last_error() not in {2, 3}:
                    raise self._error()
                if not self.kernel.CreateDirectoryW(str(candidate), ctypes.byref(attributes)):
                    if ctypes.get_last_error() != 183:  # ERROR_ALREADY_EXISTS
                        raise self._error()
        handle = self.open(path, directory=True)
        self.close(handle)


def private_directory(path):
    WindowsFiles().ensure_directory(path)


def ensure_private_file(path):
    api = WindowsFiles()
    handle = api.open(path, create=True, write=True)
    api.close(handle)


def private_open(path, *, write=False, create=False, create_new=False):
    """Transfer one already verified native file handle into a non-inheritable CRT fd."""
    import msvcrt

    api = WindowsFiles()
    handle = api.open(path, create=create, create_new=create_new, write=write)
    try:
        fd = msvcrt.open_osfhandle(handle, (os.O_RDWR if write else os.O_RDONLY) | os.O_BINARY)
    except BaseException:
        api.close(handle)
        raise
    try:
        os.set_inheritable(fd, False)
    except BaseException:
        os.close(fd)
        raise
    return fd
