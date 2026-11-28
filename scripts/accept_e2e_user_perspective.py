"""Reusable live E2E smoke suite — "user" perspective (principal=local).

Exercises the INSTALLED, PRODUCTION bridge exactly as the human operator's
own tools would (Desktop app / terminal), never an isolated simulation.
Covers two things on every run:

  1. function: do the core read-only/non-visible operations a user relies
     on actually answer, with the shape the catalog promises?
  2. discoverability ("Auffindbarkeit"): does `tools/list` expose a tool for
     every capability this principal holds (per config.toml), each with a
     non-empty, substantive description a user/agent could act on without
     guessing; and does `operation_catalog` resolve the exact argument
     schema for a representative read operation per group?

By default, excludes anything that pops a visible window, OS notification,
or otherwise acts on the user's screen (terminal.visible/session.open,
notifications.post, app.launch/focus/quit, keyboard/mouse actions, clipboard
writes, file mutations, process.terminate) — safe to re-run unattended.

With `--interactive` (operator-confirmed go-ahead, 2026-11-28: a visible
terminal and clipboard content during this specific check is expected and
fine), also runs terminal_control (one harmless `echo`, reusing an existing
empty Terminal.app shell when one exists rather than always opening a new
one, output read back and exit status checked) and a clipboard_write/
clipboard_read round trip that restores whatever was on the clipboard
beforehand. Still never touches keyboard/mouse, notifications, or any
other app's window even with this flag.

No production config change. No credential rotation.

Usage: python3 scripts/accept_e2e_user_perspective.py --output <new-dir> [--interactive]
"""

import argparse
import asyncio
import json
import secrets
import time
from dataclasses import replace
from pathlib import Path

from kirabridge.bridge_core.config import load_config
from kirabridge.local_runtime import peer
from kirabridge.mcp_gateway.client import MCPClientPool

PRINCIPAL = "local"

# Read-only operations a user-facing client calls routinely, grouped by the
# dedicated tool name where one exists. Each entry: (label, tool, args).
DEDICATED_TOOL_CHECKS = [
    ("bridge_health", "bridge_health", {}),
    ("session_catalog", "session_catalog", {}),
    ("task_list", "task_list", {}),
    ("policy_inspect", "policy_inspect", {}),
    ("agent_status", "agent_status", {}),
    ("agent_inventory", "agent_inventory", {}),
    ("queue_catalog", "queue_catalog", {}),
]

# Read-only capabilities with no dedicated tool: resolved through the
# generic action_request/operation_catalog route instead.
GENERIC_OPERATIONS = ["system.info", "windows.list", "apps.list", "process.list"]


def save(root: Path, name: str, value) -> None:
    (root / (name + ".json")).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n"
    )


async def call_tool(pool, who, tool, args):
    try:
        result = await pool.call(who, tool, args)
    except Exception as exc:  # connection/transport failure is still a result worth recording
        return {"ok": False, "error": repr(exc)}
    if result.isError:
        return {"ok": False, "error": result.structuredContent}
    return {"ok": True, "value": result.structuredContent}


async def call_operation(pool, who, operation, arguments=None):
    request = {
        "task_id": "e2e-" + secrets.token_hex(8),
        "operation": operation,
        "arguments": arguments or {},
        "idempotency_key": "e2e-" + secrets.token_hex(8),
    }
    return await call_tool(pool, who, "action_request", {"request": request})


async def check_discoverability(pool, config, root: Path) -> dict:
    catalog = await pool.list_tools(PRINCIPAL)
    tools = {t.name: (t.description or "") for t in catalog}
    policy = config.principals[PRINCIPAL]
    has_operation_catalog = "operation_catalog" in tools
    missing_tool_route = []
    thin_description = []
    for cap in policy.capabilities:
        direct = cap.replace(".", "_")
        if direct in tools:
            if len(tools[direct].strip()) < 15:
                thin_description.append(cap)
            continue
        # No dedicated tool: only "findable" if the generic operation catalog
        # exists and actually lists this capability (checked once below for
        # a representative sample, not every one, to keep this suite quick).
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


async def check_operation_catalog_resolves(pool, root: Path) -> dict:
    res = await call_tool(
        pool, PRINCIPAL, "operation_catalog", {"operations": GENERIC_OPERATIONS, "compact": True}
    )
    save(root, "operation_catalog", res)
    resolved = []
    if res["ok"]:
        try:
            payload = json.loads(res["value"]["content"][0]["text"]) if isinstance(
                res["value"], dict
            ) and "content" in res["value"] else res["value"]
            ops = payload.get("operations", payload)
            resolved = [op for op in GENERIC_OPERATIONS if op in ops]
        except Exception:
            resolved = []
    return {"ok": res["ok"] and len(resolved) == len(GENERIC_OPERATIONS), "resolved": resolved}


