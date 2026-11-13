"""Scoped authority through the real parser/hook; only a version-only fake CLI."""

import json
import sys
from datetime import datetime, timedelta, timezone

import pytest

from kirabridge.bridge_core.config import AgentConfig
from kirabridge.bridge_core.models import AgentInput
from kirabridge.capability_routing.hook import DelegationGuard
from kirabridge.capability_routing.router import RoutingError, Runtime, Task, fingerprint, select
from kirabridge.capability_routing.source import BEGIN, END, ThreadDeskSource

SCOPE_BEGIN = "<!-- bigplan-cli-scope:v1:qwen -->"
SCOPE_END = "<!-- /bigplan-cli-scope:qwen -->"


@pytest.fixture
def scoped(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    binary = tmp_path / "qwen-version-only"
    binary.write_text(
        f"#!{sys.executable}\nimport sys\n"
        "assert sys.argv[1:] == ['--bare', '--safe-mode', '--version']\n"
        "print('0.27.2')\n"
    )
    binary.chmod(0o700)
    settings = tmp_path / ".qwen"
    settings.mkdir()
    (settings / "settings.json").write_text(
        json.dumps({"security": {"auth": {"selectedType": "qwen-subscription"}}})
    )
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    model = "qwen4.0-max-preview"
    base = {
        "schema_version": "bigplan.cli-matrix.v1",
        "checked_at": (now - timedelta(days=8)).isoformat(),
        "expires_at": (now - timedelta(days=1)).isoformat(),
        "clis": [],
    }
    scope = {
        "schema_version": "bigplan.cli-scope.v1",
        "cli": "qwen",
        "adapter": "qwen_acp",
        "authority_ref": "fixture-scoped-refresh-v1",
        "checked_at": (now - timedelta(minutes=1)).isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "read_only": True,
        "capability": {
            "id": "qwen",
            "installed_version": "0.27.2",
            "capabilities": ["headless", "coding", "mcp"],
            "models": [
                {
                    "id": model,
                    "provider": "qwen",
                    "efforts": ["medium"],
                    "fit": {"implementation": 4},
                    "cost_rank": 0,
                    "evidence": "fixture",
                }
            ],
            "documented_models": [],
            "sources": [],
            "limitations": "synthetic scoped ACP read",
        },
    }
    document = {"id": "matrix", "revision": 8}

    def read(_):
        return {
            **document,
            "notes": BEGIN + json.dumps(base) + END + SCOPE_BEGIN + json.dumps(scope) + SCOPE_END,
        }

    source = ThreadDeskSource(read, "matrix")
    runtime = Runtime(
        schema_version="bigplan.cli-runtime.v1",
        allowed_roots=[str(tmp_path)],
        state_dir=str(tmp_path / "routing"),
        allow_write=False,
        access=[
            {
                "cli": "qwen",
                "executable": str(binary),
                "version": "0.27.2",
                "models": [model],
                "access_kind": "subscription",
                "verified_at": scope["checked_at"],
                "expires_at": scope["expires_at"],
                "evidence": "synthetic existing subscription",
            }
        ],
    )
    task = Task(
        task_id="sealed-qwen-task",
        workload="implementation",
        prompt="Read exact input",
        cwd=str(tmp_path),
        ownership_ref="fixture-sealed-core",
        allowed_clis=["qwen"],
        explicit_cli="qwen",
        explicit_model=model,
        explicit_effort="medium",
        execution_adapter="qwen_acp",
        read_only=True,
        timeout_seconds=30,
    )
    config = AgentConfig(
        kind="qwen_acp",
        executable=str(binary),
        model=model,
        qwen_auth_type="qwen-subscription",
        qwen_reasoning_effort="medium",
        sandbox_mode="workspace-write",
        allow_local_tools=True,
        bridge_tools=True,
        qwen_mcp_tools=["read_queries"],
        qwen_mcp_operations=["file.read", "file.list"],
        qwen_mcp_read_roots=[str(tmp_path)],
    )
    args = AgentInput(
        agent="qwen",
        cwd=task.cwd,
        prompt=task.prompt,
        timeout=30,
        mcp_operations=["file.read"],
        mcp_read_roots=[str(tmp_path)],
    )
    return source, runtime, task, config, args, scope, base, document, settings


def test_explicit_qwen_scope_uses_real_hook_without_refreshing_global_matrix(scoped):
    source, runtime, task, config, args, _, base, *_ = scoped
    before = json.dumps(base)
    guard = DelegationGuard(source, runtime)
    decision = guard.validate_qwen_task(task, args=args, config=config)
    assert decision["observed_version"] == "0.27.2"
    assert decision["observed_auth_route"] == "qwen-subscription_selection_only"
    assert decision["thread_desk"] == {"thread_id": "matrix", "revision": 8}
    assert decision["agent_input_sha256"] == fingerprint(args)
    assert decision["effective_model"] == "unverified"
    assert guard.validate_qwen_task(task, args=args, config=config, expected=decision)
    assert json.dumps(base) == before
    matrix, _ = source.load()
    with pytest.raises(RoutingError, match="expired"):
        select(matrix, runtime, task.model_copy(update={"explicit_cli": "codex"}))


def test_generic_native_prepare_cannot_consume_scoped_qwen(scoped):
    """Only the argument-validating scoped hook may opt into Qwen evidence."""
    source, runtime, task, config, args, *_ = scoped
    from kirabridge.bridge_core.models import BridgeError
    from kirabridge.capability_routing.native import NativeRoutedAdapter

    guard = DelegationGuard(source, runtime)
    with pytest.raises(RoutingError, match="dedicated scoped Qwen validation"):
        guard.prepare(task)
    generic = NativeRoutedAdapter(object(), "qwen", guard, profiles=None)
    with pytest.raises(BridgeError) as error:
        generic.prepare(task)
    assert error.value.code == "routing_preflight_blocked"

    # The permitted path has already bound actual args/config and passes the
    # MEDIUM, read-only, operation, grant, auth and executable checks.
    decision = guard.validate_qwen_task(task, args=args, config=config)
    assert decision["cli"] == "qwen"
    assert decision["effort"] == "medium"


@pytest.mark.parametrize(
    "change",
    [
        "scope_expired",
        "scope_over_24h",
        "access_expired",
        "adapter",
        "write",
        "effort",
        "model",
        "version",
        "auth",
        "prompt",
        "local_tools",
        "write_operation",
        "read_root",
    ],
)
def test_scoped_qwen_negatives_fail_before_any_model_turn(scoped, change):
    source, runtime, task, config, args, scope, _, _, settings = scoped
    now = datetime.now(timezone.utc)
    if change == "scope_expired":
        scope["expires_at"] = (now - timedelta(seconds=1)).isoformat()
    elif change == "scope_over_24h":
        scope["expires_at"] = (now + timedelta(days=2)).isoformat()
    elif change == "access_expired":
        runtime.access[0].expires_at = (now - timedelta(seconds=1)).isoformat()
    elif change == "adapter":
        task.execution_adapter = None
    elif change == "write":
        task.read_only = False
    elif change == "effort":
        config.qwen_reasoning_effort = "high"
    elif change == "model":
        config.model = "foreign"
    elif change == "version":
        scope["capability"]["installed_version"] = "0.27.3"
    elif change == "auth":
        (settings / "settings.json").write_text('{"security":{"auth":{"selectedType":"openai"}}}')
    elif change == "prompt":
        args.prompt = "changed"
    elif change == "local_tools":
        args.local_tools = True
    elif change == "write_operation":
        args.mcp_operations = ["file.write"]
    elif change == "read_root":
        args.mcp_read_roots = ["/foreign"]
    with pytest.raises(RoutingError):
        DelegationGuard(source, runtime).validate_qwen_task(task, args=args, config=config)


@pytest.mark.parametrize("change", ["revision", "authority", "arguments", "configuration"])
def test_final_recheck_binds_source_and_actual_task_metadata(scoped, change):
    source, runtime, task, config, args, scope, _, document, _ = scoped
    guard = DelegationGuard(source, runtime)
    decision = guard.validate_qwen_task(task, args=args, config=config)
    if change == "revision":
        document["revision"] += 1
    elif change == "authority":
        scope["authority_ref"] = "replaced"
    elif change == "arguments":
        args.mcp_operations = ["file.list"]
    else:
        config.qwen_max_tool_calls += 1
    with pytest.raises(RoutingError, match="changed before effect"):
        guard.validate_qwen_task(task, args=args, config=config, expected=decision)


@pytest.mark.parametrize("mutation", ["duplicate", "reversed", "wrong_cli", "no_scope"])
def test_prose_missing_or_ambiguous_scope_never_renews_the_global_matrix(scoped, mutation):
    source, runtime, task, _, _, scope, base, *_ = scoped
    raw = json.dumps(scope)
    if mutation == "duplicate":
        raw = raw[:-1] + ',"cli":"qwen"}'
    elif mutation == "wrong_cli":
        raw = raw.replace('"cli": "qwen"', '"cli": "codex"')
    block = SCOPE_BEGIN + raw + SCOPE_END
    if mutation == "reversed":
        block = SCOPE_END + raw + SCOPE_BEGIN
    elif mutation == "no_scope":
        block = "Qwen observed today; this prose is not machine-readable authority"
    source.get_thread = lambda _: {
        "id": "matrix",
        "revision": 8,
        "notes": BEGIN + json.dumps(base) + END + block,
    }
    with pytest.raises((RoutingError, ValueError)):
        matrix, _ = source.load()
        select(matrix, runtime, task)


@pytest.mark.parametrize("change", ["future", "duplicate_model", "sensitive_extra"])
def test_invalid_scope_has_bounded_non_disclosing_errors(scoped, change):
    source, runtime, task, _, _, scope, *_ = scoped
    sentinel = "SENTINEL_DO_NOT_COPY_PROVIDER_SECRETS"
    if change == "future":
        scope["checked_at"] = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    elif change == "duplicate_model":
        scope["capability"]["models"] *= 2
    else:
        scope["raw_provider_response"] = {"apiKey": sentinel}
    with pytest.raises(RoutingError) as error:
        matrix, _ = source.load()
        select(matrix, runtime, task)
    assert sentinel not in str(error.value)
