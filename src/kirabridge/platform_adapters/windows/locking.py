"""Exclusive native handle lock, scoped to one owner-verified non-reparse file."""

from kirabridge.bridge_core.models import BridgeError
from kirabridge.platform_adapters.windows.filesystem_security import WindowsFiles


class WindowsRuntimeLock:
    def __init__(self, path, *, api=None):
        self.path, self.api, self.handle = path, api, None

    def acquire(self):
        if self.handle is not None:
            return
        api = self.api or WindowsFiles()
        try:
            handle = api.open(self.path, create=True, exclusive=True, write=True)
        except OSError as error:
            if getattr(error, "winerror", None) in {32, 33}:
                raise BridgeError(
                    "already_running", "A dispatcher already owns this state directory"
                ) from error
            raise
        self.api, self.handle = api, handle

    def release(self):
        if self.handle is not None:
            self.api.close(self.handle)
            self.handle = None
