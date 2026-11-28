"""Reusable live E2E smoke suite — "ChatGPT/Kira" perspective (principal=chatgpt).

Exercises the INSTALLED, PRODUCTION bridge exactly as ChatGPT/Kira's own MCP
connection would, covering:

  1. function: connection check, channel status, and the addressed-message
     round trip (send as chatgpt -> read as the recipient -> ack), which is
     also a direct regression check for "one mailbox per participant" (a
     message addressed to one principal must land in THAT principal's own
     mailbox and nowhere else); plus a second, separate regression check
     that an explicit recipient is never silently rewritten to the
     coordinator (the real incident fixed 2026-11-27 in commit 41648f9).
  2. discoverability ("Auffindbarkeit"): does `tools/list` expose a tool for
     every capability the chatgpt principal holds, each with a substantive
     description.

Every message this suite sends is tagged "[E2E-TEST]" with a fresh
conversation/idempotency id per run, uses dispatch=false and
request_reply=false (a passive inbox post — it never wakes or steers an
active session, never opens a window), and is acknowledged (cleaned up) by
the recipient before the run ends. The isolation check connects briefly as
a third, normally-idle principal (qwen3) purely to confirm the test message
is absent there too; if that connection fails for any reason the isolation
check is skipped, never treated as a hard failure of the rest of the suite.

No production config change. No credential rotation. No window opened.

Usage: python3 scripts/accept_e2e_chatgpt_perspective.py --output <new-dir>
"""

import argparse
import asyncio
import json
import secrets
import sys
import time
from dataclasses import replace
from pathlib import Path

from kirabridge.bridge_core.config import load_config
from kirabridge.local_runtime import peer
from kirabridge.mcp_gateway.client import MCPClientPool

SENDER = "chatgpt"
RECIPIENT = "local"
ISOLATION_PROBE = "qwen3"

DEDICATED_TOOL_CHECKS = [
    ("message_channel_status", "message_channel_status", {}),
    ("team_list", "team_list", {}),
    ("agent_status", "agent_status", {}),
]


def save(root: Path, name: str, value) -> None:
    (root / (name + ".json")).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n"
    )


async def call_tool(pool, who, tool, args):
    try:
        result = await pool.call(who, tool, args)
    except Exception as exc:
        return {"ok": False, "error": repr(exc)}
    value = result.structuredContent
    if result.isError or not isinstance(value, dict) or value.get("error"):
        return {"ok": False, "error": value}
    return {"ok": True, "value": value}


async def check_discoverability(pool, config, root: Path) -> dict:
    catalog = await pool.list_tools(SENDER)
    tools = {t.name: (t.description or "") for t in catalog}
    policy = config.principals[SENDER]
    missing_tool_route = []
    thin_description = []
    has_operation_catalog = "operation_catalog" in tools
    for cap in policy.capabilities:
        direct = cap.replace(".", "_")
        if direct in tools:
            if len(tools[direct].strip()) < 15:
                thin_description.append(cap)
            continue
        if not has_operation_catalog:
            missing_tool_route.append(cap)
    result = {
        "tool_count": len(tools),
        "capabilities_checked": len(policy.capabilities),
        "missing_tool_route": missing_tool_route,
        "thin_description": thin_description,
        "ok": not missing_tool_route,
    }
    save(root, "discoverability", result)
    return result


async def read_test_note(pool, root: Path, label, recipient, message) -> tuple[bool, bool]:
    message_id = message["id"]
    after = message["seq"] - 1
    inbox = await call_tool(
        pool,
        recipient,
        "team_messages",
        {"after_direct": after, "after": 2**63 - 1, "limit": 1, "body_chars": 0},
    )
    save(root, f"{label}-inbox", inbox)
    if not inbox["ok"]:
        return False, False
    matched = any(
        item.get("id") == message_id and item.get("to") == recipient
        for item in inbox["value"].get("items", [])
    )
    if not matched:
        return False, False

    if message["seq"] in inbox["value"].get("acknowledged_by_read", {}).get("direct", []):
        # The inbox read already acknowledged this note for a configured observer/coordinator.
        acked = await call_tool(pool, recipient, "message_get", {"message_id": message_id})
    else:
        received = await call_tool(
            pool,
            recipient,
            "message_receive",
            {"after": after, "limit": 1, "conversation_id": message["conversation_id"]},
        )
        save(root, f"{label}-receive", received)
        if not received["ok"]:
            return True, False
        receipt = next(
            (
                item.get("receipt")
                for item in received["value"].get("messages", [])
                if item.get("id") == message_id
            ),
            None,
        )
        if not receipt:
            return True, False
        acked = await call_tool(
            pool, recipient, "message_ack", {"message_id": message_id, "receipt": receipt}
        )
    save(root, f"{label}-ack", acked)
    return True, bool(acked["ok"] and acked["value"].get("acknowledged"))


def message_is_hidden(result) -> bool:
    if result["ok"]:
        return False
    error = result.get("error")
    return isinstance(error, dict) and error.get("error", {}).get("code") == "not_found"


