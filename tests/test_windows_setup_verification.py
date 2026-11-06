"""Handshake/policy tests with injected private records; no Windows/cloud acceptance."""

import copy
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import httpx
import pytest
from mcp.types import CallToolResult
from pydantic import ValidationError
from test_mcp import http_bridge  # noqa: F401

from kirabridge import windows_setup_verification as module
from kirabridge.bridge_core.models import BridgeError, TaskRequest
from kirabridge.mcp_gateway.client import MCPClientPool, Peer
from kirabridge.read_query import ReadQuery

GENERATION = "a" * 32


class Records:
    def __init__(self):
        self.values, self.lock = {}, threading.Lock()
        self.refuse = False

    @contextmanager
    def locked(self):
        with self.lock:
            yield

    def read(self, identity, kind):
        if self.refuse:
            raise BridgeError("unsafe_credentials", "Owner/reparse guard refused the file")
        if (identity, kind) not in self.values:
            raise FileNotFoundError
        return copy.deepcopy(self.values[identity, kind])

    def create(self, identity, kind, value):
        if self.refuse:
            raise BridgeError("unsafe_credentials", "Owner/reparse guard refused the file")
        if (identity, kind) in self.values:
            raise FileExistsError
        self.values[identity, kind] = copy.deepcopy(value)

    def count(self):
        return len(self.values)


@pytest.fixture
def handshake():
    records, now = Records(), [1_700_000_000_000_000_000, 1_000_000_000]

    def instance(generation=GENERATION, principal="local"):
        return module.WindowsSetupVerification(
            None,
            generation,
            enabled=True,
            principal=principal,
            records=records,
            wall_clock=lambda: now[0],
            monotonic_clock=lambda: now[1],
            host="win32",
        )

    return records, now, instance


def test_manual_return_code_is_required_consumed_once_and_never_in_receipt_or_proof(handshake):
    records, _, instance = handshake
    gui, server = instance(), instance()
    prompt = gui.begin_verification()
    assert not gui.finish_verification("A" * 16)
    assert not gui.public_proof()["verified"]
    reply = server.answer(prompt["challenge"], "local")
    code = reply["response_code"]
    assert len(code) == 16 and code not in json.dumps(list(records.values.values()))
    wrong = ("B" if code[0] == "A" else "A") + code[1:]
    assert not gui.finish_verification(wrong)
    assert gui.finish_verification(code.lower())
    assert not gui.finish_verification(code)
    proof = gui.public_proof()
    assert proof["verified"] and not proof["cloud_attested"]
    assert not proof["desktop_effects_tested"] and not proof["permissions_tested"]
    assert code not in json.dumps(proof) and prompt["challenge"] not in json.dumps(proof)
    assert "sha256" not in json.dumps(proof)


def test_local_simulation_never_becomes_cloud_or_real_verified_proof(handshake):
    _, _, instance = handshake
    gui, server = instance(), instance()
    request = gui.begin_verification(simulated=True)
    reply = server.answer(request["challenge"], "local")
    assert reply["simulated"] is True
    assert gui.finish_verification(reply["response_code"])
    assert gui.public_proof()["local_test_verified"]
    assert not gui.public_proof()["verified"] and not gui.public_proof()["cloud_attested"]


def test_repeated_or_parallel_challenge_answer_mints_only_one_response(handshake, monkeypatch):
    _, _, instance = handshake
    gui = instance()
    challenge = gui.begin_verification()["challenge"]
    choices = []

    def choice(alphabet):
        choices.append(1)
        return "A"

    monkeypatch.setattr(module.secrets, "choice", choice)

    def answer():
        try:
            return instance().answer(challenge, "local")
        except BridgeError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: answer(), range(2)))
    assert sum(isinstance(value, dict) for value in results) == 1
    assert "setup_challenge_answered" in results and len(choices) == 16


@pytest.mark.parametrize("which", [0, 1])
def test_wall_or_monotonic_expiry_refuses_answer_and_confirmation(handshake, which):
    _, now, instance = handshake
    gui = instance()
    prompt = gui.begin_verification(ttl_seconds=30)
    reply = instance().answer(prompt["challenge"], "local")
    now[which] += 30_000_000_000
    assert not gui.finish_verification(reply["response_code"])
    with pytest.raises(BridgeError) as caught:
        instance().answer(prompt["challenge"], "local")
    assert caught.value.code == "setup_verification_expired"


