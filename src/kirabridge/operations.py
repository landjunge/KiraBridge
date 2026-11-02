"""Operation properties shared by authorization, catalog and dispatch.

Input models remain assembled by the composition root. This module imports no
manager, platform adapter or configuration and cannot start work.
"""

from dataclasses import asdict, dataclass
from typing import Literal

from kirabridge.system_operations import SYSTEM_LEAVES, SYSTEM_READ_OPERATIONS

READ_OPERATIONS = frozenset(
    {
        *SYSTEM_READ_OPERATIONS,
        "keyboard.profiles.list",
        "keyboard.profiles.get",
        "keyboard.profiles.resolve",
        "process.output",
        "system.report",
        "platform.status",
        "files.inventory",
        "files.status",
        "connection.check",
        "session.catalog",
        "session.read",
        "file.read",
        "file.list",
        "file.image",
        "clipboard.info",
        "process.list",
        "process.inspect",
        "agent.status",
        "policy.inspect",
        "handoff.status",
        "handoff.inbox",
        "threaddesk.read",
        "observations.read",
    }
)
STOP_OPERATIONS = frozenset(
    {"process.terminate", "workflow.stop", "files.pause", "files.abort", "queue.control"}
)
RESERVED_READ_OPERATIONS = frozenset(
    {
        "platform.status",
        "session.catalog",
        "session.read",
        "files.inventory",
        "files.status",
        "process.list",
        "process.inspect",
        "agent.status",
        "policy.inspect",
        "handoff.status",
    }
)
LEGACY_CONTROL_OPERATIONS = (
    RESERVED_READ_OPERATIONS - {"session.catalog", "session.read"}
) | STOP_OPERATIONS


@dataclass(frozen=True)
class Operation:
    capability: str
    effect: Literal["read", "write", "execute", "control"]
    execution_class: Literal["normal", "read", "stop"]

    def describe(self):
        return asdict(self)


OPERATIONS = {}
for _name in (
    *READ_OPERATIONS,
    *STOP_OPERATIONS,
    *SYSTEM_LEAVES,
    "files.prepare",
    "files.transfer",
    "session.open",
    "keyboard.key",
    "keyboard.control",
    "keyboard.chord",
    "keyboard.text",
    "keyboard.action",
    "keyboard.profiles.put",
    "keyboard.profiles.delete",
    "session.input",
    "session.focus",
    "session.close",
    "terminal.execute",
    "terminal.visible",
    "file.write",
    "file.mkdir",
    "file.move",
    "file.delete",
    "clipboard.read",
    "clipboard.write",
    "agent.execute",
    "handoff.issue",
    "handoff.start",
    "handoff.answer",
    "handoff.reconcile",
    "handoff.decide",
    "threaddesk.dynamic",
    "threaddesk.manage",
    "threaddesk.knowledge",
    "admin.execute",
):
    OPERATIONS[_name] = Operation(
        capability="process.inspect"
        if _name == "process.output"
        else "keyboard.profiles.read"
        if _name in {"keyboard.profiles.list", "keyboard.profiles.get", "keyboard.profiles.resolve"}
        else "keyboard.profiles.manage"
        if _name in {"keyboard.profiles.put", "keyboard.profiles.delete"}
        else "keyboard.shortcuts.read"
        if _name == "keyboard.shortcuts.discover"
        else "keyboard.execute"
        if _name
        in {
            "keyboard.key",
            "keyboard.chord",
            "keyboard.text",
            "keyboard.action",
            "keyboard.control",
        }
        else "bridge.health"
        if _name == "platform.status"
        else "threaddesk.manage"
        if _name == "threaddesk.dynamic"
        else "task.cancel"
        if _name == "queue.control"
        else "files.inspect"
        if _name in {"files.inventory", "files.status"}
        else "files.transfer"
        if _name in {"files.pause", "files.abort"}
        else "session.input"
        if _name in {"session.focus", "session.close"}
        else "session.inspect"
        if _name in {"session.catalog", "session.read"}
        else "terminal.execute"
        if _name == "terminal.visible"
        else _name,
        effect="read"
        if _name in READ_OPERATIONS or _name == "clipboard.read"
        else "control"
        if _name in STOP_OPERATIONS
        else "execute"
        if _name in {"terminal.execute", "admin.execute", "agent.execute"}
        else "write",
        execution_class="stop"
        if _name in STOP_OPERATIONS
        else "read"
        if _name in RESERVED_READ_OPERATIONS
        else "normal",
    )


def capability_for(operation):
    descriptor = OPERATIONS.get(operation)
    return descriptor.capability if descriptor else operation


def lane_operations(lane):
    if lane == "control":  # Compatibility for existing local Store callers.
        return LEGACY_CONTROL_OPERATIONS
    return frozenset(name for name, spec in OPERATIONS.items() if spec.execution_class == lane)
