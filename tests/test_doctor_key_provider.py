from pathlib import Path
import pytest
from kirabridge.doctor_key_provider import load_systemd_credential


def test_systemd_key(monkeypatch, tmp_path):
    (tmp_path / 'doctor-hmac-key').write_bytes(b'a' * 32)
    monkeypatch.setenv('CREDENTIALS_DIRECTORY', str(tmp_path))
    assert load_systemd_credential() == b'a' * 32


def test_missing_and_invalid(monkeypatch, tmp_path):
    monkeypatch.delenv('CREDENTIALS_DIRECTORY', raising=False)
    with pytest.raises(RuntimeError): load_systemd_credential()
    monkeypatch.setenv('CREDENTIALS_DIRECTORY', str(tmp_path))
    (tmp_path / 'doctor-hmac-key').write_bytes(b'short')
    with pytest.raises(ValueError): load_systemd_credential()
    with pytest.raises(ValueError): load_systemd_credential('../secret')


def test_platform_dispatch(monkeypatch, tmp_path):
    from kirabridge.doctor_key_provider import load_doctor_key
    (tmp_path / 'doctor-hmac-key').write_bytes(b'b' * 32)
    monkeypatch.setenv('CREDENTIALS_DIRECTORY', str(tmp_path))
    assert load_doctor_key('linux') == b'b' * 32
    with pytest.raises(RuntimeError, match='Keychain'):
        load_doctor_key('darwin')
    with pytest.raises(RuntimeError, match='unsupported'):
        load_doctor_key('win32')
