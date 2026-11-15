"""Actual ACP SDK peer for host tests; no model/account/external command."""

import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

from acp import Agent, RequestError, run_agent
from acp.schema import (
    AgentMessageChunk,
    InitializeResponse,
    NewSessionResponse,
    PermissionOption,
    PromptResponse,
    TextContentBlock,
    ToolCallUpdate,
)

TRACE = Path(sys.argv[1])


def trace(value):
    with TRACE.open("a") as output:
        output.write(value + "\n")


class Peer(Agent):
    def on_connect(self, connection):
        self.connection = connection
        self.cancelled = {}

    async def initialize(self, protocol_version, **kwargs):
        return InitializeResponse(protocol_version=protocol_version)

    async def new_session(self, cwd, **kwargs):
        session_id = uuid4().hex
        self.cancelled[session_id] = asyncio.Event()
        return NewSessionResponse(session_id=session_id)

    async def prompt(self, session_id, prompt, **kwargs):
        trace("prompt")
        text = prompt[0].text
        if text == "eof":
            os._exit(23)
        if text == "permission":
            decision = await self.connection.request_permission(
                session_id=session_id,
                tool_call=ToolCallUpdate(tool_call_id="synthetic-permission"),
                options=[PermissionOption(option_id="ok", name="Allow", kind="allow_once")],
            )
            if decision.outcome.outcome == "cancelled":
                return PromptResponse(stop_reason="cancelled")
        elif text.startswith("read:") or text.startswith("foreign:"):
            try:
                response = await self.connection.read_text_file(
                    session_id="foreign-session" if text.startswith("foreign:") else session_id,
                    path=text.split(":", 1)[1],
                )
                text = response.content
            except RequestError:
                text = "read-rejected"
        elif text == "terminal":
            try:
                await self.connection.create_terminal(session_id=session_id, command="synthetic")
                text = "terminal-delivered"
            except RequestError:
                text = "terminal-rejected"
        elif "kirabridge_team" in text:
            text = json.dumps(
                {"kirabridge_team": "1", "result": "SYNTHETIC_TEAM_OK", "actions": []}
            )
        await self.connection.session_update(
            session_id=session_id, update=AgentMessageChunk(content=TextContentBlock(text=text))
        )
        if text == "slow":
            await asyncio.Event().wait()
        return PromptResponse(stop_reason="end_turn")

    async def cancel(self, session_id, **kwargs):
        self.cancelled[session_id].set()


if __name__ == "__main__":
    trace("spawn")
    asyncio.run(run_agent(Peer()))
