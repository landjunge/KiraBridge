"""Native team result text remains lossless in read-only owner-scoped queue views."""

import hashlib
import json

import pytest

from kirabridge.bridge_core.config import TeamConfig, TeamWorkerConfig
from kirabridge.bridge_core.models import BridgeError, canonical
from kirabridge.team_manager.models import TeamCreate, TeamWorkCreate


@pytest.fixture
def team_entry(bridge, config):
    for name in ("local", "other"):
        policy = config.principals[name]
        policy.capabilities += ["team.manage", "team.read", "team.write"]
        policy.permission_level = "full"
    config.team = TeamConfig(
        enabled=True, workers={name: TeamWorkerConfig() for name in ("local", "other")}
    )
    bridge.teams.create(
        "local",
        TeamCreate(
            team_id="isolated",
            name="Synthetic queue",
            members={"other": "worker"},
            coordinator="local",
            idempotency_key="create",
        ),
    )
    entry = bridge.teams.delegate(
        "local",
        TeamWorkCreate(
            team_id="isolated",
            assignee="other",
            title="Result readback",
            body="Synthetic only",
            idempotency_key="work",
        ),
    )
    return bridge, entry["id"]


@pytest.mark.parametrize("result", ["Completed native result ä🧠", "", '{"native":"text"}', "123"])
def test_catalog_and_paged_team_entry_preserve_native_text_without_writes(team_entry, result):
    bridge, identifier = team_entry
    evidence = {"actions": [], "model_turn_completed": True}
    bridge.store.db.execute(
        "UPDATE team_work SET result=?,state='processing_result',evidence=? WHERE id=?",
        (result, canonical(evidence), identifier),
    )
    before = tuple(bridge.store.db.iterdump())
    catalog = bridge.queues.catalog("local")
    assert next(q for q in catalog["queues"] if q["queue_id"] == "team-work")["count"] == 1
    page = bridge.queues.entries("local", "team-work")
    summary = page["entries"][0]
    assert summary["id"] == identifier and summary["state"] == "processing_result"
    text, offset, content_hash = "", 0, None
    while True:
        chunk = bridge.queues.read_entry(
            "local",
            "team-work",
            identifier,
            offset=offset,
            max_chars=31,
            expected_revision=summary["revision"],
        )
        text += chunk["detail_json_chunk"]
        content_hash = chunk["content_sha256"]
        if not chunk["has_more_content"]:
            break
        offset = chunk["next_content_offset"]
    value = json.loads(text)
    assert type(value["result"]) is str and value["result"] == result
    assert value["evidence"] == evidence  # Genuine JSON columns remain decoded.
    assert hashlib.sha256(text.encode()).hexdigest() == content_hash
    assert tuple(bridge.store.db.iterdump()) == before


def test_completed_plaintext_history_does_not_block_catalog_or_cross_owner_scope(
    team_entry, config
):
    bridge, identifier = team_entry
    bridge.store.db.execute(
        "UPDATE team_work SET result='Completed plain text',state='completed' WHERE id=?",
        (identifier,),
    )
    config.principals["outsider"] = config.principals["local"].model_copy(deep=True)
    before = tuple(bridge.store.db.iterdump())
    catalog = bridge.queues.catalog("local")
    assert next(q for q in catalog["queues"] if q["queue_id"] == "team-work")["count"] == 0
    assert bridge.queues.entries("local", "team-work")["entries"] == []
    assert (
        bridge.queues.entries("local", "team-work", active_only=False)["entries"][0]["id"]
        == identifier
    )
    assert bridge.queues.entries("outsider", "team-work", active_only=False)["entries"] == []
    with pytest.raises(BridgeError) as exc:
        bridge.queues.get("outsider", "team-work", identifier)
    assert exc.value.code == "not_found"
    assert tuple(bridge.store.db.iterdump()) == before
