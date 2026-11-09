"""Synthetic stdio MCP peer for ThreadDesk recovery tests (newline-delimited JSON-RPC).

Usage: td_synthetic_peer.py STATE_DIR. Every spawn appends its PID to STATE_DIR/pids and
reads STATE_DIR/mode once. Mode tokens (comma separated):
  die_at_start    exit before answering initialize
  serial          handle requests on the main thread; a hanging call blocks everything
  hang_get_thread  tools/call get_thread never answers
  exit_get_thread  the process exits when tools/call get_thread arrives
  close_get_thread stdout is closed on get_thread, the process stays alive
Every tools/call is also appended to STATE_DIR/calls (one tool name per line).
No file outside STATE_DIR is touched; no network is used.
"""

import json
import os
import sys
import threading
import time
from pathlib import Path

state = Path(sys.argv[1])
with (state / "pids").open("a") as handle:
    handle.write(f"{os.getpid()}\n")
modes = set((state / "mode").read_text().strip().split(",")) if (state / "mode").exists() else set()
if "die_at_start" in modes:
    sys.exit(1)
out_lock = threading.Lock()
SCHEMA = {"type": "object", "properties": {"id": {"type": "string"}}, "additionalProperties": False}
READ = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}
TOOLS = [
    {"name": "list_threads", "inputSchema": {"type": "object"}, "annotations": READ},
    {"name": "get_thread", "inputSchema": SCHEMA, "annotations": READ},
    {"name": "thread_manage", "inputSchema": {"type": "object"}},
    {"name": "echo_read", "inputSchema": SCHEMA, "annotations": READ},
]


def send(message):
    with out_lock:
        sys.stdout.write(json.dumps(message) + "\n")
        sys.stdout.flush()


def reply(request, result):
    send({"jsonrpc": "2.0", "id": request["id"], "result": result})


def handle(request):
    method, name = request.get("method"), (request.get("params") or {}).get("name")
    if "id" not in request:
        return
    if method == "initialize":
        reply(
            request,
            {
                "protocolVersion": request["params"]["protocolVersion"],
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "synthetic-td", "version": "0"},
            },
        )
    elif method == "tools/list":
        reply(request, {"tools": TOOLS})
    elif method == "tools/call":
        with (state / "calls").open("a") as handle:
            handle.write(f"{name}\n")
        if name == "get_thread" and "hang_get_thread" in modes:
            time.sleep(3600)
        if name == "get_thread" and "exit_get_thread" in modes:
            os._exit(0)
        if name == "get_thread" and "close_get_thread" in modes:
            os.close(1)
            time.sleep(3600)
        reply(request, {"content": [], "structuredContent": {"tool": name}, "isError": False})
    else:
        send({"jsonrpc": "2.0", "id": request["id"], "result": {}})


for line in sys.stdin:
    request = json.loads(line)
    if "serial" in modes:
        handle(request)
    else:
        threading.Thread(target=handle, args=(request,), daemon=True).start()
