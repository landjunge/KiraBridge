#!/usr/bin/env python3
"""Install an independent pinned launcher/skill; never restart or edit live agents."""

import hashlib
import json
import os
from pathlib import Path


def create_or_verify(path, content, mode=0o600):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode)
    except FileExistsError:
        if path.read_text() != content:
            raise RuntimeError(f"Existing file differs; preserve it: {path}") from None
    else:
        with os.fdopen(fd, "w") as stream:
            stream.write(content)


def main():
    source = Path(__file__).resolve().parents[1]
    home = Path.home()
    payload = sorted((source / "src/kirabridge/capability_routing").glob("*.py"))
    payload += sorted((source / "skills/cli-model-router").rglob("*.md"))
    payload += sorted((source / "skills/cli-model-router").rglob("*.yaml"))
    payload += [source / "docs/cli-routing/RESEARCH.md", source / "docs/cli-routing/matrix.json"]
    hashes = {
        str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest() for p in payload
    }
    pin = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()[:16]
    root = home / ".local/share/bigplan-cli-routing"
    release = root / "releases" / pin
    for path in payload:
        target = release / path.relative_to(source)
        create_or_verify(target, path.read_text())
    create_or_verify(
        release / "src/kirabridge/__init__.py", '"""Isolated Big Plan routing package."""\n'
    )
    runtime = home / ".config/bigplan-cli-routing/runtime.json"
    create_or_verify(runtime, (source / "docs/cli-routing/runtime.local.json").read_text())
    current = root / "current"
    previous_release = current.resolve() if current.exists() else None
    if current.exists() or current.is_symlink():
        if current.resolve() != release:
            previous = json.loads((current / "installation.json").read_text())
            if previous["source"] != str(source):
                raise RuntimeError("Current installation belongs to another workspace")
            for name, sha in previous["sha256"].items():
                if hashlib.sha256((current / name).read_bytes()).hexdigest() != sha:
                    raise RuntimeError("Previous release modified; preserve it for reconciliation")
            pending = root / ("current-" + pin)
            pending.symlink_to(release, target_is_directory=True)
            pending.replace(current)
    else:
        current.symlink_to(release, target_is_directory=True)
    python = home / "KiraBridge/.venv/bin/python"
    td_src = home / ".local/share/kirabridge/install/shared/threaddesk-aa940db/src"
    if not python.is_file() or not td_src.is_dir():
        raise RuntimeError("Verified local Python/ThreadDesk dependency is unavailable")
    import shlex

    command = (
        "#!/bin/sh\n"
        f"export PYTHONPATH={shlex.quote(str(current / 'src') + os.pathsep + str(td_src))}\n"
        f"exec {shlex.quote(str(python))} -m kirabridge.capability_routing "
        f"--workspace {shlex.quote(str(home / '.local/share/threaddesk/kirabridge-operator'))} "
        "--matrix-thread c9a396be4081 "
        f'--runtime {shlex.quote(str(runtime))} "$@"\n'
    )
    create_or_verify(home / ".local/bin/bigplan-delegate", command, 0o700)
    skill = home / ".codex/skills/cli-model-router"
    for path in (source / "skills/cli-model-router").rglob("*"):
        if path.is_file():
            text = path.read_text().replace(
                "../../docs/cli-routing/RESEARCH.md", str(current / "docs/cli-routing/RESEARCH.md")
            )
            relative = path.relative_to(source / "skills/cli-model-router")
            target = skill / relative
            if target.exists() and target.read_text() != text and previous_release:
                old = previous_release / "skills/cli-model-router" / relative
                expected = old.read_text().replace(
                    "../../docs/cli-routing/RESEARCH.md",
                    str(current / "docs/cli-routing/RESEARCH.md"),
                )
                if target.read_text() != expected:
                    raise RuntimeError("Installed skill changed elsewhere; preserve it")
                pending_skill = target.with_suffix(target.suffix + ".pending")
                create_or_verify(pending_skill, text)
                pending_skill.replace(target)
            else:
                create_or_verify(target, text)
    grok = home / ".grok/skills/cli-model-router/SKILL.md"
    create_or_verify(
        grok,
        "---\nname: cli-model-router\ndescription: "
        "Big-Plan-Delegation mit aktueller ThreadDesk-Matrix und "
        "echter CLI-/Modell-/Denkstufenwahl.\n"
        "---\n\nLies den gemeinsamen Skill vor einer neuen KI-Delegation: "
        f"[{skill / 'SKILL.md'}]({skill / 'SKILL.md'}).\n"
        "Nutze den automatischen Hook über `~/.local/bin/bigplan-delegate --task TASK.json`; "
        "`--execute` startet genau einen neuen eigenen Lauf. Keine fremden Sitzungen ändern.\n",
    )
    receipt = {
        "schema": "bigplan.cli-router-install.v1",
        "payload_pin": pin,
        "release": str(release),
        "source": str(source),
        "sha256": hashes,
        "launcher": str(home / ".local/bin/bigplan-delegate"),
        "native_global_hooks_modified": False,
        "services_restarted": False,
    }
    create_or_verify(release / "installation.json", json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
