import asyncio
import datetime
import ipaddress
import socket
import ssl

import httpx
import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from kirabridge.mcp_gateway.client import MCPClientPool, Peer
from kirabridge.mcp_gateway.http import create_http_app


async def test_real_tls_with_certificate_validation(bridge, tmp_path, monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "KiraBridge local test")])
    now = datetime.datetime.now(datetime.UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(hours=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / "test-cert.pem", tmp_path / "test-key.pem"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    key_path.chmod(0o600)
    monkeypatch.setenv("TLS_TEST_TOKEN", "t" * 40)
    bridge.config.principals["local"].token_env = "TLS_TEST_TOKEN"
    bridge.config.tls_cert, bridge.config.tls_key = str(cert_path), str(key_path)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(32)
    endpoint = f"https://127.0.0.1:{sock.getsockname()[1]}/mcp"
    server = uvicorn.Server(
        uvicorn.Config(
            create_http_app(bridge),
            log_level="critical",
            access_log=False,
            ssl_certfile=str(cert_path),
            ssl_keyfile=str(key_path),
        )
    )
    async with bridge:
        task = asyncio.create_task(server.serve(sockets=[sock]))
        try:
            async with asyncio.timeout(10):
                while not server.started:
                    await asyncio.sleep(0.01)
            async with httpx.AsyncClient(
                verify=ssl.create_default_context(cafile=str(cert_path))
            ) as client:
                assert (await client.post(endpoint, json={})).status_code == 401
            async with MCPClientPool() as pool:
                await pool.connect(
                    Peer("tls", url=endpoint, token="t" * 40, ca_file=str(cert_path))
                )
                result = await pool.call("tls", "bridge_health", {})
                assert result.structuredContent["dispatcher_active"]
        finally:
            server.should_exit = True
            await asyncio.wait_for(task, 10)
            sock.close()
