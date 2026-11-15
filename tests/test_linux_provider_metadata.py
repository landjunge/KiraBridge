"""Passive Linux metadata never grants or reroutes a native operation."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from macos_provider_fixture import bind_macos_provider

import kirabridge.bridge_core.bridge as bridge_module
from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.models import BridgeError
from kirabridge.discovery import snapshot
from kirabridge.platform_adapters.linux.provider import LinuxProvider
from kirabridge.platform_adapters.macos import CapabilityProbe, MacOSProvider, PermissionProbe


def facts(platform="linux"):
    return {
        "platform": platform,
        "os_version": "15.7" if platform == "darwin" else "",
        "os_build": "",
        "architecture": "x86_64",
        "process": {"pid": 42, "executable": "/python"},
    }


def forbidden(*args, **kwargs):
    raise AssertionError("Metadata must not probe or invoke a transport")


def provider(**kwargs):
    return LinuxProvider(
        files=object(),
        processes=object(),
        owned_terminal=object(),
        terminal_app=SimpleNamespace(desktop=object()),
        capabilities=CapabilityProbe(
            facts=facts(), executable=forbidden, native_metadata=forbidden
        ),
        permissions=PermissionProbe(reader=forbidden),
        **kwargs,
    )


@pytest.mark.parametrize("leaf", ["files", "processes", "owned_terminal"])
def test_bound_leaf_is_not_a_transport_success_or_permission_grant(leaf):
    native = provider()
    row = native.snapshot()["capabilities"][leaf]
    assert row["supported"] and row["bound"]
    assert row["available"] is False
    assert row["state"] == "unknown" and row["reason"] == "transport_not_probed"
    assert row["runtime_availability"] == "not_probed"
    # Snapshot facts follow the actual binding, not a cached OS-name assumption.
    native.leaves[leaf] = None
    missing = native.snapshot()["capabilities"][leaf]
    assert missing["supported"] and not missing["bound"]
    assert missing["available"] is False and missing["state"] == "unavailable"
    assert missing["reason"] == "transport_not_bound"


def test_linux_snapshot_keeps_desktop_unsupported_and_revision_stable():
    native = provider()
    before = native.snapshot()
    assert before["provider_id"] == "linux.existing_native"
    assert before["provider_version"] == "1" and before["host"]["platform"] == "linux"
    for leaf in ("terminal_app", "clipboard", "windows", "capture", "keyboard"):
        assert before["capabilities"][leaf]["available"] is False
        assert before["capabilities"][leaf]["reason"] == "unsupported_platform"
    assert native.snapshot() == before
    before["capabilities"]["files"]["bound"] = False
    assert native.snapshot()["capabilities"]["files"]["bound"]
    revision = native.snapshot()["revision"]
    native.leaves["files"] = None
    assert native.snapshot()["revision"] != revision
    assert native.snapshot()["revision"] == native.snapshot()["revision"]


def test_provider_does_not_replace_descriptors_permissions_or_execution_guards():
    native = provider()
    legacy = MacOSProvider(capabilities=CapabilityProbe(facts=facts()))
    assert native.descriptors == legacy.descriptors
    assert all(native.descriptors[op] is item for op, item in legacy.descriptors.items())
    assert LinuxProvider.require is MacOSProvider.require
    assert LinuxProvider.execute is MacOSProvider.execute
    assert not any(item.leaf == "owned_terminal" for item in native.descriptors.values())
    for operation in ("session.read", "session.input", "session.close", "terminal.visible"):
        assert (
            native.descriptors[operation].permissions == legacy.descriptors[operation].permissions
        )
        assert native.descriptors[operation].permissions

    def denied(op):
        return {"authorized": False, "approval_required": True}

    rows = native.operation_catalog(denied)
    previous = legacy.operation_catalog(denied)
    # Only the provider label changes; operation policy, eligibility, permission
    # and leaf routing remain the original contract, including unknown checks.
    assert [dict(row, provider_id="same") for row in rows] == [
        dict(row, provider_id="same") for row in previous
    ]
    assert native.snapshot()["provider_id"] == "linux.existing_native"


@pytest.mark.parametrize("operation", ["file.read", "process.list", "session.input"])
def test_unprobed_linux_metadata_does_not_enable_the_legacy_native_guard(operation):
    with pytest.raises(BridgeError) as error:
        provider().require(operation)
    assert error.value.code == "macos_capability_unavailable"


async def test_all_existing_native_guards_keep_their_linux_outcome_after_metadata_change():
    native = provider()
    previous = MacOSProvider(capabilities=CapabilityProbe(facts=facts()))
    for operation in previous.descriptors:
        with pytest.raises(BridgeError) as before:
            previous.require(operation)
        with pytest.raises(BridgeError) as after:
            native.require(operation)
        assert (after.value.code, str(after.value)) == (before.value.code, str(before.value))
        # execute consumes the same capability facts indirectly through require;
        # changed metadata must not permit even revalidation or the first effect.
        with pytest.raises(BridgeError) as execution:
            await native.execute(operation, forbidden, revalidate=forbidden)
        assert execution.value.code == before.value.code


@pytest.fixture
def linux_bridge(config, monkeypatch):
    monkeypatch.setattr(bridge_module, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(
        "kirabridge.platform_adapters.macos.capabilities.host_facts", lambda: facts()
    )
    instance = Bridge(config)
    yield instance
    instance.store.close()


def test_bridge_discovery_binds_linux_metadata_to_existing_leaf_objects(linux_bridge):
    native = linux_bridge.macos
    assert isinstance(native, LinuxProvider)
    assert native.leaves["files"] is linux_bridge.filesystem
    assert native.leaves["processes"] is linux_bridge.processes
    assert native.leaves["owned_terminal"] is linux_bridge.sessions.linux
    before = linux_bridge.config.model_dump()
    observed = snapshot(linux_bridge, "local")["platform"]
    assert observed["provider_id"] == "linux.existing_native"
    assert observed["host"]["platform"] == "linux"
    assert observed["capabilities"]["owned_terminal"]["state"] == "unknown"
    assert linux_bridge.config.model_dump() == before


def test_metadata_does_not_grant_an_existing_actor_a_missing_capability(linux_bridge):
    policy = linux_bridge.config.principals["local"]
    policy.capabilities.remove("session.input")
    before = policy.model_dump()
    snapshot(linux_bridge, "local")
    linux_bridge.macos.operation_catalog(lambda op: {"authorized": False})
    assert policy.model_dump() == before
    with pytest.raises(BridgeError):
        linux_bridge.security.principal("local", "session.input")


def test_explicit_mac_fixture_keeps_other_linux_bindings_and_policy_unchanged(linux_bridge):
    original = linux_bridge.macos
    config = linux_bridge.config.model_dump()
    native = bind_macos_provider(linux_bridge)
    assert type(native) is MacOSProvider
    assert linux_bridge.native_queries.provider is native
    assert native.permission_probe is original.permission_probe
    assert native.descriptors == original.descriptors
    assert native.leaves["files"] is original.leaves["files"]
    assert bind_macos_provider(linux_bridge) is native
    native.capability_probe.facts.update(platform="darwin", os_version="15.7.4")
    assert native.snapshot()["provider_id"] == "macos.existing_native"
    assert native.snapshot()["capabilities"]["files"]["available"]
    assert original.snapshot()["provider_id"] == "linux.existing_native"
    assert original.snapshot()["capabilities"]["files"]["available"] is False
    assert linux_bridge.config.model_dump() == config


@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_other_hosts_keep_existing_provider_selection(config, monkeypatch, platform):
    monkeypatch.setattr(bridge_module, "sys", SimpleNamespace(platform=platform))
    instance = Bridge(config)
    try:
        assert type(instance.macos) is MacOSProvider
    finally:
        instance.store.close()


@pytest.mark.parametrize(
    "operation",
    ["file.list", "process.list", "session.input", "terminal.visible", "terminal.execute"],
)
async def test_linux_portable_dispatch_never_enters_the_desktop_provider(linux_bridge, operation):
    expected = {"original_route": operation}
    dispatch = AsyncMock(return_value=expected)
    linux_bridge._execute_operation = dispatch
    linux_bridge.macos.execute = AsyncMock(side_effect=AssertionError("No desktop dispatch"))
    task = {"id": "metadata-route", "principal": "local", "operation": operation, "args": {}}
    assert linux_bridge.platform_operation(operation, {}, "local") is None
    assert await linux_bridge.execute(task, AsyncMock(), AsyncMock()) is expected
    dispatch.assert_awaited_once()
    linux_bridge.macos.execute.assert_not_awaited()
