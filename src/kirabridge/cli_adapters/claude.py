"""Claude Code as the third CLI module on the shared adapter core (BP-CLI-01).

Only headless semantics exist (see agent_manager.claude). No visible-terminal
input, return or navigation capability is claimed, so every such query stays unknown.
`probe` reads version and login state without any model request or cost.
"""

import json
import os
import re
import subprocess

from .contract import Capabilities

BILLING_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


class ClaudeCodeAdapter:
    name = "claude"
    capabilities = Capabilities()

    def input_view(self, raw):
        return ""

    def observe(self, raw, binding, protocol=None):
        return {
            "target": self.name,
            "ready": False,
            "state": "unknown",
            "reason": "headless_only_cli_module",
            "input_empty": False,
            "ui_state": "unknown",
            "work_state": "unknown",
            "allowed_actions": [],
        }

    def return_readiness(self, raw, binding, protocol=None):
        return {**self.observe(raw, binding, protocol), "reason": "unsupported_return_frame"}

    def insertion_observed(self, *args, **options):
        return False

    def navigation_preserves(self, before, after, observation, after_state):
        return False

    async def protocol_state(self, binding, observer):
        return None

    def has_bound_protocol(self, binding):
        return False

    def paste_source(self, text):
        return None

    def slash_insertion_observed(self, sessions, binding, raw, text, before, **options):
        return False

    def command_result(self, command, before, after, binding, protocol=None):
        return {"acceptance_observed": False, "acceptance_evidence": "unsupported"}

    def allows_text(self, text, submit):
        return False

    async def preflight_input(self, sessions, binding, text, before):
        return None


def _run(argv, env):
    done = subprocess.run(  # noqa: S603 - fixed argv, no shell, no model request
        argv, capture_output=True, text=True, timeout=20, env=env, check=False
    )
    return done.returncode, done.stdout


def probe(executable, *, runner=_run, environ=None):
    """Version and login without a model turn. Usage/quota is never inferred.

    Returns only non-identifying fields (no email, organization or token values).
    """
    environ = os.environ if environ is None else environ
    env = {k: v for k, v in environ.items() if k in {"PATH", "HOME", "USER", "LOGNAME", "LANG"}}
    result = {
        "version": None,
        "logged_in": False,
        "auth_method": None,
        "subscription_type": None,
        "api_key_env_present": any(environ.get(key) for key in BILLING_ENV),
        "usage": "unknown",
    }
    try:
        code, out = runner([executable, "--version"], env)
        match = re.match(r"^(\d+\.\d+\.\d+)\b", out.strip()) if code == 0 else None
        result["version"] = match.group(1) if match else None
        code, out = runner([executable, "auth", "status", "--json"], env)
        status = json.loads(out) if out.strip() else {}
    except (OSError, ValueError, subprocess.SubprocessError):
        return result
    if isinstance(status, dict) and status.get("loggedIn") is True:
        result["logged_in"] = True
        result["auth_method"] = status.get("authMethod")
        result["subscription_type"] = status.get("subscriptionType")
    return result


def login_evidence(executable, *, runner=_run, environ=None, now=None):
    """Subscription login proof only (no budget, no usage figure).

    Budget belongs to TollGate (BP-TG-01). A missing login or an API-key route raises.
    """
    import time

    state = probe(executable, runner=runner, environ=environ)
    if state["api_key_env_present"]:
        raise RuntimeError("API-key billing is not authorized for this loop")
    if not state["logged_in"] or state["auth_method"] != "claude.ai":
        raise RuntimeError("Claude subscription login is not confirmed")
    return {
        "observed_at": time.time() if now is None else now,
        "version": state["version"],
        "subscription_confirmed": True,
    }
