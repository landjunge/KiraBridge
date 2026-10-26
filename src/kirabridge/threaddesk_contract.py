"""Bounded, content-free preflight for the declared ThreadDesk administration contract.

The legacy limits are explicit KiraBridge compatibility limits, not a claim about
an unobserved server. Current peer declarations take precedence when available.
"""

from __future__ import annotations

import json
import re

FIELDS = {
    "create": {"title", "description", "project_id", "parent_thread_id"},
    "update": {"title", "description", "status"},
    "set_note": {"text", "append"},
    "add_file": {"path"},
    "remove_file": {"path"},
    "organize": {"project_id", "parent_thread_id", "related_thread_ids"},
    "archive": set(),
    "unarchive": set(),
    "delete": set(),
    "switch": set(),
}
REQUIRED = {
    "create": {"title"},
    "set_note": {"text"},
    "add_file": {"path"},
    "remove_file": {"path"},
}
ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def field_schema(field):
    if field == "append":
        return {"type": "boolean"}
    if field in {"project_id", "parent_thread_id"}:
        return {"type": ["string", "null"]}
    if field == "related_thread_ids":
        return {"type": "array", "maxItems": 100, "uniqueItems": True}
    result = {"type": "string", "maxLength": 100000 if field == "text" else 10000}
    if field == "status":
        result["enum"] = ["idea", "active", "paused", "done"]
    return result


class ContractSchemaError(ValueError):
    """Untrusted declaration has an unsupported shape; never include its contents."""


def _mapping(value):
    if not isinstance(value, dict):
        raise ContractSchemaError()
    return value


def _field(field, peer):
    peer = _mapping(peer)
    if "$ref" in peer:
        raise ContractSchemaError()  # Never resolve external or local references implicitly.
    result = {**field_schema(field), **peer}
    kind = result.get("type")
    kinds = kind if isinstance(kind, list) else [kind]
    allowed = {"string", "boolean", "integer", "number", "array", "object", "null"}
    if (
        not kinds
        or len(kinds) > 7
        or any(not isinstance(item, str) or item not in allowed for item in kinds)
    ):
        raise ContractSchemaError()
    for key in ("maxLength", "minLength", "maxItems"):
        if key in peer and (type(peer[key]) is not int or peer[key] < 0):
            raise ContractSchemaError()
        if key in result:
            result["_" + key + "_source"] = (
                "peer_tools_list" if key in peer else "kirabridge_legacy_compatibility"
            )
    if "uniqueItems" in peer and type(peer["uniqueItems"]) is not bool:
        raise ContractSchemaError()
    if "enum" in peer and (not isinstance(peer["enum"], list) or len(peer["enum"]) > 256):
        raise ContractSchemaError()
    return result


def _safe_schema_tree(schema):
    pending, visited = [(schema, 0)], 0
    while pending:
        value, depth = pending.pop()
        visited += 1
        if visited > 4096 or depth > 32:
            raise ContractSchemaError()
        if isinstance(value, dict):
            if "$ref" in value or len(value) > 4096 - visited - len(pending):
                raise ContractSchemaError()
            pending.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, list):
            if len(value) > 4096 - visited - len(pending):
                raise ContractSchemaError()
            pending.extend((item, depth + 1) for item in value)


def declaration(schema, action):
    if schema is not None:
        schema = _mapping(schema)
        _safe_schema_tree(schema)
        _mapping(schema.get("properties", {}))
        if "$ref" in schema:
            raise ContractSchemaError()
        variants = schema.get("oneOf", [])
        if not isinstance(variants, list) or len(variants) > 64:
            raise ContractSchemaError()
        for variant in variants:
            properties = _mapping(_mapping(variant).get("properties", {}))
            discriminator = _mapping(properties.get("action", {}))
            if discriminator.get("const") != action:
                continue
            data = _mapping(properties.get("data", {}))
            fields = _mapping(data.get("properties", {}))
            required = data.get("required", [])
            if (
                len(fields) > 64
                or not isinstance(required, list)
                or any(not isinstance(item, str) or item not in fields for item in required)
            ):
                raise ContractSchemaError()
            bounded = {field: _field(field, spec) for field, spec in fields.items()}
            return bounded, set(required), "peer_tools_list"
    return (
        {field: field_schema(field) for field in FIELDS[action]},
        REQUIRED.get(action, set()),
        "kirabridge_legacy_compatibility",
    )


def violation(field, constraint, *, source, actual=None, limit=None, text=None):
    public_fields = set().union(*FIELDS.values()) | {"data", "id", "create", "thread_manage"}
    field = field if field in public_fields else "data"
    details = {
        "field": field,
        "constraint": constraint,
        "limit_source": source,
        "request_sent": False,
    }
    if actual is not None:
        details["actual"] = actual
    if limit is not None:
        details["limit"] = limit
    if isinstance(text, str):
        details["characters"] = len(text)
        try:
            details["utf8_bytes"] = len(text.encode("utf-8"))
        except UnicodeEncodeError:
            details["utf8_bytes"] = None
    return {
        "code": "threaddesk_validation",
        "message": (
            f"ThreadDesk field {field}: {constraint}"
            + (f" (actual {actual}, limit {limit})" if limit is not None else "")
            + "; no mutation sent. Preserve the original input; do not truncate or retry create."
        ),
        "details": details,
    }


