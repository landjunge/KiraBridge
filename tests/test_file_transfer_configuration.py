import tomllib

import pytest

from kirabridge.bridge_core.config import load_config
from kirabridge.bridge_core.models import BridgeError
from kirabridge.file_transfer.authorization import TransferAuthorization
from kirabridge.file_transfer.configuration import enabled_text


def test_explicit_activation_survives_reload_update_and_preserves_other_configuration(tmp_path):
    raw = (
        'data_dir = "/tmp/isolated-state"\n[threaddesk]\nenabled = true\n'
        'workspace = "/tmp/receiver"\n'
    )
    path = tmp_path / "config.toml"
    first = enabled_text(raw, export_roots=["/tmp/exports"], allowed_projects=["project"])
    path.write_text(first)
    assert load_config(str(path)).file_transfer.enabled is True
    # The update loader reads the same persistent user configuration, not a package default.
    assert load_config(str(path)).file_transfer.export_roots == ["/tmp/exports"]
    second = enabled_text(first, export_roots=["/tmp/exports"], allowed_projects=["project"])
    assert tomllib.loads(second) == tomllib.loads(first)
    assert tomllib.loads(second)["threaddesk"] == tomllib.loads(raw)["threaddesk"]


def test_existing_source_hosts_and_limits_remain_explicit():
    raw = (
        '[file_transfer]\nenabled=false\nsource_hosts=["files.example"]\n'
        "[file_transfer.limits]\nchunk_bytes=32768\n"
    )
    parsed = tomllib.loads(enabled_text(raw, export_roots=[], allowed_projects=["project"]))
    assert parsed["file_transfer"]["enabled"] is True
    assert parsed["file_transfer"]["source_hosts"] == ["files.example"]
    assert parsed["file_transfer"]["limits"]["chunk_bytes"] == 32768


def test_disabled_transfer_allows_scoped_inspection_but_refuses_writes(config):
    calls = []

    def principal(identity, capability):
        calls.append((identity, capability))
        if identity != "owner":
            raise BridgeError("forbidden", "Missing capability")
        return config.principals["local"]

    authorization = TransferAuthorization(config.file_transfer, principal)
    assert not config.file_transfer.enabled
    authorization.check("owner", "files.inspect")
    with pytest.raises(BridgeError) as denied:
        authorization.check("owner", "files.prepare")
    assert denied.value.code == "transfer_disabled"
    with pytest.raises(BridgeError) as foreign:
        authorization.check("other", "files.inspect")
    assert foreign.value.code == "forbidden"
    assert len(calls) == 3
