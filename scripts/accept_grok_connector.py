"""Opt-in public TLS/OAuth/MCP check. A controlled client is not a real Grok/Eve session."""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import re
import secrets
import sqlite3
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx

from kirabridge.approval_console import ORIGIN, signed_token
from kirabridge.bridge_core.config import load_config
from kirabridge.console_runtime import console_key, probe
from kirabridge.grok_connector import effective_settings
from kirabridge.local_runtime import peer
from kirabridge.mcp_gateway.client import MCPClientPool, Peer


def local_login(config_path):
    with httpx.Client(trust_env=False, timeout=10, follow_redirects=False) as local:
        key = console_key(config_path)
        instance = probe(local, key)
        assert instance
        login = local.post(
            ORIGIN + "/login",
            data={"ticket": signed_token(key, "login:" + instance)},
            headers={"Origin": ORIGIN},
        )
        assert login.status_code == 200
        return re.search(r'data-session="([^"]+)"', login.text)[1]


async def run(config_path: Path, output: Path):
    if output.exists():
        raise RuntimeError("Keep previous acceptance evidence; use a fresh output file")
    config = load_config(str(config_path))
    settings = effective_settings(config)
    issuer, resource = settings.public_origin, settings.public_origin + "/mcp"
    callback = "https://grok.com/connector/controlled-acceptance-callback"
    verifier, state = secrets.token_urlsafe(48), secrets.token_urlsafe(24)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    session = await asyncio.to_thread(local_login, config_path)
    async with httpx.AsyncClient(timeout=20, trust_env=False, follow_redirects=False) as public:
        metadata = (await public.get(issuer + "/.well-known/oauth-authorization-server")).json()
        assert metadata["issuer"] == issuer
        unauthorized = await public.post(
            resource, json={"jsonrpc": "2.0", "id": 1, "method": "ping"}
        )
        assert unauthorized.status_code == 401
        registered = await public.post(
            metadata["registration_endpoint"],
            json={
                "client_name": "Technischer KiraBridge-Abnahmetest — kein Handy-Nachweis",
                "redirect_uris": [callback],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
                "scope": "kirabridge",
            },
        )
        assert registered.status_code == 201, registered.status_code
        client_id = registered.json()["client_id"]
        authorization = await public.get(
            metadata["authorization_endpoint"],
            params={
                "client_id": client_id,
                "redirect_uri": callback,
                "response_type": "code",
                "scope": "kirabridge",
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "resource": resource,
            },
        )
        assert authorization.status_code in {302, 303, 307}
        location = authorization.headers["location"]
        assert location.startswith(issuer + "/oauth/consent/")
        request_id = location.rsplit("/", 1)[1]
        async with httpx.AsyncClient(timeout=10, trust_env=False) as local:
            decision = await local.post(
                ORIGIN + "/api/grok-connector/" + request_id + "/decision",
                json={"allow": True},
                headers={"Authorization": "Bearer " + session, "Origin": ORIGIN},
            )
            assert decision.status_code == 200
        poll = await public.get(issuer + "/oauth/poll/" + request_id)
        redirect = poll.json()["redirect_url"]
        target = urlsplit(redirect)
        assert target.scheme == "https" and target.hostname == "grok.com"
        assert target.path == urlsplit(callback).path
        values = parse_qs(target.query)
        assert values["state"] == [state] and values["iss"] == [issuer]
        grant = {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": values["code"][0],
            "code_verifier": verifier,
            "redirect_uri": callback,
            "resource": resource,
        }
        minted = await public.post(metadata["token_endpoint"], data=grant)
        assert minted.status_code == 200
        tokens = minted.json()
        result = {
            "public_TLS": True,
            "OAuth_DCR_consent_PKCE": True,
            "fixed_principal": "grok_app",
            "CLI_principal": "grok",
            "actual_Grok_app_call_verified": False,
            "Eve_voice_verified": False,
            "provider_voice_API_used": False,
            "native_model_calls": 0,
        }
        try:
            async with MCPClientPool(call_timeout=20) as app, MCPClientPool(call_timeout=15) as cli:
                await app.connect(Peer("app", url=resource, token=tokens["access_token"]))
                await cli.connect(peer(config, "grok"))

                async def call(name, args):
                    response = await app.call("app", name, args)
                    value = response.structuredContent
                    assert isinstance(value, dict) and not value.get("error"), (name, value)
                    return value

                health = await call("bridge_health", {})
                assert health["dispatcher_active"] and health["approval_mode"] == "automatic"
                team = await call("team_get", {"team_id": "kirabridge-team"})
                request = {
                    "team_id": "kirabridge-team",
                    "recipient": "grok",
                    "kind": "note",
                    "body": "Technischer OAuth-MCP-Verbindungstest. Kein Modellauftrag.",
                    "idempotency_key": "connector-native-app-link-20261019",
                }
                first = await call("team_message_send", {"request": request})
                assert first["sender"] == "grok_app"
                repeated = await call("team_message_send", {"request": request})
                assert repeated["id"] == first["id"]
                receipt = await cli.call(
                    "daemon",
                    "team_message_ack",
                    {"team_id": "kirabridge-team", "message_id": first["id"]},
                )
                assert receipt.structuredContent["acknowledged"]
                spoofed = await app.call(
                    "app", "team_message_send", {"request": {**request, "sender": "grok"}}
                )
                assert spoofed.isError or spoofed.structuredContent.get("error")
                with sqlite3.connect(
                    (config.state_path / "bridge.sqlite3").as_uri() + "?mode=ro", uri=True
                ) as db:
                    private_id = db.execute(
                        "SELECT id FROM tasks WHERE principal='local' LIMIT 1"
                    ).fetchone()[0]
                denied = await app.call("app", "task_get", {"task_id": private_id})
                assert denied.structuredContent["error"]["code"] == "not_found"
                proof_dir = (
                    Path.home() / "workspace/KiraBridge/abnahmen/grok-app-connector-20261019"
                )
                proof_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
                file = proof_dir / "oauth-connector-proof.txt"
                task_id = "grok-app-connector-write-20261019-01"
                task = {
                    "task_id": task_id,
                    "idempotency_key": task_id,
                    "operation": "file.write",
                    "arguments": {
                        "path": str(file),
                        "text": "KIRABRIDGE_GROK_APP_MCP_OK\n",
                        "overwrite": False,
                    },
                }
                queued = await call("task_request", {"request": task})
                assert queued["approval_required"] is False
                async with asyncio.timeout(15):
                    while True:
                        outcome = await call("task_get", {"task_id": task_id})
                        if outcome["state"] in {
                            "completed",
                            "failed",
                            "unknown",
                            "blocked",
                            "cancelled",
                        }:
                            break
                        await asyncio.sleep(0.2)
                assert outcome["state"] == "completed", outcome.get("error")
                assert file.read_text() == "KIRABRIDGE_GROK_APP_MCP_OK\n"
                same_task = await call("task_request", {"request": task})
                assert same_task["id"] == task_id
                result.update(
                    MCP_to_real_bridge=True,
                    separate_app_sender=first["sender"],
                    team_coordinator_preserved=team["coordinator"],
                    CLI_receipt_confirmed=True,
                    message_id=first["id"],
                    same_message_on_repeat=True,
                    forged_sender_rejected=True,
                    private_task_rejected=True,
                    automatic_file_write={
                        "task_id": task_id,
                        "state": outcome["state"],
                        "attempt": outcome["attempt"],
                        "same_task_on_repeat": True,
                        "existing_file_overwritten": False,
                    },
                )
            refreshed = await public.post(
                metadata["token_endpoint"],
                data={
                    "grant_type": "refresh_token",
                    "client_id": client_id,
                    "refresh_token": tokens["refresh_token"],
                    "resource": resource,
                },
            )
            assert refreshed.status_code == 200
            rotated = refreshed.json()
            assert rotated["access_token"] != tokens["access_token"]
            assert rotated["refresh_token"] != tokens["refresh_token"]
            reused = await public.post(
                metadata["token_endpoint"],
                data={
                    "grant_type": "refresh_token",
                    "client_id": client_id,
                    "refresh_token": tokens["refresh_token"],
                    "resource": resource,
                },
            )
            assert reused.status_code == 400
            refused = await public.post(
                resource,
                headers={"Authorization": "Bearer " + rotated["access_token"]},
                json={"jsonrpc": "2.0", "id": 2, "method": "ping"},
            )
            assert refused.status_code == 401
            result.update(refresh_rotated=True, refresh_replay_revokes_family=True)
            replay = await public.post(metadata["token_endpoint"], data=grant)
            assert replay.status_code == 400
            result["authorization_code_replay_denied"] = True
            output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
            output.chmod(0o600)
            print(json.dumps(result, indent=2, ensure_ascii=False))
        finally:
            # Revoke this controlled client only; never any user-created app connector.
            from kirabridge.grok_connector import state_dir
            from kirabridge.grok_connector.auth_store import OAuthStore

            store = OAuthStore(
                state_dir(config) / "oauth.sqlite3",
                issuer=issuer,
                principal=settings.principal,
                redirect_hosts=settings.redirect_hosts,
            )
            try:
                store.revoke_client(client_id)
            finally:
                store.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=Path.home() / ".config/kirabridge/config.toml"
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--run-public-check", action="store_true", required=True)
    args = parser.parse_args()
    asyncio.run(run(args.config, args.out))
