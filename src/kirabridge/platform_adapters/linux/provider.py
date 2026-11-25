"""Passive Linux binding metadata; existing dispatch and permissions stay intact."""

from kirabridge.platform_adapters.macos.capabilities import CapabilityProbe
from kirabridge.platform_adapters.macos.provider import MacOSProvider


class _LinuxCapabilities(CapabilityProbe):
    def __init__(self, facts, leaves):
        # macOS helper metadata cannot establish a Linux transport observation.
        super().__init__(facts=facts)
        self.leaves = leaves

    def snapshot(self):
        result = super().snapshot()
        linux = self.facts.get("platform", "").startswith("linux")
        if not linux:
            for capability in result["capabilities"].values():
                capability.update(available=False, reason="unsupported_platform")
        for name in ("files", "processes", "owned_terminal"):
            bound = self.leaves.get(name) is not None
            result["capabilities"][name] = {
                "available": False,
                "supported": linux,
                "bound": bound,
                "state": "unsupported" if not linux else "unknown" if bound else "unavailable",
                "reason": "unsupported_platform"
                if not linux
                else "transport_not_probed"
                if bound
                else "transport_not_bound",
                "runtime_availability": "not_probed",
                "permission_scope": "existing_principal_policy_and_target_guards_not_checked",
            }
        return result


class LinuxProvider(MacOSProvider):
    """Identify Linux and its bindings without inferring execution readiness.

    Inherited descriptors, require/execute and OS-permission rows are unchanged.
    The owned-terminal row is informational, not another session dispatch route.
    """

    provider_id = "linux.existing_native"
    provider_version = "1"

    def __init__(self, *, owned_terminal=None, **kwargs):
        super().__init__(**kwargs)
        self.leaves["owned_terminal"] = owned_terminal
        self.capability_probe = _LinuxCapabilities(self.capability_probe.facts, self.leaves)
