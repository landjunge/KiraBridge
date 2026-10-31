"""Manual native acceptance in one new, owned Intel-macOS Terminal window.

Run against worktree source with PYTHONPATH=src. This starts a private authenticated
HTTP MCP instance, never installs/restarts a service, and never types into an
existing agent. Captures under --root are private, not publication artifacts.
An unknown input outcome stops the test; the input is never replayed.
Known separate limitation: a short, noncollapsed multiline draft may wrap so
native_paste_observation cannot prove its full last logical line. Run04 stopped
with visible_paste_unconfirmed before Return; this harness does not relax that
product guard. The optional agent setup fixture is explicitly one short line.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import re
import secrets
import shlex
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import uvicorn

import kirabridge
from kirabridge.bridge_core.bridge import Bridge
from kirabridge.bridge_core.config import (
    AgentConfig,
    Config,
    PrincipalConfig,
    VisibleTerminalBinding,
)
from kirabridge.bridge_core.models import TaskRequest
from kirabridge.literal_session_input import insertion_observed
from kirabridge.mcp_gateway.client import MCPClientPool, Peer
from kirabridge.mcp_gateway.http import create_http_app
from kirabridge.platform_adapters.shell_prompt import empty_shell_prompt
from kirabridge.session_return import return_readiness
from kirabridge.visible_readiness import assess, input_view

TERMINAL = {"completed", "failed", "cancelled", "unknown", "blocked"}
BUSY_SOURCE = """import sys,time
from pathlib import Path
root=Path(sys.argv[1]); (root/'busy-started').write_text('own bounded fixture')
deadline=time.monotonic()+45
while not (root/'release-busy').exists():
    if time.monotonic()>deadline: sys.exit(99)
    time.sleep(.05)
