"""Artificial package files only; OS-layout fixtures are not native CLI tests."""

import asyncio
import hashlib
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from kirabridge import doctor_view
from kirabridge.agent_manager import codex_package as package
from kirabridge.bridge_core.config import AgentConfig


def native_file(path, platform):
    path.parent.mkdir(parents=True, exist_ok=True)
    if platform == "win32":
        header = b"MZ" + bytes(58) + (64).to_bytes(4, "little") + b"PE\0\0"
    else:
        header = (b"\x7fELF" if platform == "linux" else b"\xcf\xfa\xed\xfe") + bytes(60)
    path.write_bytes(header)
    path.chmod(0o700)
    return path


def fixture_package(tmp_path, platform="linux", target=None):
    target = target or sorted(package.TARGETS[platform])[0]
    root = tmp_path / "package"
    suffix = ".exe" if platform == "win32" else ""
    exe = native_file(root / f"bin/codex{suffix}", platform)
    for relative in (
        f"bin/codex-code-mode-host{suffix}",
        f"bin/codex-exec-server{suffix}",
        f"codex-path/rg{suffix}",
    ):
        native_file(root / relative, platform)
    (root / "codex-resources").mkdir()
    if platform == "linux":
        native_file(root / "codex-resources/bwrap", platform)
    if platform == "win32":
        for name in ("codex-command-runner.exe", "codex-windows-sandbox-setup.exe"):
            native_file(root / "codex-resources" / name, platform)
    metadata = {
        "layoutVersion": 1,
        "version": "0.169.0",
        "target": target,
        "variant": "codex",
        "entrypoint": f"bin/codex{suffix}",
        "execServer": f"bin/codex-exec-server{suffix}",
        "resourcesDir": "codex-resources",
        "pathDir": "codex-path",
    }
    (root / "codex-package.json").write_text(json.dumps(metadata))
    return root, exe, metadata


def write_metadata(root, value):
    (root / "codex-package.json").write_text(json.dumps(value))


def unverified(result):
    assert result["non_blocking"] is True
    assert result["cli_version_status"] == "not_probed"
    assert result["companion_version_binding"] == "unverified"
    assert result["publisher_integrity"] == "unverified"
    assert result["abi_compatibility"] == "unverified"
    assert result["full_distribution_integrity"] == "unverified"
    assert result["tool_execution"] == "not_probed"


@pytest.mark.parametrize(
    "platform,target", [(p, t) for p, ts in package.TARGETS.items() for t in ts]
)
def test_all_documented_target_layout_fixtures_remain_presence_only(tmp_path, platform, target):
    root, exe, _ = fixture_package(tmp_path, platform, target)
    before = {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()
    }
    result = package.inspect_codex_package(str(exe), platform=platform)
    assert result["status"] == "layout_observed"
    assert result["declared_package_version"] == "0.169.0"
    assert result["target"] == target and result["layout"] == "package_bin"
    assert all(row["state"] == "present" for row in result["components"].values())
    unverified(result)
    assert before == {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()
    }
    assert str(root) not in json.dumps(result)


@pytest.mark.parametrize(
    "role,relative",
    [
        ("code_mode_host", "bin/codex-code-mode-host"),
        ("exec_server", "bin/codex-exec-server"),
        ("search_tool", "codex-path/rg"),
        ("linux_sandbox_resource", "codex-resources/bwrap"),
    ],
)
def test_known_manifest_missing_reference_file_is_visible_not_a_gate(tmp_path, role, relative):
    root, exe, _ = fixture_package(tmp_path)
    (root / relative).unlink()
    result = package.inspect_codex_package(str(exe), platform="linux")
    assert result["status"] == "layout_incomplete"
    assert result["components"][role]["state"] == "missing"
    unverified(result)


def test_resource_host_precedes_bin_even_when_not_executable(tmp_path):
    root, exe, _ = fixture_package(tmp_path)
    resource = native_file(root / "codex-resources/codex-code-mode-host", "linux")
    resource.chmod(0o600)
    result = package.inspect_codex_package(str(exe), platform="linux")
    assert result["status"] == "layout_incomplete"
    assert result["components"]["code_mode_host"] == {
        "relative_path": "codex-resources/codex-code-mode-host",
        "state": "not_executable",
    }


