"""Explicit owner configuration; updates preserve this section instead of changing defaults."""

import json
import re
import tomllib

from kirabridge.bridge_core.config import FileTransferConfig


def enabled_text(raw, *, export_roots, allowed_projects):
    parsed = tomllib.loads(raw)
    current = parsed.get("file_transfer", {})
    settings = FileTransferConfig.model_validate(
        {
            **current,
            "enabled": True,
            "export_roots": export_roots,
            "allowed_projects": allowed_projects,
        }
    )
    # Preserve unrelated sections, source-host grants and explicit limit overrides.
    text = raw
    edits = {
        "enabled": "true",
        "export_roots": json.dumps(settings.export_roots),
        "allowed_projects": json.dumps(settings.allowed_projects),
    }
    match = re.search(r"(?m)^\[file_transfer\]\s*$", text)
    if match is None:
        text = text.rstrip() + "\n\n[file_transfer]\n"
        start, end = len(text), len(text)
    else:
        start = match.end()
        following = re.search(r"(?m)^\[", text[start:])
        end = start + following.start() if following else len(text)
    section = text[start:end]
    for key, value in edits.items():
        pattern = rf"(?m)^{key}\s*=.*$"
        if re.search(pattern, section):
            section = re.sub(pattern, key + " = " + value, section)
        else:
            section = section.rstrip() + "\n" + key + " = " + value + "\n"
    result = text[:start] + section + "\n" + text[end:]
    check = tomllib.loads(result)
    assert check["file_transfer"]["enabled"] is True
    assert {k: v for k, v in check.items() if k != "file_transfer"} == {
        k: v for k, v in parsed.items() if k != "file_transfer"
    }
    return result
