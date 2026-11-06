"""Explicit leaf-certificate pins for optional remote peers; no trust-store changes."""

from __future__ import annotations

import hashlib
import re
import ssl
from dataclasses import dataclass
from pathlib import Path

from kirabridge.bridge_core.models import BridgeError


@dataclass(frozen=True)
class CertificateIdentity:
    certificate_sha256: str
    public_key_sha256: str


def _certificate_data(path: str) -> bytes:
    try:
        with Path(path).open("rb") as source:
            data = source.read(65537).strip()
    except (OSError, TypeError, ValueError):
        raise BridgeError("tls_pin_config", "Cannot read explicit leaf certificate") from None
    if (
        len(data) > 65536
        or data.count(b"-----BEGIN") != 1
        or not data.startswith(b"-----BEGIN CERTIFICATE-----")
        or not data.endswith(b"-----END CERTIFICATE-----")
    ):
        raise BridgeError("tls_pin_config", "One explicit leaf certificate is required")
    return data


def _identity(data: bytes) -> CertificateIdentity:
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization
    except ImportError:
        raise BridgeError("tls_pin_unavailable", "Certificate-pin support is unavailable") from None
    try:
        certificate = x509.load_pem_x509_certificate(data)
        if certificate.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:
            raise ValueError("CA is not a leaf pin")
        der = certificate.public_bytes(serialization.Encoding.DER)
        public = certificate.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    except (ValueError, x509.ExtensionNotFound):
        raise BridgeError("tls_pin_config", "Invalid explicit leaf certificate") from None
    return CertificateIdentity(hashlib.sha256(der).hexdigest(), hashlib.sha256(public).hexdigest())


def certificate_identity(path: str) -> CertificateIdentity:
    return _identity(_certificate_data(path))


def pinned_context(path: str | None, expected_sha256: str) -> ssl.SSLContext:
    if (
        not path
        or not isinstance(expected_sha256, str)
        or not re.fullmatch(r"[a-f0-9]{64}", expected_sha256)
    ):
        raise BridgeError("tls_pin_config", "An explicit certificate pin is required")
    data = _certificate_data(path)
    if _identity(data).certificate_sha256 != expected_sha256:
        raise BridgeError("tls_pin_mismatch", "Configured certificate does not match its pin")
    flag = getattr(ssl, "VERIFY_X509_PARTIAL_CHAIN", None)
    if flag is None:
        raise BridgeError("tls_pin_unavailable", "Leaf-pinned TLS is unavailable")
    # Trust this non-CA leaf only. Verification happens in TLS, before HTTP credentials.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.verify_mode = ssl.CERT_REQUIRED
    context.check_hostname = True
    # Use the exact bytes just checked, even if the configured file changes meanwhile.
    context.load_verify_locations(cadata=data.decode("ascii"))
    context.verify_flags |= flag
    return context