def test_resource_host_can_supply_missing_bin_host(tmp_path):
    root, exe, _ = fixture_package(tmp_path)
    (root / "bin/codex-code-mode-host").unlink()
    native_file(root / "codex-resources/codex-code-mode-host", "linux")
    result = package.inspect_codex_package(str(exe), platform="linux")
    assert result["status"] == "layout_observed"
    assert result["components"]["code_mode_host"]["relative_path"].startswith("codex-resources/")


def test_launcher_symlink_is_resolved_without_executing_it(tmp_path):
    _, exe, _ = fixture_package(tmp_path)
    link = tmp_path / "ordinary-name"
    link.symlink_to(exe)
    result = package.inspect_codex_package(str(link), platform="linux")
    assert result["status"] == "layout_observed"


def test_macos_provisioned_bundle_uses_actual_bound_entrypoint(tmp_path):
    root, exe, _ = fixture_package(tmp_path, "darwin")
    app = native_file(root / "CodexCLI.app/Contents/MacOS/codex", "darwin")
    exe.unlink()
    exe.symlink_to(app)
    result = package.inspect_codex_package(str(exe), platform="darwin")
    assert result["status"] == "layout_observed" and result["layout"] == "macos_provisioned"


@pytest.mark.parametrize("target", sorted(package.TARGETS["win32"]))
def test_documented_winget_root_layout(tmp_path, target):
    root, exe, metadata = fixture_package(tmp_path, "win32", target)
    entrypoint = root / f"codex-{target}.exe"
    exe.rename(entrypoint)
    (root / "bin/codex-code-mode-host.exe").rename(root / "codex-code-mode-host.exe")
    metadata["entrypoint"] = entrypoint.name
    write_metadata(root, metadata)
    result = package.inspect_codex_package(str(entrypoint), platform="win32")
    assert result["status"] == "layout_observed" and result["layout"] == "winget_root"
    assert result["components"]["code_mode_host"]["relative_path"] == "./codex-code-mode-host.exe"
    unverified(result)


@pytest.mark.parametrize("name", ["codex", "codex.exe", "codex-kirabridge", "anything"])
def test_script_launchers_stay_unknown_independently_of_filename(tmp_path, name):
    script = tmp_path / name
    script.write_text('#!/bin/sh\nexec /private/unobserved/codex "$@"\n')
    script.chmod(0o700)
    result = package.inspect_codex_package(str(script), platform="linux")
    assert result["status"] == "unknown" and result["reason"] == "launcher_target_not_observed"
    assert "components" not in result and "/private/unobserved" not in json.dumps(result)


@pytest.mark.parametrize("version", ["0.167.0", "0.170.0", "0.169.0-beta.1", "secret-version"])
def test_uncovered_versions_do_not_inherit_169_requirements(tmp_path, monkeypatch, version):
    root, exe, metadata = fixture_package(tmp_path)
    metadata["version"] = version
    write_metadata(root, metadata)
    monkeypatch.setattr(package, "_component", lambda *a, **k: pytest.fail("No 0.169 rules"))
    result = package.inspect_codex_package(str(exe), platform="linux")
    assert result["status"] == "unknown" and result["reason"] == "package_version_not_covered"
    assert "components" not in result and "secret-version" not in json.dumps(result)


@pytest.mark.parametrize(
    "changes",
    [
        {"layoutVersion": True},
        {"layoutVersion": 2},
        {"variant": "codex-app-server"},
        {"target": []},
        {"target": "x86_64-apple-darwin"},
        {"entrypoint": "../../secret"},
        {"execServer": "/outside/secret"},
        {"resourcesDir": "../secret"},
        {"pathDir": "unknown"},
    ],
)
def test_uncovered_metadata_does_not_infer_components(tmp_path, changes):
    root, exe, metadata = fixture_package(tmp_path)
    write_metadata(root, {**metadata, **changes})
    result = package.inspect_codex_package(str(exe), platform="linux")
    assert result["status"] == "unknown" and "components" not in result


@pytest.mark.parametrize(
    "payload",
    [
        b"[1,2]",
        b"{",
        b" " * (package.METADATA_LIMIT + 1),
        b'{"version":"0.169.0","version":"0.167.0"}',
    ],
)
def test_metadata_parse_and_byte_bounds_are_scoped_unknown(tmp_path, payload):
    root, exe, _ = fixture_package(tmp_path)
    (root / "codex-package.json").write_bytes(payload)
    result = package.inspect_codex_package(str(exe), platform="linux")
    assert result["status"] == "unknown" and "components" not in result


