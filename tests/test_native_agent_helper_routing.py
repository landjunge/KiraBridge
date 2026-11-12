"""The target app's own helpers are UI infrastructure, not hosted agents.

The semantic cases run in the compiled Swift fixture. This test guards the
production call site and the retained blanket agent/terminal protection from
being silently bypassed or widened again.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def swift(name: str) -> str:
    return (ROOT / "integrations" / "desktop" / name).read_text()


def body(source: str, start: str, end: str) -> str:
    return source.split(start, 1)[1].split(end, 1)[0]


def test_descendant_guard_uses_the_explicit_app_owned_helper_rule():
    control = swift("SystemControl.swift")
    guard = body(
        control,
        "static func protectLiveTerminalDescendants(",
        "\n    static func axGranted(",
    )
    # The old inline (knownProtected || tty) decision also caught the target
    # app itself. The final decision must use the explicit helper predicate.
    decision = guard.split("if blocking.contains(where:", 1)[1]
    assert "requiresGuardedRoute(" in decision
    assert "knownProtected" not in decision
    # Electron helpers are not AppKit applications, so their public path must be
    # observed with kernel identity binding before a helper can be exempted.
    assert "SystemServices.read(" in guard
    assert "blocking[index] = observed" in guard
    assert "blocking.count <= 128" in guard


def test_app_owned_helper_requires_exact_bundle_no_tty_and_helper_identity():
    control = swift("SystemControl.swift")
    helper = body(
        control,
        "static func isAppOwnedHelper(",
        "\n    /// A descendant that still requires",
    )
    assert "!record.tty" in helper
    assert 'bundle.hasSuffix(".app")' in helper
    assert 'executable.hasPrefix(bundle + "/")' in helper
    assert "executable == main" in helper
    assert r" helper( \\([a-z]+\\))?$" in helper


def test_blanket_agent_and_terminal_protection_remains():
    services = swift("SystemServices.swift")
    protected = body(services, "static func knownProtected(", "\n    static func noLater(")
    for agent in ("codex", "grok", "claude", "chatgpt", "gemini", "opencode", "copilot"):
        assert f'"{agent}"' in protected
    for runtime in ("node", "bun", "deno", "ruby", "java", "perl", "python"):
        assert f'"{runtime}"' in protected
    control = swift("SystemControl.swift")
    predicate = body(
        control,
        "static func requiresGuardedRoute(",
        "\n    static func protectLiveTerminalDescendants(",
    )
    assert "SystemServices.knownProtected(record) || record.tty" in predicate
