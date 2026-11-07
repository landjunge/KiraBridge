"""Provider contracts without inspecting or changing the operator desktop."""

from types import SimpleNamespace

import pytest

from kirabridge.bridge_core.models import BridgeError, UncertainExecution
from kirabridge.platform_adapters.macos import CapabilityProbe, MacOSProvider, PermissionProbe


def probe(version="15.7.4", platform="darwin", executable=None):
    return CapabilityProbe(
        facts={
            "platform": platform,
            "os_version": version,
            "os_build": "24G517",
            "architecture": "x86_64",
            "process": {"pid": 42, "executable": "/python"},
        },
        executable=executable or (lambda path: True),
    )


def provider(**kwargs):
    return MacOSProvider(
        terminal_app=SimpleNamespace(desktop=object()),
        clipboard=object(),
        files=object(),
        processes=object(),
        capabilities=kwargs.pop("capabilities", probe()),
        **kwargs,
    )


@pytest.mark.parametrize("version", ["12.0", "15.7.4", "26.7.2", "27.2"])
def test_supported_versions_keep_existing_leaves_without_enabling_optional_features(version):
    snapshot = probe(version).snapshot()
    assert snapshot["capabilities"]["terminal_app"]["available"]
    for optional in ("windows", "capture", "notifications", "preferences"):
        assert not snapshot["capabilities"][optional]["available"]


@pytest.mark.parametrize("version,platform", [("11.7", "darwin"), ("", "darwin"), ("15", "linux")])
def test_unavailable_platform_or_version_does_not_enable_native_provider(version, platform):
    with pytest.raises(BridgeError, match="unavailable") as error:
        provider(capabilities=probe(version, platform)).require("session.input")
    assert error.value.code == "macos_capability_unavailable"


def test_missing_osascript_only_disables_its_leaf():
    snapshot = probe(executable=lambda path: path != "/usr/bin/osascript").snapshot()
    assert not snapshot["capabilities"]["terminal_app"]["available"]
    assert snapshot["capabilities"]["clipboard"]["available"]
    assert snapshot["capabilities"]["files"]["available"]


@pytest.mark.parametrize(
    "protocol,available", [(None, False), (True, False), (2, False), (1, True)]
)
def test_keyboard_requires_its_own_advertised_native_contract(protocol, available):
    current = probe()
    current.native_metadata = lambda: {
        "available": True,
        "reason": "available",
        "keyboard_protocol": protocol,
    }
    leaves = current.snapshot()["capabilities"]
    assert leaves["keyboard"]["available"] is available
    assert leaves["apps"]["available"] is True
    if not available:
        assert leaves["keyboard"]["reason"] == "keyboard_protocol_unavailable"


def test_internal_native_guard_is_available_but_not_advertised_as_public_execution():
    native = provider()
    assert native.require("terminal.native").leaf == "terminal_app"
    assert native.require("file.image").leaf == "files"
    rows = native.operation_catalog(lambda op: {"authorized": True})
    assert "terminal.native" not in {row["operation"] for row in rows}
    assert "file.image" in {row["operation"] for row in rows}


def test_snapshot_and_catalog_do_not_probe_permissions_or_use_leaves():
    def forbidden(resource):
        raise AssertionError("Discovery must not invoke a native permission probe")

    native = provider(permissions=PermissionProbe(reader=forbidden))
    before = native.snapshot()
    rows = native.operation_catalog(lambda op: {"authorized": op != "session.input"})
    assert (
        next(row for row in rows if row["operation"] == "session.input")["eligible_for_submission"]
        is False
    )
    assert native.snapshot() == before
    assert native.leaves["desktop_session"] is native.leaves["terminal_app"].desktop
    before["capabilities"]["terminal_app"]["available"] = False
    assert native.snapshot()["capabilities"]["terminal_app"]["available"]


def test_manual_policy_is_submission_eligibility_not_execution_authorization():
    native = provider()
    rows = native.operation_catalog(lambda op: {"authorized": True, "approval_required": True})
    row = next(item for item in rows if item["operation"] == "session.input")
    assert row["eligible_for_submission"] is True
    assert row["approval_required"] is True
    assert row["os_permission_state"] == "requires_native_target_check"
    assert "executable" not in row


def test_permission_status_is_bound_to_exact_actor_target_identity_and_freshness():
    now = [10.0]
    permissions = PermissionProbe(clock=lambda: now[0])
    identity = {"pid": 10, "executable": "/usr/bin/osascript"}
    permissions.record(
        "automation",
        actor="/usr/bin/osascript",
        target="com.apple.Terminal",
        identity=identity,
        observation={"state": "denied", "method": "test"},
    )
    assert (
        permissions.status(
            "automation",
            actor="/usr/bin/osascript",
            target="com.apple.Terminal",
            identity=identity,
        )["state"]
        == "denied"
    )
    for actor, target, current in [
        ("core", "com.apple.Terminal", identity),
        ("/usr/bin/osascript", "com.apple.systemevents", identity),
        ("/usr/bin/osascript", "com.apple.Terminal", {**identity, "pid": 11}),
        ("/usr/bin/osascript", "com.apple.Terminal", None),
    ]:
        assert (
            permissions.status("automation", actor=actor, target=target, identity=current)["state"]
            == "unknown"
        )
    now[0] += 6
    assert (
        permissions.status(
            "automation",
            actor="/usr/bin/osascript",
            target="com.apple.Terminal",
            identity=identity,
        )["state"]
        == "unknown"
    )