def test_generation_principal_or_challenge_mismatch_does_not_create_receipt(handshake):
    records, _, instance = handshake
    prompt = instance().begin_verification()
    for server, challenge, principal in [
        (instance("b" * 32), prompt["challenge"], "local"),
        (instance(), prompt["challenge"], "other"),
        (instance(), prompt["challenge"][:33] + "f" * 32, "local"),
    ]:
        with pytest.raises(BridgeError):
            server.answer(challenge, principal)
    assert len(records.values) == 1


def test_active_challenge_and_reply_cannot_be_swapped_between_gui_attempts(handshake):
    _, _, instance = handshake
    gui, server = instance(), instance()
    first = gui.begin_verification()
    first_reply = server.answer(first["challenge"], "local")
    second = gui.begin_verification()
    assert not gui.finish_verification(first_reply["response_code"])
    second_reply = server.answer(second["challenge"], "local")
    assert gui.finish_verification(second_reply["response_code"])


def test_private_owner_or_reparse_refusal_is_not_turned_into_success(handshake):
    records, _, instance = handshake
    gui = instance()
    prompt = gui.begin_verification()
    records.refuse = True
    with pytest.raises(BridgeError) as caught:
        instance().answer(prompt["challenge"], "local")
    assert caught.value.code == "unsafe_credentials"
    with pytest.raises(BridgeError):
        gui.finish_verification("A" * 16)
    assert not gui.public_proof()["verified"]


@pytest.mark.parametrize("lifetime", [True, 0, 29, 601, float("nan"), "300"])
def test_lifetime_is_strict_and_bounded_before_any_write(handshake, lifetime):
    records, _, instance = handshake
    with pytest.raises(ValueError):
        instance().begin_verification(lifetime)
    assert not records.values


def test_disabled_or_nonwindows_construction_does_not_create_private_state(monkeypatch):
    monkeypatch.setattr(module, "_PrivateRecords", lambda _: pytest.fail("Unexpected state access"))
    with pytest.raises(BridgeError):
        module.WindowsSetupVerification(None, GENERATION, enabled=False, host="win32")
    with pytest.raises(BridgeError):
        module.WindowsSetupVerification(None, GENERATION, enabled=True, host="darwin")


@pytest.mark.parametrize(
    "changes", [{"path": "secret"}, {"task_id": "x"}, {"arguments": {}}, {"max_bytes": 1}]
)
def test_read_selector_refuses_unrelated_fields(changes):
    with pytest.raises(ValidationError):
        ReadQuery(operation=module.OPERATION, challenge="a" * 32 + "." + "b" * 32, **changes)


def test_read_schema_revalidation_preserves_valid_batched_challenge():
    value = ReadQuery(operation=module.OPERATION, challenge="a" * 32 + "." + "b" * 32)
    assert ReadQuery.model_validate(value.model_dump()).challenge == value.challenge
    with pytest.raises(ValidationError):
        ReadQuery(operation="platform.status", challenge=value.challenge)


def test_catalog_is_opt_in_authorized_windows_metadata_without_state_work(bridge, monkeypatch):
    monkeypatch.setattr(
        module, "_PrivateRecords", lambda _: pytest.fail("Catalog performed state work")
    )
    monkeypatch.setattr(module, "host_platform", lambda: "win32")
    assert module.verification_catalog(bridge, "local") == {}
    bridge.config.windows_setup_verification_enabled = True
    assert module.verification_catalog(bridge, "local") == {}
    bridge.config.principals["local"].capabilities.append(module.OPERATION)
    row = module.verification_catalog(bridge, "local")[module.OPERATION]
    assert row["transport"] == "read_query" and not row["task_submission_supported"]
    monkeypatch.setattr(module, "host_platform", lambda: "darwin")
    assert module.verification_catalog(bridge, "local") == {}


