"""Recognize supported Codex menus; never grant approvals or send a key.

Only the captured resume selector is a supported confirmation menu. Unknown
menus and permission dialogs do not become generic Enter/approval actions.
"""

import re

from kirabridge.visible_readiness import input_view


def resume_selector(text):
    titles = list(re.finditer(r"(?m)^[ \t]*Resume a previous session[ \t]*$", text))
    if not titles:
        return False
    lines = [line.strip(" \t") for line in text[titles[-1].start() :].splitlines()]
    while lines and not lines[-1]:
        lines.pop()
    if len(lines) < 6:
        return False
    position = re.fullmatch(
        r"─{3,}[ \t]*([0-9]+)[ \t]*/[ \t]*([0-9]+)[ \t]*·[ \t]*[0-9]+%[ \t]*─+",
        lines[-3],
    )
    if position is None:
        return False
    wide = bool(
        re.fullmatch(
            r"enter resume[ \t]+esc exit[ \t]+⌃c exit[ \t]+tab focus sort/filter"
            r"[ \t]+←/→ change option",
            lines[-2],
        )
        and re.fullmatch(
            r"⌃o comfortable view[ \t]+⌃t transcript[ \t]+⌃e expand[ \t]+↑/↓ browse",
            lines[-1],
        )
    )
    compact_nonempty = bool(
        1 <= int(position[1]) <= int(position[2])
        and any(re.match(r"›[ \t]+\S", line) for line in lines[1:-3])
        and re.fullmatch(
            r"enter resume[ \t]+⌃a archive[ \t]+esc exit[ \t]+⌃c exit"
            r"[ \t]+tab focus[ \t]+←/→ option",
            lines[-2],
        )
        and re.fullmatch(r"⌃o comfy[ \t]+⌃t preview[ \t]+⌃e exp[ \t]+↑/↓ browse", lines[-1])
    )
    wide_archive_nonempty = bool(
        1 <= int(position[1]) <= int(position[2])
        and any(re.match(r"›[ \t]+\S", line) for line in lines[1:-3])
        and re.fullmatch(
            r"enter resume[ \t]+⌃a archive[ \t]+esc exit[ \t]+⌃c exit"
            r"[ \t]+tab focus sort/filter[ \t]+←/→ change option",
            lines[-2],
        )
        and re.fullmatch(
            r"⌃o comfortable view[ \t]+⌃t transcript[ \t]+⌃e expand[ \t]+↑/↓ browse",
            lines[-1],
        )
    )
    return bool(
        (wide or compact_nonempty or wide_archive_nonempty)
        and any(
            re.fullmatch(
                r"Filter:[ \t]+Cwd[ \t]+All[ \t]+Status:[ \t]+Active[ \t]+Archived"
                r"[ \t]+Sort:[ \t]+Updated[ \t]+Created",
                line,
            )
            for line in lines[1:-1]
        )
        and "Type to search" in lines
    )


def resume_readiness(text):
    """Called only after resume_selector matched the complete current menu."""
    title = list(re.finditer(r"(?m)^[ \t]*Resume a previous session[ \t]*$", text))[-1]
    prelude = text[: title.start()].rstrip()
    current = re.split(r"\n[ \t]*\n", prelude)[-1] if prelude else ""
    if re.search(r"(?m)^[ \t]*[•◦]\s+[^\n]*\([^\n]*esc to interrupt", current):
        return {
            "target": "codex",
            "ready": False,
            "state": "working",
            "reason": "current_progress_row",
        }
    return {
        "target": "codex",
        "ready": True,
        "state": "ready",
        "reason": "observed_codex_resume_selector",
    }


def unsupported_confirmation_frame(text):
    """A known permission heading is not an ordinary input composer.

    Inspect only the block immediately before the current composer, not quoted
    headings in older transcript output. Unrecognized footer rows are separately
    refused by the ordinary composer parser.
    """
    view = input_view("codex", text)
    if not view:
        return False
    prelude = text[: len(text) - len(view)].rstrip()
    current = re.split(r"\n[ \t]*\n", prelude)[-1] if prelude else ""
    return any(
        line.strip()
        in {
            "Approval required",
            "Would you like to run the following command?",
            "Would you like to make the following edits?",
            "Do you want to allow this action?",
        }
        for line in current.splitlines()
    )
