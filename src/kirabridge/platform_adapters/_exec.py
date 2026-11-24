"""Internal POSIX trampoline: fchdir without unsafe preexec_fn in a threaded parent."""

import os
import sys


def main():
    cwd_fd, status_fd = int(sys.argv[1]), int(sys.argv[2])
    start = 3
    gate_fd = -1
    if sys.argv[3:4] == ["--start-gate"]:
        gate_fd = int(sys.argv[4])
        start = 5
    try:
        os.fchdir(cwd_fd)
        os.close(cwd_fd)
        if gate_fd != -1:
            os.write(status_fd, b"READY\n")
            while os.read(gate_fd, 4096):
                pass
            os.close(gate_fd)
        os.set_inheritable(status_fd, False)
        os.execve(sys.argv[start], sys.argv[start:], os.environ)
    except OSError:
        os.write(status_fd, b"exec_failed")
        os._exit(127)


if __name__ == "__main__":
    main()
