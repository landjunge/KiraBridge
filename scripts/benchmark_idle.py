"""Reproducible, local-only idle resource measurement using temporary state."""

import argparse
import asyncio
import json
import platform
import resource
import sys
import tempfile
import time

from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import Config
from kirabridge.mcp_gateway.server import create_server


async def main(seconds):
    with tempfile.TemporaryDirectory(prefix="kirabridge-benchmark-") as folder:
        async with Bridge(Config(data_dir=folder + "/state")) as bridge:
            create_server(bridge)
            wall, cpu = time.monotonic(), time.process_time()
            await asyncio.sleep(seconds)
            elapsed, used = time.monotonic() - wall, time.process_time() - cpu
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            emit = {
                "os": platform.system(),
                "architecture": platform.machine(),
                "python": platform.python_version(),
                "idle_seconds": round(elapsed, 3),
                "cpu_seconds": round(used, 6),
                "cpu_percent_one_core": round(100 * used / elapsed, 3),
                "peak_rss_mib": round(rss / (1048576 if sys.platform == "darwin" else 1024), 2),
                "execution_workers": bridge.config.concurrency,
                "control_workers": 1,
                "gpu_required": False,
            }
            print(json.dumps(emit, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=5)
    args = parser.parse_args()
    asyncio.run(main(max(1, min(args.seconds, 60))))