def test_missing_manifest_does_not_mean_legacy_cli_cannot_run(tmp_path):
    root, exe, _ = fixture_package(tmp_path)
    (root / "codex-package.json").unlink()
    result = package.inspect_codex_package(str(exe), platform="linux")
    assert result["status"] == "unknown" and result["non_blocking"]


def test_external_component_symlink_does_not_probe_or_claim_other_package(tmp_path):
    root, exe, _ = fixture_package(tmp_path)
    outside = native_file(tmp_path / "private-other-package/host", "linux")
    (root / "bin/codex-code-mode-host").unlink()
    (root / "bin/codex-code-mode-host").symlink_to(outside)
    result = package.inspect_codex_package(str(exe), platform="linux")
    assert result["status"] == "unknown"
    assert result["components"]["code_mode_host"]["state"] == "unknown"
    assert str(outside) not in json.dumps(result)


def test_external_metadata_symlink_is_unknown(tmp_path):
    root, exe, metadata = fixture_package(tmp_path)
    outside = tmp_path / "private-metadata"
    outside.write_text(json.dumps(metadata))
    (root / "codex-package.json").unlink()
    (root / "codex-package.json").symlink_to(outside)
    assert package.inspect_codex_package(str(exe), platform="linux")["status"] == "unknown"


@pytest.mark.parametrize(
    "role,relative",
    [
        ("code_mode_host", "bin/codex-code-mode-host"),
        ("exec_server", "bin/codex-exec-server"),
        ("search_tool", "codex-path/rg"),
        ("linux_sandbox_resource", "codex-resources/bwrap"),
    ],
)
def test_external_dangling_component_is_unknown_not_missing(tmp_path, role, relative):
    root, exe, _ = fixture_package(tmp_path)
    component = root / relative
    component.unlink()
    component.symlink_to(tmp_path / "unobserved-package/absent")
    result = package.inspect_codex_package(str(exe), platform="linux")
    assert result["status"] == "unknown"
    assert result["components"][role]["state"] == "unknown"
    assert "unobserved-package" not in json.dumps(result)


def test_external_dangling_resource_host_does_not_infer_bin_fallback(tmp_path):
    root, exe, _ = fixture_package(tmp_path)
    resource = root / "codex-resources/codex-code-mode-host"
    resource.symlink_to(tmp_path / "unobserved-package/absent")
    result = package.inspect_codex_package(str(exe), platform="linux")
    assert result["status"] == "unknown"
    assert result["components"]["code_mode_host"] == {
        "relative_path": "codex-resources/codex-code-mode-host",
        "state": "unknown",
    }


def test_internal_dangling_component_remains_missing(tmp_path):
    root, exe, _ = fixture_package(tmp_path)
    component = root / "bin/codex-code-mode-host"
    component.unlink()
    component.symlink_to(root / "codex-resources/absent")
    result = package.inspect_codex_package(str(exe), platform="linux")
    assert result["status"] == "layout_incomplete"
    assert result["components"]["code_mode_host"]["state"] == "missing"


def test_component_symlink_cycle_stays_unknown(tmp_path):
    root, exe, _ = fixture_package(tmp_path)
    component = root / "bin/codex-code-mode-host"
    component.unlink()
    component.symlink_to(component)
    result = package.inspect_codex_package(str(exe), platform="linux")
    assert result["status"] == "unknown"
    assert result["components"]["code_mode_host"]["state"] == "unknown"


