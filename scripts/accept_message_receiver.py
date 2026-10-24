"""One installed real Codex receiver turn + isolated Grok ACP SIMULATION.

No production config changes. No real Grok execution. No response auto-chain.
"""

import argparse
import asyncio
import json
import os
import secrets
import sys
from dataclasses import replace
from pathlib import Path

from kirabridge.automatic_review_demo import isolated_http
from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import (
    AgentConfig,
    Config,
    PrincipalConfig,
    ReceiverConfig,
    load_config,
)
from kirabridge.local_runtime import peer
from kirabridge.mcp_gateway.client import MCPClientPool, Peer

BODY = "Antworte ausschließlich mit: KiraBridge-Test empfangen."
ANSWER = "KiraBridge-Test empfangen."


def save(root, name, value):
    (root / (name + ".json")).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


async def call(pool, who, tool, args):
    result = await pool.call(who, tool, args)
    value = result.structuredContent
    if result.isError or not isinstance(value, dict) or value.get("error"):
        raise RuntimeError(f"{tool} rejected: {value}")
    return value


async def wait_job(pool, who, message_id, timeout=100):
    async with asyncio.timeout(timeout):
        while True:
            message = await call(pool, who, "message_get", {"message_id": message_id})
            job = message.get("processing") or {}
            if job.get("state") in {"completed", "failed", "blocked", "unknown"}:
                return message
            await asyncio.sleep(0.5)


async def installed_codex(root):
    config = load_config()
    async with MCPClientPool(call_timeout=20) as pool:
        for identity in ["codex", "grok"]:
            await pool.connect(replace(peer(config, identity), id=identity))
            status = await call(pool, identity, "message_channel_status", {})
            save(root, "installed-status-" + identity, status)
            print(
                identity
                + ": receiver_configured="
                + str(status["receiver_configured"])
                + ", receiver_active="
                + str(status["receiver_active"]),
                flush=True,
            )
        # Existing Grok identity is an authorized Codex peer. request_reply=false
        # prevents the receiver from scheduling a REAL Grok followup on its answer.
        value = await call(
            pool,
            "grok",
            "message_send",
            {
                "message": {
                    "recipient": "codex",
                    "conversation_id": "receiver-codex-20261019-01",
                    "idempotency_key": "receiver-codex-20261019-01",
                    "kind": "question",
                    "body": BODY,
                    "dispatch": True,
                    "request_reply": False,
                }
            },
        )
        save(root, "codex-submission", value)
        print("Echte Codex-Nachricht eingereicht: " + value["id"], flush=True)
        final = await wait_job(pool, "grok", value["id"])
        events = await call(pool, "grok", "message_events", {"message_id": value["id"]})
        save(root, "codex-final", final)
        save(root, "codex-events", events)
        job = final["processing"]
        evidence = job["evidence"]
        print(
            "Codex: "
            + job["state"]
            + "; tatsächliche CLI-Antwort: "
            + str(evidence.get("response_preview")),
            flush=True,
        )
        return {
            "scope": "INSTALLED PRODUCTION RECEIVER; REAL CODEX",
            "message_id": final["id"],
            "state": job["state"],
            "delivered": final["delivered"],
            "acknowledged": final["acknowledged"],
            "answer": evidence.get("response_preview"),
            "run_id": job["run_id"],
            "session_id": evidence.get("session_id"),
            "reply_id": job.get("reply_id"),
            "exact_answer": evidence.get("response_preview") == ANSWER,
            "standalone_reply_message": False,
            "reply_limit": "request_reply=false prevents a real Grok followup; "
            "answer is actual receiver CLI evidence",
            "events_file": "codex-events.json",
        }