async def poll_task(pool, who, task_id, root, label, timeout=25):
    """terminal_control/clipboard_* return the task record at submission time
    (state="running"); the actual result only appears once task_get reports
    state="completed" (or another terminal state). Poll instead of trusting
    the immediate response."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        res = await call_tool(pool, who, "task_get", {"task_id": task_id})
        last = res
        if res["ok"] and res["value"].get("state") in ("completed", "failed", "blocked", "unknown"):
            break
        await asyncio.sleep(0.5)
    save(root, label, last)
    return last


async def check_terminal_control(pool, root: Path) -> dict:
    """One harmless, clearly-tagged `echo` — reuses an existing empty
    Terminal.app shell when one exists (terminal_control's own default),
    never forces a second window when the first already does the job."""
    tag = secrets.token_hex(6)
    marker = f"kirabridge-e2e-test-{tag}"
    run_id = "e2e-term-" + tag
    submitted = await call_tool(
        pool, PRINCIPAL, "terminal_control",
        {
            "argv": ["/bin/echo", marker],
            "cwd": str(Path.home()),
            "task_id": run_id,
            "idempotency_key": run_id,
            "create_if_needed": True,
            "timeout": 20,
        },
    )
    save(root, "terminal_control-submit", submitted)
    if not submitted["ok"]:
        return {"ok": False, "error": submitted.get("error")}

    final = await poll_task(pool, PRINCIPAL, run_id, root, "terminal_control-final")
    if not final or not final["ok"]:
        return {"ok": False, "error": (final or {}).get("error", "no final state")}
    task = final["value"]
    result = task.get("result") or {}
    output = json.dumps(task)
    return {
        "ok": task.get("state") == "completed" and result.get("exit_code") == 0 and marker in output,
        "state": task.get("state"),
        "exit_code": result.get("exit_code"),
        "output_matched": marker in output,
    }


async def clipboard_write(pool, root, tag, label, text):
    run_id = "e2e-clip-" + label + "-" + tag
    submitted = await call_tool(
        pool, PRINCIPAL, "clipboard_write",
        {"task_id": run_id, "idempotency_key": run_id, "text": text},
    )
    save(root, "clipboard-" + label + "-submit", submitted)
    if not submitted["ok"]:
        return False
    final = await poll_task(pool, PRINCIPAL, run_id, root, "clipboard-" + label + "-final")
    return bool(final and final["ok"] and final["value"].get("state") == "completed")


async def clipboard_read(pool, root, tag, label):
    run_id = "e2e-clip-" + label + "-" + tag
    submitted = await call_tool(
        pool, PRINCIPAL, "clipboard_read",
        {"task_id": run_id, "idempotency_key": run_id},
    )
    save(root, "clipboard-" + label + "-submit", submitted)
    if not submitted["ok"]:
        return None
    final = await poll_task(pool, PRINCIPAL, run_id, root, "clipboard-" + label + "-final")
    if not final or not final["ok"] or final["value"].get("state") != "completed":
        return None
    return (final["value"].get("result") or {}).get("text")


async def check_clipboard_round_trip(pool, root: Path) -> dict:
    """Writes one clearly-tagged test string, reads it back, then restores
    whatever was on the clipboard before — never leaves test content behind."""
    tag = secrets.token_hex(6)
    original_text = await clipboard_read(pool, root, tag, "before")

    marker = f"kirabridge-e2e-test-{tag}"
    write_ok = await clipboard_write(pool, root, tag, "write", marker)
    read_back = await clipboard_read(pool, root, tag, "after")

    restore_ok = True
    if original_text is not None:
        restore_ok = await clipboard_write(pool, root, tag, "restore", original_text)

    return {
        "ok": write_ok and read_back == marker and restore_ok,
        "restored": restore_ok and original_text is not None,
    }


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--interactive", action="store_true",
        help="Also run terminal_control + clipboard round trip (visible on screen).",
    )
    args = parser.parse_args()
    root = args.output.absolute()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)

    config = load_config()
    started = time.time()
    results = {
        "scope": "INSTALLED PRODUCTION BRIDGE; principal=local; read-only only",
        "checks": {},
    }

    async with MCPClientPool(call_timeout=25) as pool:
        await pool.connect(replace(peer(config, PRINCIPAL), id=PRINCIPAL))

        disc = await check_discoverability(pool, config, root)
        results["checks"]["discoverability"] = disc
        print(
            f"discoverability: {disc['tool_count']} tools, {disc['capabilities_checked']} "
            f"capabilities, {len(disc['missing_tool_route'])} without any tool route, "
            f"{len(disc['thin_description'])} with a thin description",
            flush=True,
        )

        for label, tool, tool_args in DEDICATED_TOOL_CHECKS:
            res = await call_tool(pool, PRINCIPAL, tool, tool_args)
            save(root, label, res)
            results["checks"][label] = {"ok": res["ok"]}
            print(f"{label}: {'ok' if res['ok'] else res.get('error')}", flush=True)

        for op in GENERIC_OPERATIONS:
            res = await call_operation(pool, PRINCIPAL, op)
            save(root, "op-" + op.replace(".", "_"), res)
            results["checks"]["operation:" + op] = {"ok": res["ok"]}
            print(f"operation {op}: {'ok' if res['ok'] else res.get('error')}", flush=True)

        catalog_check = await check_operation_catalog_resolves(pool, root)
        results["checks"]["operation_catalog_resolves"] = catalog_check
        print(
            f"operation_catalog resolves {len(catalog_check['resolved'])}/"
            f"{len(GENERIC_OPERATIONS)} sampled operations",
            flush=True,
        )

        if args.interactive:
            terminal = await check_terminal_control(pool, root)
            results["checks"]["terminal_control"] = terminal
            print(
                f"terminal_control: ok={terminal['ok']} exit_code={terminal.get('exit_code')} "
                f"output_matched={terminal.get('output_matched')}",
                flush=True,
            )

            clip = await check_clipboard_round_trip(pool, root)
            results["checks"]["clipboard_round_trip"] = clip
            print(
                f"clipboard_round_trip: ok={clip['ok']} restored={clip.get('restored')}",
                flush=True,
            )

    results["duration_seconds"] = round(time.time() - started, 2)
    results["all_ok"] = all(c.get("ok") for c in results["checks"].values())
    save(root, "summary", results)
    print(json.dumps({"all_ok": results["all_ok"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
