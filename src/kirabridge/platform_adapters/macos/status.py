"""Explicit status selectors; helper diagnostics never become execution grants."""

from kirabridge.bridge_core.models import Input


class PlatformStatusInput(Input):
    check_helpers: bool = False
