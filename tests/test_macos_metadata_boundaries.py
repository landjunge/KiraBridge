"""Malformed passive plist metadata must not break discovery or start a worker."""

import io
import plistlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from kirabridge.bridge_core.models import BridgeError
from kirabridge.platform_adapters.macos import capabilities
from kirabridge.platform_adapters.macos import system_transport as native


@pytest.mark.parametrize("metadata", [[], ["not a mapping"], "text", 42, True, b"bytes"])
async def test_native_non_mapping_plist_is_unavailable_before_launch(
    tmp_path, monkeypatch, metadata
):
    monkeypatch.setattr(native.sys, "platform", "darwin")
    app = tmp_path / "KiraBridge.app"
    (app / "Contents").mkdir(parents=True)
    (app / "Contents/Info.plist").write_bytes(plistlib.dumps(metadata))
    spawn = AsyncMock(side_effect=AssertionError("Passive discovery must not start a worker"))
    worker = native.NativeSystemTransport(app, process_factory=spawn)

    assert worker.snapshot_metadata() == {
        "available": False,
        "reason": "native_app_protocol_unavailable",
    }
    probe = capabilities.CapabilityProbe(
        facts={"platform": "darwin", "os_version": "15.7.4"},
        executable=lambda _: True,
        native_metadata=worker.snapshot_metadata,
    )
    assert probe.snapshot()["capabilities"]["system"]["available"] is False
    with pytest.raises(BridgeError) as caught:
        await worker.request("system.info", {}, principal="local")
    assert caught.value.code == "system_transport_unavailable"
    spawn.assert_not_awaited()


@pytest.mark.parametrize("metadata", [[], ["not a mapping"], "text", 42, True, b"bytes"])
def test_host_non_mapping_plist_yields_unknown_version(monkeypatch, metadata):
    monkeypatch.setattr(capabilities.sys, "platform", "darwin")
    raw = plistlib.dumps(metadata)

    def metadata_path(path):
        assert path == "/System/Library/CoreServices/SystemVersion.plist"
        return SimpleNamespace(open=lambda mode: io.BytesIO(raw))

    monkeypatch.setattr(capabilities, "Path", metadata_path)
    facts = capabilities.host_facts()
    assert facts["platform"] == "darwin"
    assert facts["os_version"] == ""
    assert facts["os_build"] == ""
