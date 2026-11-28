"""Claude Code's visible composer between two horizontal rules; literal text only.

Claude wraps long input over continuation rows, so insertion is compared without
whitespace. A collapsed paste ("[Pasted text #1 +k lines]") counts as the text only
when the field was empty before and k matches the text's line count: no Return otherwise.
No slash, menu, navigation or reply capability is claimed.
"""

import json
import re

from . import _legacy_readiness as legacy
from .contract import Capabilities

_RULE = re.compile(r"[ \t]*─{3,}(?: [^─\n]{1,120} ─+)?[ \t]*")
_PROMPT = "❯"
_LIVE_SPINNER = re.compile(r"^[ \t]*[✻✽✶✳✢·*] \S+… \(", re.M)
_OUTPUT = "⏺"


def live_block(above):
    """Rows between the last output block and the input separator.

    A todo list (``⎿ ☐ …``), queued messages or hints may sit between the spinner and
    the input, so the whole block counts, not only the two nearest rows.
    """
    for index in range(len(above) - 1, -1, -1):
        if above[index].lstrip().startswith(_OUTPUT):
            return above[index + 1 :]
    return above[-30:]


def _compact(text):
    return re.sub(r"\s+", "", text)


_FOLDED = re.compile(r"\[Pastedtext#\d+(?:\+(\d+)lines?)?\]")


def _folded_counts(text):
    """Line counts Claude Code may show in "[Pasted text #N +k lines]" for this text."""
    counts = set()
    for variant in (text, text.rstrip("\r\n")):
        newlines = len(re.findall(r"\r\n|\r|\n", variant))
        counts.update({newlines, newlines + 1} if newlines else {0})
    return counts


def folded_paste(field, text):
    """The whole input field is exactly one folded-paste marker for this text."""
    match = _FOLDED.fullmatch(_compact(field))
    return bool(match) and int(match.group(1) or 0) in _folded_counts(text)


def composer(text):
    """(status rows above, input rows, footer rows) of the LAST composer, or None."""
    lines = text.split("\n")
    for index in range(len(lines) - 1, 0, -1):
        if lines[index].lstrip().startswith(_PROMPT) and _RULE.fullmatch(lines[index - 1]):
            for end in range(index + 1, len(lines)):
                if _RULE.fullmatch(lines[end]):
                    return lines[: index - 1], lines[index:end], lines[end + 1 :]
            return None
    return None


def typed(rows):
    """Input text without the prompt marker and continuation indentation."""
    first = rows[0].lstrip()[len(_PROMPT) :].lstrip("  ")
    return "\n".join([first, *(row.strip() for row in rows[1:])]).strip()


