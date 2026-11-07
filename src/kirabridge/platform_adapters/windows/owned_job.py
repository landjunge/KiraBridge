"""A suspended owned child joins a kill-on-close job before running any code."""

from __future__ import annotations

import ctypes


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("process_time", ctypes.c_int64),
        ("job_time", ctypes.c_int64),
        ("flags", ctypes.c_uint32),
        ("min_working_set", ctypes.c_size_t),
        ("max_working_set", ctypes.c_size_t),
        ("active_processes", ctypes.c_uint32),
        ("affinity", ctypes.c_size_t),
        ("priority", ctypes.c_uint32),
        ("scheduling", ctypes.c_uint32),
    ]


class _IOCounters(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_uint64)
        for name in (
            "read_ops",
            "write_ops",
            "other_ops",
            "read_bytes",
            "write_bytes",
            "other_bytes",
        )
    ]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("basic", _BasicLimits),
        ("io", _IOCounters),
        ("process_memory", ctypes.c_size_t),
        ("job_memory", ctypes.c_size_t),
        ("peak_process_memory", ctypes.c_size_t),
        ("peak_job_memory", ctypes.c_size_t),
    ]


class _ThreadEntry(ctypes.Structure):
    _fields_ = [
        ("size", ctypes.c_uint32),
        ("usage", ctypes.c_uint32),
        ("tid", ctypes.c_uint32),
        ("pid", ctypes.c_uint32),
        ("base_priority", ctypes.c_int32),
        ("delta_priority", ctypes.c_int32),
        ("flags", ctypes.c_uint32),
    ]


class WindowsChildJob:
    def __init__(self):
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel = self.kernel
        handle = ctypes.c_void_p
        boolean = ctypes.c_int
        dword = ctypes.c_uint32
        kernel.CreateJobObjectW.argtypes = [handle, ctypes.c_wchar_p]
        kernel.CreateJobObjectW.restype = handle
        kernel.SetInformationJobObject.argtypes = [handle, ctypes.c_int, handle, dword]
        kernel.SetInformationJobObject.restype = boolean
        kernel.AssignProcessToJobObject.argtypes = [handle, handle]
        kernel.AssignProcessToJobObject.restype = boolean
        kernel.TerminateJobObject.argtypes = [handle, dword]
        kernel.TerminateJobObject.restype = boolean
        kernel.CloseHandle.argtypes = [handle]
        kernel.CloseHandle.restype = boolean
        kernel.CreateToolhelp32Snapshot.argtypes = [dword, dword]
        kernel.CreateToolhelp32Snapshot.restype = handle
        kernel.Thread32First.argtypes = [handle, ctypes.POINTER(_ThreadEntry)]
        kernel.Thread32First.restype = boolean
        kernel.Thread32Next.argtypes = [handle, ctypes.POINTER(_ThreadEntry)]
        kernel.Thread32Next.restype = boolean
        kernel.OpenThread.argtypes = [dword, boolean, dword]
        kernel.OpenThread.restype = handle
        kernel.GetProcessIdOfThread.argtypes = [handle]
        kernel.GetProcessIdOfThread.restype = dword
        kernel.ResumeThread.argtypes = [handle]
        kernel.ResumeThread.restype = dword
        self.handle = kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = _ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel.SetInformationJobObject(
            self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            error = ctypes.get_last_error()
            self.close()
            raise ctypes.WinError(error)

    def assign_and_resume(self, process):
        # CREATE_SUSPENDED prevents the leader from spawning an escaping child
        # before job assignment. Popen retains the exact owned process handle.
        if not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise ctypes.WinError(ctypes.get_last_error())
        snapshot = self.kernel.CreateToolhelp32Snapshot(4, 0)  # TH32CS_SNAPTHREAD
        if snapshot == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        tids = []
        try:
            entry = _ThreadEntry()
            entry.size = ctypes.sizeof(entry)
            more = self.kernel.Thread32First(snapshot, ctypes.byref(entry))
            while more:
                if entry.pid == process.pid:
                    tids.append(entry.tid)
                more = self.kernel.Thread32Next(snapshot, ctypes.byref(entry))
        finally:
            self.kernel.CloseHandle(snapshot)
        if len(tids) != 1:
            raise OSError("Cannot identify the suspended owned primary thread")
        thread = self.kernel.OpenThread(0x42, False, tids[0])  # query + suspend/resume
        if not thread:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if self.kernel.GetProcessIdOfThread(thread) != process.pid:
                raise OSError("Owned thread identity changed before resume")
            if self.kernel.ResumeThread(thread) != 1:
                raise OSError("Owned primary thread suspend state changed")
        finally:
            self.kernel.CloseHandle(thread)

    def terminate(self):
        if not self.kernel.TerminateJobObject(self.handle, 1):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
