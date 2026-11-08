"""Entwurf BP-AA-02: synthetische Beispiele gegen das v2-Schema; kein Sender, keine Laufzeit."""

import copy
import json
from pathlib import Path

import pytest
from jsonschema import ValidationError
from jsonschema.validators import validator_for

from kirabridge.mcp_gateway.schema_validation import SchemaValidatorCache

SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "docs/contracts/agent-event-v2.draft.schema.json"
)
SCHEMA = json.loads(SCHEMA_PATH.read_text())


def validate(event):
    SchemaValidatorCache().validate(event, SCHEMA)


def test_schema_is_well_formed():
    validator_for(SCHEMA).check_schema(SCHEMA)


@pytest.mark.parametrize("index", range(len(SCHEMA["examples"])))
def test_synthetic_examples_validate(index):
    validate(SCHEMA["examples"][index])


def test_v1_event_stays_valid_and_rejects_v2_blocks():
    v1 = next(e for e in SCHEMA["examples"] if e["schema_version"] == "1")
    bad = copy.deepcopy(v1)
    bad["task"] = {"task_id": "x"}
    with pytest.raises(ValidationError):
        validate(bad)


@pytest.mark.parametrize("key", ["token", "secret", "prompt", "api_key"])
def test_forbidden_keys_are_rejected(key):
    bad = copy.deepcopy(SCHEMA["examples"][0])
    bad[key] = "x"
    with pytest.raises(ValidationError):
        validate(bad)


def test_v2_requires_honesty_block():
    bad = copy.deepcopy(SCHEMA["examples"][0])
    del bad["assertion"]
    with pytest.raises(ValidationError):
        validate(bad)
