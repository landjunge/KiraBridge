"""Scoped KiraBridge -> real ThreadDesk import of explicitly supplied local exports.

Inventory-only references are never opened, downloaded or counted as stored bytes.
This process enables transfers only for its supplied export root and thread IDs;
it neither changes the daemon configuration nor dispatches an older queued task.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import Config, PrincipalConfig, private_directory
from kirabridge.bridge_core.models import BridgeError, TaskRequest
from kirabridge.file_transfer.integrity import logical_path


def save(path, value):
    from uuid import uuid4

    temporary = path.with_name(path.name + "." + uuid4().hex + ".partial")
    with temporary.open("x", encoding="utf-8") as output:
        os.chmod(temporary, 0o600)
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)


async def run(args):
    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    entries = inventory["files"]
    projects = sorted({e["thread_id"] for e in entries if not e.get("blocked_reason")})
    private_directory(args.state)
    report_path = args.state / "reconciliation.json"
    # Dedicated state/principal: no live daemon tokens, global roots or broad grants.
    config = Config(
        data_dir=str(args.state / "bridge"),
        principals={
            "library-import": PrincipalConfig(
                capabilities=["files.prepare", "files.transfer", "files.inspect", "file.read"],
                roots=[str(args.exports.resolve())],
                permission_level="full",
                approval_mode="automatic",
            )
        },
    )
    config.file_transfer.enabled = True
    config.file_transfer.allowed_projects = projects
    config.file_transfer.export_roots = [str(args.exports.resolve())]
    settings = config.threaddesk
    settings.enabled = True
    settings.command = str(args.receiver_python.absolute())
    settings.args = ["-m", "threaddesk.ui.mcp_stdio"]
    settings.source_root = str(args.receiver_source.resolve())
    settings.workspace = str(args.workspace.resolve())
    settings.timeout = 30
    bridge = Bridge(config)
    report = {
        "expected": len(entries),
        "files": [],
        "source": str(args.inventory),
        "scope": "explicit exported bytes only; no Library account enumeration",
    }

    async def execute(operation, arguments):
        from uuid import uuid4

        task_id = "library_" + uuid4().hex
        request = TaskRequest(
            task_id=task_id, idempotency_key=task_id, operation=operation, arguments=arguments
        )
        bridge.prepare("library-import", request)
        return await bridge.tasks.wait("library-import", task_id, 3600)

    try:
        async with bridge:
            report["receiver"] = await bridge.file_transfers.receiver.capabilities()
            for entry in entries:
                item = {**entry, "state": "blocked", "reason": entry.get("blocked_reason")}
                report["files"].append(item)
                if item["reason"]:
                    save(report_path, report)
                    continue
                if not entry.get("export_relative"):
                    item["reason"] = (
                        "source_bytes_unavailable: Library reference is not a download capability"
                    )
                    save(report_path, report)
                    continue
                try:
                    logical_path(entry["export_relative"])
                    path = args.exports / entry["export_relative"]
                    if not path.is_file() or path.is_symlink():
                        item["reason"] = "source_export_missing_or_linked"
                        save(report_path, report)
                        continue
                    if path.name != Path(entry["original_path"]).name:
                        item["reason"] = "export_filename_differs_from_original"
                        save(report_path, report)
                        continue
                    sid = bridge.file_sources.export(
                        "library-import",
                        entry["source_ref"],
                        str(path.absolute()),
                        config.file_transfer.export_roots,
                    )
                    prepared = await execute(
                        "files.prepare",
                        {
                            "source_id": sid,
                            "project_id": entry["thread_id"],
                            "folder": entry["project"],
                            "library_path": entry["original_path"],
                            "source_version": entry.get("source_version"),
                            "expected_sha256": entry.get("sha256"),
                        },
                    )
                    item["prepare_task"] = prepared["id"]
                    result = prepared.get("result") or {}
                    if prepared["state"] != "completed" or "id" not in result:
                        item.update(
                            state="failed", reason=result.get("error_code") or prepared.get("error")
                        )
                        save(report_path, report)
                        continue
                    item["transfer_id"] = result["id"]
                    manifest = result["manifest"]
                    if (
                        manifest["size"] != entry["size"]
                        or manifest["mime_type"] != entry["mime_type"]
                    ):
                        item.update(
                            state="blocked", reason="export_size_or_mime_differs_from_inventory"
                        )
                        save(report_path, report)
                        continue
                    if result["state"] in {"paused", "running", "transferred"} and not args.resume:
                        item.update(
                            state="unknown",
                            reason="explicit_resume_required; no automatic write replay",
                        )
                        save(report_path, report)
                        break
                    sent = await execute("files.transfer", {"transfer_id": result["id"]})
                    item["transfer_task"] = sent["id"]
                    value = sent.get("result") or {}
                    if sent["state"] != "completed" or not value.get("import_successful"):
                        item.update(state=sent["state"], reason=sent.get("error"))
                        save(report_path, report)
                        if sent["state"] == "unknown":
                            break
                        continue
                    item.update(
                        state="stored",
                        receipt=value["receipt"],
                        manifest=value["manifest"],
                        reason=None,
                    )
                    # Independent on-disk readback; never open or run the stored document.
                    stored = args.workspace / "library-files/blobs" / manifest["sha256"]
                    from kirabridge.file_transfer.integrity import sha256_file

                    item["readback"] = (
                        stored.stat().st_size == manifest["size"]
                        and sha256_file(stored) == manifest["sha256"]
                    )
                    query = Path(entry["original_path"]).name
                    # ThreadDesk rebuilds its index in the runtime (5 s tick), not per write.
                    for _attempt in range(40):
                        raw = await bridge.threaddesk.pool.call(
                            "threaddesk",
                            "library_search",
                            {"thread_id": entry["thread_id"], "query": query, "limit": 100},
                        )
                        ok, search = bridge.threaddesk.decode(raw, mutation=False)
                        item["indexed"] = ok and value["receipt"]["artifact_id"] in json.dumps(
                            search
                        )
                        if item["indexed"]:
                            break
                        await asyncio.sleep(1)
                    if not item["readback"] or not item["indexed"]:
                        item["reason"] = "stored_but_readback_or_search_unconfirmed"
                    save(report_path, report)
                except (BridgeError, OSError, ValueError) as exc:
                    item["reason"] = getattr(exc, "code", type(exc).__name__)
                    if item["state"] != "stored":
                        item["state"] = "failed"
                    save(report_path, report)

    finally:
        bridge.store.close()
        done = report["files"]
        report["counts"] = {
            "expected": len(entries),
            "transferred": sum(e["state"] == "stored" for e in done),
            "durably_confirmed": sum(bool(e.get("receipt")) for e in done),
            "readback_confirmed": sum(e.get("readback") is True for e in done),
            "indexed": sum(e.get("indexed") is True for e in done),
            "blocked": sum(e["state"] == "blocked" for e in done),
            "failed": sum(e["state"] == "failed" for e in done),
            "unknown": sum(e["state"] == "unknown" for e in done),
            "not_processed": len(entries) - len(done),
        }
        save(report_path, report)
    print(json.dumps({"report": str(report_path), **report["counts"]}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "inventory",
        "exports",
        "state",
        "workspace",
        "receiver-python",
        "receiver-source",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Explicitly reconcile and resume the same existing transfer IDs",
    )
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
