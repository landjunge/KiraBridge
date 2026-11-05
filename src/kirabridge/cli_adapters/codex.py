"""Codex UI/action semantics, separate from target identity and native IO."""

import re

from . import _legacy_readiness as legacy
from .contract import Capabilities

COPY_TOOLBAR = "⌃c copy · enter copy & follow · esc clear"


class CodexAdapter:
    name = "codex"
    slash_verifier_version = "codex-slash-widget-v1"
    capabilities = Capabilities(
        text=True,
        separate_return=True,
        return_to_input=True,
        slash_commands=("/status", "/model", "/resume"),
        softwrap=True,
        cwd_proof=True,
        bound_turn=True,
        bound_reply=True,
    )

    def input_view(self, raw):
        return legacy.input_view(self.name, raw)

    def _special(self, raw, binding, protocol):
        text, controls = legacy.display_text(raw)
        from .codex_menus import model_selector, unsupported_confirmation_frame

        if unsupported_confirmation_frame(text):
            return None
        if controls or (protocol is not None and protocol.get("state") != "idle"):
            return None
        if model_selector(text):
            header = text.rfind("Select Model and Effort")
            previous = re.split(r"\n[ \t]*\n", text[:header].rstrip())[-1]
            if re.search(r"esc to interrupt|tab to queue message|Approval required", previous):
                return None
            return {
                "target": self.name,
                "ready": False,
                "state": "navigation_required",
                "reason": "known_model_selector",
                "ui_state": "model_menu",
                "work_state": "idle" if protocol else "unknown",
                "input_empty": False,
                "allowed_actions": ["return_to_input"],
                "navigation_key": "escape",
            }
        view = self.input_view(text)
        if not view:
            return None
        lines = view.splitlines()
        footer = [s.strip() for s in lines[1:] if s.strip()]
        prelude = text[: len(text) - len(view)].rstrip()
        block = re.split(r"\n[ \t]*\n", prelude)[-1] if prelude else ""
        if re.search(r"(?m)^[ \t]*[•◦].*esc to interrupt", block) or view.lstrip().startswith("»"):
            return None
        kind, normalized = None, None
        if footer and footer[-1] in {COPY_TOOLBAR, "New activity · " + COPY_TOOLBAR}:
            # Full known toolbar has different Return semantics. Never submit it.
            # Activity decorates this complete control row; it is not a free
            # warning/dialog prefix and does not establish an idle work state.
            toolbar = footer[-1]
            offset = text.rfind(toolbar)
            normalized = text[:offset] + text[offset + len(toolbar) :]
            base = legacy.assess(self.name, normalized, binding, protocol)
            if base["ready"] and base["input_empty"]:
                kind = "copy"
        if not kind and re.fullmatch(r"↓ Back to bottom · esc", block.strip()):
            # Exact current UI control, not an assumed user scroll or free warning row.
            if footer and re.fullmatch(
                r"esc latest(?:[ \t]+⚠ [1-9][0-9]* warnings? · f2 to view)?", footer[-1]
            ):
                if any(re.fullmatch(r"GPT-\S+ [^·\n]+ · [^\n]+", s) for s in footer):
                    draft = self.draft(view)
                    expected = [s.strip() for s in view[len(draft) :].splitlines() if s.strip()]
                    continuation = draft.splitlines()[1:]
                    from .codex_menus import unsupported_confirmation_frame

                    safe_rows = all(
                        line.startswith("  ")
                        and line.strip()
                        and not unsupported_confirmation_frame(line + "\n› ")
                        and "tab to queue message" not in line
                        for line in continuation
                    )
                    if (
                        safe_rows
                        and len(expected) == 2
                        and expected == footer[-2:]
                        and re.fullmatch(r"GPT-\S+ [^·\n]+ · [^\n]+", expected[0])
                    ):
                        kind = "transcript"
        if kind:
            return {
                "target": self.name,
                "ready": False,
                "state": "navigation_required",
                "reason": "known_" + kind + "_view",
                "ui_state": kind,
                "work_state": "idle" if protocol else "unknown",
                "input_empty": bool(re.fullmatch(binding.ready_pattern, lines[0].strip())),
                "allowed_actions": ["return_to_input"],
                "navigation_key": "escape",
                "preserve_draft": kind == "transcript",
                "return_requires_navigation": kind == "transcript",
            }
        return None

    def observe(self, raw, binding, protocol=None):
        special = self._special(raw, binding, protocol)
        if special:
            return special
        result = legacy.assess(self.name, raw, binding, protocol)
        return {
            **result,
            "ui_state": "composer"
            if result["ready"]
            else "draft"
            if result["state"] == "input_not_empty"
            else "unknown",
            "work_state": protocol.get("state", "unknown")
            if protocol
            else "working"
            if result["state"] == "working"
            else "unknown",
            "allowed_actions": ["insert", "submit"] if result["ready"] else [],
        }

    def return_readiness(self, raw, binding, protocol=None):
        special = self._special(raw, binding, protocol)
        if special:
            return special
        from .codex_return import return_readiness

        draft = self.draft(raw).splitlines()
        marker = re.match(r"^[ \t]*›[ \t]*(/.*)$", draft[0]) if draft else None
        if marker:
            payload = "\n".join([marker[1], *draft[1:]]).strip()
            if not self.allows_text(payload, True):
                return {
                    "target": self.name,
                    "ready": False,
                    "state": "unknown",
                    "reason": "unsupported_slash_submission",
                }
        result = return_readiness(self.name, raw, binding, protocol)
        if result.get("reason") == "observed_codex_resume_selector":
            result["semantic_action"] = "menu_confirmation"
        return result

    def allows_text(self, text, submit):
        return (
            not submit
            or not text.lstrip().startswith("/")
            or text in self.capabilities.slash_commands
        )

    async def preflight_input(self, sessions, binding, text, before):
        from .rendering import check_codex_paste_geometry

        await check_codex_paste_geometry(sessions, self.name, binding, text, before)

    def command_result(self, command, before, after, binding, protocol=None):
        state = self.observe(after, binding, protocol)
        accepted = None
        if command == "/model" and state.get("ui_state") == "model_menu":
            accepted = "model_menu"
        if command == "/status" and state.get("ready"):
            # The exact new status block must be appended after the old transcript.
            # A stale status page anywhere in scrollback is not new CLI output.
            old = before[: len(before) - len(self.input_view(before))].rstrip()
            new = after[: len(after) - len(self.input_view(after))].rstrip()
            delta = new[len(old) :] if new.startswith(old) else ""
            marker = re.search(r"(?m)^/status[ \t]*$", delta)
            if marker:
                output = delta[marker.end() :]
                fields = ("Model", "Model provider", "Directory", "Permissions", "Session")
                if re.search(r">_ OpenAI Codex \(v[^\n]+\)", output) and all(
                    re.search(r"(?m)^[ \t]*" + re.escape(field) + r":[ \t]+\S", output)
                    for field in fields
                ):
                    accepted = "status_output"
        return {
            "acceptance_observed": accepted is not None,
            "acceptance_evidence": accepted or "unconfirmed",
            "response_observed": False,
            "ui_state_after": state.get("ui_state", "unknown"),
            "ready_to_input": state.get("ready", False),
        }

    def draft(self, raw):
        view = self.input_view(raw)
        lines = view.splitlines(keepends=True)
        for index in range(1, len(lines)):
            if not lines[index].strip():
                return "".join(lines[:index])
        return view

    def insertion_observed(self, raw, text, before, **options):
        from .rendering import insertion_observed

        return insertion_observed(self.name, raw, text, before, **options)

    def paste_source(self, text):
        from .codex_echo import paste_source

        return paste_source(text)

    def navigation_preserves(self, before, after, observation, after_state):
        if observation["ui_state"] == "transcript":
            return self.draft(before) == self.draft(after)
        return after_state.get("input_empty") is True

    def slash_insertion_observed(
        self, sessions, binding, raw, text, before, *, cwd=None, home=None
    ):
        from .codex_slash import bound_thread_title, resume_insertion_observed

        title = bound_thread_title(sessions, binding) if cwd is not None else None
        return resume_insertion_observed(
            self.name, raw, text, before, cwd=cwd, home=home, title=title
        )

    async def protocol_state(self, binding, observer):
        if binding.codex_thread_id:
            return await observer.read(binding.codex_rollout_path, binding.codex_thread_id)
        return None

    def has_bound_protocol(self, binding):
        return bool(binding.codex_thread_id)
