"""Classify CLI slash commands and reuse the guarded literal-input executor.

This module neither interprets commands nor confirms any resulting menu or
permission dialog. The addressed CLI owns slash-command semantics.
"""

import re
from pathlib import Path

from kirabridge.bridge_core.models import BridgeError


def command_name(text):
    match = re.match(r"/([A-Za-z][A-Za-z0-9_-]*)(?=$|[ \t\n])", text)
    return "/" + match[1] if match else None


def bound_thread_title(sessions, binding):
    """Read one already-bound thread title, never expose the global title index."""
    selected = sessions.current_selection()
    if (
        not selected
        or selected[0] != "codex"
        or selected[1] != binding
        or binding.agent_pid not in selected[2]
        or not binding.codex_thread_id
        or not binding.codex_rollout_path
    ):
        return None
    from kirabridge.platform_adapters.codex_metadata import read_thread_title

    return read_thread_title(binding.codex_rollout_path, binding.codex_thread_id)


def resume_insertion_observed(target, raw, text, before, *, cwd=None, home=None, title=None):
    """Only a selected /resume suggestion may acquire a bound thread-title footer."""
    from kirabridge.literal_session_input import (
        _cwd_footer,
        _displays_cwd,
        _without_empty_composer_hint,
        _without_viewport_padding,
        insertion_observed,
    )
    from kirabridge.visible_readiness import display_text, input_view

    if insertion_observed(target, raw, text, before, cwd=cwd, home=home):
        return True
    if target != "codex" or text != "/resume" or not cwd or not title:
        return False
    cleaned, controls = display_text(raw)
    previous, previous_controls = display_text(before)
    if controls or previous_controls:
        return False
    view, old_view = input_view("codex", cleaned), input_view("codex", previous)
    if not view.startswith("› /resume\n") or "\n" not in old_view:
        return False
    prelude = cleaned[: len(cleaned) - len(view)].rstrip(" \t\n")
    if not prelude or not re.fullmatch(
        r"[ \t]*› /resume[ \t]+resume a saved chat[ \t]*", prelude.splitlines()[-1]
    ):
        return False
    suggestion_start = prelude.rfind("\n") + 1
    old_prelude = previous[: len(previous) - len(old_view)].rstrip(" \t\n")
    if prelude[:suggestion_start].rstrip(" \t\n") != old_prelude:
        # Exactly one supported suggestion may appear. Preserve the entire
        # prior transcript so extra options or dialog headings cannot hide here.
        return False
    old_suffix = old_view[old_view.index("\n") :]
    new_suffix = view[len("› /resume") :]
    variants = [old_suffix]
    without_hint = _without_empty_composer_hint(_without_viewport_padding(old_suffix))
    if without_hint is not None:
        variants.append(without_hint)
    new = _cwd_footer(new_suffix)
    if new is None:
        return False
    new_rows, new_index, new_model, new_path_title, new_badge = new
    new_path, separator, displayed_title = new_path_title.partition(" · ")
    title_matches = displayed_title == title or (
        displayed_title.endswith("…")
        and displayed_title.count("…") == 1
        and len(displayed_title) > 1
        and title.startswith(displayed_title[:-1])
        and len(displayed_title) - 1 < len(title)
    )
    if (
        not separator
        or not title_matches
        or new_badge
        or not _displays_cwd(new_path, cwd, home or str(Path.home()))
    ):
        return False
    for suffix in variants:
        old = _cwd_footer(suffix)
        if old is None:
            continue
        old_rows, old_index, old_model, old_path, old_badge = old
        if (
            old_badge
            and old_path.endswith("…")
            and old_index == new_index
            and old_model == new_model
            and len(old_rows) == len(new_rows)
            and _displays_cwd(old_path, cwd, home or str(Path.home()))
            and new_path.startswith(old_path[:-1])
            and all(old_rows[i] == new_rows[i] for i in range(len(old_rows)) if i != old_index)
        ):
            return True
    return False


async def execute(bridge, task, args, target, binding, running, progress):
    command = command_name(args.text)
    if command is None or args.key is not None:
        raise BridgeError("invalid_arguments", "A slash command requires explicit literal text")
    from kirabridge.literal_session_input import execute as literal_execute

    def verifier(target, raw, text, before, *, cwd=None, home=None):
        title = bound_thread_title(bridge.sessions, binding) if cwd is not None else None
        return resume_insertion_observed(target, raw, text, before, cwd=cwd, home=home, title=title)

    result = await literal_execute(
        bridge,
        task,
        args,
        target,
        binding,
        running,
        progress,
        verifier=verifier,
        verifier_version="codex-slash-widget-v1",
    )
    return {**result, "input_kind": "slash_command", "slash_command": command}
