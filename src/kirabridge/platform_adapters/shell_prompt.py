"""Pure conservative empty-shell predicate shared by transport and coordination."""

import re


def empty_shell_prompt(text):
    # Only the ordinary zsh/bash prompt is supported. A busy/unknown/input-filled
    # prompt is not an invitation to press Return or clear somebody else's input.
    if re.search(r"[\x00-\x08\x0b-\x1f\x7f]", text):
        return False
    line = text.rstrip("\n").split("\n")[-1].rstrip("\r")
    if line.endswith("KiraBridge visible % "):
        return True
    return bool(re.fullmatch(r"[^\n%$#]{1,240}[%$#] ", line))
