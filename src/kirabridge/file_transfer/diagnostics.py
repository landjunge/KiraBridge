"""Whitelisted progress/receipt view: never include source capabilities or byte contents."""


def public_record(record):
    fields = ("id", "manifest", "state", "offset", "receipt", "error_code", "updated")
    return {
        **{key: record[key] for key in fields},
        "import_successful": record["state"] == "stored" and record["receipt"] is not None,
        "storage_verification_scope": (
            "receipt validated at completion; no continuous downstream deletion tracking"
        ),
    }
