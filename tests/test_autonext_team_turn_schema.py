"""The coordinator output schema accepts only an inert, complete team envelope."""

import json
from importlib.resources import files

import pytest
from jsonschema import Draft202012Validator, ValidationError


def validator():
    schema = json.loads(files("kirabridge.autonext").joinpath("team_turn.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def test_strict_coordinator_team_turn_schema():
    validator().validate({"kirabridge_team": "1", "result": "reviewed result", "actions": []})
    validator().validate({"kirabridge_team": "1", "result": '{"verdict":"pass"}', "actions": []})


@pytest.mark.parametrize(
    "payload",
    [
        '{"kirabridge_team":"1","result":"double encoded","actions":[]}',
        {"kirabridge_team": 1, "result": "wrong version type", "actions": []},
        {"kirabridge_team": "2", "result": "wrong version", "actions": []},
        {"kirabridge_team": "1", "result": "missing actions"},
        {"kirabridge_team": "1", "result": {}, "actions": []},
        {"kirabridge_team": "1", "result": "never delegate", "actions": ["run"]},
        {"kirabridge_team": "1", "result": "unexpected", "actions": [], "extra": True},
    ],
)
def test_invalid_coordinator_envelopes_are_rejected(payload):
    with pytest.raises(ValidationError):
        validator().validate(payload)
