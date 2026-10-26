"""Execute only the read expression in JXA, with a fake tab and no GUI access."""

import asyncio
import json
import sys

import pytest

from kirabridge.platform_adapters.terminal_app import TerminalAppTransport


@pytest.mark.skipif(sys.platform != "darwin", reason="JXA interpreter is macOS-only")
@pytest.mark.parametrize(
    "text",
    ["🧠" * 32768 + "X", "ascii" * 15000, "短い😀"],
    ids=["surrogate-boundary", "ascii-boundary", "short-unicode"],
)
async def test_terminal_read_suffix_preserves_unicode_scalar_boundaries(text, monkeypatch):
    transport = TerminalAppTransport(asyncio.Lock())
    monkeypatch.setattr(
        transport,
        "native_target",
        lambda _: "const tab = {contents: function() {return " + json.dumps(text) + ";}};",
    )

    async def interpreter_only(source, *, mutation=False):
        assert mutation is False
        assert "Application(" not in source
        child = await asyncio.create_subprocess_exec(
            "/usr/bin/osascript",
            "-l",
            "JavaScript",
            "-",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        async with asyncio.timeout(5):
            stdout, stderr = await child.communicate(source.encode("utf-8"))
        assert child.returncode == 0, stderr.decode()
        return json.loads(stdout)

    monkeypatch.setattr(transport, "native", interpreter_only)
    result = await transport.read("unused-fixture-handle")
    assert result == text[-65536:]
    assert result.encode("utf-8").decode("utf-8") == result