@pytest.mark.parametrize("denied_strict", [False, True])
def test_component_resolution_access_denial_stays_unknown(tmp_path, monkeypatch, denied_strict):
    root, exe, _ = fixture_package(tmp_path)
    component = root / "bin/codex-code-mode-host"
    original = Path.resolve

    def resolve(path, strict=False):
        if path == component and strict == denied_strict:
            raise PermissionError("PRIVATE_DENIAL_MUST_NOT_ESCAPE")
        return original(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", resolve)
    result = package.inspect_codex_package(str(exe), platform="linux")
    assert result["status"] == "unknown"
    assert result["components"]["code_mode_host"]["state"] == "unknown"
    assert "PRIVATE_DENIAL_MUST_NOT_ESCAPE" not in json.dumps(result)


def test_strict_resolution_still_checks_containment_after_link_change(tmp_path, monkeypatch):
    root, exe, _ = fixture_package(tmp_path)
    component = root / "bin/codex-code-mode-host"
    outside = native_file(tmp_path / "other-package/host", "linux")
    original = Path.resolve
    changed = False

    def resolve(path, strict=False):
        nonlocal changed
        if path == component and strict and not changed:
            component.unlink()
            component.symlink_to(outside)
            changed = True
        return original(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", resolve)
    result = package.inspect_codex_package(str(exe), platform="linux")
    assert changed
    assert result["status"] == "unknown"
    assert result["components"]["code_mode_host"]["state"] == "unknown"


def test_broken_and_cyclic_launcher_links_are_unknown(tmp_path):
    broken = tmp_path / "broken"
    broken.symlink_to(tmp_path / "absent")
    cycle = tmp_path / "cycle"
    cycle.symlink_to(cycle)
    for p in (broken, cycle):
        assert package.inspect_codex_package(str(p), platform="linux")["status"] == "unknown"


def test_manifest_directory_cannot_be_read_as_file(tmp_path):
    root, exe, _ = fixture_package(tmp_path)
    (root / "codex-package.json").unlink()
    (root / "codex-package.json").mkdir()
    assert package.inspect_codex_package(str(exe), platform="linux")["status"] == "unknown"


def test_passive_observation_never_spawns_or_walks_directories(tmp_path, monkeypatch):
    root, exe, metadata = fixture_package(tmp_path)
    metadata["unrelated"] = "PRIVATE_CONTENT_MUST_NOT_ESCAPE"
    write_metadata(root, metadata)

    def forbidden(*args, **kwargs):
        pytest.fail("No CLI process, shell, recursive traversal or unrelated file probe")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
    monkeypatch.setattr(os, "system", forbidden)
    monkeypatch.setattr(Path, "rglob", forbidden)
    monkeypatch.setattr(Path, "iterdir", forbidden)
    result = package.inspect_codex_package(str(exe), platform="linux")
    assert result["status"] == "layout_observed"
    assert "PRIVATE_CONTENT_MUST_NOT_ESCAPE" not in json.dumps(result)


def test_inventory_retains_runnable_wrapper_and_never_executes_it(bridge, config, tmp_path):
    script = tmp_path / "wrapper"
    marker = tmp_path / "unexpected-execution"
    script.write_text(f"#!/bin/sh\ntouch '{marker}'\n")
    script.chmod(0o700)
    config.agents["codex"] = AgentConfig(kind="codex", executable=str(script))
    result = bridge.agents.inventory(["codex"])["agents"][0]
    assert result["executable_present"] and result["executable_runnable"]
    assert result["runtime_package"]["status"] == "unknown" and not marker.exists()


def test_inventory_observes_only_allowed_codex_identities(bridge, config, monkeypatch):
    config.agents["visible"] = AgentConfig(kind="codex", executable="/visible/codex")
    config.agents["private"] = AgentConfig(kind="codex", executable="/private/secret")
    from kirabridge import agent_manager

    calls = []

    def observe(path):
        calls.append(path)
        return {"status": "unknown", "non_blocking": True}

    monkeypatch.setattr(agent_manager, "inspect_codex_package", observe)
    result = bridge.agents.inventory(["visible"])
    assert [row["id"] for row in result["agents"]] == ["visible"]
    assert calls == ["/visible/codex"] and "/private/secret" not in json.dumps(result)


@pytest.mark.parametrize(
    "state,expected",
    [("layout_observed", "info"), ("unknown", "info"), ("layout_incomplete", "warn")],
)
def test_doctor_separates_executable_and_package_observation(state, expected):
    config = SimpleNamespace(agents={"codex": SimpleNamespace(kind="codex", executable="/codex")})
    result = doctor_view.agents_section(
        config,
        {
            "agents": [
                {
                    "id": "codex",
                    "executable_present": True,
                    "executable_runnable": True,
                    "runtime_package": {
                        "status": state,
                        "components": {"code_mode_host": {"state": "missing"}},
                    },
                }
            ]
        },
    )
    assert result["items"][0]["status"] == "ok"
    assert result["items"][1]["status"] == expected
    assert "Paketdateien" in result["items"][1]["label"]
    assert all(item["status"] != "fail" for item in result["items"])
