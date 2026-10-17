from kirabridge.bridge_core.models import digest
from kirabridge.task_manager.store import Store


def verify(store: Store) -> dict:
    import json

    previous, count = "0" * 64, 0
    for row in store.db.execute("SELECT * FROM audit ORDER BY seq"):
        record = {k: row[k] for k in ("at", "kind", "principal", "task_id", "previous")}
        record["metadata"] = json.loads(row["metadata"])
        if row["previous"] != previous or digest(record) != row["hash"]:
            return {"valid": False, "failed_sequence": row["seq"]}
        previous, count = row["hash"], count + 1
    return {"valid": True, "records": count, "head": previous}