"""


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def old_insertion_verifier(source_root):
    """Offline baseline replay only; git source contains function definitions."""
    source = subprocess.check_output(
        ["git", "-C", str(source_root), "show", "fa863a6:src/kirabridge/literal_session_input.py"],
        text=True,
        timeout=5,
    )
    namespace = {"__name__": "kirabridge_acceptance_baseline"}
    exec(compile(source, "fa863a6:literal_session_input.py", "exec"), namespace)
    return namespace["insertion_observed"]


def owned_turn_messages(records, thread_id, expected_prompt, expected_answer):
    """Read one typed own turn, never flatten arbitrary records or count mirrors.

    Modern Codex emits item_completed UserMessage/AgentMessage events as well as
    response_item mirrors. Only the authoritative event family is counted here.
    The legacy event family is used only when there are no modern message items.
    """
    assert records and records[0].get("type") == "session_meta"
    assert records[0].get("payload", {}).get("id") == thread_id
    events = [r["payload"] for r in records if r.get("type") == "event_msg"]
    modern = [
        (index, event)
        for index, event in enumerate(events)
        if event.get("type") == "item_completed"
        and isinstance(event.get("item"), dict)
        and event["item"].get("type") in {"UserMessage", "AgentMessage"}
    ]

    def item_text(item):
        content = item.get("content")
        if not isinstance(content, list) or len(content) != 1:
            return None
        block = content[0]
        if not isinstance(block, dict) or block.get("type") not in {"text", "Text"}:
            return None
        return block.get("text") if isinstance(block.get("text"), str) else None

    if modern:
        users = [
            (index, event)
            for index, event in modern
            if event.get("thread_id") == thread_id
            and event["item"].get("type") == "UserMessage"
            and item_text(event["item"]) == expected_prompt
        ]
    else:
        users = [
            (index, event)
            for index, event in enumerate(events)
            if event.get("type") == "user_message"
            and event.get("message") == expected_prompt
            and event.get("thread_id", thread_id) == thread_id
        ]
    if not users:
        return None
    assert len(users) == 1, "Expected exactly one own prompt in authoritative events"
    user_index, user = users[0]
    turn_id = user.get("turn_id")
    if not isinstance(turn_id, str) or not turn_id:
        return None
    if modern:
        answers = [
            (index, event)
            for index, event in modern
            if event.get("thread_id") == thread_id
            and event.get("turn_id") == turn_id
            and event["item"].get("type") == "AgentMessage"
            and event["item"].get("phase") == "final_answer"
        ]
        if not answers:
            return None
        assert len(answers) == 1 and item_text(answers[0][1]["item"]) == expected_answer
        user_id, answer_id = user["item"].get("id"), answers[0][1]["item"].get("id")
    else:
        answers = [
            (index, event)
            for index, event in enumerate(events)
            if event.get("type") == "agent_message"
            and event.get("turn_id") == turn_id
            and event.get("thread_id", thread_id) == thread_id
            and event.get("message") == expected_answer
        ]
        if not answers:
            return None
        assert len(answers) == 1
        user_id, answer_id = user.get("id"), answers[0][1].get("id")
    starts = [
        index
        for index, event in enumerate(events)
        if event.get("type") == "task_started" and event.get("turn_id") == turn_id
    ]
    completions = [
        index
        for index, event in enumerate(events)
        if event.get("type") == "task_complete"
        and event.get("turn_id") == turn_id
        and event.get("last_agent_message", expected_answer) == expected_answer
    ]
    if not starts or not completions:
        return None
    assert len(starts) == len(completions) == 1
    assert starts[0] < user_index < answers[0][0] < completions[0]
    return {
        "thread_id": thread_id,
        "turn_id": turn_id,
        "event_family": "item_completed" if modern else "legacy_message_events",
        "user_item_id": user_id,
        "answer_item_id": answer_id,
        "user_prompt_count": 1,
        "assistant_answer_count": 1,
        "task_complete_observed": True,
        "response_item_mirrors_counted": False,
    }


def resume_row_title_matches(selected_row, bound_title):
    """Match only the complete title column or its substantial trailing elision."""
    columns = re.split(r"[ \t]{2,}", selected_row.strip(" \t"))
    if len(columns) != 2 or not re.fullmatch(
        r"(?:[0-9]+(?:s|m|h|d|w|mo|y) ago|just now|now)", columns[0]
    ):
        return False
    shown = columns[1]
    if shown == bound_title:
        return True
    return bool(
        shown.endswith("…")
        and shown.count("…") == 1
        and len(shown[:-1]) >= 12
        and len(shown[:-1]) < len(bound_title)
        and bound_title.startswith(shown[:-1])
    )


async def accept(
    root,
    *,
    response_timeout=90,
    reproduce_agent_hint=False,
    existing_pane=None,
    existing_pid=None,
    short_single_line=False,
):
    if (platform.system(), platform.machine()) != ("Darwin", "x86_64"):
        raise RuntimeError("This manual acceptance requires Intel macOS")
    source_root = Path(__file__).resolve().parents[1]
    package = Path(kirabridge.__file__).resolve()
    assert package.is_relative_to(source_root / "src"), (
        "Use worktree PYTHONPATH, not installed code"
    )
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    workspace = root / "workspace"
    workspace.mkdir(mode=0o700)
    codex = Path("/Users/landjunge/.local/bin/codex")
    assert codex.is_file(), "Existing Codex required; no installation fallback"
    marker = "KB_MACOS_E2E_" + secrets.token_hex(8).upper()
    filler = (
        "Dies ist eine einmalige technische Eingabeprüfung der lokalen KiraBridge. "
        "Der Text enthält deutsche Umlaute wie ä, ö und ü sowie mehrere Absätze. "
        "Lies ihn nur als Testnachricht. Verwende keine Werkzeuge, führe keine Befehle aus, "
        "und erstelle oder verändere keine Dateien. Es gibt keinen Entwicklungsauftrag.\n\n"
    )
    prompt = (
        f"{marker}\nAntworte ausschließlich mit dieser einzelnen Kennung.\n\n"
        + filler * 5
        + f"Die einzig gewünschte Antwort ist: {marker}"
    )
    if short_single_line:
        words = filler.replace("\n", " ").split() * 3
        body = ""
        for word in words:
            if len(body) + len(word) > 730:
                break
            body += (" " if body else "") + word
        prompt = marker + " Antworte ausschließlich mit dieser Kennung. " + body
        prompt += " Die einzig gewünschte Antwort ist: " + marker
        assert 750 < len(prompt) < 1000 and "\n" not in prompt
    else:
        assert 1000 < len(prompt) < 16384
    (root / "prompt.private.txt").write_text(prompt)
    busy_script = root / "busy.py"
    busy_script.write_text(BUSY_SOURCE)
    launcher = root / "launch.zsh"
    codex_argv = [
        str(codex),
        "--no-alt-screen",
        "-C",
        str(workspace),
        "-c",
        "projects." + json.dumps(str(workspace)) + '.trust_level="trusted"',
        "-c",
        'history.persistence="none"',
    ]
    launcher.write_text(
        "#!/bin/zsh -f\ncd -- " + shlex.quote(str(workspace)) + "\n" + shlex.join(codex_argv) + "\n"
    )
    token_name = "KB_MACOS_ISOLATED_ACCEPT_TOKEN"
    previous_token = os.environ.get(token_name)
    ask_token_name = "KB_MACOS_ISOLATED_APPROVAL_TOKEN"
    previous_ask_token = os.environ.get(ask_token_name)
    token = secrets.token_urlsafe(48)
    ask_token = secrets.token_urlsafe(48)
    os.environ[token_name] = token
    os.environ[ask_token_name] = ask_token
    config = Config(
        data_dir=str(root / "state"),
        concurrency=2,
        principals={
            "chatgpt": PrincipalConfig(
                client_type="chatgpt",
                permission_level="full",
                approval_mode="automatic",
                token_env=token_name,
                roots=[str(root)],
                terminal_roots=[str(root)],
                executables=[sys.executable, "/bin/zsh", str(codex)],
                agents=["codex"],
                capabilities=[
                    "session.open",
                    "session.inspect",
                    "session.input",
                    "terminal.execute",
                    "agent.execute",
                    "bridge.health",
                    "task.read",
                    "task.cancel",
                ],
            ),
            "ask": PrincipalConfig(
                permission_level="ask",
                approval_mode="manual",
                token_env=ask_token_name,
                roots=[str(root)],
                capabilities=["file.write", "task.read", "bridge.health"],
            ),
        },
        agents={"codex": AgentConfig(kind="codex", executable=str(codex))},
    )
    bridge = Bridge(config)
    transport = bridge.sessions.terminal_app
    original_catalog, original_native = transport.catalog, transport.native
    original_check = bridge.visible_handoffs.check_target
    inventory = await transport.window_inventory()
    original_windows = {row["window_id"] for row in inventory["windows"]}
    original_rows = await original_catalog()
    identities = {
        process["pid"]: await transport.process_identity(process["pid"], detailed=True)
        for row in original_rows
        for process in row["processes"]
    }
    evidence = {
        "platform": platform.platform(),
        "package": str(package),
        "runtime": bridge.runtime,
        "root": str(root),
        "scope": "private authenticated HTTP MCP, confirmed existing idle terminal"
        if existing_pane
        else "private authenticated HTTP MCP, one new owned visible terminal",
        "prompt_sha256": sha(prompt),
        "prompt_chars": len(prompt),
        "marker": marker,
        "before_windows": sorted(original_windows),
        "before_pids": sorted(identities),
        "checks": [],
        "native_mutations": [],
        "acceptance": "in_progress",
        "production_modified": False,
        "known_native_input_limitation": (
            "Short noncollapsed multiline input can remain visible_paste_unconfirmed; "
            "no Return/replay. Separate from the corrected disappearing shortcut footer."
        ),
    }
    owned = binding = rollout = None
    active_literal_label = "startup"
    server = server_task = sock = None
    started = False
    captures = []

    def checkpoint():
        (root / "evidence.private.json").write_text(json.dumps(evidence, indent=2) + "\n")

    def check(name, **detail):
        record = {"name": name, **detail}
        evidence["checks"].append(record)
        checkpoint()
        print(json.dumps(record), flush=True)

    async def traced_native(source, *, mutation=False):
        if mutation:
            trace = {"source_sha256": sha(source), "at": time.time()}
            evidence["native_mutations"].append(trace)
            checkpoint()
            try:
                value = await original_native(source, mutation=mutation)
            except BaseException as error:
                trace["error"] = getattr(error, "code", type(error).__name__)
                checkpoint()
                raise
            trace["result"] = value
            checkpoint()
            return value
        return await original_native(source, mutation=False)

    async def traced_check(principal, target, selected, *, ready=False):
        assert owned and selected.pane_id == owned["pane_id"], "No unrelated target may be read"
        value = await original_check(principal, target, selected, ready=ready)
        record = {
            "at": time.time(),
            "current_task": asyncio.current_task().get_name(),
            "ready_required": ready,
            "principal": principal,
            "target": target,
            "input_label": active_literal_label,
            "binding": selected.model_dump(),
            "text": value["text"],
        }
        captures.append(record)
        (root / "inside-task-frames.private.json").write_text(
            json.dumps(captures, indent=2, ensure_ascii=False) + "\n"
        )
        return value

    transport.native = traced_native
    bridge.visible_handoffs.check_target = traced_check

    async def current_owned():
        rows = [row for row in await original_catalog() if row["pane_id"] == owned["pane_id"]]
        assert len(rows) == 1 and rows[0]["expected_pid"] == owned["expected_pid"]
        assert not rows[0].get("identity_ambiguous"), "Owned target is ambiguous"
        return rows[0]

    async def wait_shell():
        async with asyncio.timeout(20):
            while True:  # noqa: ASYNC110 -- bounded own native shell observation
                row = await current_owned()
                if not row["busy"] and [p["pid"] for p in row["processes"]] == [
                    owned["expected_pid"]
                ]:
                    raw = await transport.read(owned["pane_id"])
                    if empty_shell_prompt(raw):
                        return raw
                await asyncio.sleep(0.2)

    def request(label, operation="session.input", arguments=None):
        return TaskRequest(
            task_id="macos-" + root.name[-55:] + "-" + label,
            idempotency_key="macos-" + root.name[-55:] + "-" + label,
            operation=operation,
            arguments=arguments or {},
        )

    def input_request(label, text, **overrides):
        return request(
            label,
            arguments={
                "pane_id": owned["pane_id"],
                "expected_pid": owned["expected_pid"],
                "text": text,
                "submit": True,
                **overrides,
            },
        )

    async def cleanup_owned():
        if owned is None:
            after = await transport.window_inventory()
            assert {row["window_id"] for row in after["windows"]} == original_windows
            for pid, expected in identities.items():
                assert await transport.process_identity(pid, detailed=True) == expected
            evidence["cleanup"] = {
                "owned_window_never_established": True,
                "original_windows_and_process_identities_preserved": True,
                "native_mutation_count": len(evidence["native_mutations"]),
                "no_native_or_session_effects": not evidence["native_mutations"],
            }
            return
        row = await current_owned()
        raw = await transport.read(owned["pane_id"])
        if binding is not None:
            processes = [p for p in row["processes"] if p["name"] == "codex"]
            if processes:
                assert [p["pid"] for p in processes] == [binding.agent_pid]
                protocol = None
                if binding.codex_thread_id:
                    protocol = await bridge.visible_handoffs.codex_state.read(
                        binding.codex_rollout_path, binding.codex_thread_id
                    )
                return_state = return_readiness("codex", raw, binding, protocol)
                if return_state.get("reason") == "observed_codex_resume_selector":
                    identities_for_escape = {
                        pid: await transport.process_identity(pid, detailed=True)
                        for pid in [owned["expected_pid"], binding.agent_pid]
                    }
                    evidence["own_picker_cleanup"] = await transport.native(
                        transport.native_focus(owned["pane_id"])
                        + transport.native_identity_guard(identities_for_escape)
                        + "\ncheckFocus();checkTargetIdentity();"
                        + transport.native_screen_guard(raw)
                        + "\nse.keyCode(53);JSON.stringify({own_picker_escape:true});",
                        mutation=True,
                    )
                    await asyncio.sleep(0.3)
                    raw = await transport.read(owned["pane_id"])
                assert assess("codex", raw, binding, protocol)["ready"], (
                    "No cleanup of busy/nonempty Codex"
                )
                guard = {
                    pid: await transport.process_identity(pid, detailed=True)
                    for pid in [owned["expected_pid"], binding.agent_pid]
                }
                evidence["codex_cleanup"] = await transport.native(
                    transport.native_focus(owned["pane_id"])
                    + transport.native_identity_guard(guard)
                    + "\ncheckFocus();checkTargetIdentity();"
                    + transport.native_screen_guard(raw)
                    + "\nse.keystroke('d',{using:'control down'});"
                    + "JSON.stringify({owned_codex_eof:true,return_sent:false});",
                    mutation=True,
                )
                await wait_shell()
        raw = await wait_shell()
        assert empty_shell_prompt(raw)
        row = await current_owned()
        assert [p["pid"] for p in row["processes"]] == [owned["expected_pid"]]
        if existing_pane is None:
            evidence["close"] = await transport.close_tab(owned["pane_id"])
        after = await transport.window_inventory()
        after_ids = {r["window_id"] for r in after["windows"]}
        assert after_ids == original_windows, "Original windows changed"
        pids = await transport.process_ids()
        assert (owned["expected_pid"] in pids) == (existing_pane is not None)
        if binding is not None:
            assert binding.agent_pid not in pids
        for pid, expected in identities.items():
            assert await transport.process_identity(pid, detailed=True) == expected
        evidence["cleanup"] = {
            "owned_window_absent": existing_pane is None,
            "owned_shell_absent": existing_pane is None,
            "reused_existing_idle_shell_preserved": existing_pane is not None,
            "owned_agent_absent": binding is not None,
            "original_windows_and_process_identities_preserved": True,
        }

    try:
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        sock.listen(64)
        config.port = sock.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(create_http_app(bridge), log_level="critical", access_log=False)
        )
        await bridge.tasks.start()
        started = True
        server_task = asyncio.create_task(server.serve(sockets=[sock]))
        async with asyncio.timeout(10):
            while not server.started:
                if server_task.done():
                    await server_task
                await asyncio.sleep(0.03)
        endpoint = f"http://127.0.0.1:{config.port}/mcp"
        async with httpx.AsyncClient(trust_env=False) as client:
            assert (await client.post(endpoint, json={})).status_code == 401
        check("private endpoint rejects unauthenticated request")
        async with MCPClientPool(call_timeout=55) as clients:
            await clients.connect(Peer("chatgpt", url=endpoint, token=token))
            await clients.connect(Peer("ask", url=endpoint, token=ask_token))

            async def call(tool, arguments, *, peer="chatgpt"):
                result = await clients.call(peer, tool, arguments)
                assert isinstance(result.structuredContent, dict), result
                return result.structuredContent

            async def completed(value, *, peer="chatgpt"):
                async with asyncio.timeout(45):
                    while True:  # noqa: ASYNC110 -- own persisted task state readback
                        task = await call("task_get", {"task_id": value.task_id}, peer=peer)
                        if task.get("state") in TERMINAL:
                            (root / (value.task_id + ".private.json")).write_text(
                                json.dumps(task, indent=2) + "\n"
                            )
                            return task
                        await asyncio.sleep(0.15)

            async def submit(value):
                result = await call("action_request", {"request": value.model_dump()})
                # Immediate native admission can already return the terminal
                # task's expected failure (busy/stale); this is still an
                # accepted, persisted task, distinct from schema rejection.
                assert result.get("id") == value.task_id, result
                return await completed(value)

            tools = await clients.list_tools("chatgpt")
            names = {tool.name for tool in tools}
            assert "macos_status" in names, "Provider integration/status tool not present"
            status = await call("macos_status", {})
            assert not status.get("error"), status
            catalogue = await call("operation_catalog", {})
            assert "platform.status" in catalogue["operations"], catalogue
            evidence["macos_status"] = status
            evidence["discovery_revision"] = catalogue["discovery"]["revision"]
            check("new status tool and generic operation discovered through authenticated HTTP")
            helper_status = await call("macos_status", {"check_helpers": True})
            diagnostic = helper_status.get("helper_diagnostics", {})
            assert diagnostic.get("status") == "observed", diagnostic
            assert diagnostic.get("authorizes_future_helpers") is False, diagnostic
            assert diagnostic.get("updates_provider_permissions") is False, diagnostic
            assert diagnostic.get("cleanup_confirmed") is True, diagnostic
            assert not bridge.macos.actor_identities
            evidence["helper_diagnostics"] = diagnostic
            check(
                "explicit native helper diagnostics are identity-bound and never execution grants"
            )
            generic_status = await submit(request("platform-status", "platform.status"))
            assert generic_status["state"] == "completed", generic_status
            check("platform.status executed through the existing task/policy path")

            approval_path = root / "approved-once.txt"
            approval_request = request(
                "approval-once",
                "file.write",
                {"path": str(approval_path), "text": "one exact approved write\n"},
            )
            waiting = await call(
                "action_request", {"request": approval_request.model_dump()}, peer="ask"
            )
            assert waiting.get("state") == "created" and waiting.get("approval_required"), waiting
            assert waiting.get("started") is None and not approval_path.exists()
            grant = bridge.security.grant("ask", approval_request)
            approved = await call(
                "task_submit",
                {"request": approval_request.model_dump(), "approval": grant},
                peer="ask",
            )
            assert not approved.get("error"), approved
            approved_task = await completed(approval_request, peer="ask")
            assert approved_task["state"] == "completed", approved_task
            assert approved_task["attempt"] == 1
            assert approval_path.read_text() == "one exact approved write\n"
            changed_path = root / "must-not-be-approved.txt"
            changed_request = request(
                "approval-reuse-rejected",
                "file.write",
                {"path": str(changed_path), "text": "MUST NOT BE WRITTEN"},
            )
            reused = await call(
                "task_submit",
                {"request": changed_request.model_dump(), "approval": grant},
                peer="ask",
            )
            assert reused.get("error", {}).get("code") == "approval_required", reused
            assert not changed_path.exists()
            duplicate_approval = await call(
                "task_submit",
                {"request": approval_request.model_dump(), "approval": grant},
                peer="ask",
            )
            assert duplicate_approval.get("state") == "completed", duplicate_approval
            assert approval_path.read_text() == "one exact approved write\n"
            approved_events = await call(
                "task_events", {"task_id": approval_request.task_id}, peer="ask"
            )
            assert sum(event["state"] == "running" for event in approved_events["events"]) == 1
            check("manual approval waits without effect; exact grant executes once; reuse denied")

            if existing_pane is None:
                opened = await submit(
                    request(
                        "open", "session.open", {"cwd": str(workspace), "controlled_shell": True}
                    )
                )
                assert opened["state"] == "completed", opened
                result = opened["result"]
            else:
                result = next(row for row in original_rows if row["pane_id"] == existing_pane)
                assert result["expected_pid"] == existing_pid and not result["busy"]
                assert [p["pid"] for p in result["processes"]] == [existing_pid]
                assert empty_shell_prompt(await transport.read(existing_pane))
            owned = {key: result[key] for key in ("pane_id", "expected_pid", "tty")}
            added = {
                row["window_id"] for row in (await transport.window_inventory())["windows"]
            } - original_windows
            assert added == (set() if existing_pane else {int(owned["pane_id"].split(":")[1])})
            evidence["owned"] = owned
            checkpoint()
            await wait_shell()

            # Narrowing real observations is not a fabricated ready state. Only
            # the newly created, independently identified resource can be used.
            async def owned_catalog():
                return [
                    row for row in await original_catalog() if row["pane_id"] == owned["pane_id"]
                ]

            transport.catalog = owned_catalog

            async def forbidden(*_args, **_kwargs):
                evidence.setdefault("forbidden_fallback_attempts", []).append(True)
                checkpoint()
                raise AssertionError("No hidden/raw-send/additional-window fallback allowed")

            transport.open = transport.send = bridge.sessions.tmux.send = forbidden
            bridge.terminal.execute = forbidden
            busy = await submit(
                input_request(
                    "busy-start", shlex.join([sys.executable, str(busy_script), str(root)])
                )
            )
            assert busy["state"] == "completed", busy
            async with asyncio.timeout(10):
                while not (root / "busy-started").exists():  # noqa: ASYNC110 -- own fixture witness
                    await asyncio.sleep(0.1)
            mutations = len(evidence["native_mutations"])
            blocked = await submit(input_request("busy-rejected", "# MUST_NOT_BE_INSERTED"))
            assert blocked["state"] == "failed" and blocked["error"]["code"] == "session_busy"
            assert len(evidence["native_mutations"]) == mutations
            (root / "release-busy").write_text("release only own test fixture\n")
            await wait_shell()
            check("real busy shell rejected before native mutation")

            launched_at = time.time()
            session_files = set((Path.home() / ".codex" / "sessions").rglob("*.jsonl"))
            startup = await submit(
                input_request("codex-start", shlex.join(["/bin/zsh", str(launcher)]))
            )
            assert startup["state"] == "completed", startup
            async with asyncio.timeout(70):
                previous = None
                stable = 0
                while True:  # noqa: ASYNC110 -- native startup observation
                    row = await current_owned()
                    agents = [p for p in row["processes"] if p["name"] == "codex"]
                    raw = await transport.read(owned["pane_id"])
                    if len(agents) == 1:
                        candidate = VisibleTerminalBinding(
                            **{k: owned[k] for k in ("pane_id", "expected_pid")},
                            agent_pid=agents[0]["pid"],
                            ready_pattern=r"(?m)^[ \t]*›(?: Ask Codex to do anything)?[ \t]*$",
                        )
                        view = input_view("codex", raw)
                        ready = assess("codex", raw, candidate)["ready"] and "\n  GPT-" in view
                        stable = stable + 1 if ready and view == previous else int(ready)
                        previous = view
                        if stable >= 2:
                            binding = candidate
                            break
                    await asyncio.sleep(0.35)
            config.visible_handoffs.bindings["codex"] = binding
            evidence["binding"] = binding.model_dump()
            (root / "startup.private.json").write_text(
                json.dumps({"row": row, "text": raw}, indent=2)
            )
            check("own Codex reached two identical ready frames", agent_pid=binding.agent_pid)

            async def wait_owned_answer(prompt, marker, label):
                nonlocal binding, rollout
                answer = None
                async with asyncio.timeout(response_timeout):
                    while True:  # noqa: ASYNC110 -- bounded real agent answer observation
                        observed = await call(
                            "read_query",
                            {
                                "query": {
                                    "operation": "session.read",
                                    "pane_id": owned["pane_id"],
                                    "expected_pid": owned["expected_pid"],
                                }
                            },
                        )
                        assert not observed.get("error"), observed
                        raw = observed["text"]
                        (root / (label + "-screen.private.txt")).write_text(raw)
                        if rollout is None:
                            candidates = []
                            for path in (Path.home() / ".codex" / "sessions").rglob("*.jsonl"):
                                if path in session_files or path.stat().st_mtime < launched_at:
                                    continue
                                with path.open() as stream:
                                    first = stream.readline(4 * 1024 * 1024)
                                try:
                                    header = json.loads(first)
                                except json.JSONDecodeError:
                                    continue
                                if header.get("type") == "session_meta" and header.get(
                                    "payload", {}
                                ).get("cwd") == str(workspace):
                                    candidates.append(path)
                            assert len(candidates) <= 1, "Ambiguous own Codex rollout"
                            rollout = candidates[0] if candidates else None
                        if rollout is not None:
                            assert rollout.stat().st_size < 8 * 1024 * 1024
                            contents = rollout.read_text()
                            # The writer may be appending its last record. Only
                            # complete newline-terminated records are evidence.
                            records = [
                                json.loads(line)
                                for line in contents[: contents.rfind("\n") + 1].splitlines()
                                if line
                            ]
                            header = records[0]["payload"]
                            turn = owned_turn_messages(records, header["id"], prompt, marker)
                            protocol = await bridge.visible_handoffs.codex_state.read(
                                str(rollout), header["id"]
                            )
                            if turn and assess("codex", raw, binding, protocol)["ready"]:
                                assert re.search(
                                    r"(?m)^\s*(?:•\s*)?" + re.escape(marker) + r"\s*$", raw
                                )
                                answer = {
                                    "rollout": str(rollout),
                                    "screen_sha256": sha(raw),
                                    **turn,
                                }
                                binding = binding.model_copy(
                                    update={
                                        "codex_thread_id": header["id"],
                                        "codex_rollout_path": str(rollout),
                                    }
                                )
                                config.visible_handoffs.bindings["codex"] = binding
                                break
                        await asyncio.sleep(0.4)
                return answer

            if reproduce_agent_hint:
                setup_marker = marker + "_SETUP"
                setup_prompt = setup_marker + " 1 Text-Unteragent; warten+schließen; nur Kennung."
                assert "\n" not in setup_prompt and len(setup_prompt) < 90
                (root / "setup-prompt.private.txt").write_text(setup_prompt)
                active_literal_label = "agent-hint-setup"
                setup_task = await submit(input_request("agent-hint-setup", setup_prompt))
                assert setup_task["state"] == "completed", setup_task
                assert setup_task["result"].get("return_sent") is True
                setup_answer = await wait_owned_answer(setup_prompt, setup_marker, "setup-response")
                evidence["agent_hint_setup"] = setup_answer
                check("one explicitly requested own test-subagent turn completed", **setup_answer)
                raw = await transport.read(owned["pane_id"])
                view = input_view("codex", raw)
                hint_present = any(
                    row.strip() == "← for agents · ? for shortcuts" for row in view.splitlines()[1:]
                )
                (root / "agent-hint-before-long.private.txt").write_text(raw)
                evidence["agent_hint_before_long_prompt"] = hint_present
                checkpoint()
                assert hint_present, (
                    "Real agent shortcut footer not present; no regression replay claimed"
                )
                check("real Codex subagent shortcut footer observed before main long prompt")

            mutations = len(evidence["native_mutations"])
            stale = await submit(
                input_request("stale-pid", "MUST_NOT_BE_INSERTED", expected_pid=99999999)
            )
            assert (
                stale["state"] == "failed" and stale["error"]["code"] == "session_selection_changed"
            )
            assert len(evidence["native_mutations"]) == mutations
            invalid = input_request("invalid", "", key="enter")
            invalid_result = await call("action_request", {"request": invalid.model_dump()})
            assert invalid_result.get("error", {}).get("code") == "invalid_arguments", (
                invalid_result
            )
            assert len(evidence["native_mutations"]) == mutations
            assert (
                bridge.store.db.execute(
                    "SELECT count(*) FROM tasks WHERE id=?", (invalid.task_id,)
                ).fetchone()[0]
                == 0
            )
            check(
                "stale PID rejected; invalid_arguments rejected before persisted task/native input"
            )
            empty_literal = input_request("invalid-empty-literal", "")
            empty_literal_result = await call(
                "action_request", {"request": empty_literal.model_dump()}
            )
            assert empty_literal_result.get("error", {}).get("code") == "invalid_arguments", (
                empty_literal_result
            )
            assert len(evidence["native_mutations"]) == mutations
            assert (
                bridge.store.db.execute(
                    "SELECT count(*) FROM tasks WHERE id=?", (empty_literal.task_id,)
                ).fetchone()[0]
                == 0
            )
            evidence["schema_rejections"] = {
                "missing_return_cursor": invalid_result,
                "empty_literal_without_key": empty_literal_result,
                "historical_failed_call_arguments_available": False,
                "historical_exact_replay_claimed": False,
            }
            check(
                "empty literal without key and Return without cursor both rejected before effects; "
                "these are concrete schema cases, not a replay of unavailable historical arguments"
            )

            active_literal_label = "main-long-prompt"
            value = input_request("prompt-once", prompt)
            completion_target = "macos-accept-" + secrets.token_hex(8)

            async def receive():
                async with asyncio.timeout(50):
                    while True:  # noqa: ASYNC110 -- durable completion consumer
                        notices = await call(
                            "completion_receive",
                            {
                                "target": completion_target,
                                "source_id": value.task_id,
                                "wait_seconds": 20,
                            },
                        )
                        if notices.get("notices"):
                            return notices["notices"]

            consumer = asyncio.create_task(receive())
            try:
                admitted = await call(
                    "action_request",
                    {"request": value.model_dump(), "completion_target": completion_target},
                )
                assert not admitted.get("error"), admitted
                task = await completed(value)
                notices = await consumer
            finally:
                if not consumer.done():
                    consumer.cancel()
                    await asyncio.gather(consumer, return_exceptions=True)
            assert task["state"] == "completed", task
            assert task["result"]["return_sent"] is True, task
            assert task["result"]["submitted"] is True
            assert task["result"].get("input_kind") == "literal_text"
            assert task["attempt"] == 1
            assert len(notices) == 1 and notices[0]["payload"]["state"] == "completed", notices
            evidence["completion"] = notices[0]
            ack = await call(
                "completion_ack", {"notice_id": notices[0]["id"], "receipt": notices[0]["receipt"]}
            )
            assert ack.get("acknowledged"), ack
            mutations = len(evidence["native_mutations"])
            await call(
                "action_request",
                {"request": value.model_dump(), "completion_target": completion_target},
            )
            assert len(evidence["native_mutations"]) == mutations, (
                "Idempotent repeat dispatched native input"
            )
            assert (await completed(value))["attempt"] == 1
            frames = [
                record
                for record in captures
                if record["target"] == "codex" and record["input_label"] == "main-long-prompt"
            ]
            pre = next(record for record in frames if record["ready_required"])
            post = next(
                record for record in frames[frames.index(pre) + 1 :] if not record["ready_required"]
            )
            original_verifier = old_insertion_verifier(source_root)
            events = await call("task_events", {"task_id": value.task_id})
            columns = next(
                (
                    event["evidence"]["verification"].get("observed_columns")
                    for event in events["events"]
                    if "verification" in event["evidence"]
                ),
                None,
            )
            replay = {
                "before_sha256": sha(pre["text"]),
                "after_sha256": sha(post["text"]),
                "old_verifier": original_verifier("codex", post["text"], prompt, pre["text"]),
                "new_verifier": insertion_observed(
                    "codex", post["text"], prompt, pre["text"], columns=columns
                ),
                "observed_columns": columns,
                "collapsed_marker_observed": f"[Pasted Content {len(prompt)} chars]"
                in input_view("codex", post["text"]),
            }
            assert replay["new_verifier"], replay
            replay["regression_reproduced_in_real_task"] = not replay["old_verifier"]
            if reproduce_agent_hint:
                assert replay["regression_reproduced_in_real_task"], replay
            evidence["literal_replay"] = replay
            check("exactly once paste/Return completed and completion consumed", **replay)

            answer = await wait_owned_answer(prompt, marker, "response")
            evidence["answer"] = answer
            check(
                "real Codex response independently confirmed in current screen and own rollout",
                **answer,
            )
            if short_single_line:
                blank_marker = marker + "_BLANK"
                blank_prompt = (
                    "Dies ist nur ein Eingabetest. Keine Werkzeuge verwenden.\n\n"
                    "Antworte ausschließlich mit " + blank_marker
                )
                active_literal_label = "expanded-blank-line"
                blank_task = await submit(input_request("expanded-blank-line", blank_prompt))
                assert blank_task["state"] == "completed", blank_task
                assert blank_task["result"]["return_sent"] and blank_task["attempt"] == 1
                blank_answer = await wait_owned_answer(blank_prompt, blank_marker, "blank-response")
                evidence["expanded_blank_line"] = blank_answer
                check(
                    "expanded multiline input with a blank payload row and Return confirmed",
                    **blank_answer,
                )

            async def enter_from_fresh_read(
                label, *, expected_reason=None, expected_menu_screen=None
            ):
                observed = await call(
                    "read_query",
                    {
                        "query": {
                            "operation": "session.read",
                            "pane_id": owned["pane_id"],
                            "expected_pid": owned["expected_pid"],
                        }
                    },
                )
                assert not observed.get("error") and observed.get("next_cursor"), observed
                if expected_menu_screen is not None:
                    assert observed["text"] == expected_menu_screen, (
                        "Own-session menu selection changed before cursor capture; no Enter"
                    )
                if expected_reason:
                    protocol = await bridge.visible_handoffs.codex_state.read(
                        binding.codex_rollout_path, binding.codex_thread_id
                    )
                    observed_return = return_readiness("codex", observed["text"], binding, protocol)
                    assert observed_return.get("reason") == expected_reason, observed_return
                value = request(label)
                mutation_count = len(evidence["native_mutations"])
                response = await call(
                    "session_enter",
                    {
                        "task_id": value.task_id,
                        "idempotency_key": value.idempotency_key,
                        "pane_id": owned["pane_id"],
                        "expected_pid": owned["expected_pid"],
                        "expected_cursor": observed["next_cursor"],
                        "expected_agent_pid": binding.agent_pid,
                    },
                )
                assert not response.get("error"), response
                entered = await completed(value)
                assert entered["state"] == "completed", entered
                assert entered["result"].get("return_sent") is True
                assert entered["result"].get("paste_event_sent") is False
                expected_kind = (
                    "menu_confirmation" if expected_menu_screen is not None else "observed_return"
                )
                assert entered["result"].get("input_kind") == expected_kind
                assert len(evidence["native_mutations"]) == mutation_count + 1
                return entered

            await enter_from_fresh_read("empty-enter")
            async with asyncio.timeout(10):
                while True:  # noqa: ASYNC110 -- observe empty Return without a new model turn
                    raw = await transport.read(owned["pane_id"])
                    protocol = await bridge.visible_handoffs.codex_state.read(
                        binding.codex_rollout_path, binding.codex_thread_id
                    )
                    if assess("codex", raw, binding, protocol)["ready"]:
                        break
                    await asyncio.sleep(0.2)
            check("explicit session_enter sends one Return without paste at own empty Codex prompt")

            slash_task = await submit(input_request("own-resume-menu", "/resume"))
            assert slash_task["state"] == "completed", slash_task
            assert slash_task["result"].get("input_kind") == "slash_command"
            assert slash_task["result"].get("slash_command") == "/resume"
            assert slash_task["result"].get("return_sent") is True
            async with asyncio.timeout(15):
                previous_picker = None
                stable_picker = 0
                while True:  # noqa: ASYNC110 -- real Codex menu observation, never navigation
                    row = await current_owned()
                    assert [p["pid"] for p in row["processes"] if p["name"] == "codex"] == [
                        binding.agent_pid
                    ]
                    raw = await transport.read(owned["pane_id"])
                    state = return_readiness("codex", raw, binding, protocol)
                    title = raw.rfind("Resume a previous session")
                    picker = raw[title:] if title >= 0 else ""
                    if state.get("reason") == "observed_codex_resume_selector":
                        stable_picker = stable_picker + 1 if picker == previous_picker else 1
                        previous_picker = picker
                        if stable_picker >= 2:
                            break
                    await asyncio.sleep(0.25)
            (root / "own-resume-menu.private.txt").write_text(raw)
            from kirabridge.platform_adapters.codex_metadata import read_thread_title

            bound_title = read_thread_title(binding.codex_rollout_path, binding.codex_thread_id)
            assert isinstance(bound_title, str) and bound_title, (
                "Own bound thread title unavailable; no menu Enter"
            )
            selected_rows = re.findall(r"(?m)^[ \t]*›[ \t]+([^\n]+)$", picker)
            assert len(selected_rows) == 1 and resume_row_title_matches(
                selected_rows[0], bound_title
            ), "Selected resume row is not the independently known own session; no Enter"
            assert re.search(r"─{3,}\s+1\s*/\s*1\s*·\s*100%\s*─", picker), (
                "More than the one known own session in menu; no Enter"
            )
            assert "Filter:" in picker and "Cwd" in picker
            assert Path(binding.codex_rollout_path).resolve() == rollout.resolve()
            own_header = json.loads(rollout.read_text().splitlines()[0])["payload"]
            assert own_header["id"] == binding.codex_thread_id
            assert own_header["cwd"] == str(workspace)
            evidence["own_resume_title"] = {
                "bound_thread_id": binding.codex_thread_id,
                "title_sha256": sha(bound_title),
                "selected_row_sha256": sha(selected_rows[0]),
                "metadata_source": "read_thread_title(bound_rollout,bound_thread_id)",
            }
            check(
                "live slash-command menu contains exactly one selected own CWD/bound thread title"
            )
            await enter_from_fresh_read(
                "confirm-own-resume-menu",
                expected_reason="observed_codex_resume_selector",
                expected_menu_screen=raw,
            )
            async with asyncio.timeout(20):
                while True:  # noqa: ASYNC110 -- observe resumption of only the known own session
                    row = await current_owned()
                    assert [p["pid"] for p in row["processes"] if p["name"] == "codex"] == [
                        binding.agent_pid
                    ]
                    raw = await transport.read(owned["pane_id"])
                    protocol = await bridge.visible_handoffs.codex_state.read(
                        binding.codex_rollout_path, binding.codex_thread_id
                    )
                    if assess("codex", raw, binding, protocol)["ready"]:
                        break
                    await asyncio.sleep(0.3)
            check("session_enter confirmed only the owned resume-menu selection, no paste")
            assert not evidence.get("forbidden_fallback_attempts")
            check("no hidden, raw-send or additional-window fallback attempted")
            evidence["acceptance"] = "tests_passed_cleanup_pending"
    except BaseException as error:
        evidence["acceptance"] = "failed"
        evidence["error"] = {
            "type": type(error).__name__,
            "code": getattr(error, "code", None),
            "message": str(error),
        }
        raise
    finally:
        try:
            # Own busy fixture may be released even after an assertion failure;
            # this neither resends input nor touches an unrelated process.
            if (root / "busy-started").exists():
                (root / "release-busy").write_text("release own fixture during cleanup\n")
            await cleanup_owned()
            evidence["cleanup_complete"] = True
        except BaseException as error:
            evidence["acceptance"] = "failed"
            evidence["cleanup_error"] = {"type": type(error).__name__, "message": str(error)}
        finally:
            if server is not None:
                server.should_exit = True
            if server_task is not None:
                await asyncio.wait_for(server_task, 10)
            if started:
                await bridge.tasks.stop()
            await bridge.threaddesk.close()
            bridge.store.close()
            if sock is not None:
                sock.close()
            if previous_token is None:
                os.environ.pop(token_name, None)
            else:
                os.environ[token_name] = previous_token
            if previous_ask_token is None:
                os.environ.pop(ask_token_name, None)
            else:
                os.environ[ask_token_name] = previous_ask_token
            checkpoint()
    assert evidence.get("cleanup_complete"), evidence.get("cleanup_error")
    evidence["acceptance"] = "passed"
    checkpoint()
    summary = {
        "acceptance": "passed",
        "private_evidence": str(root / "evidence.private.json"),
        "source_tree_sha256": bridge.runtime["source_tree_sha256"],
        "literal_replay": evidence["literal_replay"],
        "checks": [record["name"] for record in evidence["checks"]],
        "production_modified": False,
        "cleanup": evidence["cleanup"],
    }
    (root / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--allow-one-owned-visible-window", action="store_true", required=True)
    parser.add_argument("--response-timeout", type=int, default=90, choices=range(20, 181))
    parser.add_argument("--reproduce-agent-hint", action="store_true")
    parser.add_argument("--existing-pane")
    parser.add_argument("--existing-pid", type=int)
    parser.add_argument("--short-single-line", action="store_true")
    options = parser.parse_args()
    asyncio.run(
        accept(
            options.root.resolve(),
            response_timeout=options.response_timeout,
            reproduce_agent_hint=options.reproduce_agent_hint,
            existing_pane=options.existing_pane,
            existing_pid=options.existing_pid,
            short_single_line=options.short_single_line,
        )
    )
