"""In-process proof issued only by the existing sealed Core/Team session authority."""

from dataclasses import dataclass, field
from typing import Callable

from kirabridge.bridge_core.models import BridgeError


@dataclass(frozen=True)
class QwenTeamSession:
    core_task_id: str
    team_id: str
    work_id: str
    session_id: str
    generation: int
    owner: str
    agent: str
    cwd: str
    model: str
    auth_type: str
    effort: str | None
    validate: Callable[[], None] = field(repr=False, compare=False)

    def validate_effect(self, task, args, config):
        if (
            task["id"] != self.core_task_id
            or task["principal"] != self.owner
            or args.agent != self.agent
            or args.cwd != self.cwd
            or args.resume_session != self.session_id
            or config.model != self.model
            or config.qwen_auth_type != self.auth_type
            or config.qwen_reasoning_effort != self.effort
        ):
            raise BridgeError("agent_resume_denied", "Qwen continuation differs from its seal")
        self.validate()

    def policy_scope(self):
        return {
            "team_id": self.team_id,
            "work_id": self.work_id,
            "session_id": self.session_id,
            "generation": self.generation,
        }
