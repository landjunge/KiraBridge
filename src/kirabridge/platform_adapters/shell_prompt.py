"""Pure conservative empty-shell predicate shared by transport and coordination."""

import re

_CONTROLLED = "KiraBridge visible % "
_ARROW = (
    r"➜  [^\s\x7f-\x9f]{1,240} "
    r"(?:git:\([A-Za-z0-9_./-]{1,240}\) (?:✗ )?)?"
)


def _prompt_sp_prefix(prefix):
    """Zsh's PROMPT_SP end marker and padding keep a prompt on one reported row.

    When a command leaves its last output line without a newline, zsh prints
    its end-of-line marker (``%``, or ``#`` for root) and enough padding to
    fill the row before the real prompt. Terminal.app records that padding and
    prompt on the same line as the unfinished output. Only that exact marker
    plus at least two padding cells may precede an embedded prompt; ordinary
    output and typed input never do.
    """
    return bool(re.fullmatch(r".*[%#][ \t]{2,}", prefix, re.DOTALL))


def empty_shell_prompt(text):
    # Only known prompt shapes are supported. A busy/unknown/input-filled prompt
    # is not an invitation to press Return or clear somebody else's input.
    if re.search(r"[\x00-\x08\x0b-\x1f\x7f]", text):
        return False
    line = text.rstrip("\n").split("\n")[-1].rstrip("\r")
    controlled = line.find(_CONTROLLED)
    if controlled >= 0:
        # The first marker is the current prompt. A copied marker later in a
        # typed line must not be treated as a second prompt.
        prefix = line[:controlled]
        return (not prefix or _prompt_sp_prefix(prefix)) and line[controlled:] == _CONTROLLED
    # Oh My Zsh's plain robbyrussell prompt, as rendered by Terminal.app. Keep
    # the exact spacing: stripping whitespace would conceal pending input. Paths
    # containing whitespace remain unsupported/ambiguous.
    arrow = line.find("➜")
    if arrow >= 0:
        # Route the whole known family here, including malformed variants. Never
        # reclassify typed '$', '#', '%' as a different empty prompt below.
        prefix = line[:arrow]
        if prefix and not _prompt_sp_prefix(prefix):
            return False
        return bool(re.fullmatch(_ARROW, line[arrow:]))
    return bool(re.fullmatch(r"[^\n%$#]{1,240}[%$#] ", line))
