"""Program extensions register semantics, without editing or importing OS code."""

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from kirabridge.cli_adapters import AdapterRegistry, Capabilities, adapter_for


class FixtureAdapter:
    name = "fixture_cli"
    capabilities = Capabilities(text=True)

    def input_view(self, raw):
        return raw.removeprefix("fixture:")

    def observe(self, raw, binding, protocol=None):
        return {"ui_state": "composer", "work_state": "unknown", "ready": raw == "fixture:ready"}

    def return_readiness(self, *args):
        return {"ready": False, "reason": "unsupported_program_action"}

    def insertion_observed(self, raw, text, before, **options):
        return raw == "fixture:" + text

    def navigation_preserves(self, before, after, observation, after_state):
        return False

    async def protocol_state(self, binding, observer):
        return None

    def has_bound_protocol(self, binding):
        return False

    def paste_source(self, text):
        return None

    def slash_insertion_observed(self, sessions, binding, raw, text, before, **options):
        return self.insertion_observed(raw, text, before, **options)

    def command_result(self, command, before, after, binding, protocol=None):
        return {"acceptance_observed": False}

    def allows_text(self, text, submit):
        return True

    async def preflight_input(self, sessions, binding, text, before):
        return None


def test_registration_extends_observation_without_terminal_core_changes():
    registry = AdapterRegistry([FixtureAdapter()])
    assert registry.get("fixture_cli").observe("fixture:ready", None)["ready"]
    assert registry.describe("fixture_cli")["capabilities"]["text"]
    assert not registry.get("unregistered").observe("", None)["ready"]
    with pytest.raises(ValueError):
        registry.register(FixtureAdapter())


def test_new_adapter_reaches_existing_common_dispatch_facades(monkeypatch):
    import kirabridge.cli_adapters as adapters
    from kirabridge.literal_session_input import insertion_observed
    from kirabridge.session_return import return_readiness
    from kirabridge.visible_readiness import assess, input_view

    monkeypatch.setattr(adapters, "_default", AdapterRegistry([FixtureAdapter()]))
    assert assess("fixture_cli", "fixture:ready", None)["ready"]
    assert input_view("fixture_cli", "fixture:payload") == "payload"
    assert insertion_observed("fixture_cli", "fixture:payload", "payload", "fixture:ready")
    assert not return_readiness("fixture_cli", "fixture:ready", None)["ready"]


def test_builtin_capabilities_separate_codex_and_grok_without_cost_or_permission_claims():
    assert adapter_for("codex").capabilities.return_to_input
    assert adapter_for("codex").capabilities.slash_commands == ("/status", "/model", "/resume")
    grok = adapter_for("grok")
    assert grok.capabilities.text and not grok.capabilities.return_to_input
    assert not grok.return_readiness("anything", SimpleNamespace())["ready"]


def test_program_modules_cannot_import_task_dispatch_or_native_terminal_owner():
    root = Path(__file__).parents[1] / "src/kirabridge"
    forbidden = {
        "kirabridge.bridge_core.bridge",
        "kirabridge.session_manager",
        "kirabridge.visible_handoff",
        "kirabridge.platform_adapters.terminal_app",
        "kirabridge.literal_session_input",
        "kirabridge.visible_readiness",
        "kirabridge.session_return",
    }
    for path in (root / "cli_adapters").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom):
                assert node.module not in forbidden, (path, node.module)
    source = (root / "platform_adapters/terminal_app.py").read_text()
    assert 'target == "codex"' not in source and 'target == "grok"' not in source
    assert "from kirabridge.literal_session_input" not in source
