"""Fixed public macOS reports through the existing owned process-output store."""

from typing import Literal

from pydantic import Field

from kirabridge.bridge_core.models import Input

REPORT_TYPES = {
    "hardware": "SPHardwareDataType",
    "software": "SPSoftwareDataType",
    "storage": "SPStorageDataType",
    "network": "SPNetworkDataType",
    "audio": "SPAudioDataType",
    "displays": "SPDisplaysDataType",
    "usb": "SPUSBDataType",
    "bluetooth": "SPBluetoothDataType",
    "power": "SPPowerDataType",
    "printers": "SPPrintersDataType",
    "applications": "SPApplicationsDataType",
}


class SystemReportInput(Input):
    report: Literal[
        "hardware",
        "software",
        "storage",
        "network",
        "audio",
        "displays",
        "usb",
        "bluetooth",
        "power",
        "printers",
        "applications",
    ]
    detail: Literal["mini", "basic", "full"] = "basic"
    timeout: float = Field(default=60.0, gt=0, le=300, allow_inf_nan=False)
    max_output: int = Field(default=32768, ge=0, le=1048576)
