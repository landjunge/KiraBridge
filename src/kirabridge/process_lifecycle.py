"""Kernel-native process generation: (boot identity, PID, kernel birth).

A PID number alone is never identity. A *generation* is compared only for
equality with a generation recorded at an exact, authorized, fresh observation.
It is never ordered against wall-clock timestamps and never inferred for legacy
records. Where no trusted adapter exists the result is ``None`` (unverified).

* macOS: ``proc_pidinfo(PROC_PIDTBSDINFO)`` -> ``pbi_start_tvsec/usec`` (set once
  by the kernel at fork), plus ``sysctl kern.bootsessionuuid``.
* Linux: ``/proc/<pid>/stat`` field 22 ``starttime`` (clock ticks since boot),
  plus ``/proc/sys/kernel/random/boot_id``.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import sys

PROC_PIDTBSDINFO = 3
_MAXCOMLEN = 16


class _ProcBsdInfo(ctypes.Structure):
    # <sys/proc_info.h> struct proc_bsdinfo (136 bytes on arm64/x86_64).
    _fields_ = [
        ("pbi_flags", ctypes.c_uint32),
        ("pbi_status", ctypes.c_uint32),
        ("pbi_xstatus", ctypes.c_uint32),
        ("pbi_pid", ctypes.c_uint32),
        ("pbi_ppid", ctypes.c_uint32),
        ("pbi_uid", ctypes.c_uint32),
        ("pbi_gid", ctypes.c_uint32),
        ("pbi_ruid", ctypes.c_uint32),
        ("pbi_rgid", ctypes.c_uint32),
        ("pbi_svuid", ctypes.c_uint32),
        ("pbi_svgid", ctypes.c_uint32),
        ("rfu_1", ctypes.c_uint32),
        ("pbi_comm", ctypes.c_char * _MAXCOMLEN),
        ("pbi_name", ctypes.c_char * (2 * _MAXCOMLEN)),
        ("pbi_nfiles", ctypes.c_uint32),
        ("pbi_pgid", ctypes.c_uint32),
        ("pbi_pjobc", ctypes.c_uint32),
        ("e_tdev", ctypes.c_uint32),
        ("e_tpgid", ctypes.c_uint32),
        ("pbi_nice", ctypes.c_int32),
        ("pbi_start_tvsec", ctypes.c_uint64),
        ("pbi_start_tvusec", ctypes.c_uint64),
    ]


_libproc = None
_libc = None


def _darwin_libs():
    global _libproc, _libc
    if _libproc is None:
        _libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        _libproc.proc_pidinfo.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint64,
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        _libproc.proc_pidinfo.restype = ctypes.c_int
        _libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        _libc.sysctlbyname.argtypes = [
            ctypes.c_char_p,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_size_t),
            ctypes.c_void_p,
            ctypes.c_size_t,
        ]
        _libc.sysctlbyname.restype = ctypes.c_int
    return _libproc, _libc


def boot_identity() -> str | None:
    """Kernel boot identity, or None when no trusted source is available."""
    try:
        if sys.platform == "darwin":
            _, libc = _darwin_libs()
            size = ctypes.c_size_t(64)
            buffer = ctypes.create_string_buffer(64)
            if libc.sysctlbyname(b"kern.bootsessionuuid", buffer, ctypes.byref(size), None, 0):
                return None
            value = buffer.value.decode("ascii", "strict").strip()
        elif sys.platform.startswith("linux"):
            with open("/proc/sys/kernel/random/boot_id", encoding="ascii") as handle:
                value = handle.read(128).strip()
        else:
            return None
    except (OSError, UnicodeError, AttributeError):
        return None
    return value if 8 <= len(value) <= 64 else None


def _darwin_generation(pid):
    libproc, _ = _darwin_libs()
    info = _ProcBsdInfo()
    size = ctypes.sizeof(info)
    written = libproc.proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, ctypes.byref(info), size)
    if written != size or info.pbi_pid != pid or not info.pbi_start_tvsec:
        return None
    return {
        "birth": f"{info.pbi_start_tvsec}.{info.pbi_start_tvusec:06d}",
        "ppid": info.pbi_ppid,
        "pgid": info.pbi_pgid,
        "uid": info.pbi_uid,
        "tdev": info.e_tdev,
    }


def _linux_generation(pid):
    with open(f"/proc/{pid}/stat", "rb") as handle:
        raw = handle.read(4096).decode("utf-8", "replace")
    end = raw.rfind(")")
    rest = raw[end + 2 :].split() if end > 0 else []
    if len(rest) < 20 or not rest[19].isdigit():
        return None
    return {
        "birth": rest[19],
        "ppid": int(rest[1]),
        "pgid": int(rest[2]),
        "uid": os.stat(f"/proc/{pid}").st_uid,
        "tdev": int(rest[4]),
    }


def process_generation(pid, boot=None) -> dict | None:
    """One live PID's kernel generation, or None (absent, foreign, or unverifiable)."""
    if type(pid) is not int or pid <= 0:
        return None
    boot = boot if boot is not None else boot_identity()
    if boot is None:
        return None
    try:
        if sys.platform == "darwin":
            observed = _darwin_generation(pid)
        elif sys.platform.startswith("linux"):
            observed = _linux_generation(pid)
        else:
            return None
    except (OSError, ValueError, AttributeError):
        return None
    if observed is None or observed["uid"] != os.getuid():
        return None
    return {"boot": boot, "pid": pid, **observed}


def same_generation(recorded, observed) -> bool:
    """Equality of immutable kernel facts only; ppid/pgid/tty may legitimately change."""
    return (
        isinstance(recorded, dict)
        and isinstance(observed, dict)
        and all(recorded.get(key) == observed.get(key) for key in ("boot", "pid", "birth"))
        and recorded.get("boot") is not None
    )


def fresh_generations(pids) -> dict | None:
    """Generations for all PIDs under one boot identity, or None when any is unverifiable."""
    boot = boot_identity()
    if boot is None:
        return None
    result = {}
    for pid in pids:
        value = process_generation(pid, boot)
        if value is None:
            return None
        result[pid] = value
    return result
