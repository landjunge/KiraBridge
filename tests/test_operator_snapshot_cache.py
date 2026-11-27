"""Console status polling spawns ps/launchctl once per cache window."""

import asyncio

from kirabridge import operator_control
from kirabridge.operator_control import OperatorControl


def test_snapshot_reuses_observation_within_ttl(monkeypatch):
    spawns = []
    control = OperatorControl.__new__(OperatorControl)
    control.cache, control.cache_at = None, 0.0
    control.status_lock = asyncio.Lock()
    now = [1000.0]
    monkeypatch.setattr(operator_control.time, "monotonic", lambda: now[0])

    async def processes():
        spawns.append("ps")
        raise RuntimeError("stop after the observation")

    control.processes = processes
    control.config = lambda: None
    control.cache, control.cache_at = {"cached": True}, now[0]

    async def run():
        results = [await control.snapshot() for _ in range(5)]
        now[0] += operator_control.SNAPSHOT_TTL_SECONDS + 1
        try:
            await control.snapshot()
        except RuntimeError:
            pass
        return results

    results = asyncio.run(run())
    assert all(r == {"cached": True} for r in results)
    assert spawns == ["ps"]  # 6 polls -> 1 observation (was 6 with the 2 s window)
