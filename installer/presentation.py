"""Optional, hash-pinned human presentation before the candidate venv exists.

Loads only fixed stdlib leaf modules from this verified bundle. It never imports
KiraBridge services, changes sys.path, starts a writer/thread, or touches a profile.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

SCHEMA = "kirabridge.installer.presentation.v1"
ASSETS = (
    "payload/src/kirabridge/terminal_design.py",
    "payload/src/kirabridge/install_ui.py",
    "installer/presentation.py",
)


def _load(path, source, name):
    spec = importlib.util.spec_from_loader(name, loader=None, origin=str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        module.__file__ = str(path)
        exec(compile(source, str(path), "exec"), module.__dict__)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def create_presentation(
    bundle, *, language="de", stream=None, motion="auto", exclusive_output=False
):
    """Return a presenter only after every declared presentation asset is checked.

    Missing legacy metadata or invalid optional assets disable decoration. The
    installer's existing complete package-integrity check remains mandatory;
    no invalid presentation file is imported or executed here.
    """
    try:
        root = Path(bundle).resolve(strict=True)
        pin = json.loads((root / "release.json").read_text())
        descriptor = pin.get("presentation", {})
        if descriptor.get("schema") != SCHEMA:
            return None
        hashes = descriptor.get("assets")
        if not isinstance(hashes, dict) or set(hashes) != set(ASSETS):
            return None
        paths = {}
        for name in ASSETS:
            path = root / name
            expected = hashes[name]
            if (
                not isinstance(expected, str)
                or not re.fullmatch(r"[a-f0-9]{64}", expected)
                or path.is_symlink()
                or not path.resolve(strict=True).is_relative_to(root)
            ):
                return None
            source = path.read_bytes()
            if hashlib.sha256(source).hexdigest() != expected:
                return None
            if "files" in pin and pin["files"].get(name) != expected:
                return None
            paths[name] = (path, source)
        design = _load(*paths[ASSETS[0]], "_kirabridge_installer_design")
        ui = _load(*paths[ASSETS[1]], "_kirabridge_installer_ui")
        return ui.SetupUI(
            language, stream, design=design, motion=motion, exclusive_output=exclusive_output
        )
    except Exception:
        return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--language", choices=("de", "en"), default="de")
    options = parser.parse_args()
    presenter = create_presentation(options.bundle, language=options.language, motion="reduced")
    if presenter is None:
        raise SystemExit(1)
    presenter.begin()
    presenter.finish()
