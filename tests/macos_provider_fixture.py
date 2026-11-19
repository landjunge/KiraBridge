"""Explicit macOS provider injection for tests simulating native Mac transports."""

from kirabridge.platform_adapters.macos import CapabilityProbe, MacOSProvider


def bind_macos_provider(bridge):
    """Keep the selected bridge's bindings/ACLs; never mask other Linux fixtures."""
    previous = bridge.macos
    if type(previous) is not MacOSProvider:
        bridge.macos = MacOSProvider(
            terminal_app=bridge.sessions.terminal_app,
            clipboard=bridge.clipboard,
            files=bridge.filesystem,
            processes=bridge.processes,
            system_modules=bridge.system_modules,
            system_reports=bridge.terminal,
            capabilities=CapabilityProbe(
                facts=previous.capability_probe.facts,
                executable=previous.capability_probe.executable,
                native_metadata=bridge.system_modules.snapshot_metadata,
            ),
            permissions=previous.permission_probe,
            actor_identities=previous.actor_identities,
        )
    # NativeQueries captures its provider at construction, unlike the Bridge's
    # dynamic provider/terminal guard. Both must model the same explicit host.
    bridge.native_queries.provider = bridge.macos
    return bridge.macos
