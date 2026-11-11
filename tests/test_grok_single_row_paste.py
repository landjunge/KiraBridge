"""Exact decorated Grok composer replay; no native UI or input effects."""

import asyncio
import json
import shutil

import pytest

from kirabridge.cli_adapters.grok import GrokBuildAdapter
from kirabridge.cli_adapters.grok_echo import insertion_observed, paste_source
from kirabridge.cli_adapters.rendering import insertion_observed as renderer_observed

BEFORE = (
    "Earlier response\n ╭" + "─" * 78 + "╮ \n"
    " │ ❯ " + " " * 75 + "│ \n"
    " ╰" + "─" * 33 + " Grok 4.7 (xhigh) · always-approve ─╯ \n"
    " \n Ctrl+x:shortcuts\n"
)
PAYLOAD = "A bounded literal message"
AFTER = BEFORE.replace(" │ ❯ " + " " * 75, " │ ❯ " + PAYLOAD + " " * (75 - len(PAYLOAD)))


def test_decorated_box_exact_single_row_payload_is_observed():
    assert insertion_observed(AFTER, PAYLOAD, BEFORE)
    assert renderer_observed("grok", AFTER, PAYLOAD, BEFORE)
    assert GrokBuildAdapter().paste_source(PAYLOAD) == paste_source(PAYLOAD)


@pytest.mark.parametrize(
    "after,text,before",
    [
        (BEFORE, PAYLOAD, BEFORE),
        (AFTER.replace(PAYLOAD, PAYLOAD + "x"), PAYLOAD, BEFORE),
        (AFTER.replace("always-approve", "approval required"), PAYLOAD, BEFORE),
        (AFTER.replace("Ctrl+x:shortcuts", "Unrecognized dialog"), PAYLOAD, BEFORE),
        (AFTER.replace("\n ╰", "\n │   extra input │\n ╰"), PAYLOAD, BEFORE),
        (AFTER.replace(PAYLOAD, PAYLOAD.lower()), PAYLOAD, BEFORE),
        (AFTER, PAYLOAD, BEFORE.replace(" │ ❯ ", " │ ❯ q")),
        (AFTER, PAYLOAD + " ", BEFORE),
        (AFTER, "A\nmessage", BEFORE),
        (AFTER, "é", BEFORE),
        (AFTER, "x" * 76, BEFORE),
        (AFTER + "\x1b[2J", PAYLOAD, BEFORE),
    ],
)
def test_unknown_or_modified_single_row_paste_is_not_proof(after, text, before):
    assert not insertion_observed(after, text, before)


@pytest.mark.parametrize(
    "after,expected",
    [
        (AFTER, True),
        (BEFORE, False),
        (AFTER.replace(PAYLOAD, "another payload"), False),
        (AFTER.replace("Ctrl+x:shortcuts", "extra dialog"), False),
    ],
)
async def test_actual_generated_echo_javascript_matches_whole_widget(after, expected):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node required for isolated JavaScript echo replay")
    source = paste_source(PAYLOAD) + "process.stdout.write(JSON.stringify(observedPaste("
    source += json.dumps(BEFORE) + "," + json.dumps(after) + ")));"
    child = await asyncio.create_subprocess_exec(
        node,
        "-",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    async with asyncio.timeout(5):
        out, err = await child.communicate(source.encode())
    assert child.returncode == 0, err.decode()
    assert json.loads(out) is expected


def _wrapped(payload_rows):
    width = 78
    body = []
    for index, row in enumerate(payload_rows):
        prefix = " │ ❯ " if index == 0 else " │   "
        body.append(prefix + row + " " * (width - len(prefix) - len(row) - 2) + "│ ")
    return (
        "Earlier response\n ╭"
        + "─" * 78
        + "╮ \n"
        + "\n".join(body)
        + "\n ╰"
        + "─" * 33
        + " Grok 4.7 (xhigh) · always-approve ─╯ \n \n Ctrl+x:shortcuts\n"
    )


def test_multiline_box_payload_is_observed_only_inside_the_composer():
    text = "first\nsecond"
    after = _wrapped(["first", "second"])
    assert insertion_observed(after, text, BEFORE)
    quoted = BEFORE.replace("Earlier response", "first second")
    assert insertion_observed(quoted, text, BEFORE) is False


@pytest.mark.parametrize("text", [" trailing ", "lead ", "\x1b[31mred"])
async def test_unverifiable_decorated_box_payload_refuses_before_paste(text):
    from kirabridge.bridge_core.models import BridgeError

    with pytest.raises(BridgeError) as error:
        await GrokBuildAdapter().preflight_input(None, None, text, {"text": BEFORE})
    assert error.value.code == "visible_input_geometry_ambiguous"
    assert error.value.observation["terminal_input_attempted"] is False


async def test_exact_single_row_box_payload_passes_preflight():
    await GrokBuildAdapter().preflight_input(None, None, PAYLOAD, {"text": BEFORE})


@pytest.mark.parametrize("text", ["x" * 76, "first\nsecond", "ä message"])
async def test_longer_visible_payload_passes_preflight_when_the_box_is_empty(text):
    await GrokBuildAdapter().preflight_input(None, None, text, {"text": BEFORE})


@pytest.mark.parametrize("text", [PAYLOAD, "First line\nSecond line"])
async def test_unrecognized_box_does_not_block_existing_visible_input(text):
    # Regression after PR143: every payload was refused before paste when the
    # empty box lacked the decorated single-row form, so ordinary visible
    # handoffs stopped at the input step. The exact post-paste observation
    # remains the authority; an unread box is never itself accepted as proof.
    await GrokBuildAdapter().preflight_input(None, None, text, {"text": "╭\n│ ❯ │\n╰"})
