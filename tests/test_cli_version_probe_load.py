"""Background CLI version probe: cached, sequential, probe only on change."""

import asyncio
import os
import stat

from kirabridge.agent_manager import cli_versions


def _fake_cli(tmp_path, version="1.2.3"):
    path = tmp_path / "grok"
    path.write_text(f"#!/bin/sh\necho {version}\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_cache_probes_once_until_binary_changes(tmp_path, monkeypatch):
    cli = _fake_cli(tmp_path)
    monkeypatch.setenv("PATH", str(tmp_path))
    calls = []
    real = cli_versions._probe

    async def counting(executable):
        calls.append(executable)
        return await real(executable)

    monkeypatch.setattr(cli_versions, "_probe", counting)
    cache: dict = {}

    def run(**kw):
        return asyncio.run(
            cli_versions.inventory({}, [], set(), cache=cache, sequential=True, **kw)
        )

    rows = run()
    assert [r["version"] for r in rows if r["cli"] == "grok"] == ["1.2.3"]
    run()
    run()
    assert len(calls) == 1  # was 3 before: one spawn per run
    run(force=True)
    assert len(calls) == 2
    cli.write_text("#!/bin/sh\necho 1.2.4 extra\n")
    os.utime(cli, ns=(1, 1))
    rows = run()
    assert len(calls) == 3
    assert [r["version"] for r in rows if r["cli"] == "grok"] == ["1.2.4"]


def test_failed_probe_is_not_cached(tmp_path, monkeypatch):
    _fake_cli(tmp_path, version="none")
    monkeypatch.setenv("PATH", str(tmp_path))
    cache: dict = {}
    asyncio.run(cli_versions.inventory({}, [], set(), cache=cache, sequential=True))
    assert cache == {}
