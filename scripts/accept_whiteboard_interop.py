"""One real pinned ThreadDesk MCP flow in fresh private stores; no user profiles/data."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import sys
from pathlib import Path

from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import Config, PrincipalConfig
from kirabridge.bridge_core.models import TaskRequest

PIN = "64353be01082251b6af72d0096ce0a57d66c5501"
PINNED_SOURCE_SHA256 = "67bf369ec398c73e283c44877d5f4841c3ad48c0ce623f91e213e60070de62a2"


def source_hash(source):
    return hashlib.sha256(
        "".join(
            str(path.relative_to(source))
            + ":"
            + hashlib.sha256(path.read_bytes()).hexdigest()
            + "\n"
            for path in sorted((source / "src").rglob("*.py"))
        ).encode()
    ).hexdigest()


def stored_files(store):
    return {
        str(path.relative_to(store)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in store.rglob("*.json")
    }


async def accept(source, root, archive):
    repo = Path(__file__).resolve().parents[1]
    for path in (source, root, archive):
        if not path.is_relative_to(repo / "dist"):
            raise RuntimeError(
                "All source/test paths must be inside this KiraBridge dist directory"
            )
    if not (source / "src/threaddesk/ui/mcp_stdio.py").is_file():
        raise RuntimeError("Pinned source is missing")
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.umask(0o077)
    store, workspace = root / "td-store", root / "kb-workspace"
    for path in (store, workspace):
        path.mkdir(mode=0o700)
    before_source = source_hash(source)
    if before_source != PINNED_SOURCE_SHA256:
        raise RuntimeError(
            "Source Python hash does not match the accepted pinned ThreadDesk commit"
        )
    launcher = root / "mcp_launcher.py"
    launcher.write_text(
        "import os,sys\nfrom pathlib import Path\n"
        f"store=Path({str(store)!r})\nsource=Path({str(source / 'src')!r})\n"
        "assert Path(os.environ['THREADDESK_HOME']).resolve()==store\n"
        "assert store.stat().st_uid==os.getuid() and not store.stat().st_mode & 0o077\n"
        "sys.dont_write_bytecode=True\n"
        "import threaddesk\n"
        "assert Path(threaddesk.__file__).resolve().is_relative_to(source)\n"
        "from threaddesk.api.service import ThreadService\n"
        "from threaddesk.storage.json_store import JsonStore\n"
        "from threaddesk.ui.mcp_stdio import serve\n"
        "serve(ThreadService(store=JsonStore(store)))\n"
    )
    config = Config(
        data_dir=str(root / "kb-state"),
        principals={
            "interop": PrincipalConfig(
                capabilities=["threaddesk.manage", "threaddesk.read", "task.read"],
                roots=[str(workspace)],
                approval_mode="automatic",
                permission_level="full",
            )
        },
    )
    config.threaddesk.enabled = True
    config.threaddesk.workspace = str(store)
    config.threaddesk.command = sys.executable
    config.threaddesk.args = [str(launcher)]
    config.threaddesk.source_root = str(source / "src")
    evidence = {
        "scope": "KiraBridge TaskManager -> actual pinned ThreadDesk MCP -> new private JsonStore",
        "platform": platform.platform(),
        "threaddesk_commit": PIN,
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "threaddesk_sources_sha256": before_source,
        "production_modified": False,
        "live_whiteboard_modified": False,
        "dependencies_installed": False,
        "response_budget_bytes": config.threaddesk.max_result_bytes,
        "response_budget_increased": False,
        "checks": [],
    }

    async def submit(bridge, identifier, operation, arguments):
        value = TaskRequest(
            task_id=identifier, idempotency_key=identifier, operation=operation, arguments=arguments
        )
        bridge.prepare("interop", value)
        result = await bridge.tasks.wait("interop", identifier, 30)
        return result

    try:
        async with Bridge(config) as bridge:
            created = await submit(
                bridge,
                "interop-create",
                "threaddesk.manage",
                {
                    "operation_id": "interop-create-64353be0",
                    "action": "create",
                    "expected_revision": 0,
                    "data": {
                        "title": "KiraBridge isolated compatibility",
                        "description": "D" * 10000,
                    },
                },
            )
            if created["state"] != "completed" or not created["result"]["success"]:
                raise RuntimeError(
                    "Create failed: "
                    + json.dumps(
                        {
                            "state": created["state"],
                            "error": created["error"],
                            "result": created["result"],
                        }
                    )
                )
            receipt = created["result"]["value"]
            identifier = receipt["thread_id"]
            evidence["checks"].append(
                "real create: 10000-character description, correlated receipt"
            )
            note = "🧠" * 100000
            saved = await submit(
                bridge,
                "interop-note",
                "threaddesk.manage",
                {
                    "operation_id": "interop-note-64353be0",
                    "action": "set_note",
                    "id": identifier,
                    "expected_revision": receipt["revision"],
                    "data": {"text": note, "append": False},
                },
            )
            if saved["state"] != "completed" or not saved["result"]["success"]:
                raise RuntimeError(
                    "Note failed: "
                    + json.dumps(
                        {
                            "state": saved["state"],
                            "error": saved["error"],
                            "result": saved["result"],
                        }
                    )
                )
            evidence["checks"].append(
                "real set_note: 100000 Emoji / 400000 UTF-8 bytes, unchanged budget"
            )
            read = await submit(
                bridge,
                "interop-readback",
                "threaddesk.read",
                {
                    "tool": "get_thread",
                    "arguments": {"id": identifier},
                },
            )
            assert read["state"] == "completed" and read["result"]["success"]
            value = read["result"]["value"]
            # Controlled payloads contain no wrapper delimiter.
            # This does not establish a general-purpose raw readback API.
            assert (
                value["notes"]
                == '<untrusted source="threaddesk.notes">\n' + note + "\n</untrusted>"
            )
            assert (
                value["description"]
                == '<untrusted source="threaddesk.description">\n' + "D" * 10000 + "\n</untrusted>"
            )
            raw = json.loads((store / "threads" / (identifier + ".json")).read_text())
            assert raw["context"]["notes"] == note and raw["description"] == "D" * 10000
            evidence["checks"].append(
                "independent get_thread and raw JsonStore match original full values"
            )
            evidence.update(
                thread_id=identifier,
                revision=value["revision"],
                note_sha256=hashlib.sha256(note.encode()).hexdigest(),
                description_sha256=hashlib.sha256(("D" * 10000).encode()).hexdigest(),
            )
            before_limit = stored_files(store)
            rejected = await submit(
                bridge,
                "interop-limit",
                "threaddesk.manage",
                {
                    "operation_id": "interop-limit-64353be0",
                    "action": "update",
                    "id": identifier,
                    "expected_revision": value["revision"],
                    "data": {"description": "D" * 10001},
                },
            )
            assert rejected["state"] == "failed"
            error = rejected["result"]["value"]["error"]
            assert error["details"]["limit"] == 10000
            assert error["details"]["limit_source"] == "peer_tools_list"
            assert rejected["result"]["evidence"]["request_sent"] is False
            assert stored_files(store) == before_limit
            evidence["checks"].append(
                "10001-character description rejected before mutation; store unchanged"
            )
            evidence["preflight_error"] = error
        assert source_hash(source) == before_source
        evidence["checks"].append(
            "source unchanged; explicit JsonStore supplied; no default-store constructor requested"
        )
        evidence["passed"] = True
    except Exception as exc:
        evidence["error_type"] = type(exc).__name__
        evidence["error"] = str(exc)[:2000]
        raise
    finally:
        (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--td-source", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source-archive", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(
        accept(args.td_source.resolve(), args.root.resolve(), args.source_archive.resolve())
    )
