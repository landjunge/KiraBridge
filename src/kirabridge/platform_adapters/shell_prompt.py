"""Pure conservative empty-shell predicate shared by transport and coordination."""

import re


def idle_shell(row):
    processes = row.get("processes", [])
    return (
        row.get("transport") == "terminal_app"
        and row.get("busy") is False
        and len(processes) == 1
        and processes[0].get("pid") == row.get("expected_pid")
        and processes[0]["name"].lstrip("-") in {"zsh", "bash", "sh"}
    )


def empty_shell_prompt(text):
    # Only the ordinary zsh/bash prompt is supported. A busy/unknown/input-filled
    # prompt is not an invitation to press Return or clear somebody else's input.
    if re.search(r"[\x00-\x08\x0b-\x1f\x7f]", text):
        return False
    line = text.rstrip("\n").split("\n")[-1].rstrip("\r")
    if line.endswith("KiraBridge visible % "):
        return True
    return bool(re.fullmatch(r"[^\n%$#]{1,240}[%$#] ", line))
