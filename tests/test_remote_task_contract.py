"""Passive remote contract fixtures; no remote adapter, task or provider is started."""

import copy
import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import ValidationError
from jsonschema.validators import validator_for
from pydantic import ValidationError as ModelValidationError

from kirabridge.autonext.models import ReadyCard
from kirabridge.bridge_core.models import (
    AgentInput,
    HandoffStartInput,
    TaskRequest,
    canonical,
    digest,
)
from kirabridge.mcp_gateway.schema_validation import SchemaValidatorCache
from kirabridge.security_manager import request_hash

CONTRACTS = Path(__file__).resolve().parents[1] / "docs" / "contracts"
SCHEMA = json.loads((CONTRACTS / "remote-task.v1.schema.json").read_text())
EXAMPLES = json.loads((CONTRACTS / "fixtures" / "remote-task.v1.examples.json").read_text())
PROJECT_DRAFTS = json.loads(
    (CONTRACTS / "fixtures" / "remote-project-draft.m2.examples.json").read_text()
)


def validate(message):
    SchemaValidatorCache().validate(message, SCHEMA)


def test_schema_is_well_formed_and_uses_only_document_local_refs():
    validator_for(SCHEMA).check_schema(SCHEMA)
    pending = [SCHEMA]
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            if "$ref" in value:
                assert value["$ref"].startswith("#/$defs/")
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)


@pytest.mark.parametrize("name", EXAMPLES["messages"])
def test_synthetic_message_shapes(name):
    validate(EXAMPLES["messages"][name])


@pytest.mark.parametrize(
    ("name", "arguments"),
    [("card_binding", AgentInput), ("handoff_intent", HandoffStartInput)],
)
def test_requests_preserve_native_core_and_argument_contracts(name, arguments):
    intent = EXAMPLES["messages"][name]
    request = TaskRequest.model_validate(intent["request"])
    assert request.model_dump() == intent["request"]
    arguments.model_validate(request.arguments)
    assert request_hash(request) == intent["request_sha256"]
    assert request.task_id == request.idempotency_key
    # The passive envelope is not accepted as an executable native request.
    with pytest.raises(ModelValidationError):
        TaskRequest.model_validate(intent)


def test_card_hash_is_original_utf8_bytes_and_not_canonical_object_digest():
    text = EXAMPLES["ready_card_text"]
    card = ReadyCard.model_validate_json(text)
    intent = EXAMPLES["messages"]["card_binding"]
    assert card.task_id == intent["source"]["card_task_id"]
    assert intent["request"]["task_id"] == "team-" + intent["source"]["work_id"]
    assert card.task_id != intent["request"]["task_id"]
    assert hashlib.sha256(text.encode()).hexdigest() == intent["source"]["content_sha256"]
    assert digest(json.loads(text)) != intent["source"]["content_sha256"]
    assert text.endswith("\n")  # Same parsed object; different original entry bytes.
    assert (
        hashlib.sha256(text.rstrip("\n").encode()).hexdigest() != intent["source"]["content_sha256"]
    )


def test_legacy_handoff_alias_and_native_binding_are_distinct():
    intent = EXAMPLES["messages"]["handoff_intent"]
    source, request = intent["source"], intent["request"]
    assert source["original_task_id"] == "synthetic-thread:task"
    assert source["original_task_id"] != request["task_id"]
    assert source["handoff_id"] == request["arguments"]["handoff_id"]
    assert source["handoff_revision"] == request["arguments"]["revision"]


def test_historical_handoff_alias_retains_colon_but_rejects_trailing_control():
    message = copy.deepcopy(EXAMPLES["messages"]["handoff_intent"])
    message["source"]["original_task_id"] += "\n"
    with pytest.raises(ValidationError):
        validate(message)


@pytest.mark.parametrize(
    ("name", "path"),
    [
        ("handoff_intent", ("request", "arguments", "handoff_id")),
        ("unknown_receipt", ("error", "code")),
    ],
)
def test_reference_and_error_code_patterns_reject_trailing_control(name, path):
    message = copy.deepcopy(EXAMPLES["messages"][name])
    target = message
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] += "\n"
    with pytest.raises(ValidationError):
        validate(message)


def test_receipts_pin_one_intent_request_device_and_result_without_executing():
    messages = EXAMPLES["messages"]
    intent = messages["card_binding"]
    for message in messages.values():
        if message["kind"] in {"intent", "execution_binding"}:
            continue
        binding = message["binding"]
        assert binding["task_id"] == intent["request"]["task_id"]
        assert binding["envelope_sha256"] == digest(intent)
        assert binding["request_sha256"] == intent["request_sha256"]
        assert binding["device_ref"] == intent["target"]["device_ref"]
    result = messages["completed_receipt"]["result"]["sha256"]
    assert messages["acceptance_receipt"]["result_sha256"] == result
    assert messages["display_receipt"]["result_sha256"] == result
    assert messages["unknown_receipt"]["state"] == "unknown"
    assert "result" not in messages["unknown_receipt"]


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("format",), "kirabridge.remote-task.v2"),
        (("route",), "visible_terminal"),
        (("principal",), "local"),
        (("approved",), True),
        (("request", "principal"), "local"),
        (("request", "api_version"), 1),
        (("request", "operation"), "terminal.visible"),
        (("request", "task_id"), "../foreign"),
        (("request", "task_id"), "remote-example-card\n"),
        (("request", "arguments", "agent"), "grok"),
        (("request", "arguments", "local_tools"), True),
        (("request", "arguments", "wait_for_reply"), False),
        (("request", "arguments", "arbitrary_tool"), "execute"),
        (("request_sha256",), "not-a-digest"),
        (("request_sha256",), "a" * 64 + "\n"),
        (("source", "kind"), "board_prose"),
        (("source", "thread_revision"), True),
        (("source", "actor_ref"), "synthetic-actor\n"),
        (("source", "content_sha256"), "A" * 64),
        (("target", "authority_revision"), 0),
        (("target", "device_ref"), "synthetic-device\n"),
        (("target", "device_key_sha256"), "0" * 63),
        (("target", "url"), "https://foreign.invalid"),
        (("authorization", "token"), "must-not-be-a-token-field"),
        (("issued_at",), True),
    ],
)
def test_rejects_unsupported_route_self_grant_and_malformed_identity(path, value):
    message = copy.deepcopy(EXAMPLES["messages"]["card_binding"])
    target = message
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    with pytest.raises(ValidationError):
        validate(message)


