"""Bounded schema compilation reuse; instances and permissions are always checked."""

import json
from collections import OrderedDict

from jsonschema import SchemaError
from jsonschema.exceptions import best_match
from jsonschema.validators import validator_for
from referencing import Registry


class SchemaValidatorCache:
    def __init__(self, *, max_entries=64, max_bytes=8 * 1024 * 1024):
        self.max_entries, self.max_bytes = max_entries, max_bytes
        self.validators = OrderedDict()
        self.canonical_bytes = 0
        self.schema_checks = 0

    def validate(self, instance, schema):
        # Canonicalize on every call: in-place edits and fresh tool definitions
        # cannot reuse a validator for a different schema. Never mutate peer data.
        try:
            key = json.dumps(
                schema, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
            )
            size = len(key.encode("utf-8"))
        except (TypeError, ValueError, RecursionError):
            raise SchemaError("Tool schema is not valid JSON") from None
        validator = self.validators.get(key)
        if validator is None:
            document = json.loads(key)
            cls = validator_for(document)
            cls.check_schema(document)
            self.schema_checks += 1
            # Keep the SDK's explicit empty registry: no network retrieval of
            # untrusted external $refs. Document-local definitions still work.
            validator = cls(document, registry=Registry())
            if size <= self.max_bytes and self.max_entries > 0:
                while self.validators and (
                    len(self.validators) >= self.max_entries
                    or self.canonical_bytes + size > self.max_bytes
                ):
                    removed, _ = self.validators.popitem(last=False)
                    self.canonical_bytes -= len(removed.encode("utf-8"))
                self.validators[key] = validator
                self.canonical_bytes += size
        else:
            self.validators.move_to_end(key)
        # Match jsonschema.validate's error selection without repeating its
        # expensive metaschema validation for unchanged trusted schema content.
        error = best_match(validator.iter_errors(instance))
        if error is not None:
            raise error


def explicit_scalar_const_types(schema):
    """Annotate an implied scalar const type for clients that default it to string.

    Values and validation remain unchanged. Never coerce tool arguments, visit
    instance data in const/default/examples, or relax the peer's native schema.
    """
    from copy import deepcopy

    result = deepcopy(schema)

    def visit(node):
        if not isinstance(node, dict):
            return
        if "const" in node and "type" not in node:
            kind = {
                str: "string",
                int: "integer",
                float: "number",
                bool: "boolean",
                type(None): "null",
            }.get(type(node["const"]))
            if kind:
                node["type"] = kind
        for key in ("properties", "$defs", "definitions", "patternProperties", "dependentSchemas"):
            for child in node.get(key, {}).values():
                visit(child)
        for key in (
            "items",
            "additionalProperties",
            "unevaluatedProperties",
            "contains",
            "not",
            "if",
            "then",
            "else",
            "propertyNames",
        ):
            child = node.get(key)
            if isinstance(child, list):
                for entry in child:
                    visit(entry)
            else:
                visit(child)
        for key in ("allOf", "anyOf", "oneOf", "prefixItems"):
            for child in node.get(key, []):
                visit(child)

    visit(result)
    return result
