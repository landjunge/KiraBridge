"""Actual installed-wheel byte/MCP contract evidence; never a ThreadDesk product claim."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import platform
import sys
from pathlib import Path

import kirabridge
from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import Config, PrincipalConfig
from kirabridge.bridge_core.models import TaskRequest


async def accept(root, expected_package_root):
    package = Path(kirabridge.__file__).resolve()
    assert package.is_relative_to(expected_package_root.resolve())
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    workspace, receiver = root / "exports", root / "receiver-fixture"
    workspace.mkdir(mode=0o700)
    receiver.mkdir(mode=0o700)
    policy = PrincipalConfig(
        capabilities=["files.prepare", "files.transfer", "files.inspect", "file.read"],
        roots=[str(workspace)],
        approval_mode="automatic",
        permission_level="full",
    )
    config = Config(data_dir=str(root / "state"), principals={"acceptance": policy})
    config.file_transfer.enabled = True
    config.file_transfer.export_roots = [str(workspace)]
    config.file_transfer.allowed_projects = ["isolated-project"]
    config.threaddesk.enabled = True
    config.threaddesk.command = sys.executable
    config.threaddesk.args = [
        str(Path(__file__).resolve().parent.parent / "tests/file_import_mcp_fixture.py"),
        "--lose-commit-once",
    ]
    config.threaddesk.workspace = str(receiver)
    evidence = {
        "platform": platform.platform(),
        "version": kirabridge.__version__,
        "package": str(package),
        "scope": "isolated actual MCP contract fixture; NOT the ThreadDesk product",
        "production_modified": False,
        "files": [],
    }

    async def submit(bridge, identifier, operation, arguments):
        request = TaskRequest(
            task_id=identifier, idempotency_key=identifier, operation=operation, arguments=arguments
        )
        bridge.prepare("acceptance", request)
        return await bridge.tasks.wait("acceptance", identifier, 60)

    try:
        fixtures = Path(__file__).resolve().parent.parent / "tests/fixtures/file-transfer"
        samples = [
            (p.name, p.read_bytes()) for p in sorted(fixtures.iterdir()) if p.suffix != ".md"
        ]
        samples.append(("multi-chunk.bin", bytes(range(256)) * 65536))  # 16 MiB
        for index, (filename, data) in enumerate(samples):
            path = workspace / filename
            path.write_bytes(data)
            async with Bridge(config) as bridge:
                source_id = bridge.file_sources.export(
                    "acceptance", filename, str(path), [str(workspace)]
                )
                prepared = await submit(
                    bridge,
                    f"prepare-{index}",
                    "files.prepare",
                    {"source_id": source_id, "project_id": "isolated-project", "folder": "folder"},
                )
                assert prepared["state"] == "completed", prepared
                transfer_id = prepared["result"]["id"]
                result = await submit(
                    bridge, f"send-{index}", "files.transfer", {"transfer_id": transfer_id}
                )
                if index == 0:
                    assert result["state"] == "unknown", result
            # Explicit sender and receiver restart; same immutable transfer, new task/key.
            async with Bridge(config) as bridge:
                result = await submit(
                    bridge, f"resume-{index}", "files.transfer", {"transfer_id": transfer_id}
                )
                assert result["state"] == "completed", result
                row = bridge.file_repository.get("acceptance", transfer_id)
                stored = receiver / "fixture-files" / row["operation_id"] / "stored"
                assert stored.read_bytes() == data == path.read_bytes()
                assert result["result"]["import_successful"]
                receipt = result["result"]["receipt"]
                assert receipt["sha256"] == hashlib.sha256(data).hexdigest()
                evidence["files"].append(
                    {
                        "name": filename,
                        "size": len(data),
                        "sha256": receipt["sha256"],
                        "receipt": receipt,
                        "bytes_match": True,
                        "source_unchanged": True,
                    }
                )
        evidence["passed"] = True
    finally:
        (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--expected-package-root", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(accept(args.root.resolve(), args.expected_package_root))
