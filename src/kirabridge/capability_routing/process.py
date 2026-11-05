"""Drain own process output with fixed memory bounds, preserving stderr evidence."""

import subprocess
import threading
from types import SimpleNamespace


def run_bounded(argv, *, input, cwd, timeout, env):
    process = subprocess.Popen(
        argv,
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    buffers = [bytearray(), bytearray()]
    truncated = [False, False]

    def drain(pipe, index, limit):
        try:
            while chunk := pipe.read(65536):
                space = max(0, limit - len(buffers[index]))
                buffers[index].extend(chunk[:space])
                truncated[index] |= len(chunk) > space
        finally:
            pipe.close()

    def feed():
        try:
            process.stdin.write(input or b"")
            process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
        finally:
            process.stdin.close()

    threads = [
        threading.Thread(target=drain, args=(process.stdout, 0, 1048576), daemon=True),
        threading.Thread(target=drain, args=(process.stderr, 1, 65536), daemon=True),
        threading.Thread(target=feed, daemon=True),
    ]
    for thread in threads:
        thread.start()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        # Only this exact newly spawned CLI, never existing agent sessions.
        process.kill()
        process.wait()
        raise
    for thread in threads:
        thread.join(timeout=0.5)
    if any(thread.is_alive() for thread in threads):
        raise subprocess.TimeoutExpired(argv[0], timeout)
    return SimpleNamespace(
        returncode=process.returncode,
        stdout=bytes(buffers[0]),
        stderr=bytes(buffers[1]),
        output_truncated=any(truncated),
    )
