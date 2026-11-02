"""Explicit system keyboard intents, sharing the existing task and desktop lease."""

from typing import Literal

from pydantic import Field, model_validator

from kirabridge.bridge_core.models import Input
from kirabridge.keyboard_models import KeyboardKey, Modifier
from kirabridge.platform_adapters.macos.control_models import ApplicationTargetInput


class KeyboardSystemKeyInput(Input):
    scope: Literal["system"]
    target: ApplicationTargetInput
    action: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,63}$")
    key: KeyboardKey | None = None
    modifiers: list[Modifier] = Field(default_factory=list, max_length=5)
    repeat: int = Field(default=1, ge=1, le=20, strict=True)

    @model_validator(mode="after")
    def coherent(self):
        if (self.action is None) == (self.key is None):
            raise ValueError("Choose a system action or one key")
        if self.action is not None and self.modifiers:
            raise ValueError("System actions use their observed configured modifiers")
        if len(self.modifiers) != len(set(self.modifiers)):
            raise ValueError("Modifiers must be unique")
        return self


SYSTEM_NAMED_CODES = {
    "left": 123,
    "right": 124,
    "down": 125,
    "up": 126,
    "tab": 48,
    "space": 49,
    "f1": 122,
    "f2": 120,
    "f3": 99,
    "f4": 118,
    "f5": 96,
    "f6": 97,
    "f7": 98,
    "f8": 100,
    "f9": 101,
    "f10": 109,
    "f11": 103,
    "f12": 111,
    "f13": 105,
    "f14": 107,
    "f15": 113,
    "f16": 106,
    "f17": 64,
    "f18": 79,
    "f19": 80,
    "f20": 90,
}


def possible_system_shortcut(key, modifiers):
    return bool(
        key
        and "fn" not in modifiers
        and (
            modifiers
            or (key.named or "").startswith("f")
            or key.key_code
            in {code for name, code in SYSTEM_NAMED_CODES.items() if name.startswith("f")}
        )
    )


def registered_system_action(inventory, key, modifiers):
    """Only an exact enabled observed shortcut can change an automatic route."""
    if "fn" in modifiers:
        return None  # Explicit Fn is intent, not a removable classification bit.
    if "shortcut_match" in inventory:
        match = inventory["shortcut_match"]
        if (
            isinstance(match, dict)
            and match.get("registered_system_action") is True
            and isinstance(match.get("action"), str)
        ):
            return match["action"]
        return None
    code = key.key_code if key.key_code is not None else SYSTEM_NAMED_CODES.get(key.named)
    # Logical character translation belongs to the native current-layout resolver.
    if code is None:
        return None
    matches = []
    for row in inventory.get("actions", []):
        observed_key = row.get("key") or {}
        observed = set(row.get("modifiers", []))
        requested = set(modifiers)
        if code in {123, 124, 125, 126} or code in {
            value for name, value in SYSTEM_NAMED_CODES.items() if name.startswith("f")
        }:
            observed.discard("fn")
            requested.discard("fn")
        if (
            row.get("available") is True
            and observed_key.get("key_code") == code
            and observed == requested
        ):
            matches.append(row.get("action"))
    return matches[0] if len(matches) == 1 and isinstance(matches[0], str) else None


def system_receipt_verified(result, *, action, repeat):
    if action == "caps_lock":
        before, after = result.get("state_before"), result.get("state_after")
        return (
            result.get("scope") == "native_state_readback"
            and result.get("event_scope") == "system"
            and result.get("modifier") == "caps_lock"
            and result.get("resolved", {}).get("route") == "modifier_lock_state"
            and result.get("resolved", {}).get("action") == "caps_lock"
            and result.get("effect_verified") is True
            and result.get("system_processing_confirmed") is True
            and all(
                type(result.get(k)) is int
                for k in ("completed_repeat", "state_set_calls_returned", "post_calls_returned")
            )
            and result.get("completed_repeat") == repeat
            and result.get("requested_repeat") == repeat
            and result.get("state_set_calls_returned") == repeat
            and result.get("post_calls_returned") == 0
            and type(before) is bool
            and type(after) is bool
            and after == (before ^ bool(repeat % 2))
        )
    return result.get("post_calls_returned") == 2 * repeat
