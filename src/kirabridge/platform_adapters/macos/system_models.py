"""Typed native system operations; no scripts, OS grants or caller-supplied domains."""

from typing import Literal

from pydantic import Field, model_validator

from kirabridge.bridge_core.models import EmptyInput, Input

START = r"^[0-9]{1,12}\.[0-9]{6}$"
REVISION = r"^[a-f0-9]{64}$"


class WindowListInput(Input):
    owner_pid: int | None = Field(default=None, gt=0)
    expected_start: str | None = Field(default=None, pattern=START)
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=10000)
    expected_revision: str | None = Field(default=None, pattern=REVISION)
    include_titles: bool = False
    include_ax: bool = False

    @model_validator(mode="after")
    def exact_ax_target(self):
        if self.include_ax and (self.owner_pid is None or self.expected_start is None):
            raise ValueError("AX window enumeration needs an exact existing application")
        if self.expected_start is not None and self.owner_pid is None:
            raise ValueError("Application start requires owner_pid")
        if self.offset and self.expected_revision is None:
            raise ValueError("Window continuation requires the observed inventory revision")
        return self


class WindowInspectInput(Input):
    window_id: int = Field(gt=0, le=2**32 - 1)
    expected_pid: int = Field(gt=0)
    expected_start: str = Field(pattern=START)
    expected_revision: str | None = Field(default=None, pattern=REVISION)
    include_titles: bool = False


class AppFocusInput(Input):
    expected_pid: int = Field(gt=0)
    expected_start: str = Field(pattern=START)


class WindowFocusInput(AppFocusInput):
    ax_identifier: str = Field(min_length=1, max_length=256)


class WindowCaptureInput(WindowInspectInput):
    expected_revision: str = Field(pattern=REVISION)
    max_side: int | None = Field(default=None, ge=64, le=4096)


class DisplayCaptureInput(Input):
    display_id: int = Field(gt=0, le=2**32 - 1)
    expected_revision: str = Field(pattern=REVISION)
    max_side: int | None = Field(default=None, ge=64, le=4096)


class NotificationPostInput(Input):
    title: str = Field(default="", max_length=1024)
    body: str = Field(min_length=1, max_length=8192)
    sound: bool | None = None


PreferenceKey = Literal[
    "appearance", "notification_sound", "capture_max_side", "window_width", "window_height"
]


class PreferenceReadInput(Input):
    key: PreferenceKey


class PreferenceResetInput(PreferenceReadInput):
    expected_revision: str = Field(pattern=REVISION)


class PreferenceWriteInput(PreferenceResetInput):
    value: str | bool | int

    @model_validator(mode="after")
    def typed_value(self):
        if self.key == "appearance":
            valid = type(self.value) is str and self.value in {"system", "light", "dark"}
        elif self.key == "notification_sound":
            valid = type(self.value) is bool
        else:
            low = {"capture_max_side": 64, "window_width": 820, "window_height": 620}[self.key]
            valid = type(self.value) is int and low <= self.value <= 4096
        if not valid:
            raise ValueError("Value does not match the allowed application preference")
        return self


SYSTEM_INPUTS = {
    "windows.list": WindowListInput,
    "windows.inspect": WindowInspectInput,
    "app.focus": AppFocusInput,
    "windows.focus": WindowFocusInput,
    "capture.window": WindowCaptureInput,
    "capture.display": DisplayCaptureInput,
    "notifications.status": EmptyInput,
    "notifications.post": NotificationPostInput,
    "preferences.read": PreferenceReadInput,
    "preferences.write": PreferenceWriteInput,
    "preferences.reset": PreferenceResetInput,
}

from kirabridge.platform_adapters.macos.control_models import CONTROL_INPUTS  # noqa: E402
from kirabridge.platform_adapters.macos.system_services_models import SERVICE_INPUTS  # noqa: E402

SYSTEM_INPUTS.update(CONTROL_INPUTS)
SYSTEM_INPUTS.update(SERVICE_INPUTS)

from kirabridge.keyboard_models import KeyboardInspectInput, KeyboardShortcutsInput  # noqa: E402

SYSTEM_INPUTS["keyboard.inspect"] = KeyboardInspectInput
SYSTEM_INPUTS["keyboard.shortcuts.discover"] = KeyboardShortcutsInput
