"""Worker permission truth, process scope and least-needed operator guidance."""

import ctypes
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from kirabridge.platform_adapters.macos import permissions
from kirabridge.platform_adapters.macos.keyboard_permissions import (
    SETTINGS_URLS,
    permission_guidance,
)


def native(**values):
    return {
        "actor_pid": 123,
        "native_helper": {"pid": 123, "executable": "/exact/KiraBridge", "generation": "worker-1"},
        "accessibility_granted": True,
        "post_events_granted": True,
        **values,
    }


def test_optional_monitoring_recording_and_automation_do_not_block_keyboard():
    result = permission_guidance(
        native(input_monitoring_granted=False, screen_capture_granted=False)
    )
    assert result["keyboard_ready"] is True
    assert [r["resource"] for r in result["checks"] if r["required_for_keyboard"]] == [
        "accessibility",
        "post_events",
    ]
    assert not result["permission_requested"] and not result["input_attempted"]


@pytest.mark.parametrize("field", ["accessibility_granted", "post_events_granted"])
def test_missing_required_permission_is_reported_without_fabricated_denial_reason(field):
    result = permission_guidance(native(**{field: False}))
    assert result["keyboard_ready"] is False
    failed = next(
        row for row in result["checks"] if row["resource"] == field.removesuffix("_granted")
    )
    assert failed["state"] == "not_granted"
    assert failed["settings_url"] == SETTINGS_URLS["accessibility"]
    assert "Bedienungshilfen" in failed["manual_steps"]


@pytest.mark.parametrize("value", [None, "true", 1, [], {}])
def test_unsupported_post_preflight_stays_unknown(value):
    assert permission_guidance(native(post_events_granted=value))["keyboard_ready"] is None


def test_core_and_finished_helper_grants_cannot_satisfy_worker_requirements():
    platform = {
        "permissions": [
            {
                "actor": "core",
                "resource": "accessibility",
                "state": "granted",
                "identity": {"pid": 55},
            }
        ],
        "helper_diagnostics": {
            "identity": {"pid": 77},
            "permissions": [
                {"resource": "automation", "target": "com.apple.Terminal", "state": "granted"}
            ],
        },
    }
    result = permission_guidance(None, platform)
    assert result["keyboard_ready"] is None
    assert [r["actor"] for r in result["other_actors"]] == ["core", "completed_helper"]
    assert all(r["identity"] == {} for r in result["checks"])
    result["other_actors"][0]["identity"]["pid"] = 999
    assert platform["permissions"][0]["identity"]["pid"] == 55


def test_missing_or_mismatched_actor_identity_never_appears_ready():
    assert (
        permission_guidance({"accessibility_granted": True, "post_events_granted": True})[
            "keyboard_ready"
        ]
        is None
    )
    assert permission_guidance(native(actor_pid=124))["keyboard_ready"] is None


def test_settings_links_are_fixed_and_input_is_not_mutated():
    observed = native(
        native_helper={
            "pid": 123,
            "executable": "/exact/KiraBridge",
            "untrusted_url": "javascript:bad()",
        }
    )
    before = json.dumps(observed, sort_keys=True)
    result = permission_guidance(observed)
    assert json.dumps(observed, sort_keys=True) == before
    assert all(r["settings_url"] in SETTINGS_URLS.values() for r in result["checks"])
    assert "untrusted_url" not in result["checks"][0]["identity"]


@pytest.mark.parametrize(
    "resource,symbol",
    [
        ("post_events", "CGPreflightPostEventAccess"),
        ("input_monitoring", "CGPreflightListenEventAccess"),
    ],
)
def test_core_event_checks_use_only_current_process_public_preflight(monkeypatch, resource, symbol):
    seen = []

    def check():
        seen.append(symbol)
        return False

    library = SimpleNamespace(**{symbol: check})
    monkeypatch.setattr(permissions.sys, "platform", "darwin")
    monkeypatch.setattr(ctypes, "CDLL", lambda path: library)
    result = permissions.core_permission(resource)
    assert result == {"state": "unknown", "raw_granted": False, "method": symbol}
    assert seen == [symbol]
    assert check.argtypes == [] and check.restype == ctypes.c_bool


def test_core_default_status_checks_both_event_permissions_without_grant_transfer():
    seen = []

    def reader(resource):
        seen.append(resource)
        return {"state": "granted"}

    probe = permissions.PermissionProbe(reader=reader)
    result = probe.refresh_core()
    assert set(seen) == {"accessibility", "screen_capture", "post_events", "input_monitoring"}
    assert all(r["actor"] == "core" for r in result)


@pytest.mark.skipif(shutil.which("node") is None, reason="Node required for isolated UI rendering")
def test_empty_policy_exceptions_still_render_os_guidance_and_only_needed_links(tmp_path):
    script = Path(__file__).parents[1] / "src/kirabridge/console_assets/center.js"
    harness = r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const registry=new Map();
class Element{
 constructor(tag){this.tag=tag;this.children=[];this.hidden=false;}
 set id(value){this._id=value;registry.set(value,this);}get id(){return this._id;}
 append(...items){this.children.push(...items);}replaceChildren(...items){this.children=items;}
 setAttribute(){}addEventListener(){}
}
const host=new Element('section'),exceptions=new Element('div');
exceptions.id='permission-exceptions';exceptions.parentElement=host;
const context={document:{getElementById:id=>registry.get(id),
createElement:tag=>new Element(tag)},console};
vm.createContext(context);let source=fs.readFileSync(process.argv[1],'utf8');
source=source.slice(0,source.indexOf('function renderConnections'));
vm.runInContext(source,context);
context.fixture=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
vm.runInContext('renderPermissionExceptions({permission_details:{},keyboard_permissions:fixture})',context);
const area=registry.get('macos-keyboard-permissions');assert.equal(area.hidden,false);
// Periodic service status has no worker permission payload. It must not erase
// the separately completed, explicit OS permission diagnostic and its links.
vm.runInContext('renderPermissionExceptions({permission_details:{}})',context);
assert.equal(registry.get('macos-keyboard-permissions'),area);
assert.equal(area.hidden,false);
const all=[];function visit(n){all.push(n);for(const c of n.children||[])visit(c);}visit(area);
const links=all.filter(n=>n.tag==='a');assert.equal(links.length,1);
assert.equal(links[0].href,'x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility');
assert.ok(all.some(n=>String(n.textContent).includes('Für Tastatureingaben nicht erforderlich')));
assert.equal(exceptions.textContent,'Keine dauerhaften Ausnahmen.');
"""
    fixture = tmp_path / "guidance.json"
    fixture.write_text(json.dumps(permission_guidance(native(post_events_granted=False))))
    subprocess.run(["node", "-e", harness, str(script), str(fixture)], check=True, timeout=10)
