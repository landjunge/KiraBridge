"""Strict checkpoint/receipt validation: transmitted bytes are not a stored import."""

from kirabridge.bridge_core.models import BridgeError, digest
from kirabridge.file_transfer.models import PROTOCOL


def checkpoint(value, operation_id, manifest, *, allow_aborted=False):
    if value.get("receiver_contract") == "threaddesk.library.receive.v1":
        expected = {
            "filename": manifest.name,
            "thread_id": manifest.project_id,
            "size": manifest.size,
            "sha256": manifest.sha256,
        }
        if (
            value.get("protocol") != PROTOCOL
            or value.get("found") is not True
            or value.get("operation_id") != operation_id
            or value.get("transfer_id") != operation_id
            or value.get("manifest") != expected
            or any(type(value["manifest"][k]) is not type(v) for k, v in expected.items())
            or value.get("state") not in {"receiving", "committed", "aborted"}
            or type(value.get("next_offset")) is not int
            or not 0 <= value["next_offset"] <= manifest.size
            or value.get("state") == "committed"
            and value["next_offset"] != manifest.size
        ):
            raise BridgeError("transfer_receipt_mismatch", "Checkpoint manifest/state mismatch")
        if value["state"] == "aborted" and not allow_aborted:
            raise BridgeError("transfer_closed", "Aborted transfer cannot be reopened")
        return value["next_offset"]
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
    if value.get("receiver_contract") == "threaddesk.library.receive.v1":
        checkpoint(value, operation_id, manifest)
        receipt = value.get("receipt")
        expected = {
            "format": "threaddesk.library.receipt.v1",
            "transfer_id": operation_id,
            "sha256": manifest.sha256,
            "size": manifest.size,
            "thread_id": manifest.project_id,
        }
        import re

        if (
            value.get("state") != "committed"
            or not isinstance(receipt, dict)
            or any(
                receipt.get(k) != v or type(receipt.get(k)) is not type(v)
                for k, v in expected.items()
            )
            or not isinstance(receipt.get("record_id"), str)
            or not re.fullmatch(r"[0-9a-f]{12}", receipt["record_id"])
            or receipt.get("open_path") != "/library/files/" + receipt["record_id"]
        ):
            raise BridgeError("transfer_storage_unconfirmed", "No durable native receipt")
        # Index result is evidence, not proof of searchable document bodies.
        native = {**expected, "record_id": receipt["record_id"], "open_path": receipt["open_path"]}
        return {
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
            "artifact_id": receipt["record_id"],
            "storage_revision": digest(native),
            "receiver_receipt": native,
        }
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