def test_explicit_core_probe_is_not_reused_for_helper_and_does_not_read_clipboard():
    seen = []

    def reader(resource):
        seen.append(resource)
        return {"state": "unknown", "raw_granted": False, "method": "AXIsProcessTrusted"}

    permissions = PermissionProbe(reader=reader)
    permissions.refresh_core(("accessibility",))
    assert seen == ["accessibility"]
    native = provider(permissions=permissions)
    # The Core Boolean says nothing about the existing JXA transport identity.
    native.require("session.input")
    assert native.snapshot()["permissions"][0]["raw_granted"] is False


def test_returned_permission_metadata_cannot_change_cached_identity_or_grant():
    permissions = PermissionProbe()
    identity = {"pid": 10, "executable": "/python"}
    permissions.record(
        "accessibility", actor="core", identity=identity, observation={"state": "denied"}
    )
    exposed = permissions.snapshot()[0]
    exposed["identity"]["pid"] = 11
    exposed["state"] = "granted"
    assert permissions.status("accessibility", actor="core", identity=identity)["state"] == "denied"
    assert (
        permissions.status("accessibility", actor="core", identity={**identity, "pid": 11})["state"]
        == "unknown"
    )


@pytest.mark.parametrize(
    "observation",
    [{"state": "denied"}, {"state": "unknown", "raw_granted": False}, {"state": "not_determined"}],
)
async def test_matching_non_granted_permission_prevents_any_native_invocation(observation):
    identity = {"pid": 10, "executable": "/usr/bin/osascript"}
    permissions = PermissionProbe()
    permissions.record(
        "accessibility", actor="/usr/bin/osascript", identity=identity, observation=observation
    )
    native = provider(permissions=permissions, actor_identities={"/usr/bin/osascript": identity})
    calls = []
    with pytest.raises(BridgeError) as error:
        await native.execute(
            "session.input", lambda: calls.append("input"), revalidate=lambda: calls.append("check")
        )
    assert error.value.code == "macos_permission_denied"
    assert calls == []


async def test_revalidate_runs_before_single_dispatch_and_revocation_after_await_is_checked():
    permissions = PermissionProbe()
    identity = {"pid": 10}
    native = provider(permissions=permissions, actor_identities={"/usr/bin/osascript": identity})
    calls = []

    async def revalidate():
        calls.append("revalidate")
        permissions.record(
            "accessibility",
            actor="/usr/bin/osascript",
            identity=identity,
            observation={"state": "denied"},
        )

    with pytest.raises(BridgeError) as error:
        await native.execute("session.input", lambda: calls.append("effect"), revalidate=revalidate)
    assert error.value.code == "macos_permission_denied"
    assert calls == ["revalidate"]


async def test_unknown_effect_is_never_retried_or_routed_to_another_leaf():
    native = provider()
    calls = []

    def invoke():
        calls.append("effect")
        raise UncertainExecution("session_input_unknown", "No replay")

    with pytest.raises(UncertainExecution):
        await native.execute("session.input", invoke, revalidate=lambda: calls.append("checked"))
    assert calls == ["checked", "effect"]


async def test_false_revalidation_and_stale_revision_stop_before_effect():
    native = provider()
    calls = []
    with pytest.raises(BridgeError) as error:
        await native.execute(
            "clipboard.write", lambda: calls.append("effect"), revalidate=lambda: False
        )
    assert error.value.code == "macos_revalidation_denied"
    with pytest.raises(BridgeError) as error:
        await native.execute(
            "clipboard.write",
            lambda: calls.append("effect"),
            revalidate=lambda: None,
            expected_revision="stale",
        )
    assert error.value.code == "macos_provider_changed"
    assert calls == []


async def test_existing_leaf_result_is_preserved_and_only_called_once():
    native = provider()
    expected = {"return_sent": False, "execution_confirmed": False}
    calls = []

    async def invoke():
        calls.append("invoke")
        return expected

    result = await native.execute(
        "session.input", invoke, revalidate=lambda: calls.append("validate")
    )
    assert result is expected
    assert calls == ["validate", "invoke"]


def test_unbound_leaf_and_unknown_operation_do_not_gain_an_executor():
    native = MacOSProvider(capabilities=probe())
    with pytest.raises(BridgeError):
        native.require("clipboard.read")
    with pytest.raises(BridgeError) as error:
        native.require("capture.start")
    assert error.value.code == "macos_operation_unavailable"
