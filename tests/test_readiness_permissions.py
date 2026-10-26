from kirabridge.permissions import decision
from kirabridge.readiness import ReadinessInput, readiness


def test_missing_secondary_capability_is_not_ready_and_other_principal_stays_separate(bridge):
    policy = bridge.config.principals["local"]
    policy.approval_mode = "automatic"
    policy.capabilities = ["bridge.health", "session.input"]
    bridge.config.principals["other"].capabilities.extend(["session.inspect", "terminal.execute"])
    original = bridge.store.db.total_changes
    result = readiness(bridge, "local", ReadinessInput(operations=["session.input"]))
    item = result["operation_checks"][0]
    assert item["ok"] is False
    assert item["code"] == "forbidden"
    assert item["permission_decision"] == decision(bridge.config, "local", "session.input")
    assert item["authorized"] is False
    assert item["execution_ready"] is False
    other = readiness(bridge, "other", ReadinessInput(operations=["session.input"]))
    assert other["operation_checks"][0]["authorized"] is True
    assert bridge.store.db.total_changes == original


async def test_manual_permission_and_runtime_are_separate_and_revocation_is_immediate(bridge):
    requirements = ReadinessInput(operations=["file.list"])
    item = readiness(bridge, "other", requirements)["operation_checks"][0]
    assert item["authorized"] is True
    assert item["runtime_ready"] is False
    assert item["execution_ready"] is False
    async with bridge:
        before = bridge.store.db.total_changes
        item = readiness(bridge, "local", requirements)["operation_checks"][0]
        assert item["authorized"] is True
        assert item["approval_required"] is True
        assert item["prerequisites_ready"] is True
        assert item["runtime_ready"] is True
        assert item["execution_ready"] is False
        bridge.config.principals["local"].approval_mode = "automatic"
        item = readiness(bridge, "local", requirements)["operation_checks"][0]
        assert item["execution_ready"] is True
        bridge.config.principals["local"].capabilities.remove("file.list")
        item = readiness(bridge, "local", requirements)["operation_checks"][0]
        assert item["authorized"] is False
        assert item["execution_ready"] is False
        assert bridge.store.db.total_changes == before
