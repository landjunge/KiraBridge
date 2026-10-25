"""Existing policy authority plus explicit, independently configured source/destination scopes."""

from kirabridge.bridge_core.models import BridgeError
from kirabridge.file_transfer.integrity import logical_path


class TransferAuthorization:
    def __init__(self, settings, principal):
        self.settings, self.principal = settings, principal

    def check(self, identity, capability):
        policy = self.principal(identity, capability)
        if not self.settings.enabled and capability != "files.inspect":
            raise BridgeError("transfer_disabled", "File transfer is not enabled by the operator")
        return policy

    def prepare(self, identity, args):
        self.check(identity, "files.prepare")
        if args.project_id not in self.settings.allowed_projects:
            raise BridgeError(
                "transfer_project_denied", "Project is not operator-authorized for file import"
            )
        from kirabridge.file_transfer.integrity import SecretScan

        SecretScan().update(args.model_dump_json(exclude={"source_id", "expected_sha256"}).encode())
        logical_path(args.folder)
        if args.library_path:
            logical_path(args.library_path, allow_absolute=True)

    def source(self, identity, source):
        if source.kind == "authorized_export":
            policy, roots = self.export_roots(identity)
            policy.split(source.path)
            from pathlib import Path

            from kirabridge.filesystem_manager import PathScope

            PathScope(roots).split(source.path)
            if any(
                part.casefold() in {".ssh", ".aws", ".gnupg", ".config", ".git"}
                for part in Path(source.path).parts
            ):
                raise BridgeError(
                    "transfer_source_denied", "Credential/configuration sources are excluded"
                )
        else:
            from urllib.parse import urlsplit

            if urlsplit(source.download_url).hostname not in self.settings.source_hosts:
                raise BridgeError("transfer_source_denied", "Source host authorization was revoked")
            source.hosts = tuple(self.settings.source_hosts)
            source.max_bytes = self.settings.limits.max_file_bytes

    def export_roots(self, identity):
        policy = self.check(identity, "files.prepare")
        self.principal(identity, "file.read")
        # Both grants are necessary; a broad filesystem grant does not authorize an export source.
        from kirabridge.filesystem_manager import PathScope

        return PathScope(policy.roots + policy.read_roots), list(self.settings.export_roots)
