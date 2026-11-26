"""KirOS view of the kirabridge.kiros_api facade: stability contract, no secrets."""

from __future__ import annotations

import re

import pytest

from kirabridge import kiros_api

EXPECTED_NAMES = {
    "ACPClient",
    "OPENROUTER_DEFAULT_MODEL",
    "OPENROUTER_DEEPSEEK_MAX_PRICE",
    "OPENROUTER_FREE_MODELS",
    "OPENROUTER_PAID_MODELS",
    "OpenRouterAdapter",
    "credential_status",
    "keychain_credential",
    "record_completion",
}

_SECRET_SHAPE = re.compile(r"sk-[A-Za-z0-9_-]{8,}|[A-Za-z0-9_-]{32,}")


def test_all_names_importable_from_caller_view():
    for name in EXPECTED_NAMES:
        assert hasattr(kiros_api, name), f"{name} is missing from the facade"


def test_all_matches_stability_contract():
    assert set(kiros_api.__all__) == EXPECTED_NAMES
    assert sorted(kiros_api.__all__) == list(kiros_api.__all__)


def test_exported_types_unchanged():
    assert isinstance(kiros_api.OPENROUTER_FREE_MODELS, frozenset)
    assert isinstance(kiros_api.OPENROUTER_PAID_MODELS, frozenset)
    assert isinstance(kiros_api.OPENROUTER_DEEPSEEK_MAX_PRICE, dict)
    assert isinstance(kiros_api.OPENROUTER_DEFAULT_MODEL, str)
    assert kiros_api.OPENROUTER_DEFAULT_MODEL in kiros_api.OPENROUTER_FREE_MODELS
    assert not (kiros_api.OPENROUTER_FREE_MODELS & kiros_api.OPENROUTER_PAID_MODELS)


def test_facade_reexports_are_canonical_objects():
    from kirabridge import openrouter_models
    from kirabridge.agent_manager import acp, openrouter, openrouter_credentials
    from kirabridge.completion_handoff import record_completion as canonical_record

    assert kiros_api.OpenRouterAdapter is openrouter.OpenRouterAdapter
    assert kiros_api.ACPClient is acp.ACPClient
    assert kiros_api.keychain_credential is openrouter_credentials.keychain_credential
    assert kiros_api.credential_status is openrouter_credentials.credential_status
    assert kiros_api.record_completion is canonical_record
    assert kiros_api.OPENROUTER_FREE_MODELS is openrouter_models.OPENROUTER_FREE_MODELS
    assert kiros_api.OPENROUTER_PAID_MODELS is openrouter_models.OPENROUTER_PAID_MODELS
    assert kiros_api.OPENROUTER_DEFAULT_MODEL == openrouter_models.OPENROUTER_DEFAULT_MODEL
    assert kiros_api.OPENROUTER_DEEPSEEK_MAX_PRICE == (
        openrouter_models.OPENROUTER_DEEPSEEK_MAX_PRICE
    )


def test_no_export_is_a_secret_string():
    for name in kiros_api.__all__:
        value = getattr(kiros_api, name)
        if isinstance(value, str):
            assert not _SECRET_SHAPE.fullmatch(value), f"{name} looks like a secret"
        elif isinstance(value, (frozenset, set)):
            assert all(not _SECRET_SHAPE.fullmatch(item) for item in value)
        elif isinstance(value, dict):
            assert all(not _SECRET_SHAPE.fullmatch(str(item)) for item in value)


def test_facade_exports_are_callable_or_data():
    for name in kiros_api.__all__:
        value = getattr(kiros_api, name)
        assert callable(value) or isinstance(value, (str, dict, frozenset)), (
            f"{name} has an unexpected export kind {type(value)!r}"
        )


@pytest.mark.parametrize("name", sorted(EXPECTED_NAMES))
def test_name_importable_via_from_import(name):
    assert getattr(__import__("kirabridge.kiros_api", fromlist=[name]), name) is not None
