"""Rendering parity does not merge native fresh-echo and whole-widget authorization."""

import json
import random
import shutil
import subprocess

import pytest

from kirabridge.literal_session_input import codex_payload_forms
from kirabridge.platform_adapters.terminal_app import TerminalAppTransport


def test_python_forms_and_actual_generated_javascript_remain_identical():
    node = shutil.which("node")
    if node is None:
        pytest.skip("JavaScript runtime unavailable")
    payloads = [
        "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu",
        "head\n\nalpha beta gamma delta epsilon zeta\nlast",
        "abc " * 95 + "abcd",
        "abc " * 95 + "abc",
        "x" * 1001,
        "head\n",
        "head\n\n",
        " spaced ",
        "two  spaces",
        "one\ttab",
        "naïve café Grüßen",
        "e\u0301 combined",
        "one 😀 emoji",
        "one 漢 wide",
        "one\u00a0nonbreaking",
        "zero\u200bwidth",
        "hyphenated-word and /tmp/own/path",
        "",
    ]
    rng = random.Random(131128)
    for _ in range(50):
        payloads.append(
            "\n".join(
                " ".join(rng.choice(["abc", "abcd", "one", "Grüßen", "word."]) for _ in range(35))
                for _ in range(rng.randrange(1, 4))
            )
        )
    columns = [None, True, 19, 20, 21, 31, 130, 131, 4096, 4097]
    cases = []
    for payload in payloads:
        source = TerminalAppTransport.native_paste_observation(payload, target="codex")
        # Observe the actual local renderer result immediately before its fresh
        # echo predicate. Neither its predicate nor final Python gate is changed.
        marker = "return forms.some("
        assert source.count(marker) == 1
        source = source.replace(marker, "globalThis.renderedForms=forms; " + marker)
        cases.append(
            {
                "source": source,
                "geometries": columns,
                "expected": [codex_payload_forms(payload, width) for width in columns],
            }
        )
    script = """
const vm=require('node:vm');
const cases=CASES;
const failures=[];
for(let i=0;i<cases.length;i++){
 const item=cases[i], context={};
 vm.runInNewContext(item.source,context);
 for(let j=0;j<item.geometries.length;j++){
  context.observedPaste('› ','› current',item.geometries[j]);
  if(JSON.stringify(context.renderedForms)!==JSON.stringify(item.expected[j]))
   failures.push([i,j]);
 }
}
process.stdout.write(JSON.stringify({failures,vectors:cases.length*cases[0].geometries.length}));
""".replace("CASES", json.dumps(cases))
    result = subprocess.run(
        [node, "-"], input=script, capture_output=True, text=True, timeout=10, check=True
    )
    assert json.loads(result.stdout) == {"failures": [], "vectors": 680}
