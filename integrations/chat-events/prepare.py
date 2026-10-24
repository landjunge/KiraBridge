"""Prepare private candidate files; NEVER activate, restart, publish or alter originals."""

import argparse
import hashlib
import json
import os
import plistlib
import shlex
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--tunnel-profile", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-callback-host", action="append", default=[])
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    python = repo / "integrations/chat-events/.venv/bin/python"
    if not python.is_file():
        raise SystemExit("First: uv sync --project integrations/chat-events --locked")
    raw = args.tunnel_profile.read_bytes()
    profile = json.loads(raw)
    commands = profile.get("mcp", {}).get("commands", [])
    main = [command for command in commands if command.get("channel") == "main"]
    if len(main) != 1 or "kirabridge" not in main[0].get("command", ""):
        raise SystemExit("Expected one existing KiraBridge main stdio command")
    root = args.output.expanduser().absolute()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    common = [
        str(python),
        str(repo / "integrations/chat-events/serve.py"),
        "--config",
        str(args.config.absolute()),
        "--principal",
        "chatgpt",
        "--state",
        str(root / "event-state"),
    ]
    for host in args.allow_callback_host:
        if "/" in host or ":" in host or not host or host != host.lower():
            raise SystemExit("Expected exact lowercase callback hostname without path/port")
        common += ["--allow-callback-host", host]
    main[0]["command"] = shlex.join([*common, "--external-sender"])
    candidate = root / "tunnel-profile.candidate.json"
    candidate.write_text(json.dumps(profile, indent=2) + "\n")
    candidate.chmod(0o600)
    plist = {
        "Label": "com.kirabridge.chat-events",
        "ProgramArguments": [*common, "--sender-only"],
        "WorkingDirectory": str(repo),
        "RunAtLoad": True,
        "KeepAlive": False,
        "StandardOutPath": str(root / "sender.stdout.log"),
        "StandardErrorPath": str(root / "sender.stderr.log"),
    }
    (root / "com.kirabridge.chat-events.candidate.plist").write_bytes(plistlib.dumps(plist))
    (root / "com.kirabridge.chat-events.candidate.plist").chmod(0o600)
    report = {
        "activated": False,
        "original_profile_unchanged": hashlib.sha256(args.tunnel_profile.read_bytes()).digest()
        == hashlib.sha256(raw).digest(),
        "original_profile_sha256": hashlib.sha256(raw).hexdigest(),
        "candidate_profile": str(candidate),
        "principal": "chatgpt",
        "callback_allowlist": args.allow_callback_host,
        "missing": [
            "ChatGPT private-plugin rescan and event subscription in original Work/Cloud chat",
            "real host-assigned callback hostname allowlist and signed challenge",
            "guarded idle activation of local sender + existing tunnel profile",
            "same-chat response after assistant turn ended; independent UI observation",
        ],
        "service_retry_policy": "No automatic crash loop; restart requires operator investigation",
        "notes": "Candidate contains existing private profile references; never commit it.",
    }
    (root / "preparation.json").write_text(json.dumps(report, indent=2) + "\n")
    (root / "preparation.json").chmod(0o600)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    os.umask(0o077)
    main()
