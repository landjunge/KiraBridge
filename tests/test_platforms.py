import pytest

from kirabridge.bridge_core.models import BridgeError
from kirabridge.platform_adapters import LinuxAdapter, MacOSAdapter, WindowsAdapter


def test_macos_text_clipboard_commands():
    assert MacOSAdapter().clipboard_command(True) == ["/usr/bin/pbcopy"]
    assert MacOSAdapter().clipboard_command(False) == ["/usr/bin/pbpaste"]


def test_linux_clipboard_backend_selection(monkeypatch):
    monkeypatch.setenv("WAYLAND_DISPLAY", "test-display")
    monkeypatch.setattr(
        "kirabridge.platform_adapters.shutil.which", lambda name: "/usr/bin/" + name
    )
    assert LinuxAdapter().clipboard_command(True) == [
        "/usr/bin/wl-copy",
        "--type",
        "text/plain;charset=utf-8",
    ]
    assert LinuxAdapter().clipboard_command(False) == ["/usr/bin/wl-paste", "--no-newline"]
    monkeypatch.delenv("WAYLAND_DISPLAY")
    assert LinuxAdapter().clipboard_command(False) == [
        "/usr/bin/xclip",
        "-selection",
        "clipboard",
        "-out",
    ]


def test_unavailable_platform_backends_fail_closed(monkeypatch):
    monkeypatch.setattr("kirabridge.platform_adapters.shutil.which", lambda name: None)
    with pytest.raises(BridgeError):
        LinuxAdapter().clipboard_command(False)
    with pytest.raises(BridgeError) as error:
        WindowsAdapter().clipboard_command(False)
    assert error.value.code == "unsupported_platform"