def _validate_management(values, schema):
    """Return a safe structured error, or None. Never retain field values in errors."""
    action, data = values["action"], values.get("data", {})
    fields, required, source = declaration(schema, action)
    if action == "create":
        if values.get("expected_revision") != 0 or "id" in values:
            return violation("create", "requires revision 0 and no id", source=source)
    elif not isinstance(values.get("id"), str) or not ID.fullmatch(values["id"]):
        return violation("id", "exact identifier required", source=source)
    if set(data) - set(fields):
        return violation("data", "unsupported field", source=source)
    if required - set(data):
        return violation("data", "required field missing", source=source)
    if action in {"update", "organize"} and not data:
        return violation("data", "at least one change required", source=source)
    for field, value in data.items():
        spec = fields[field]
        kind = spec.get("type")
        kinds = kind if isinstance(kind, list) else [kind]
        types = {
            "string": str,
            "boolean": bool,
            "integer": int,
            "array": list,
            "object": dict,
            "null": type(None),
        }
        if kind and not any(type(value) is types.get(item) for item in kinds):
            return violation(field, "wrong JSON type", source=source)
        if "enum" in spec and value not in spec["enum"]:
            return violation(field, "unsupported enum value", source=source)
        if isinstance(value, str):
            try:
                value.encode("utf-8")
            except UnicodeEncodeError:
                return violation(field, "valid UTF-8 required", source=source, text=value)
            for constraint, compare in (
                ("maxLength", lambda n, bound: n > bound),
                ("minLength", lambda n, bound: n < bound),
            ):
                limit = spec.get(constraint)
                if type(limit) is int and compare(len(value), limit):
                    return violation(
                        field,
                        constraint + " characters",
                        source=spec.get("_" + constraint + "_source", source),
                        actual=len(value),
                        limit=limit,
                        text=value,
                    )
        if isinstance(value, list):
            limit = spec.get("maxItems")
            if type(limit) is int and len(value) > limit:
                return violation(field, "maxItems", source=source, actual=len(value), limit=limit)
            if spec.get("uniqueItems") and len(
                {json.dumps(v, sort_keys=True) for v in value}
            ) != len(value):
                return violation(field, "uniqueItems", source=source)
        if field in {"project_id", "parent_thread_id"} and value is not None:
            if not isinstance(value, str) or not ID.fullmatch(value):
                return violation(field, "exact identifier required", source=source)
        if field == "related_thread_ids" and (
            not isinstance(value, list)
            or any(not isinstance(v, str) or not ID.fullmatch(v) for v in value)
        ):
            return violation(field, "exact identifiers required", source=source)
    return None


def validate_management(values, schema):
    try:
        return _validate_management(values, schema)
    except ContractSchemaError:
        result = violation(
            "thread_manage", "unsupported or malformed peer schema", source="peer_tools_list"
        )
        result["code"] = "threaddesk_contract_schema"
        return result


def safe_peer_error(code, value, *, contract=None):
    """Keep only numeric/schema diagnostics; raw peer messages may contain secrets."""
    # The frozen legacy peer drops SecretRejected's type, retaining this fixed
    # public message only. Classify that exact signature; never echo peer text.
    if (
        code == "tool_error"
        and isinstance(value, dict)
        and value.get("message") == "Keine API-Keys oder Passwörter in Thread-Dateien."
    ):
        code = "secret_detected"
    incoming = value.get("details", {}) if isinstance(value, dict) else {}
    if not isinstance(incoming, dict):
        incoming = {}
    safe = {
        key: item
        for key, item in incoming.items()
        if key
        in {
            "expected_revision",
            "actual_revision",
            "limit",
            "actual",
            "max_length",
            "actual_length",
            "max_bytes",
            "actual_bytes",
        }
        and type(item) is int
    }
    if contract:
        try:
            fields, _, source = declaration(contract, "set_note")
            safe["text_max_characters"] = fields.get("text", {}).get("maxLength")
            fields, _, _ = declaration(contract, "create")
            safe["description_max_characters"] = fields.get("description", {}).get("maxLength")
            safe["limit_source"] = source
        except ContractSchemaError:
            safe["contract_state"] = "invalid_or_unsupported"
    return {
        "error": {
            "code": code,
            "details": safe,
            "message": (
                "ThreadDesk secret protection reported a rejection; preserve input and "
                "inspect the original operation ID. No automatic replay."
                if code == "secret_detected"
                else "ThreadDesk rejected the operation; inspect declared field limits "
                "and the original operation ID. No automatic replay."
            ),
        }
    }
