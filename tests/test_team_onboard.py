import json
from types import SimpleNamespace

import pytest

from kirabridge.bridge_core.bridge import Bridge  # noqa: F401  (conftest parity)
from kirabridge.bridge_core.config import AgentConfig, TeamConfig, TeamWorkerConfig
from kirabridge.bridge_core.models import BridgeError
from kirabridge.team_manager import TeamManager
from kirabridge.team_manager.models import TeamCreate, TeamOnboardRegister


@pytest.fixture
def domain(bridge, config):
    for name in ("local", "codex"):
        policy = config.principals["local"].model_copy(deep=True)
        policy.capabilities += ["team.manage", "team.read", "team.write"]
        policy.approval_mode = "automatic"
        config.principals[name] = policy
    root = config.principals["local"].roots[0]
    config.agents = {"codex": AgentConfig(kind="codex")}
    config.team = TeamConfig(
        enabled=True,
        workers={"local": TeamWorkerConfig(), "codex": TeamWorkerConfig(agent="codex", cwd=root)},
    )
    manager = TeamManager(bridge)
    manager.create(
        "local",
        TeamCreate(
            team_id="test-team", name="t", members={"local": "worker", "codex": "worker"},
            coordinator="local", idempotency_key="create",
        ),
    )
    return manager


def files(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[daemon]\nport = 8765\n')
    creds = tmp_path / "credentials.json"
    creds.write_text(json.dumps({"local": "x" * 48, "codex": "y" * 48}))
    return cfg, creds


def request(cfg, creds, **changes):
    return TeamOnboardRegister(
        **{"identity": "worker9", "config_path": str(cfg), "credentials_path": str(creds),
           "capabilities": [], "message_peers": ["local"], **changes}
    )


def fake_probe(load_module_attr):
    def probe(_path):
        return load_module_attr
    return probe


def test_register_writes_sections_token_and_flags(tmp_path, domain, monkeypatch):
    cfg, creds = files(tmp_path)
    seen = {}

    def ok_probe(path):
        seen["text"] = open(path).read()
        return SimpleNamespace(
            principals={"worker9": object()},
            team=SimpleNamespace(workers={"worker9": object()}),
        )

    monkeypatch.setattr("kirabridge.bridge_core.config.load_config", ok_probe)
    out = domain.onboard_register("local", request(cfg, creds))
    assert out["registered"] == "written" and out["token"] == "generated"
    assert out["needs_restart"] is True and out["live"] is False
    text = cfg.read_text()
    assert "[principals.worker9]" in text and "[team.workers.worker9]" in text
    assert "KIRABRIDGE_WORKER9_TOKEN" in text
    saved = json.loads(creds.read_text())
    assert len(saved["worker9"]) >= 32 and "local" in saved
    assert saved["worker9"] not in json.dumps(out)


def test_rerun_is_idempotent_without_new_backups(tmp_path, domain, monkeypatch):
    cfg, creds = files(tmp_path)
    monkeypatch.setattr(
        "kirabridge.bridge_core.config.load_config",
        lambda _p: SimpleNamespace(principals={"worker9": object()},
                                   team=SimpleNamespace(workers={"worker9": object()})),
    )
    domain.onboard_register("local", request(cfg, creds))
    backups = list(tmp_path.glob("*.bak-*"))
    out = domain.onboard_register("local", request(cfg, creds))
    assert out["registered"] == "already" and out["token"] == "present"
    assert list(tmp_path.glob("*.bak-*")) == backups


def test_non_owner_principal_is_refused(tmp_path, domain):
    cfg, creds = files(tmp_path)
    with pytest.raises(BridgeError, match="owner"):
        domain.onboard_register("codex", request(cfg, creds))


def test_half_registered_identity_halts_conservatively(tmp_path, domain):
    cfg, creds = files(tmp_path)
    cfg.write_text(cfg.read_text() + "\n[principals.worker9]\n")
    with pytest.raises(BridgeError, match="Half-registered"):
        domain.onboard_register("local", request(cfg, creds))
    assert "[team.workers.worker9]" not in cfg.read_text()


def test_owner_identity_cannot_be_onboarded(tmp_path, domain):
    cfg, creds = files(tmp_path)
    with pytest.raises(BridgeError, match="never onboarded"):
        domain.onboard_register("local", request(cfg, creds, identity="local"))


def test_invalid_candidate_restores_files(tmp_path, domain, monkeypatch):
    cfg, creds = files(tmp_path)
    before_cfg, before_creds = cfg.read_text(), creds.read_text()

    def broken(_path):
        raise ValueError("candidate invalid")

    monkeypatch.setattr("kirabridge.bridge_core.config.load_config", broken)
    with pytest.raises(BridgeError, match="Registration aborted"):
        domain.onboard_register("local", request(cfg, creds))
    assert cfg.read_text() == before_cfg and creds.read_text() == before_creds


def test_missing_credentials_file_is_refused(tmp_path, domain):
    cfg, _ = files(tmp_path)
    with pytest.raises(BridgeError, match="must already exist"):
        domain.onboard_register("local", request(cfg, tmp_path / "nope.json"))