async def simulated_grok(root):
    state = root / "grok-simulation"
    state.mkdir(mode=0o700)
    work = state / "workspace"
    work.mkdir()
    adapter = state / "grok-acp-SIMULATOR"
    adapter.write_text(
        "#!"
        + sys.executable
        + "\n"
        + """import json,sys
for line in sys.stdin:
 msg=json.loads(line);method=msg.get('method')
 if method=='initialize': result={'protocolVersion':1,'authMethods':[{'id':'cached_token'}]}
 elif method=='authenticate':result={}
 elif method=='session/new':result={'sessionId':'SIMULATION-grok-receiver-20261019-01'}
 elif method=='session/prompt':
  text=json.dumps(msg,ensure_ascii=False)
  assert 'Antworte ausschließlich mit: KiraBridge-Test empfangen.' in text
  params={'sessionId':'SIMULATION-grok-receiver-20261019-01','update':{
   'sessionUpdate':'agent_message_chunk',
   'content':{'type':'text','text':'KiraBridge-Test empfangen.'}}}
  print(json.dumps({'jsonrpc':'2.0','method':'session/update','params':params}),flush=True)
  result={'stopReason':'end_turn'}
 else:continue
 print(json.dumps({'jsonrpc':'2.0','id':msg['id'],'result':result}),flush=True)
"""
    )
    adapter.chmod(0o700)
    caps = ["message.send", "message.read", "message.ack", "bridge.health"]
    for identity in ["operator", "grok"]:
        os.environ["KB_RECEIVER_TEST_" + identity.upper()] = secrets.token_hex(32)
    config = Config(
        data_dir=str(state / "bridge-state"),
        agents={"grok": AgentConfig(kind="grok_acp", executable=str(adapter))},
        principals={
            "operator": PrincipalConfig(
                capabilities=caps,
                message_peers=["grok"],
                approval_mode="automatic",
                token_env="KB_RECEIVER_TEST_OPERATOR",
                roots=[str(work)],
            ),
            "grok": PrincipalConfig(
                capabilities=caps,
                message_peers=["operator"],
                approval_mode="automatic",
                token_env="KB_RECEIVER_TEST_GROK",
                roots=[str(work)],
                agents=["grok"],
            ),
        },
    )
    config.messaging.receivers["grok"] = ReceiverConfig(cwd=str(work), timeout=5)
    bridge = Bridge(config)
    async with isolated_http(bridge) as url:
        async with MCPClientPool(call_timeout=10) as pool:
            await pool.connect(
                Peer("operator", url=url, token=os.environ["KB_RECEIVER_TEST_OPERATOR"])
            )
            await pool.connect(Peer("grok", url=url, token=os.environ["KB_RECEIVER_TEST_GROK"]))
            status = await call(pool, "grok", "message_channel_status", {})
            save(root, "grok-SIMULATION-status", status)
            submission = await call(
                pool,
                "operator",
                "message_send",
                {
                    "message": {
                        "recipient": "grok",
                        "conversation_id": "receiver-grok-SIMULATION-20261019-01",
                        "idempotency_key": "receiver-grok-SIMULATION-20261019-01",
                        "kind": "question",
                        "body": BODY,
                        "dispatch": True,
                        "request_reply": True,
                    }
                },
            )
            save(root, "grok-SIMULATION-submission", submission)
            final = await wait_job(pool, "operator", submission["id"], timeout=15)
            events = await call(
                pool, "operator", "message_events", {"message_id": submission["id"]}
            )
            save(root, "grok-SIMULATION-final", final)
            save(root, "grok-SIMULATION-events", events)
            job = final["processing"]
            reply = None
            reply_events = None
            if job.get("reply_id"):
                reply = await call(pool, "operator", "message_get", {"message_id": job["reply_id"]})
                inbox = await call(
                    pool,
                    "operator",
                    "message_receive",
                    {"conversation_id": submission["conversation_id"]},
                )
                actual = next(m for m in inbox["messages"] if m["id"] == reply["id"])
                await call(
                    pool,
                    "operator",
                    "message_ack",
                    {"message_id": actual["id"], "receipt": actual["receipt"]},
                )
                reply = await call(pool, "operator", "message_get", {"message_id": reply["id"]})
                reply_events = await call(
                    pool, "operator", "message_events", {"message_id": reply["id"]}
                )
            save(root, "grok-SIMULATION-reply", reply)
            save(root, "grok-SIMULATION-reply-events", reply_events)
            print(
                "Grok SIMULATION: " + job["state"] + "; Antwort: " + str(reply and reply["body"]),
                flush=True,
            )
            result = {
                "scope": "ISOLATED REAL MCP + ACP SIMULATOR; NOT INSTALLED REAL GROK",
                "receiver_configured": status["receiver_configured"],
                "receiver_active": status["receiver_active"],
                "message_id": final["id"],
                "state": job["state"],
                "delivered": final["delivered"],
                "acknowledged": final["acknowledged"],
                "answer": reply and reply["body"],
                "reply_id": job.get("reply_id"),
                "run_id": job["run_id"],
                "session_id": job["evidence"].get("session_id"),
                "exact_answer": bool(reply and reply["body"] == ANSWER),
                "reply_received_and_acknowledged": bool(
                    reply and reply["delivered"] and reply["acknowledged"]
                ),
                "real_grok_invoked": False,
            }
    bridge.store.close()
    return result


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.output.absolute()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    codex = await installed_codex(root)
    grok = await simulated_grok(root)
    summary = {
        "codex": codex,
        "grok_simulation": grok,
        "installed_real_grok_tested": False,
        "remaining": [
            "Installed Grok points at real CLI; no real Grok invocation authorized",
            "Codex answer captured as actual processing evidence; "
            "no standalone auto reply to real Grok",
        ],
        "production_configuration_changed": False,
        "existing_sessions_stopped": False,
        "project_work_started": False,
    }
    save(root, "summary", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
