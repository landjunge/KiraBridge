"""Strict checkpoint/receipt validation: transmitted bytes are not a stored import."""

from kirabridge.bridge_core.models import BridgeError, digest
from kirabridge.file_transfer.models import PROTOCOL


def checkpoint(value, operation_id, manifest):
    if (
        value.get("protocol") != PROTOCOL
        or value.get("operation_id") != operation_id
        or value.get("manifest_sha256") != digest(manifest.model_dump(mode="json"))
        or type(value.get("next_offset")) is not int
        or not 0 <= value["next_offset"] <= manifest.size
        or not isinstance(value.get("prefix_sha256"), str)
    ):
        raise BridgeError(
            "transfer_receipt_mismatch", "Receiver checkpoint is not bound to this manifest"
        )
    return value["next_offset"]


def durable_receipt(value, operation_id, manifest):
    expected = {
        "protocol": PROTOCOL,
        "operation_id": operation_id,
        "manifest_sha256": digest(manifest.model_dump(mode="json")),
        "sha256": manifest.sha256,
        "size": manifest.size,
        "project_id": manifest.project_id,
        "folder": manifest.folder,
        "name": manifest.name,
        "state": "stored",
        "durable": True,
    }
    if (
        any(
            value.get(key) != item or type(value.get(key)) is not type(item)
            for key, item in expected.items()
        )
        or not isinstance(value.get("artifact_id"), str)
        or not value["artifact_id"]
        or not isinstance(value.get("storage_revision"), str)
        or not value["storage_revision"]
    ):
        raise BridgeError(
            "transfer_storage_unconfirmed", "No matching durable ThreadDesk storage receipt"
        )
    # Whitelist safe contractual fields: never expose arbitrary receiver diagnostics/URLs/content.
    return {
        **expected,
        "artifact_id": value["artifact_id"],
        "storage_revision": value["storage_revision"],
    }