async def mailbox_round_trip(pool, root: Path) -> dict:
    run_tag = secrets.token_hex(6)
    conversation_id = "e2e-mailbox-" + run_tag
    body = f"[E2E-TEST] mailbox round trip {run_tag} — safe to ignore/delete"

    sent = await call_tool(
        pool,
        SENDER,
        "message_send",
        {
            "message": {
                "recipient": RECIPIENT,
                "conversation_id": conversation_id,
                "idempotency_key": conversation_id,
                "kind": "note",
                "body": body,
                "dispatch": False,
                "request_reply": False,
            }
        },
    )
    save(root, "mailbox-send", sent)
    if not sent["ok"]:
        return {"ok": False, "stage": "send", "detail": sent}
    message = sent["value"]
    delivered_to_recipient, acknowledged = await read_test_note(
        pool, root, "mailbox-recipient", RECIPIENT, message
    )

    isolation_clean = None
    try:
        await pool.connect(replace(peer(load_config(), ISOLATION_PROBE), id=ISOLATION_PROBE))
        result = await call_tool(
            pool, ISOLATION_PROBE, "message_get", {"message_id": message["id"]}
        )
        save(root, "mailbox-isolation-probe", result)
        isolation_clean = message_is_hidden(result)
    except Exception as exc:
        save(root, "mailbox-isolation-probe", {"skipped": True, "reason": repr(exc)})

    return {
        "ok": delivered_to_recipient and acknowledged and isolation_clean is not False,
        "message_id": message["id"],
        "delivered_to_recipient": delivered_to_recipient,
        "isolation_clean": isolation_clean,
        "acknowledged": acknowledged,
    }


THIRD_PARTY_RECIPIENT = "codex"


async def recipient_not_rewritten_check(pool, root: Path) -> dict:
    """Regression test for a real incident (fixed 2026-11-27, commit 41648f9
    "Remove coordinator-only-senders recipient rewrite"): team_manager and
    message_manager used to silently rewrite any explicit recipient to
    "coordinator" for messages sent by chatgpt. A message explicitly
    addressed to THIRD_PARTY_RECIPIENT (not RECIPIENT, which is the
    coordinator role in this suite's own config) must land only in that
    third party's own mailbox — never in the coordinator's ("local")."""
    run_tag = secrets.token_hex(6)
    conversation_id = "e2e-recip-" + run_tag
    body = f"[E2E-TEST] recipient-rewrite-check {run_tag} — safe to ignore/delete"

    sent = await call_tool(
        pool,
        SENDER,
        "message_send",
        {
            "message": {
                "recipient": THIRD_PARTY_RECIPIENT,
                "conversation_id": conversation_id,
                "idempotency_key": conversation_id,
                "kind": "note",
                "body": body,
                "dispatch": False,
                "request_reply": False,
            }
        },
    )
    save(root, "recipient-send", sent)
    if not sent["ok"]:
        return {"ok": False, "stage": "send", "detail": sent}
    message = sent["value"]
    recorded_recipient = message.get("recipient")
    delivered_to_third_party, acknowledged = await read_test_note(
        pool, root, "recipient-third-party", THIRD_PARTY_RECIPIENT, message
    )
    coordinator = await call_tool(pool, RECIPIENT, "message_get", {"message_id": message["id"]})
    save(root, "recipient-coordinator-visibility", coordinator)

    return {
        "ok": (
            recorded_recipient == THIRD_PARTY_RECIPIENT
            and delivered_to_third_party
            and message_is_hidden(coordinator)
            and acknowledged
        ),
        "message_id": message["id"],
        "recorded_recipient": recorded_recipient,
        "delivered_to_third_party": delivered_to_third_party,
        "leaked_to_coordinator": coordinator["ok"],
        "acknowledged": acknowledged,
    }


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.output.absolute()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)

    config = load_config()
    started = time.time()
    results = {
        "scope": "INSTALLED PRODUCTION BRIDGE; principal=chatgpt sending, "
        "local receiving; passive dispatch=false only",
        "checks": {},
    }

    async with MCPClientPool(call_timeout=20) as pool:
        await pool.connect(replace(peer(config, SENDER), id=SENDER))
        await pool.connect(replace(peer(config, RECIPIENT), id=RECIPIENT))
        await pool.connect(replace(peer(config, THIRD_PARTY_RECIPIENT), id=THIRD_PARTY_RECIPIENT))

        disc = await check_discoverability(pool, config, root)
        results["checks"]["discoverability"] = disc
        print(
            f"discoverability: {disc['tool_count']} tools, {disc['capabilities_checked']} "
            f"capabilities, {len(disc['missing_tool_route'])} without any tool route, "
            f"{len(disc['thin_description'])} with a thin description",
            flush=True,
        )

        conn = await call_tool(
            pool, SENDER, "connection_check", {"device": "desktop", "mode": "text"}
        )
        save(root, "connection_check", conn)
        results["checks"]["connection_check"] = {"ok": conn["ok"]}
        print("connection_check:", "ok" if conn["ok"] else conn.get("error"), flush=True)

        for label, tool, tool_args in DEDICATED_TOOL_CHECKS:
            res = await call_tool(pool, SENDER, tool, tool_args)
            save(root, label, res)
            results["checks"][label] = {"ok": res["ok"]}
            print(f"{label}: {'ok' if res['ok'] else res.get('error')}", flush=True)

        mailbox = await mailbox_round_trip(pool, root)
        results["checks"]["mailbox_round_trip"] = mailbox
        print(
            f"mailbox_round_trip: delivered={mailbox.get('delivered_to_recipient')} "
            f"isolation_clean={mailbox.get('isolation_clean')} "
            f"acknowledged={mailbox.get('acknowledged')}",
            flush=True,
        )

        recipient_check = await recipient_not_rewritten_check(pool, root)
        results["checks"]["recipient_not_rewritten"] = recipient_check
        print(
            f"recipient_not_rewritten: recorded={recipient_check.get('recorded_recipient')} "
            f"delivered_to_third_party={recipient_check.get('delivered_to_third_party')} "
            f"leaked_to_coordinator={recipient_check.get('leaked_to_coordinator')}",
            flush=True,
        )

    results["duration_seconds"] = round(time.time() - started, 2)
    results["all_ok"] = all(c.get("ok") for c in results["checks"].values())
    save(root, "summary", results)
    print(json.dumps({"all_ok": results["all_ok"]}, ensure_ascii=False), flush=True)
    return 0 if results["all_ok"] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
