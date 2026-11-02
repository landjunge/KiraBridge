"""Passive operation contracts for the native macOS system application worker."""

SYSTEM_LEAVES = {
    "keyboard.inspect": "keyboard",
    "system.info": "system",
    "system.processes": "system",
    "system.process": "system",
    "system.signal": "system",
    "system.permissions": "system",
    "system.permission_request": "system",
    "system.displays": "system",
    "system.volumes": "system",
    "apps.list": "apps",
    "apps.inspect": "apps",
    "apps.launch": "apps",
    "apps.quit": "apps",
    "app.focus": "apps",
    "windows.list": "windows",
    "windows.inspect": "windows",
    "windows.focus": "windows",
    "capture.window": "capture",
    "capture.display": "capture",
    "notifications.status": "notifications",
    "notifications.post": "notifications",
    "preferences.read": "preferences",
    "preferences.write": "preferences",
    "preferences.reset": "preferences",
    "accessibility.status": "accessibility",
    "accessibility.inspect": "accessibility",
    "accessibility.action": "accessibility",
    "accessibility.set": "accessibility",
}
SYSTEM_READ_OPERATIONS = frozenset(
    operation
    for operation in SYSTEM_LEAVES
    if operation
    not in {
        "system.permission_request",
        "system.signal",
        "apps.launch",
        "apps.quit",
        "app.focus",
        "windows.focus",
        "notifications.post",
        "preferences.write",
        "preferences.reset",
        "accessibility.action",
        "accessibility.set",
    }
)
SYSTEM_PERMISSIONS = {
    operation: "screen_capture"
    if operation.startswith("capture.")
    else "accessibility"
    if operation
    in {
        "keyboard.inspect",
        "windows.focus",
        "accessibility.inspect",
        "accessibility.action",
        "accessibility.set",
    }
    else "notifications"
    if operation == "notifications.post"
    else "per_selected_operation"
    for operation in SYSTEM_LEAVES
}
