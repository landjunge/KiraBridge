"""Drain own process output with fixed memory bounds, preserving stderr evidence."""

import subprocess
import threading
import time
from types import SimpleNamespace


def run_bounded(argv, *, input, cwd, timeout, env):
    started = time.monotonic()
    process = None
    buffers = [bytearray(), bytearray()]
    truncated = [False, False]
    seen = [0, 0]
    lock = threading.Lock()
    stream_errors = []
    termination_requested = False
    cleanup_error = None

    def snapshot(stage):
        with lock:
            output, errors = (bytes(buffer) for buffer in buffers)
            evidence = {
                "stage": stage,
                "spawn_observed": process is not None,
                "pid": getattr(process, "pid", None),
                "native_exit_code": getattr(process, "returncode", None),
                "elapsed_seconds": time.monotonic() - started,
                "timeout_seconds": timeout,
                "termination_requested": termination_requested,
                "stdout_bytes": seen[0],
                "stderr_bytes": seen[1],
                "output_truncated": any(truncated),
                "stream_errors": list(stream_errors),
            }
        if cleanup_error:
            evidence["cleanup_error_type"] = cleanup_error
        return output, errors, evidence

    def fail(exc, stage):
        output, errors, evidence = snapshot(stage)
        evidence["exception_type"] = type(exc).__name__
        if isinstance(getattr(exc, "errno", None), int):
            evidence["errno"] = exc.errno
        # Never include argv/prompt/environment or arbitrary exception text.
        if isinstance(exc, subprocess.TimeoutExpired):
            failure = subprocess.TimeoutExpired("owned CLI", timeout, output=output, stderr=errors)
        else:
            failure = subprocess.SubprocessError("Owned process transport failure")
            failure.output, failure.stderr = output, errors
        failure.process_evidence = evidence
        raise failure from None

    try:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        fail(exc, "spawn")

    def drain(pipe, index, limit):
        try:
            read = getattr(pipe, "read1", pipe.read)
            while chunk := read(65536):
                with lock:
                    seen[index] += len(chunk)
                    space = max(0, limit - len(buffers[index]))
                    buffers[index].extend(chunk[:space])
                    truncated[index] |= len(chunk) > space
        except OSError as exc:
            with lock:
                stream_errors.append({"stream": index, "exception_type": type(exc).__name__})
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
    try:
        for thread in threads:
            thread.start()
    except RuntimeError as exc:
        fail(exc, "stream_start")
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        # Only this exact newly spawned CLI, never existing agent sessions.
        termination_requested = True
        try:
            process.kill()
            process.wait(timeout=1)
        except (OSError, subprocess.SubprocessError) as cleanup:
            cleanup_error = type(cleanup).__name__
        for thread in threads:
            thread.join(timeout=0.5)
        fail(exc, "wait_main")
    except OSError as exc:
        fail(exc, "wait_main")
    for thread in threads:
        thread.join(timeout=0.5)
    if any(thread.is_alive() for thread in threads):
        fail(subprocess.TimeoutExpired("owned CLI", timeout), "drain_after_exit")
    if stream_errors:
        fail(subprocess.SubprocessError("Stream read failed"), "stream_io")
    output, errors, evidence = snapshot("completed")
    return SimpleNamespace(
        returncode=process.returncode,
        stdout=output,
        stderr=errors,
        output_truncated=any(truncated),
        process_evidence=evidence,
    )
