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


@pytest.mark.parametrize("text", ["x" * 76, "first\nsecond", "ä message", " trailing "])
async def test_unverifiable_decorated_box_payload_refuses_before_paste(text):
    from kirabridge.bridge_core.models import BridgeError

    with pytest.raises(BridgeError) as error:
        await GrokBuildAdapter().preflight_input(None, None, text, {"text": BEFORE})
    assert error.value.code == "visible_input_geometry_ambiguous"
    assert error.value.observation["terminal_input_attempted"] is False


async def test_exact_single_row_box_payload_passes_preflight():
    await GrokBuildAdapter().preflight_input(None, None, PAYLOAD, {"text": BEFORE})
