"""R4's bounded local fake CLI. No model, terminal UI, result, or return."""

import json
import os
import signal
import sys
import time
from pathlib import Path


def publish(path, value):
    path = Path(path)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as stream:
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def main(control_path):
    control = json.loads(Path(control_path).read_text())
    identity = {"nonce": control["nonce"], "pid": os.getpid(), "ppid": os.getppid()}

    def deadline_expired(*_):
        raise TimeoutError("Owned fixture's ten-second lifetime expired")

    signal.signal(signal.SIGALRM, deadline_expired)
    signal.alarm(10)
    deadline = time.monotonic() + 10
    reason = "deadline"
    try:
        sys.stdin.read()
        with Path(control["counter"]).open("a") as counter:
            counter.write(json.dumps({**identity, "argv": sys.argv[1:]}) + "\n")
            counter.flush()
            os.fsync(counter.fileno())
        print(json.dumps({"type": "thread.started", "thread_id": control["session"]}), flush=True)
        print(json.dumps({"type": "turn.started"}), flush=True)
        publish(control["started"], {**identity, "stage": "started", "at": time.time()})
        while time.monotonic() < deadline:
            try:
                if json.loads(Path(control["release"]).read_text()) == {"nonce": control["nonce"]}:
                    reason = "released"
                    break
            except (FileNotFoundError, json.JSONDecodeError):
                pass
            time.sleep(0.02)
    except TimeoutError:
        pass
    finally:
        signal.alarm(0)
        # Never write a result/completion to the pipe whose Core may now be gone.
        publish(
            control["exited"], {**identity, "stage": "exiting", "reason": reason, "at": time.time()}
        )


if __name__ == "__main__":
    main(globals()["R4_CONTROL"])
