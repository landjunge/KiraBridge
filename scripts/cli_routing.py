#!/usr/bin/env python3
"""Entrypoint also usable from a pinned, isolated Big Plan installation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from kirabridge.capability_routing.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