@pytest.mark.parametrize("field", ["source", "target", "authorization", "request_sha256"])
def test_no_intent_without_all_identity_and_authority_references(field):
    message = copy.deepcopy(EXAMPLES["messages"]["card_binding"])
    del message[field]
    with pytest.raises(ValidationError):
        validate(message)


def test_source_kind_cannot_silently_select_another_existing_execution_route():
    message = copy.deepcopy(EXAMPLES["messages"]["card_binding"])
    message["source"] = EXAMPLES["messages"]["handoff_intent"]["source"]
    with pytest.raises(ValidationError):
        validate(message)


def test_autonext_binding_is_observation_and_cannot_become_another_dispatch_intent():
    message = copy.deepcopy(EXAMPLES["messages"]["card_binding"])
    assert message["kind"] == "execution_binding"
    assert message["source"]["card_task_id"] != message["request"]["task_id"]
    assert message["request"]["task_id"] == "team-" + message["source"]["work_id"]
    # The existing TeamDispatcher seals this exact argument dict, without adding defaults.
    assert "wait_for_reply" not in message["request"]["arguments"]
    assert AgentInput.model_validate(message["request"]["arguments"]).wait_for_reply is True
    message["kind"] = "intent"
    with pytest.raises(ValidationError):
        validate(message)


@pytest.mark.parametrize("route", ["existing_visible_terminal", "structured_agent", "auto"])
def test_handoff_intent_cannot_select_visible_or_implicit_transport(route):
    message = copy.deepcopy(EXAMPLES["messages"]["handoff_intent"])
    message["route"] = route
    with pytest.raises(ValidationError):
        validate(message)


@pytest.mark.parametrize("field", ["card_task_id", "work_id"])
def test_autonext_observation_requires_both_existing_business_and_work_references(field):
    message = copy.deepcopy(EXAMPLES["messages"]["card_binding"])
    del message["source"][field]
    with pytest.raises(ValidationError):
        validate(message)


@pytest.mark.parametrize(
    ("name", "field"),
    [
        ("completed_receipt", "result"),
        ("unknown_receipt", "error"),
        ("queued_receipt", "runtime"),
        ("acceptance_receipt", "result_sha256"),
        ("acceptance_receipt", "evidence"),
        ("display_receipt", "client_ref"),
        ("display_receipt", "result_sha256"),
    ],
)
def test_receipt_types_require_their_own_evidence(name, field):
    message = copy.deepcopy(EXAMPLES["messages"][name])
    del message[field]
    with pytest.raises(ValidationError):
        validate(message)


def test_core_completion_cannot_be_relabelled_as_project_or_client_acceptance():
    for kind in ("acceptance_receipt", "display_receipt"):
        message = copy.deepcopy(EXAMPLES["messages"]["completed_receipt"])
        message["kind"] = kind
        with pytest.raises(ValidationError):
            validate(message)
    unknown = copy.deepcopy(EXAMPLES["messages"]["unknown_receipt"])
    unknown["result"] = EXAMPLES["messages"]["completed_receipt"]["result"]
    with pytest.raises(ValidationError):
        validate(unknown)


def test_shape_checks_do_not_pretend_to_verify_context_or_grants():
    message = copy.deepcopy(EXAMPLES["messages"]["card_binding"])
    message["target"]["device_ref"] = "another-syntactically-valid-device"
    validate(message)
    # A contextual adapter MUST reject this binding mismatch; none is implemented here.
    assert digest(message) != EXAMPLES["messages"]["queued_receipt"]["binding"]["envelope_sha256"]
    assert canonical(message) != canonical(EXAMPLES["messages"]["card_binding"])


@pytest.mark.parametrize("name", PROJECT_DRAFTS["cases"])
def test_td_m2_project_draft_is_neither_remote_intent_nor_issued_source(name):
    # Produced by the pinned TD M2 pure preview, including READY prose. No TD
    # import, workspace, grant resolver or remote delivery runs in this check.
    preview = PROJECT_DRAFTS["cases"][name]["preview"]
    assert preview["plan_status"] == "draft"
    assert preview["execution_started"] is False
    assert preview["source_verification"] == "referenced_unverified"
    with pytest.raises(ValidationError):
        validate(preview)
    with pytest.raises(ModelValidationError):
        TaskRequest.model_validate(preview)

    message = copy.deepcopy(EXAMPLES["messages"]["handoff_intent"])
    message["source"] = copy.deepcopy(preview)
    with pytest.raises(ValidationError):
        validate(message)