class ClaudeCodeAdapter:
    name = "claude"
    capabilities = Capabilities(text=True)
    # Process-local for a fresh owner launch only. A startup prompt suggestion renders
    # as text in the composer, which the readiness guard correctly treats as a draft
    # (input_not_empty). Disabling it yields a genuinely empty composer; it never
    # touches an existing session or weakens the draft guard (M4 live evidence).
    launch_environment = {"CLAUDE_CODE_ENABLE_PROMPT_SUGGESTION": "false"}

    def input_view(self, raw):
        text, unknown = legacy.display_text(raw)
        found = None if unknown else composer(text)
        return "" if found is None else "\n".join(found[1] + found[2])

    def observe(self, raw, binding, protocol=None):
        text, controls = legacy.display_text(raw)
        found = None if controls else composer(text)
        result = {
            "target": self.name,
            "ready": False,
            "state": "unknown",
            "reason": "unsupported_control_sequence" if controls else "prompt_not_found",
            "input_empty": False,
            "protocol_state": "not_bound",
        }
        if found is not None:
            above, rows, footer = found
            first = rows[0].replace(" ", " ").rstrip()
            empty = len(rows) == 1 and bool(re.fullmatch(binding.ready_pattern, first.strip()))
            # Only the block after the last output; quoted output never counts.
            # The footer is deliberately excluded from the busy_pattern match: current
            # Claude Code releases show a standing "esc to interrupt" keybinding hint in
            # the footer at all times, not only while a turn is running, so matching
            # binding.busy_pattern (default includes "esc to interrupt") against the
            # footer falsely classified a genuinely idle, empty composer as "working"
            # forever -- the session never got ready and never received automatic
            # input (KiraBridge message-wakeup issue, found live 2026-11-28). The live
            # spinner line (with its elapsed-time counter) is the only signal that
            # actually disappears once a turn ends, so it alone decides "busy" here.
            block = live_block(above)
            busy = _LIVE_SPINNER.search("\n".join(block))
            state, reason = (
                ("input_not_empty", "existing_input_must_not_be_overwritten")
                if not empty
                else ("working", "visible_claude_activity")
                if busy
                else ("ready", "current_empty_widget")
            )
            result.update(input_empty=empty, state=state, reason=reason, ready=state == "ready")
        return {
            **result,
            "ui_state": "composer" if result["ready"] else "unknown",
            "work_state": "working" if result["state"] == "working" else "unknown",
            "allowed_actions": ["insert", "submit"] if result["ready"] else [],
        }

    def return_readiness(self, raw, binding, protocol=None):
        return {
            "target": self.name,
            "ready": False,
            "state": "unknown",
            "reason": "unsupported_return_frame",
            "allowed_actions": [],
        }

    def insertion_observed(self, raw, text, before, **options):
        old = composer(legacy.display_text(before)[0])
        new_text, controls = legacy.display_text(raw)
        new = None if controls else composer(new_text)
        if old is None or new is None or typed(old[1]) or not _compact(text):
            return False
        field = typed(new[1])
        return _compact(field) == _compact(text) or folded_paste(field, text)

    def navigation_preserves(self, before, after, observation, after_state):
        return False

    async def protocol_state(self, binding, observer):
        return None

    def has_bound_protocol(self, binding):
        return False

    def paste_source(self, text):
        # Fresh-echo check: only the CURRENT input field, before and after. Empty before,
        # exactly the text (whitespace-free, wrapped rows) or its folded marker after.
        # __pasteDiag keeps only lengths/booleans of the LAST evaluation (never text),
        # so an unconfirmed paste can be classified without reading the terminal.
        # The verdict logic below is unchanged.
        return (
            "\nvar __pasteDiag=null;"
            "\nfunction observedPaste(before, after) {"
            "const c=s=>s.replace(/[\\s\\u00a0]+/g,''), p=c(" + json.dumps(text) + ");"
            "const counts=" + json.dumps(sorted(_folded_counts(text))) + ";"
            "const rule=/^[ \\t]*─{3,}(?: [^─\\n]{1,120} ─+)?[ \\t]*$/;"
            "const field=s=>{const l=s.split('\\n');"
            "for(let i=l.length-1;i>0;i--){"
            "if(l[i].trimStart().startsWith('" + _PROMPT + "')&&rule.test(l[i-1])){"
            "for(let e=i+1;e<l.length;e++){if(rule.test(l[e])){"
            "return [l[i].trimStart().slice(1),...l.slice(i+1,e)].join('\\n');}}"
            "return null;}}return null;};"
            "const old=field(before), now=field(after);"
            "const seen=now===null?null:c(now); let common=0;"
            "if(seen!==null){while(common<seen.length&&common<p.length"
            "&&seen[common]===p[common])common++;}"
            "__pasteDiag={before_field:old===null?-1:c(old).length,"
            "after_field:seen===null?-1:seen.length,expected:p.length,common_prefix:common,"
            "after_rows:now===null?-1:now.split('\\n').length,"
            "tail_changed:before!==after,tail_delta:after.length-before.length,"
            "marker:seen!==null&&/^\\[Pastedtext#/.test(seen)};"
            "if(!p.length||old===null||now===null||c(old).length) return false;"
            "const cur=c(now); if(cur===p) return true;"
            r"const m=/^\[Pastedtext#\d+(?:\+(\d+)lines?)?\]$/.exec(cur);"
            "return !!m && counts.includes(m[1]===undefined?0:Number(m[1]));}\n"
        )

    def slash_insertion_observed(self, sessions, binding, raw, text, before, **options):
        return False

    def command_result(self, command, before, after, binding, protocol=None):
        return {"acceptance_observed": False, "acceptance_evidence": "unsupported"}

    def allows_text(self, text, submit):
        return True

    async def preflight_input(self, sessions, binding, text, before):
        return None
