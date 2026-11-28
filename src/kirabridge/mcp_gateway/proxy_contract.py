"""SDK-independent contract for the daemon's dynamic tool aliases."""

from copy import deepcopy

from kirabridge.bridge_core.models import BridgeError, digest

PROXY_INSTRUCTIONS = (
    "Direct ChatGPT terminal work uses terminal_control (terminal.visible): an idle confirmed "
    "visible shell on macOS "
    "or a fresh owned PTY on Linux; never type into a busy/unconfirmed window or use a hidden "
    "fallback. This rule is separate from internal Codex/Grok execution and ThreadDesk. "
    "Refresh tools/list and operation_catalog after connection, version or session changes; "
    "compare discovery.revision. Check each permission_decision; request local approval only "
    "when approval_required is true. For known schemas, call directly; otherwise select only "
    "needed operations in operation_catalog. Batch independent reads with read_queries or "
    "read_query tool.batch and "
    "prefer structured results. Submit writes once; for pending work observe the same task_id, "
    "never replay an uncertain request. Completed inline results need no poll. Terminal input "
    "requires an exact pane_id and expected_pid. session.input sends literal text; "
    "use one keyboard_sequence call for physical keys. Posting input does not prove app "
    "processing. "
    "Receipts do not prove execution or completion. Keep completion_receive active and ack only "
    "after processing; ChatGPT chats are not awakened automatically. Use team tools for "
    "addressed role-based work. Agent/CLI handoffs require assigned existing visible windows; "
    "no background fallback. Historical buffers never auto-release. Eve relays Daniel's "
    "dictation unchanged."
)


def dynamic_tool_name(name):
    """One "td_" namespace: ThreadDesk command tools already carry it (no td_td_*)."""
    return name if name.startswith("td_") else "td_" + name


def dynamic_input_schema(item):
    """Mutation envelopes keep the peer schema intact and cannot collide with its fields."""
    if not item.get("requires_operation_id", False):
        return item["inputSchema"]
    schema = item["inputSchema"]
    if schema.get("$id") in (None, "", "#"):
        # Keep peer-root pointers rooted at the peer, not this host envelope.
        schema = deepcopy(schema)
        schema["$id"] = "urn:kirabridge:threaddesk-input:" + digest(schema)
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "operation_id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,128}$"},
            "arguments": schema,
        },
        "required": ["operation_id", "arguments"],
    }


def dynamic_call_arguments(item, arguments):
    if not item.get("requires_operation_id", False):
        return {"name": item["name"], "arguments": arguments}
    if (
        not isinstance(arguments, dict)
        or set(arguments) != {"operation_id", "arguments"}
        or not isinstance(arguments.get("arguments"), dict)
    ):
        raise BridgeError("invalid_arguments", "Use the advertised mutation envelope")
    return {"name": item["name"], **arguments}


async def read_dynamic_catalog(call_tool):
    """Read the peer's optional aliases without holding any stale metadata."""
    try:
        result = await call_tool("threaddesk_dynamic_catalog", {})
        if isinstance(result, dict):
            data, is_error = result.get("structuredContent"), result.get("isError", False)
        else:
            data, is_error = result.structuredContent, result.isError
    except Exception as exc:
        return {}, {
            "code": "threaddesk_catalog_failed",
            "message": f"ThreadDesk catalog read failed: {type(exc).__name__}",
        }
    if isinstance(data, dict) and isinstance(data.get("error"), dict):
        error = data["error"]
        return {}, {
            "code": str(error.get("code") or "threaddesk_catalog_failed"),
            "message": str(error.get("message") or "ThreadDesk catalog could not be read"),
            "diagnostic": data.get("diagnostic"),
        }
    if is_error or not isinstance(data, dict):
        return {}, {
            "code": "threaddesk_catalog_failed",
            "message": "ThreadDesk catalog could not be read",
        }
    entries = data.get("tools")
    if not isinstance(entries, list) or len(entries) > 256:
        return {}, {
            "code": "threaddesk_catalog_failed",
            "message": "ThreadDesk catalog was not usable",
        }
    names = {}
    for item in entries:
        if not isinstance(item, dict):
            continue
        name, schema = item.get("name"), item.get("inputSchema")
        if (
            isinstance(name, str)
            and name.startswith(tuple("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"))
            and name.replace("_", "").replace("-", "").isalnum()
            and len(name) <= 64
            and isinstance(schema, dict)
        ):
            names.setdefault(dynamic_tool_name(name), item)
    return names, None


def dynamic_tool_definition(name, item):
    return {
        "name": name,
        "description": "ThreadDesk: " + (item.get("description") or ""),
        "inputSchema": dynamic_input_schema(item),
        "annotations": item.get(
            "annotations",
            {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
        ),
    }


async def require_dynamic_tool(call_tool, name):
    discovered, problem = await read_dynamic_catalog(call_tool)
    if problem:
        failure = BridgeError("threaddesk_catalog_unavailable", problem["message"])
        failure.diagnostic = {
            **(problem.get("diagnostic") or {}),
            "cause_code": problem["code"],
            "cause": problem["message"],
            "automatic_retry": False,
        }
        raise failure
    item = discovered.get(name)
    if item is None:
        raise BridgeError("threaddesk_tool_denied", "Dynamic tool is unavailable")
    return item
