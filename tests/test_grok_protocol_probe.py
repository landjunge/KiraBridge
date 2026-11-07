import runpy
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("silent", [False, True])
async def test_probe_is_only_initialize_and_fails_bounded_without_secrets(
    tmp_path, monkeypatch, silent
):
    probe = runpy.run_path(str(Path(__file__).parents[1] / "scripts/probe_grok_acp.py"))["probe"]
    executable = tmp_path / "fake-grok"
    executable.write_text(
        f"#!{sys.executable}\n"
        + """import json,sys,os,time
request=json.loads(sys.stdin.readline())
assert request['method']=='initialize'
assert not any('TOKEN' in key or 'KEY' in key for key in os.environ)
"""
        + (
            "time.sleep(60)\n"
            if silent
            else """
print(json.dumps({'jsonrpc':'2.0','id':1,'result':{'protocolVersion':1,'authMethods':[{'id':'cached_token'},{'id':'PRIVATE_MUST_NOT_ESCAPE'}]}}),flush=True)
time.sleep(60)
"""
        )
    )
    executable.chmod(0o700)
    monkeypatch.setenv("PRIVATE_TEST_TOKEN", "not inherited")
    result = await probe(str(executable), timeout=0.1 if silent else 2)
    assert result["ok"] is not silent
    if not silent:
        assert not result["model_prompt_sent"] and not result["authentication_tested"]
        assert result["auth_methods_declared"] == ["cached_token"]
    assert "PRIVATE_MUST_NOT_ESCAPE" not in str(result)
