"""Injectable macOS provider over existing desktop/clipboard/domain leaves."""

from kirabridge.platform_adapters.macos.capabilities import CapabilityProbe
from kirabridge.platform_adapters.macos.permissions import PermissionProbe
from kirabridge.platform_adapters.macos.provider import (
    DESCRIPTORS,
    MacOSProvider,
    OperationDescriptor,
)

__all__ = [
    "CapabilityProbe",
    "DESCRIPTORS",
    "MacOSProvider",
    "OperationDescriptor",
    "PermissionProbe",
]
