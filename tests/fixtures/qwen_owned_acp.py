import asyncio
import json
import pathlib
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

session = "fixture-qwen-owned"
cwd = None
spec = None
mode = "default"


async def epoch():
    p = StdioServerParameters(
        command=spec["command"], args=spec["args"], env={x["name"]: x["value"] for x in spec["env"]}
    )
    async with stdio_client(p) as (r, w), ClientSession(r, w) as c:
        await c.initialize()
        a = await c.call_tool("bridge_epoch", {})
        assert not a.isError and a.structuredContent["discovery"]["principal"] == "codex"
        assert (await c.call_tool("bridge_epoch", {})).isError


option = {
    "id": "reasoning_effort",
    "category": "thought_level",
    "currentValue": "xhigh",
    "options": [{"value": "xhigh", "name": "xhigh"}],
}
for line in sys.stdin:
    m = json.loads(line)
    method = m.get("method")
    p = m.get("params", {})
    if method == "initialize":
        r = {
            "protocolVersion": 1,
            "agentInfo": {"name": "qwen-code", "version": "0.27.2"},
            "agentCapabilities": {"loadSession": True},
        }
    elif method in {"session/new", "session/load"}:
        cwd = p["cwd"]
        spec = p["mcpServers"][0]
        sys.stderr = open(pathlib.Path(cwd) / "qwen-fixture-errors.log", "a")
        policy = json.loads(pathlib.Path(spec["args"][-1]).read_text())
        log = pathlib.Path(cwd) / "fixture-qwen-scopes.jsonl"
        previous = [json.loads(x) for x in log.read_text().splitlines()] if log.exists() else []
        if method == "session/load":
            assert p["sessionId"] == session and len(previous) == 1
            assert (
                policy["task_id"] != previous[0]["task_id"]
                and policy["team_scope"]["session_id"] == session
            )
            update = {
                "sessionId": session,
                "update": {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": "REPLAYED_TEXT"},
                },
            }
            print(
                json.dumps({"jsonrpc": "2.0", "method": "session/update", "params": update}),
                flush=True,
            )
        else:
            assert not previous
        with log.open("a") as f:
            f.write(
                json.dumps(
                    {
                        "method": method,
                        "task_id": policy["task_id"],
                        "arguments_sha256": policy["arguments_sha256"],
                        "policy_path": spec["args"][-1],
                    }
                )
                + "\n"
            )
        r = {"sessionId": session, "configOptions": [option]}
    elif method == "session/set_mode":
        mode = p["modeId"]
        r = {}
    elif method == "session/set_config_option":
        assert p["value"] == "xhigh"
        r = {"configOptions": [option]}
    elif method == "qwen/status/session/context":
        r = {
            "state": {
                "models": {"currentModelId": "fixture-model(qwen-subscription)"},
                "modes": {"currentModeId": mode},
                "configOptions": [option],
            }
        }
    elif method == "qwen/status/session/resources":
        r = {
            "sessionId": session,
            "workspaceCwd": cwd,
            "mcp": {
                "discoveryState": "completed",
                "servers": [{"name": "kirabridge", "mcpStatus": "connected"}],
            },
        }
    elif method == "qwen/status/session/context_usage":
        r = {"usage": {"mcpTools": [{"name": "kirabridge__bridge_epoch"}]}}
    elif method == "session/prompt":
        asyncio.run(epoch())
        content = json.dumps(
            {"kirabridge_team": "1", "result": "FRESH_SCOPED_MCP_OK", "actions": []}
        )
        update = {
            "sessionId": session,
            "update": {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": content},
            },
        }
        print(
            json.dumps({"jsonrpc": "2.0", "method": "session/update", "params": update}), flush=True
        )
        r = {"stopReason": "end_turn"}
    else:
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": r}), flush=True)
