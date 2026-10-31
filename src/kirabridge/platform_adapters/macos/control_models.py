"""Typed public macOS application, system and accessibility operations."""

from typing import Literal

from pydantic import Field, model_validator

from kirabridge.bridge_core.models import Input


class SystemInfoInput(Input):
    pass


class PermissionRequestInput(Input):
    resource: Literal["accessibility", "screen_capture", "notifications"]
    alert: bool = True
    sound: bool = False
    badge: bool = False

    @model_validator(mode="after")
    def notification_options(self):
        if self.resource == "notifications" and not any((self.alert, self.sound, self.badge)):
            raise ValueError("Choose at least one notification authorization option")
        return self


class ApplicationListInput(Input):
    offset: int = Field(default=0, ge=0, le=100000)
    limit: int = Field(default=100, ge=1, le=1000)
    expected_revision: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def stable_page(self):
        if self.offset and not self.expected_revision:
            raise ValueError("Application continuation requires the catalog revision")
        return self


class ApplicationTargetInput(Input):
    pid: int = Field(gt=0, le=2**31 - 1)
    expected_started_at: float = Field(gt=0, allow_inf_nan=False)


class ApplicationLaunchInput(Input):
    app_path: str = Field(min_length=6, max_length=4096)

    @model_validator(mode="after")
    def bundle(self):
        if not self.app_path.startswith("/") or not self.app_path.endswith(".app"):
            raise ValueError("Use an exact absolute application bundle path")
        return self


class AccessibilityInspectInput(ApplicationTargetInput):
    element_token: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    helper_pid: int | None = Field(default=None, gt=0, le=2**31 - 1)
    worker_generation: str | None = Field(default=None, pattern=r"^[A-Fa-f0-9-]{36}$")
    offset: int = Field(default=0, ge=0, le=100000)
    limit: int = Field(default=50, ge=1, le=250)
    value_offset: int = Field(default=0, ge=0, le=10000000)
    max_value_chars: int = Field(default=4096, ge=1, le=16384)
    expected_revision: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def token_owner(self):
        if bool(self.element_token) != (self.helper_pid is not None) or bool(
            self.element_token
        ) != (self.worker_generation is not None):
            raise ValueError("Element tokens require the native helper PID")
        if (self.offset or self.value_offset) and (
            not self.element_token or not self.expected_revision
        ):
            raise ValueError("Continue using the returned token, worker and revision")
        return self


class AccessibilityElementInput(ApplicationTargetInput):
    element_token: str = Field(pattern=r"^[a-f0-9]{32}$")
    helper_pid: int = Field(gt=0, le=2**31 - 1)
    worker_generation: str = Field(pattern=r"^[A-Fa-f0-9-]{36}$")
    expected_revision: str = Field(pattern=r"^[a-f0-9]{64}$")


class AccessibilityActionInput(AccessibilityElementInput):
    action: Literal[
        "press", "confirm", "cancel", "raise", "increment", "decrement", "show_menu", "pick"
    ]


class AccessibilitySetInput(AccessibilityElementInput):
    attribute: Literal["value", "focused", "selected", "expanded", "minimized", "position", "size"]
    value: str | bool | int | float | list[float]

    @model_validator(mode="after")
    def supported_value(self):
        if self.attribute in {"focused", "selected", "expanded", "minimized"}:
            if type(self.value) is not bool:
                raise ValueError("This accessibility attribute requires a boolean")
        elif self.attribute in {"position", "size"}:
            if not isinstance(self.value, list) or len(self.value) != 2:
                raise ValueError("Geometry requires exactly two coordinates")
            if any(not -100000 <= v <= 100000 for v in self.value):
                raise ValueError("Geometry exceeds the supported coordinate range")
            if self.attribute == "size" and any(v <= 0 for v in self.value):
                raise ValueError("Window dimensions must be positive")
        elif (
            isinstance(self.value, list) or isinstance(self.value, str) and len(self.value) > 16384
        ):
            raise ValueError("Unsupported or excessive value")
        return self


CONTROL_INPUTS = {
    "system.info": SystemInfoInput,
    "system.permissions": SystemInfoInput,
    "system.permission_request": PermissionRequestInput,
    "accessibility.status": SystemInfoInput,
    "system.displays": SystemInfoInput,
    "system.volumes": SystemInfoInput,
    "apps.list": ApplicationListInput,
    "apps.inspect": ApplicationTargetInput,
    "apps.launch": ApplicationLaunchInput,
    "apps.quit": ApplicationTargetInput,
    "accessibility.inspect": AccessibilityInspectInput,
    "accessibility.action": AccessibilityActionInput,
    "accessibility.set": AccessibilitySetInput,
}
