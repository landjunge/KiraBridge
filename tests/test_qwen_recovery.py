"""Owned-session recovery metadata; never real user history or model turns."""

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from kirabridge.agent_manager.qwen_recovery import QwenRecoveryBinding
from kirabridge.bridge_core.config import AgentConfig
from kirabridge.bridge_core.models import AgentInput, BridgeError
from kirabridge.capability_routing.integration import RoutedAdapter
from kirabridge.capability_routing.router import RoutingError, fingerprint
from kirabridge.private_files import write_private


def recovery(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    cwd = str(tmp_path / "cwd")
    project = tmp_path / ".qwen/projects" / cwd.replace("/", "-") / "chats"
    project.mkdir(parents=True)
    (tmp_path / ".qwen").chmod(0o700)
    history = project / "session.jsonl"
    history.write_text(
        json.dumps({"sessionId": "session", "cwd": cwd, "type": "assistant", "model": "model"})
        + "\n"
    )
    history.chmod(0o644)  # Native format; private ancestor supplies traversal protection.
    receipt = tmp_path / "receipt.json"
    write_private(
        receipt,
        json.dumps(
            {
                "task_id": "original",
                "core_task_id": "old-core",
                "core_state": "unknown",
                "source_handoff_sha256": "handoff",
                "last_native_observation": {"session_id": "session", "owner": "owner", "cwd": cwd},
            }
        ),
    )
    binding = QwenRecoveryBinding(
        original_task_id="original",
        original_core_task_id="old-core",
        owner="owner",
        session_id="session",
        cwd=cwd,
        model="model",
        auth_type="qwen-subscription",
        effort="xhigh",
        transcript_path=str(history),
        transcript_sha256=hashlib.sha256(history.read_bytes()).hexdigest(),
        receipt_path=str(receipt),
        receipt_sha256=hashlib.sha256(receipt.read_bytes()).hexdigest(),
        source_handoff_sha256="handoff",
    )
    args = AgentInput(agent="qwen", prompt="continue", cwd=cwd)
    config = AgentConfig(
        kind="qwen_acp",
        model="model",
        qwen_auth_type="qwen-subscription",
        qwen_reasoning_effort="xhigh",
    )
    return binding, {"id": "new-core", "principal": "owner"}, args, config


@pytest.mark.skipif(os.name != "posix", reason="POSIX native Qwen transcript metadata")
def test_owned_native_history_uses_private_ancestor_without_chmod(tmp_path, monkeypatch):
    binding, task, args, config = recovery(tmp_path, monkeypatch)
    binding.validate_effect(task, args, config)
    assert Path(binding.transcript_path).stat().st_mode & 0o777 == 0o644
    with pytest.raises(BridgeError):
        binding.validate_effect({**task, "id": "old-core"}, args, config)
    with pytest.raises(BridgeError):
        binding.validate_effect(task, args, config.model_copy(update={"model": "other"}))
    with Path(binding.transcript_path).open("a") as stream:
        stream.write("{}\n")
    with pytest.raises(BridgeError):
        binding.validate_effect(task, args, config)


@pytest.mark.skipif(os.name != "posix", reason="POSIX native Qwen transcript metadata")
def test_recovery_requires_private_receipt_and_owned_parent_chain(tmp_path, monkeypatch):
    binding, task, args, config = recovery(tmp_path, monkeypatch)
    Path(binding.receipt_path).chmod(0o644)
    with pytest.raises(BridgeError):
        binding.validate_effect(task, args, config)
    Path(binding.receipt_path).chmod(0o600)
    (tmp_path / ".qwen").chmod(0o755)
    with pytest.raises(BridgeError):
        binding.validate_effect(task, args, config)


async def test_qwen_routing_pins_native_effort_without_cli_shim(tmp_path):
    matrix, source = {"fixture": "matrix"}, {"revision": 6}
    decision = {
        "cli": "qwen",
        "access_kind": "subscription",
        "model": "qwen4.0-max-preview",
        "effort": "xhigh",
        "executable": str(tmp_path / "qwen"),
        "thread_desk": source,
        "matrix_sha256": fingerprint(matrix),
    }
    guard = SimpleNamespace(
        prepare=lambda _: decision, source=SimpleNamespace(load=lambda: (matrix, source))
    )
    args = AgentInput(agent="qwen", prompt="open task", cwd=str(tmp_path), timeout=120)
    task = {"id": "sealed", "principal": "owner"}
    profile = SimpleNamespace(
        task_id="sealed",
        prompt=args.prompt,
        cwd=args.cwd,
        timeout_seconds=args.timeout,
        read_only=True,
    )
    delegate = SimpleNamespace(execute=AsyncMock(return_value={"success": True}))
    routed = RoutedAdapter(delegate, "qwen", guard, lambda *_: profile)
    config = AgentConfig(
        kind="qwen_acp", model="previous", qwen_auth_type="qwen-subscription", bridge_tools=True
    )
    await routed.execute(task, args, config, [str(tmp_path)], AsyncMock(), AsyncMock())
    selected = delegate.execute.call_args.args[2]
    assert selected.executable == decision["executable"]
    assert selected.model == decision["model"]
    assert selected.qwen_reasoning_effort == "xhigh"
    assert not (tmp_path / "effort-shims").exists()
    with pytest.raises(RoutingError):
        await routed.execute(
            task,
            args,
            config.model_copy(update={"qwen_auth_type": "openai"}),
            [str(tmp_path)],
            AsyncMock(),
            AsyncMock(),
        )
