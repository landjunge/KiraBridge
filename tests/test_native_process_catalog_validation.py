"""Native ps format keeps paths with spaces and refuses partial/invalid inventories."""

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from kirabridge.bridge_core.models import BridgeError
from kirabridge.platform_adapters.terminal_app import TerminalAppTransport

VALID = f"  {os.getuid()}   345   1 ttys004 /bin/zsh\n".encode()
SPACE_PATH = "/Applications/Example Name.app/Contents/MacOS/Example Binary"


def catalog_transport(monkeypatch, output, returncode=0):
    transport = TerminalAppTransport(asyncio.Lock(), desktop=object())
    monkeypatch.setattr(
        "kirabridge.platform_adapters.terminal_app.sys", SimpleNamespace(platform="darwin")
    )
    transport.native = AsyncMock(
        return_value=[{"window_id": 123, "tty": "/dev/ttys004", "busy": False}]
    )
    child = SimpleNamespace(
        communicate=AsyncMock(return_value=(output, b"")), returncode=returncode
    )
    spawn = AsyncMock(return_value=child)
    cleanup = AsyncMock()
    monkeypatch.setattr(
        "kirabridge.platform_adapters.terminal_app.asyncio.create_subprocess_exec", spawn
    )
    monkeypatch.setattr("kirabridge.platform_adapters.terminal_app.reap_process", cleanup)
    return transport, child, cleanup


@pytest.mark.parametrize(
    "output,returncode",
    [
        (VALID, 1),
        (b"", 0),
        (VALID + b"partial row\n", 0),
        (VALID + b"501 nope 1 ttys005 /bin/zsh\n", 0),
        (VALID + b"501 456 1 ttys005\n", 0),
        (VALID + b"\xff 456 1 ttys005 /bin/zsh\n", 0),
        (VALID + "² 456 1 ttys005 /bin/zsh\n".encode(), 0),
        (VALID + VALID, 0),
    ],
)
async def test_invalid_native_inventory_raises_typed_observation_error(
    monkeypatch, output, returncode
):
    transport, child, cleanup = catalog_transport(monkeypatch, output, returncode)
    with pytest.raises(BridgeError) as error:
        await transport.catalog()
    assert error.value.code == "session_observation_invalid"
    assert error.value.provider_error["phase"] == "native_process_catalog"
    cleanup.assert_awaited_once_with(child, process_group=False)


async def test_real_mac_ps_field_layout_retains_spaced_executable_paths(monkeypatch):
    output = (
        b"    0   0    0 ?? kernel_task\n"
        + VALID
        + f" {os.getuid()} 346 345 ttys004 {SPACE_PATH}\n".encode()
        + b"    0 999 1 console /System/Library/CoreServices/loginwindow.app/loginwindow\n"
    )
    transport, child, cleanup = catalog_transport(monkeypatch, output)
    rows = await transport.catalog()
    assert len(rows) == 1 and rows[0]["expected_pid"] == 345
    assert rows[0]["processes"][-1]["image"] == SPACE_PATH
    assert rows[0]["processes"][-1]["name"] == "Example Binary"
    cleanup.assert_awaited_once_with(child, process_group=False)


async def test_grouped_catalog_keeps_live_views_legacy_root_and_foreign_boundaries(monkeypatch):
    output = (
        b"0 344 1 ttys000 /usr/bin/login\n"
        b"501 345 344 ttys000 /bin/zsh\n"
        b"501 346 345 ttys000 /Applications/Name With Spaces.app/Contents/MacOS/codex\n"
        b"502 347 1 ttys000 /foreign/worker\n"
        b"501 400 1 ttys003 /bin/zsh\n"
        b"501 401 1 ttys003 /bin/zsh\n"
    )
    transport, _, _ = catalog_transport(monkeypatch, output)
    monkeypatch.setattr(
        "kirabridge.platform_adapters.terminal_app.os", SimpleNamespace(getuid=lambda: 501)
    )
    transport.native.return_value = [
        {"window_id": window, "tty": "/dev/ttys000", "busy": True} for window in (100, 101, 102)
    ] + [{"window_id": 103, "tty": "/dev/ttys003", "busy": False}]
    transport.ended_windows = AsyncMock(return_value={102})

    rows = await transport.catalog()

    assert [row["pane_id"] for row in rows] == ["terminal:100:ttys000", "terminal:101:ttys000"]
    assert all(row["expected_pid"] == 345 and row["legacy_expected_pid"] == 344 for row in rows)
    assert all(row["identity_ambiguous"] for row in rows)
    assert all([p["pid"] for p in row["processes"]] == [345, 346] for row in rows)
    assert transport.last_catalog_incomplete is True
    transport.ended_windows.assert_awaited_once_with([100, 101, 102])
