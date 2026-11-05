"""Read native CLI wrapper metadata; never infer identity from model-authored text."""

import json
import re


def native_metadata(cli, stdout, requested_model):
    if cli != "grok":
        return {}
    try:
        body = json.loads(stdout)
        if (
            not isinstance(body, dict)
            or not isinstance(body.get("modelUsage"), dict)
            or not isinstance(body.get("sessionId"), str)
            or not isinstance(body.get("requestId"), str)
        ):
            return {}
        models = sorted(body["modelUsage"])
        if not models or any(
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/+-]{0,160}", m) for m in models
        ):
            return {}
        return {
            "reported_model_ids": models,
            "model_evidence_source": "grok_json.modelUsage",
            "model_matches_requested_id": models == [requested_model],
            "effective_model": models[0] if len(models) == 1 else "multiple_cli_reported_models",
            "effective_model_status": "cli_reported",
            "effective_effort": "unverified",
        }
    except (ValueError, TypeError):
        return {}
