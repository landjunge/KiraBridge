"""Pure conservative empty-shell predicate shared by transport and coordination."""

import re


def empty_shell_prompt(text):
    # Only known prompt shapes are supported. A busy/unknown/input-filled prompt
    # is not an invitation to press Return or clear somebody else's input.
    if re.search(r"[\x00-\x08\x0b-\x1f\x7f]", text):
        return False
    line = text.rstrip("\n").split("\n")[-1].rstrip("\r")
    controlled = "KiraBridge visible % "
    if controlled in line:
        # A copied marker inside existing input is not the controlled prompt.
        return line == controlled
    # Oh My Zsh's plain robbyrussell prompt, as rendered by Terminal.app. Keep
    # the exact spacing: stripping whitespace would conceal pending input. Paths
    # containing whitespace remain unsupported/ambiguous.
    if line.lstrip(" \t").startswith("➜"):
        # Route the whole known family here, including malformed variants. Never
        # reclassify typed '$', '#', '%' as a different empty prompt below.
        return bool(
            re.fullmatch(
                r"➜  [^\s\x7f-\x9f]{1,240} "
                r"(?:git:\([A-Za-z0-9_./-]{1,240}\) (?:✗ )?)?",
                line,
            )
        )
    return bool(re.fullmatch(r"[^\n%$#]{1,240}[%$#] ", line))
