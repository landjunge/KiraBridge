"""Test-only helpers that give synthetic running jobs a genuine current claim seal.

The seal is always computed by the production ``MessageReceiver.claim_seal`` over
the fresh stored message row, run_id and configured receiver cwd. Nothing here
weakens validation: fixtures that intentionally model a missing or damaged seal
must not use these helpers.
"""

import json

from kirabridge.bridge_core.models import canonical
from kirabridge.message_manager.receiver import MessageReceiver


def with_stored_seal(bridge, message_id, evidence):
    """Keep the seal (and pinned context) that a real ``_claim`` stored for this job."""
    stored = json.loads(
        bridge.store.db.execute(
            "SELECT evidence FROM message_jobs WHERE message_id=?", (message_id,)
        ).fetchone()[0]
    )
    assert isinstance(stored.get("claim_seal"), dict), "job was not claimed with a seal"
    kept = {k: stored[k] for k in ("claim_seal", "managed_guidance_context") if k in stored}
    return {**evidence, **kept}


def seal_running_job(bridge, message_id, run_id, evidence):
    """Mark a job running under run_id with a full current seal bound to the receiver cwd."""
    row = bridge.store.db.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
    cwd = bridge.config.messaging.receivers[row["recipient"]].cwd
    seal = MessageReceiver(bridge).claim_seal(row, run_id, cwd)
    bridge.store.db.execute(
        "UPDATE message_jobs SET state='running',run_id=?,execution_cwd=?,evidence=? "
        "WHERE message_id=?",
        (run_id, cwd, canonical({**evidence, "claim_seal": seal}), message_id),
    )
    return seal
