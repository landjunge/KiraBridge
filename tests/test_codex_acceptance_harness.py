"""Offline guards only: never instantiate a Core, native UI, process or server."""

import importlib.util
import json
import os
import runpy
import signal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from kirabridge.platform_adapters.terminal_app import TerminalAppTransport

NONCE = "0123456789abcdef"
IDENTITY = f"{os.getuid()} ttys004 Sun Nov 1 12:00:00 2026 344 /bin/codex"


@pytest.fixture
def harness():
    path = Path(__file__).resolve().parents[1] / "scripts/accept_codex_handoff_intel.py"
    spec = importlib.util.spec_from_file_location("codex_acceptance_offline", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def owned():
    return {"pane_id": "terminal:123:ttys004", "expected_pid": 345, "tty": "/dev/ttys004"}


def native_row():
    return {
        **owned(),
        "window_id": 123,
        "visual_window_id": 123,
        "tab_count": 1,
        "identity_ambiguous": False,
    }


def test_default_entrypoint_prints_only_review_plan(harness, monkeypatch, capsys):
    def forbid(*args, **kwargs):
        pytest.fail("Plan-only invocation performed work")

    import kirabridge.bridge_core.bridge

    monkeypatch.setattr(kirabridge.bridge_core.bridge, "Bridge", forbid)
    monkeypatch.setattr(harness.subprocess, "run", forbid)
    monkeypatch.setattr(harness.subprocess, "check_output", forbid)
    monkeypatch.setattr(harness.os, "kill", forbid)
    monkeypatch.setattr(harness.sys, "argv", [harness.__file__])
    runpy.run_path(harness.__file__, run_name="__main__")
    plan = json.loads(capsys.readouterr().out)
    assert plan == harness.review_plan() and plan["execute"] is False


def test_fixtures_keep_collapsed_positive_and_supported_full_row_negative(harness):
    marker, raw, body, ambiguous = harness.build_prompts(NONCE)
    assert NONCE.upper() in marker and len(raw) > 1000
    assert raw.count(marker + "_RAW") == 2
    assert len(body) < 1000 and body.count(marker + "_HANDOFF") == 1
    assert harness.codex_full_row_widths(body, 130) == ()
    assert harness.codex_full_row_widths(ambiguous, 131) == (128,)
    assert harness.codex_full_row_widths(ambiguous, 130) == ()
    with pytest.raises(RuntimeError, match="fresh"):
        harness.build_prompts("previous-unknown-task")


def test_argv_does_not_change_home_auth_or_add_resume_prompt(harness, tmp_path):
    binary, workspace = tmp_path / "codex", tmp_path / "workspace"
    argv, overrides = harness.codex_arguments(binary, workspace, ["kirabridge"])
    assert argv[0] == str(binary) and argv[argv.index("-C") + 1] == str(workspace)
    assert {"--no-alt-screen", "--no-daemon", "--strict-config"} <= set(argv)
    assert argv[argv.index("-s") + 1] == "read-only"
    assert argv[argv.index("-a") + 1] == "never"
    values = overrides[1::2]
    assert "mcp_servers.kirabridge.enabled=false" in values
    assert "mcp_servers={}" not in values
    assert all(
        "features." + feature + "=false" in values for feature in harness.CODEX_DISABLED_FEATURES
    )
    assert not any(word in argv for word in ("resume", "--last", "fork", "login", "logout"))
    assert not any(word.startswith(("HOME=", "CODEX_HOME=")) for word in argv)


def test_effective_cli_isolation_rejects_enabled_unknown_and_missing_feature(harness):
    features = "\n".join(feature + " stable false" for feature in harness.CODEX_DISABLED_FEATURES)
    disabled = [{"name": "kirabridge", "enabled": False}]
    harness.verify_cli_isolation(features, json.dumps(disabled), ["kirabridge"])
    for changed in (
        [{"name": "kirabridge", "enabled": True}],
        disabled + [{"name": "managed-extra", "enabled": False}],
        [],
        {"servers": []},
    ):
        with pytest.raises(RuntimeError):
            harness.verify_cli_isolation(features, json.dumps(changed), ["kirabridge"])
    with pytest.raises(RuntimeError, match="features"):
        harness.verify_cli_isolation("hooks stable false", json.dumps(disabled), ["kirabridge"])


def test_config_reader_extracts_names_and_hashes_without_copying_secrets(harness, tmp_path):
    source = tmp_path / "config.toml"
    source.write_text('[mcp_servers.kirabridge]\nurl="http://private"\ntoken="secret-value"\n')
    missing = tmp_path / "missing.toml"
    snapshot, names = harness.read_codex_configs({source, missing})
    assert names == ["kirabridge"] and snapshot[str(missing)] is None
    assert snapshot[str(source)] == harness.file_sha(source)
    assert "secret-value" not in json.dumps(snapshot)
    source.write_text("[mcp_servers.other]\nenabled=false\n")
    assert harness.read_codex_configs({source, missing}) != (snapshot, names)


def test_config_reader_refuses_symlink_profile_and_unsafe_server_identifier(harness, tmp_path):
    source = tmp_path / "config.toml"
    source.write_text("[mcp_servers.kirabridge]\nenabled=true\n")
    link = tmp_path / "link.toml"
    link.symlink_to(source)
    with pytest.raises(RuntimeError, match="symlink"):
        harness.read_codex_configs({link})
    source.write_text('profile="production"\n')
    with pytest.raises(RuntimeError, match="profile"):
        harness.read_codex_configs({source})
    source.write_text('[mcp_servers."unreviewed.name"]\nenabled=true\n')
    with pytest.raises(RuntimeError, match="identifier"):
        harness.read_codex_configs({source})


def test_same_owned_shell_context_binds_reader_root_without_changing_environment(harness):
    environment = {"HOME": "/private/owned-home", "UNRELATED_SECRET": "do-not-capture"}
    before = dict(environment)
    expected = harness.codex_config_context(environment)
    assert set(expected) == set(harness.CODEX_CONTEXT_KEYS)
    assert "UNRELATED_SECRET" not in expected
    assert harness.verify_shell_config_context({"config_context": dict(expected)}, expected) == (
        "/private/owned-home/.codex"
    )
    assert environment == before


def test_busy_fixture_records_only_bounded_config_context_fields(harness, monkeypatch, tmp_path):
    (tmp_path / "release-busy").write_text("own offline fixture already released")
    monkeypatch.setattr(harness.os, "ttyname", lambda _: "/dev/ttys004")
    monkeypatch.setattr(harness.sys, "argv", ["own-busy-fixture", str(tmp_path)])
    monkeypatch.setenv("KIRABRIDGE_HARNESS_UNRELATED_SECRET", "must-not-be-captured")
    exec(compile(harness.BUSY_SOURCE, "private-busy-fixture", "exec"), {})
    receipt = json.loads((tmp_path / "busy-started.json").read_text())
    assert set(receipt) == {"pid", "tty", "config_context"}
    assert receipt["config_context"] == harness.codex_config_context(harness.os.environ)
    assert "must-not-be-captured" not in json.dumps(receipt)


def test_observed_managed_input_change_refuses_without_reading_or_repairing(harness, tmp_path):
    expected_absent = tmp_path / "managed_config.toml"
    assert harness.require_known_managed_absent([expected_absent]) == {str(expected_absent): False}
    expected_absent.write_text("not read or changed")
    with pytest.raises(RuntimeError, match="managed Codex config"):
        harness.require_known_managed_absent([expected_absent])
    assert expected_absent.read_text() == "not read or changed"


@pytest.mark.parametrize(
    "key",
    [
        "HOME",
        "CODEX_HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_STATE_HOME",
        "XDG_CACHE_HOME",
        "CODEX_PROFILE",
        "CODEX_CONFIG_PROFILE",
    ],
)
def test_shell_config_context_change_refuses_before_start(harness, key):
    expected = harness.codex_config_context({"HOME": "/private/owned-home"})
    shell = dict(expected)
    shell[key] = "/private/different-context"
    with pytest.raises(RuntimeError, match="differs"):
        harness.verify_shell_config_context({"config_context": shell}, expected)


@pytest.mark.parametrize(
    "environment", [{}, {"HOME": "relative-home"}, {"HOME": "/owned", "CODEX_HOME": "/other"}]
)
def test_unresolved_or_unsupported_reader_root_refuses(harness, environment):
    expected = harness.codex_config_context(environment)
    with pytest.raises(RuntimeError, match="reader root"):
        harness.verify_shell_config_context({"config_context": expected}, expected)


async def test_cli_listing_helper_verifies_both_effective_outputs_in_same_workspace(
    harness, monkeypatch, tmp_path
):
    features = "\n".join(feature + " stable false" for feature in harness.CODEX_DISABLED_FEATURES)
    run = Mock(
        side_effect=[
            SimpleNamespace(stdout=features),
            SimpleNamespace(stdout='[{"name":"kirabridge","enabled":false}]'),
        ]
    )
    monkeypatch.setattr(harness.subprocess, "run", run)
    _, overrides = harness.codex_arguments(tmp_path / "codex", tmp_path, ["kirabridge"])
    result = await harness.inspect_cli_isolation(
        tmp_path / "codex", overrides, ["kirabridge"], tmp_path
    )
    assert result["known_servers_disabled"] is True
    assert run.call_count == 2
    assert run.call_args_list[0].args[0][-2:] == ["features", "list"]
    assert run.call_args_list[1].args[0][-3:] == ["mcp", "list", "--json"]
    for call in run.call_args_list:
        assert call.kwargs["cwd"] == tmp_path and call.kwargs["check"] is True
        assert "--strict-config" not in call.args[0]
        assert "mcp_servers.kirabridge.enabled=false" in call.args[0]


def test_fresh_task_is_reserved_before_uncertain_dispatch_and_never_replayed(harness):
    submitted = set()
    request = harness.fresh_request(NONCE, "raw", "session.input", {"text": "fresh"}, submitted)
    assert request.task_id == request.idempotency_key == f"codex-accept-{NONCE}-raw"
    # A lost HTTP response must not clear this reservation or authorize retry.
    with pytest.raises(RuntimeError, match="Never replay"):
        harness.fresh_request(NONCE, "raw", "session.input", {"text": "fresh"}, submitted)
    other = harness.fresh_request(NONCE, "handoff", "agent.execute", {}, submitted)
    assert other.task_id != request.task_id


def test_exact_one_new_owned_window_is_accepted(harness):
    row = native_row()
    assert harness.owned_row([row], owned(), {17, 18}) is row


@pytest.mark.parametrize(
    "change",
    [
        {"expected_pid": 999},
        {"tty": "/dev/ttys099"},
        {"tab_count": 2},
        {"visual_window_id": 17},
        {"identity_ambiguous": True},
    ],
)
def test_changed_shared_or_ambiguous_view_cannot_be_adopted(harness, change):
    with pytest.raises(RuntimeError, match="identity changed"):
        harness.owned_row([{**native_row(), **change}], owned(), {17})


def test_old_window_or_multiple_same_views_cannot_be_adopted(harness):
    with pytest.raises(RuntimeError):
        harness.owned_row([native_row()], owned(), {123})
    with pytest.raises(RuntimeError):
        harness.owned_row([native_row(), native_row()], owned(), {17})
    with pytest.raises(RuntimeError):
        harness.owned_row([], owned(), {17})


@pytest.mark.parametrize(
    "expected,current", [(None, None), (IDENTITY, IDENTITY.replace("12:00:00", "12:00:01"))]
)
async def test_cleanup_missing_or_reused_identity_cannot_signal(
    harness, monkeypatch, expected, current
):
    signal_process = Mock()
    monkeypatch.setattr(harness.os, "kill", signal_process)
    transport = SimpleNamespace(process_identity=AsyncMock(return_value=current))
    binding = SimpleNamespace(agent_pid=456)
    with pytest.raises(RuntimeError):
        await harness.terminate_owned(transport, binding, expected)
    signal_process.assert_not_called()


async def test_cleanup_signals_only_exact_unchanged_owned_pid(harness, monkeypatch):
    signal_process = Mock()
    monkeypatch.setattr(harness.os, "kill", signal_process)
    transport = SimpleNamespace(process_identity=AsyncMock(return_value=IDENTITY))
    await harness.terminate_owned(transport, SimpleNamespace(agent_pid=456), IDENTITY)
    transport.process_identity.assert_awaited_once_with(456, detailed=True)
    signal_process.assert_called_once_with(456, signal.SIGTERM)


async def test_naturally_gone_foreign_child_does_not_block_owned_cleanup(
    harness, monkeypatch, tmp_path
):
    signal_process = Mock()
    monkeypatch.setattr(harness.os, "kill", signal_process)
    native = AsyncMock(return_value={"closed": True})
    transport = SimpleNamespace(
        window_inventory=AsyncMock(return_value={"windows": [{"window_id": 123}]}),
        process_ids=AsyncMock(return_value=frozenset({345})),
        process_identity=AsyncMock(
            side_effect=AssertionError("Absent foreign child must not be read")
        ),
        process_working_directory=AsyncMock(return_value=str(tmp_path)),
        native_target=TerminalAppTransport.native_target,
        native_identity_guard=TerminalAppTransport.native_identity_guard,
        native_screen_guard=TerminalAppTransport.native_screen_guard,
        native=native,
    )
    delta = await harness.original_deltas(transport, {17}, {900: IDENTITY}, 123)
    assert delta["foreign_processes"]["absent"] == [900]
    assert delta["foreign_windows_absent"] == [17] and delta["read_only"] is True
    assert await harness.close_owned_idle(
        transport, owned(), IDENTITY, "owned idle prompt", tmp_path
    ) == {"closed": True}
    source = native.call_args.args[0]
    assert native.call_args.kwargs == {"mutation": True}
    assert "app.windows.byId(123)" in source and "app.windows.byId(17)" not in source
    assert "targetWindow.close()" in source and "tab.busy()" in source
    assert "tabs().length!==1" in source and "owned idle prompt" in source
    signal_process.assert_not_called()


async def test_cleanup_changed_cwd_preserves_owned_window_without_close(harness, tmp_path):
    transport = SimpleNamespace(
        process_working_directory=AsyncMock(return_value=str(tmp_path / "changed")),
        native=AsyncMock(),
    )
    with pytest.raises(RuntimeError, match="CWD changed before close"):
        await harness.close_owned_idle(transport, owned(), IDENTITY, "owned idle prompt", tmp_path)
    transport.process_working_directory.assert_awaited_once_with(345, expected_identity=IDENTITY)
    transport.native.assert_not_awaited()
