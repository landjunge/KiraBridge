"""Opt-in real Codex/Ollama team roundtrip in its own private temporary runtime.

Uses the existing Codex ChatGPT login/plan allowance and an already local model.
No new account, API key, model download, system service or live policy is changed.
Never invoked by ordinary tests. Each native turn is bounded; failed work is not retried.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import secrets
import socket
import time
from pathlib import Path

import uvicorn

from kirabridge.audit_manager import verify
from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import (
    AgentConfig,
    Config,
    PrincipalConfig,
    TeamConfig,
    TeamWorkerConfig,
    TerminalConfig,
)
from kirabridge.local_runtime import peer
from kirabridge.mcp_gateway.client import MCPClientPool
from kirabridge.mcp_gateway.http import create_http_app


async def run(
    folder: Path, reprocess_work_id: str | None = None, expected_sha256: str | None = None
):
    if reprocess_work_id:
        if (
            not (folder / "receipt.json").is_file()
            or not (folder / "state/bridge.sqlite3").is_file()
        ):
            raise RuntimeError("Reprocessing requires the original isolated acceptance state")
    else:
        folder.mkdir(mode=0o700, parents=True, exist_ok=False)
    workspace = folder / "workspace"
    workspace.mkdir(mode=0o700, exist_ok=bool(reprocess_work_id))
    names = ("local", "chatgpt", "codex", "opencode", "outsider")
    principals = {}
    for name in names:
        variable = "KB_TEAM_LIVE_" + name.upper()
        os.environ[variable] = secrets.token_urlsafe(40)
        principals[name] = PrincipalConfig(
            approval_mode="automatic",
            capabilities=[
                "bridge.health",
                "team.manage",
                "team.read",
                "team.write",
                "agent.execute",
                "task.read",
            ],
            roots=[str(workspace)],
            agents=[name] if name in {"codex", "opencode"} else [],
            token_env=variable,
            team_only_execution=name in {"codex", "opencode"},
        )
    # Force the existing OAuth path, without changing the caller's environment.
    os.environ.pop("CODEX_API_KEY", None)
    selected_key = "KB_TEAM_LIVE_UNUSED_PROVIDER_KEY"
    os.environ.pop(selected_key, None)
    config = Config(
        data_dir=str(folder / "state"),
        principals=principals,
        terminal=TerminalConfig(
            home=str(Path.home()),
            search_path=[
                "/usr/local/bin",
                "/usr/bin",
                "/bin",
                "/usr/sbin",
                "/sbin",
            ],
        ),
        agents={
            "codex": AgentConfig(
                kind="codex",
                executable=str(Path.home() / ".local/bin/codex"),
                sandbox_mode="read-only",
                api_key_env=selected_key,
            ),
            "opencode": AgentConfig(
                kind="opencode",
                executable="/usr/local/bin/opencode",
                model="ollama/kirabridge-team:latest",
                base_url="http://127.0.0.1:11434/v1",
                local_output_tokens=512,
                api_key_env=selected_key,
            ),
        },
        team=TeamConfig(
            enabled=True,
            workers={
                "local": TeamWorkerConfig(),
                "chatgpt": TeamWorkerConfig(),
                "codex": TeamWorkerConfig(agent="codex", cwd=str(workspace), timeout=90),
                "opencode": TeamWorkerConfig(
                    agent="opencode",
                    cwd=str(workspace),
                    timeout=240,
                    response_framing="work_reply_header",
                ),
            },
            max_work_per_root=4,
            max_hops=3,
            max_runs_per_hour=4,
        ),
    )
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    config.port = listener.getsockname()[1]
    config.validate_network()
    bridge = Bridge(config)
    server = uvicorn.Server(
        uvicorn.Config(create_http_app(bridge), log_level="critical", access_log=False)
    )
    async with bridge:
        serving = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(10):
                while not server.started:
                    if serving.done():
                        await serving
                    await asyncio.sleep(0.02)
            async with MCPClientPool(call_timeout=15) as pool:
                await pool.connect(peer(config, "chatgpt"))

                async def call(tool, arguments):
                    response = await pool.call("daemon", tool, arguments)
                    value = response.structuredContent
                    if not isinstance(value, dict) or value.get("error"):
                        raise RuntimeError("Live team tool rejected: " + tool)
                    return value

                await call(
                    "team_create",
                    {
                        "request": {
                            "team_id": "live-team",
                            "name": "Real Codex/OpenCode team proof",
                            "members": {
                                "local": "worker",
                                "chatgpt": "coordinator",
                                "codex": "worker",
                                "opencode": "worker",
                            },
                            "coordinator": "chatgpt",
                            "idempotency_key": "create",
                        }
                    },
                )
                final_instruction = (
                    "Verify the shared OpenCode result and incoming message. "
                    "Reply exactly KIRABRIDGE_TEAM_ROUNDTRIP_OK. No tools or actions."
                )
                child_answer = {
                    "kirabridge_team": "1",
                    "result": "OPENCODE_TEAM_OK",
                    "actions": [
                        {
                            "type": "message",
                            "recipient": "codex",
                            "kind": "answer",
                            "body": "FROM_OPENCODE_OK",
                        },
                        {
                            "type": "task",
                            "assignee": "codex",
                            "title": "Confirm local result",
                            "body": final_instruction,
                        },
                    ],
                }
                child_request = (
                    "Return ONLY this exact JSON object, no Markdown or tools: "
                    + json.dumps(child_answer)
                )
                first_answer = {
                    "kirabridge_team": "1",
                    "result": "CODEX_TEAM_DELEGATED",
                    "actions": [
                        {
                            "type": "task",
                            "assignee": "opencode",
                            "title": "Local text proof",
                            "body": child_request,
                        },
                    ],
                }
                body = (
                    "Harmless team acceptance. Do not use any tools. "
                    "Return ONLY this exact JSON object: " + json.dumps(first_answer)
                )
                first = await call(
                    "team_work_create",
                    {
                        "request": {
                            "team_id": "live-team",
                            "assignee": "codex",
                            "title": "Delegate local proof",
                            "body": body,
                            "idempotency_key": "roundtrip",
                        }
                    },
                )
                postprocess = None
                if reprocess_work_id:
                    prior = await call(
                        "team_work_get",
                        {
                            "team_id": "live-team",
                            "work_id": reprocess_work_id,
                        },
                    )
                    original = bridge.store.get(prior["core_task_id"])
                    text = original["result"].get(
                        "text", original["result"].get("final_message", "")
                    )
                    actual_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
                    if actual_sha256 != expected_sha256:
                        raise RuntimeError(
                            "Native result does not match the explicitly pinned hash"
                        )
                    postprocess = await call(
                        "team_work_reprocess",
                        {
                            "request": {
                                "team_id": "live-team",
                                "work_id": reprocess_work_id,
                                "core_task_id": original["id"],
                                "expected_result_sha256": expected_sha256,
                                "idempotency_key": "explicit-result-postprocessing-"
                                + expected_sha256,
                            }
                        },
                    )
                    print(
                        "Live-Team: gespeichertes Ergebnis ausdrücklich nachverarbeiten; "
                        "Codex/OpenCode-Originalturns werden nicht wiederholt.",
                        flush=True,
                    )
                else:
                    print(
                        "Live-Team: Codex→OpenCode→Codex eingereiht; keine Wiederholung.",
                        flush=True,
                    )
                deadline = time.monotonic() + 420
                while True:
                    board = (await call("team_work_list", {"team_id": "live-team"}))["work"]
                    terminal = {"completed", "failed", "unknown", "blocked", "cancelled"}
                    if (
                        (len(board) >= 3 and all(item["state"] in terminal for item in board))
                        or any(item["state"] in terminal - {"completed"} for item in board)
                        or (board and all(item["state"] in terminal for item in board))
                    ):
                        break
                    if time.monotonic() > deadline:
                        raise RuntimeError(
                            "Bounded acceptance ended; inspect original IDs, never retry blindly"
                        )
                    await asyncio.sleep(0.3)
                messages = await call("team_messages", {"team_id": "live-team"})
                repeat = await call(
                    "team_work_create",
                    {
                        "request": {
                            "team_id": "live-team",
                            "assignee": "codex",
                            "title": "Delegate local proof",
                            "body": body,
                            "idempotency_key": "roundtrip",
                        }
                    },
                )
                receipt = {
                    "real_native_agents": ["codex", "opencode"],
                    "coordinator": "chatgpt",
                    "runtime": "isolated authenticated loopback MCP",
                    "work": board,
                    "messages": messages["messages"],
                    "same_assignment_on_duplicate": repeat["id"] == first["id"],
                    "roundtrip_verified": len(board) == 3
                    and board[-1]["result"] == "KIRABRIDGE_TEAM_ROUNDTRIP_OK"
                    and all(item["state"] == "completed" for item in board),
                    "core_attempts": [
                        dict(row)
                        for row in bridge.store.db.execute(
                            "SELECT id,agent,state,attempt FROM tasks"
                        )
                    ],
                    "audit_chain": verify(bridge.store),
                    "api_keys_used": False,
                    "new_accounts": False,
                    "external_chatgpt_ui_verified": False,
                    "explicit_result_postprocessing": postprocess,
                    "original_core_result_sha256": expected_sha256,
                }
                target = folder / (
                    "receipt-postprocess.json" if reprocess_work_id else "receipt.json"
                )
                if target.exists():
                    raise RuntimeError(
                        "Acceptance evidence already exists; never overwrite a prior proof"
                    )
                target.write_text(json.dumps(receipt, indent=2) + "\n")
                target.chmod(0o600)
                print(
                    json.dumps(
                        {
                            "roundtrip_verified": receipt["roundtrip_verified"],
                            "work": [
                                {
                                    key: item.get(key)
                                    for key in ("id", "assignee", "state", "result", "error")
                                }
                                for item in board
                            ],
                            "proof": str(target),
                        },
                        indent=2,
                    )
                )
        finally:
            server.should_exit = True
            await asyncio.wait_for(serving, 10)
            listener.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--use-existing-codex-plan", action="store_true", required=True)
    parser.add_argument("--reprocess-work-id")
    parser.add_argument("--expected-result-sha256")
    args = parser.parse_args()
    if bool(args.reprocess_work_id) != bool(args.expected_result_sha256):
        parser.error("Reprocessing requires both the original work ID and the native result SHA256")
    asyncio.run(
        run(args.out.expanduser().absolute(), args.reprocess_work_id, args.expected_result_sha256)
    )
