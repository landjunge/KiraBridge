"""Host guidance is metadata; it neither probes terminals nor changes permission decisions."""

from types import SimpleNamespace

import pytest

from kirabridge.permissions import decision
from kirabridge.terminal_access import terminal_access


@pytest.mark.parametrize(
    "host, platform", [("macos", "darwin"), ("linux", "linux"), ("windows", "win32")]
)
@pytest.mark.parametrize("granted", [False, True])
def test_host_guidance_preserves_policy_and_unprobed_runtime(
    config, monkeypatch, host, platform, granted
):
    monkeypatch.setattr("kirabridge.platform_adapters.sys", SimpleNamespace(platform=platform))
    policy = config.principals["local"]
    policy.capabilities = (
        ["terminal.execute", "session.inspect", "session.input", "session.open"] if granted else []
    )
    policy.permission_level = "ask"
    policy.executables = []
    policy.allow_any_executable = False
    before = config.model_dump()
    result = terminal_access(config, "local")
    assert config.model_dump() == before
    assert result["host_platform"] == host
    assert result["availability"] == "not_probed"
    assert result["grant_is_not_runtime_readiness"] is True
    assert result["policy_authorized"] is granted
    for field, operation in [
        ("input_decision", "session.input"),
        ("direct_command_decision", "terminal.visible"),
        ("new_window_decision", "session.open"),
    ]:
        assert result[field] == decision(config, "local", operation)
        assert result[field]["automatic"] is False
    if host == "macos":
        assert result["direct_command_availability"] == "not_probed"
        assert result["alternative_terminal_route"] is None
        assert result["runtime_requirements"] == [
            "interactive macOS desktop",
            "Terminal.app automation",
            "fresh window/TTY/PID identity",
            "confirmed empty shell input",
        ]
        assert result["description"] == (
            "Terminalrechte sind erteilt. Vorhandene Fenster über den Katalog auswählen; "
            "Lesen und Eingabe verwenden Fenster-ID, TTY und PID. "
            "Ein ausgeschalteter Zusatzpuffer deaktiviert den Terminalzugriff nicht."
            if granted
            else "Terminalrechte sind nicht vollständig erteilt."
        )
    else:
        assert result["direct_command_availability"] == "unsupported_platform"
        assert "macOS desktop" not in " ".join(result["runtime_requirements"])
        alternative = result["alternative_terminal_route"]
        assert alternative["availability"] == "not_probed"
        assert alternative["requires_separate_authorization"] is True
        assert alternative["operation"] == (
            "session.open" if host == "linux" else "windows.console.handoff"
        )
        assert "nicht unterstützt" in result["description"]
