"""Keyboard intent contracts. Registration and native effects are separate steps."""

from typing import Literal

from pydantic import Field, model_validator

from kirabridge.bridge_core.models import Input
from kirabridge.platform_adapters.macos.control_models import ApplicationTargetInput

MAX_TEXT_UTF8_BYTES = 1024 * 1024
NamedKey = Literal[
    "enter",
    "keypad_enter",
    "escape",
    "tab",
    "space",
    "backspace",
    "delete",
    "left",
    "right",
    "up",
    "down",
    "home",
    "end",
    "page_up",
    "page_down",
    "f1",
    "f2",
    "f3",
    "f4",
    "f5",
    "f6",
    "f7",
    "f8",
    "f9",
    "f10",
    "f11",
    "f12",
    "f13",
    "f14",
    "f15",
    "f16",
    "f17",
    "f18",
    "f19",
    "f20",
    "help",
    "keypad_clear",
    "keypad_0",
    "keypad_1",
    "keypad_2",
    "keypad_3",
    "keypad_4",
    "keypad_5",
    "keypad_6",
    "keypad_7",
    "keypad_8",
    "keypad_9",
    "keypad_decimal",
    "keypad_multiply",
    "keypad_plus",
    "keypad_divide",
    "keypad_minus",
    "keypad_equals",
    "keypad_comma",
]
Modifier = Literal["command", "control", "option", "shift", "fn"]


def literal_text(value: str) -> bytes:
    """Validate Unicode scalars and size without changing a single character."""
    try:
        raw = value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("Text must contain valid Unicode scalars") from None
    if not raw or len(raw) > MAX_TEXT_UTF8_BYTES:
        raise ValueError("Text must contain between 1 byte and 1 MiB of UTF-8")
    if any((ord(c) < 32 and c not in "\t\r\n") or ord(c) == 127 for c in value):
        raise ValueError("Text may contain tab and line breaks, but no other ASCII controls")
    return raw


class KeyboardInspectInput(ApplicationTargetInput):
    """Inspect an exact existing app; never activate it implicitly."""


class KeyboardShortcutsInput(ApplicationTargetInput):
    """Read a bounded menu snapshot; continuation never starts a new scan."""

    limit: int = Field(default=100, ge=1, le=250)
    offset: int = Field(default=0, ge=0, le=2000)
    expected_revision: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def bound_page(self):
        if self.offset and self.expected_revision is None:
            raise ValueError("Shortcut continuation requires its observed snapshot revision")
        return self


class KeyboardTarget(ApplicationTargetInput):
    target_token: str = Field(pattern=r"^[a-f0-9]{32}$")
    helper_pid: int = Field(gt=0, le=2**31 - 1)
    worker_generation: str = Field(pattern=r"^[A-Fa-f0-9-]{36}$")
    expected_revision: str = Field(pattern=r"^[a-f0-9]{64}$")


class KeyboardKey(Input):
    """A named key, logical base-key label or physical macOS position; exactly one."""

    named: NamedKey | None = None
    character: str | None = Field(
        default=None,
        min_length=1,
        max_length=1,
        description="Base-key label; letter case never adds Shift. Use explicit modifiers.",
    )
    key_code: int | None = Field(default=None, ge=0, le=127)

    @model_validator(mode="after")
    def one_key(self):
        if sum(v is not None for v in (self.named, self.character, self.key_code)) != 1:
            raise ValueError("Choose exactly one key representation")
        if self.character is not None:
            literal_text(self.character)
            if not self.character.isprintable():
                raise ValueError("Use a named key for control characters")
        return self


class KeyboardKeyInput(Input):
    target: KeyboardTarget
    key: KeyboardKey
    repeat: int = Field(default=1, ge=1, le=20, strict=True)


class KeyboardActionInput(Input):
    target: KeyboardTarget
    profile_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    expected_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    action: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,79}$")


class KeyboardChordInput(KeyboardKeyInput):
    modifiers: list[Modifier] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def unique_modifiers(self):
        if len(set(self.modifiers)) != len(self.modifiers):
            raise ValueError("Modifier names must be unique")
        return self


class KeyboardTextInput(Input):
    target: KeyboardTarget
    text: str = Field(min_length=1, max_length=MAX_TEXT_UTF8_BYTES)
    submit: bool = False

    @model_validator(mode="after")
    def valid_text(self):
        literal_text(self.text)
        return self
