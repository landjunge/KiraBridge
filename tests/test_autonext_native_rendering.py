"""The actual card prompt must stay verifiable through the existing Codex renderer."""

import json
import sqlite3
from types import SimpleNamespace

from kirabridge.autonext.manager import AutoNextManager
from kirabridge.autonext.models import ReadyCard
from kirabridge.cli_adapters.rendering import codex_wrapped_renderings, insertion_observed


def test_complete_json_card_has_native_verifiable_line_breaks():
    card = ReadyCard(
        autonext=1,
        task_id="native-46ce73e89be1f13d-1",
        state="READY",
        product="KiraBridge",
        cwd="/home/operator/workspaces/native-e2e/workspace",
        sandbox="read-only",
        title="Bounded native continuation probe 1",
        instruction="Do not use tools or change files. Return the required team JSON with "
        "result exactly BIGPLAN_NATIVE_46ce73e89be1f13d_1 and actions an empty array.",
        acceptance={"kind": "result_sha256", "expected_sha256": "3" * 64},
    )
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE autonext_items(work_id TEXT,card TEXT)")
    db.execute("INSERT INTO autonext_items VALUES(?,?)", ("one", card.model_dump_json()))
    manager = AutoNextManager.__new__(AutoNextManager)
    manager.store = SimpleNamespace(db=db)
    prompt = manager.prompt_for({"id": "one"})
    assert json.loads(prompt.split("\n", 1)[1]) == card.model_dump()
    # Compact JSON created long unbroken punctuation/hash/path runs in the
    # captured failure; pretty rows preserve the card without widening proof.
    forms = codex_wrapped_renderings(prompt, 130)
    assert forms
    footer = "\n\n  GPT-6.1-Sol high · ~\n"
    assert insertion_observed("codex", "› " + forms[0] + footer, prompt, "› " + footer, columns=130)
    db.close()