def test_preview_setup_flag_adds_only_proof_capability_and_is_strict(monkeypatch, tmp_path):
    from kirabridge import windows_preview as preview

    monkeypatch.setattr(preview, "require_windows", lambda: None)
    monkeypatch.setattr(preview, "require_desktop", lambda: None)
    monkeypatch.setattr(preview, "private_directory", lambda path: path.mkdir(exist_ok=True))
    monkeypatch.setattr(preview, "write_private", lambda path, text: path.write_text(text))
    monkeypatch.setattr(preview, "private_json", lambda path: json.loads(path.read_text()))
    normal = preview.prepare(tmp_path / "normal", port=18865)
    setup = preview.prepare(tmp_path / "setup", port=18868, setup_verification=True)
    assert normal.config.windows_setup_verification_enabled is False
    assert tuple(normal.config.principals["local"].capabilities) == preview.CAPABILITIES
    assert setup.config.windows_setup_verification_enabled is True
    assert setup.public("http")["capabilities"] == [*preview.CAPABILITIES, module.OPERATION]
    for value in (1, "true", None):
        with pytest.raises(BridgeError) as caught:
            preview.prepare(tmp_path / "invalid", setup_verification=value)
        assert caught.value.code == "invalid_setup_mode"
        assert not (tmp_path / "invalid").exists()


@pytest.mark.parametrize("host, enabled", [("win32", False), ("darwin", True)])
def test_read_handler_platform_and_mode_refuse_before_state_work(
    bridge, monkeypatch, host, enabled
):
    bridge.config.principals["local"].capabilities.append(module.OPERATION)
    bridge.config.windows_setup_verification_enabled = enabled
    monkeypatch.setattr(module, "host_platform", lambda: host)
    monkeypatch.setattr(module, "_PrivateRecords", lambda _: pytest.fail("Unexpected state work"))
    with pytest.raises(BridgeError) as caught:
        module.verify_read(bridge, "local", "a" * 32 + "." + "b" * 32)
    assert caught.value.code == "windows_setup_disabled"


async def test_authenticated_http_roundtrip_uses_no_task_and_is_explicitly_simulated(
    http_bridge,  # noqa: F811
    monkeypatch,
):
    bridge, endpoint = http_bridge
    records = Records()
    monkeypatch.setattr(module, "host_platform", lambda: "win32")
    monkeypatch.setattr(module, "_PrivateRecords", lambda root: records)
    bridge.config.windows_setup_verification_enabled = True
    bridge.config.principals["local"].capabilities.append(module.OPERATION)
    gui = module.WindowsSetupVerification(
        None,
        bridge.runtime["instance_id"],
        enabled=True,
        records=records,
        host="win32",
    )
    prompt = gui.begin_verification(simulated=True)
    async with httpx.AsyncClient(trust_env=False) as client:
        assert (await client.post(endpoint, json={})).status_code == 401
    assert len(records.values) == 1
    async with MCPClientPool() as pool:
        await pool.connect(Peer("setup", url=endpoint, token="local-test-" + "a" * 40))
        await pool.call("setup", "bridge_health", {})
        assert len(records.values) == 1 and not gui.public_proof()["verified"]
        catalog = (
            await pool.call("setup", "operation_catalog", {"operations": [module.OPERATION]})
        ).structuredContent
        assert catalog["operations"][module.OPERATION]["transport"] == "read_query"
        reply = await pool.call("setup", "read_query", {"query": prompt["query"]})
        assert isinstance(reply, CallToolResult) and not reply.isError
        assert gui.finish_verification(reply.structuredContent["response_code"])
        assert not gui.public_proof()["verified"] and gui.public_proof()["local_test_verified"]
        bridge.config.principals["local"].capabilities.remove(module.OPERATION)
        refused = await pool.call("setup", "read_query", {"query": prompt["query"]})
        assert refused.structuredContent["error"]["code"] == "forbidden"
    assert bridge.store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0
    with pytest.raises(BridgeError):
        bridge.submit(
            "local",
            TaskRequest(
                task_id="not-a-task",
                idempotency_key="not-a-task",
                operation=module.OPERATION,
                arguments={"challenge": prompt["challenge"]},
            ),
        )


def test_private_record_adapter_uses_existing_guarded_reader_and_sanitizes_decode_errors(
    monkeypatch, tmp_path
):
    from kirabridge import private_files

    records = module._PrivateRecords.__new__(module._PrivateRecords)
    records.root = tmp_path
    seen = []

    def malformed(path):
        seen.append(path)
        raise ValueError("SECRET credential bytes must never appear in an error")

    monkeypatch.setattr(private_files, "private_json", malformed)
    with pytest.raises(BridgeError) as caught:
        records.read(GENERATION, "reply")
    assert "SECRET" not in str(caught.value) and seen == [tmp_path / (GENERATION + ".reply.json")]
    with pytest.raises(BridgeError):
        records.read("../outside", "reply")
    assert len(seen) == 1
