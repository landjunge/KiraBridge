"""Bounded ACP initialize only: no authentication, model prompt or existing session attachment."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path


async def probe(executable: str, timeout: float = 10) -> dict:
    process = None
    try:
        async with asyncio.timeout(timeout):
            process = await asyncio.create_subprocess_exec(
                executable,
                "--no-subagents",
                "--disable-web-search",
                "--permission-mode",
                "dontAsk",
                "--deny",
                "Bash",
                "--deny",
                "Edit",
                "--deny",
                "MCPTool",
                "agent",
                "--no-leader",
                "stdio",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                limit=65536,
                env={"PATH": os.defpath, "HOME": str(Path.home()), "LANG": "en_US.UTF-8"},
            )
            request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": 1, "clientCapabilities": {}},
            }
            process.stdin.write((json.dumps(request) + "\n").encode())
            await process.stdin.drain()
            total = 0
            while line := await process.stdout.readline():
                total += len(line)
                if total > 65536:
                    return {"ok": False, "code": "byte_limit"}
                value = json.loads(line)
                if value.get("id") != 1:
                    continue
                result = value.get("result", {})
                return {
                    "ok": result.get("protocolVersion") == 1 and "error" not in value,
                    "protocol_version": result.get("protocolVersion"),
                    "auth_methods_declared": [
                        m["id"]
                        for m in result.get("authMethods", [])
                        if isinstance(m, dict) and m.get("id") in {"cached_token", "xai.api_key"}
                    ],
                    "authentication_tested": False,
                    "model_prompt_sent": False,
                    "existing_session_attached": False,
                    "scope": "ACP initialization only",
                }
            return {"ok": False, "code": "disconnected_before_initialize"}
    except (TimeoutError, OSError, ValueError):
        return {"ok": False, "code": "initialization_unavailable"}
    finally:
        if process is not None and process.returncode is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), 2)
            except TimeoutError:
                process.kill()
                await process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", required=True)
    args = parser.parse_args()
    if not Path(args.executable).is_absolute():
        parser.error("Use the actual configured absolute executable")
    result = asyncio.run(probe(args.executable))
    print(json.dumps(result))
    raise SystemExit(0 if result.get("ok") else 1)


if __name__ == "__main__":
    main()
