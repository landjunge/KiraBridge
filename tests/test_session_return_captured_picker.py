"""Native Codex 0.166.0 nonempty picker at the captured narrow window width."""

import pytest

from kirabridge.bridge_core.config import VisibleTerminalBinding
from kirabridge.session_return import return_readiness

COMPACT_PICKER = (
    " Resume a previous session\n"
    " Filter:  Cwd  All    Status:  Active  Archived    Sort:  Updated  Created\n"
    " Type to search\n \n"
    "  › 10m ago     Owned diagnostic chat                                    \n \n\n\n\n\n"
    "────────────────────────────────────────────────────────────── 1 / 1 · 100% ─\n"
    " enter resume   ⌃a archive   esc exit   ⌃c exit   tab focus   ←/→ option\n"
    " ⌃o comfy   ⌃t preview   ⌃e exp   ↑/↓ browse\n\n"
)

# Exact full-width footer with archive action from native E2E07 (31.10.2026).
WIDE_ARCHIVE_PICKER = COMPACT_PICKER.replace(
    "tab focus   ←/→ option", "tab focus sort/filter   ←/→ change option"
).replace("⌃o comfy   ⌃t preview   ⌃e exp", "⌃o comfortable view   ⌃t transcript   ⌃e expand")


def binding():
    return VisibleTerminalBinding(
        pane_id="terminal:100:ttys001", expected_pid=42, agent_pid=43, ready_pattern=r"(?m)^›\s*$"
    )


def test_captured_compact_nonempty_picker_is_return_ready():
    result = return_readiness("codex", COMPACT_PICKER, binding())
    assert result["ready"] and result["reason"] == "observed_codex_resume_selector"


def test_captured_wide_archive_picker_is_return_ready():
    result = return_readiness("codex", WIDE_ARCHIVE_PICKER, binding())
    assert result["ready"] and result["reason"] == "observed_codex_resume_selector"


@pytest.mark.parametrize(
    "frame",
    [
        WIDE_ARCHIVE_PICKER.replace("⌃a archive", "⌃a approve"),
        WIDE_ARCHIVE_PICKER.replace("1 / 1", "0 / 0"),
        WIDE_ARCHIVE_PICKER.replace(
            "  › 10m ago     Owned diagnostic chat", "  No selected session"
        ),
        WIDE_ARCHIVE_PICKER.replace("⌃t transcript", "⌃t approve"),
        WIDE_ARCHIVE_PICKER + "Approve another operation?\n",
    ],
)
def test_wide_archive_picker_keeps_selection_and_exact_footer_guards(frame):
    assert not return_readiness("codex", frame, binding())["ready"]


@pytest.mark.parametrize(
    "frame",
    [
        COMPACT_PICKER.replace("⌃a archive", "⌃a approve"),
        COMPACT_PICKER.replace("⌃t preview", "⌃t execute"),
        COMPACT_PICKER.replace("1 / 1", "0 / 0"),
        COMPACT_PICKER.replace("  › 10m ago     Owned diagnostic chat", "  No selected session"),
        COMPACT_PICKER + "Approve another operation?\n",
        "• Working (3s • esc to interrupt)\n" + COMPACT_PICKER,
    ],
)
def test_unknown_or_busy_compact_picker_variants_remain_refused(frame):
    assert not return_readiness("codex", frame, binding())["ready"]


@pytest.mark.parametrize("state", ["working", "unknown"])
def test_compact_picker_does_not_override_bound_turn_state(state):
    assert not return_readiness("codex", COMPACT_PICKER, binding(), {"state": state})["ready"]
