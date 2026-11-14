"""A changed AX wrapper needs a retained tab or CG identity, not just a title."""

import pytest
from test_terminal_window_creation import product  # noqa: F401

from kirabridge.bridge_core.models import UncertainExecution


@pytest.mark.parametrize(
    "hidden,same_cg", [(True, True), (False, True), (False, False), (True, False)]
)
async def test_detached_wrapper_requires_retained_own_native_identity(
    product,  # noqa: F811
    hidden,
    same_cg,
):
    scene, leaf, events, _, created = product
    scene.no_own_group = hidden
    groups = scene.groups

    def surfaces():
        current = groups()
        if scene.phase == "detached" and not same_cg:
            return [
                (777 if index == 0 else 999, title, count)
                for index, (_, title, count) in enumerate(current)
            ]
        return current

    scene.groups = surfaces
    request = leaf.system_transport.request
    own_old_token = f"{1 if hidden else 2:032x}"
    own_new_token = "f" * 32

    async def replaced_wrapper(operation, arguments, **kwargs):
        forwarded = dict(arguments)
        if scene.phase == "detached" and forwarded.get("element_token") == own_new_token:
            forwarded["element_token"] = own_old_token
        value = await request(operation, forwarded, **kwargs)
        if scene.phase == "detached" and operation == "accessibility.inspect":
            if "element_token" not in arguments:
                own = next(c for c in value["children"] if c["element_token"] == own_old_token)
                own["element_token"] = own_new_token
            elif arguments["element_token"] == own_new_token:
                value["element_token"] = own_new_token
        return value

    leaf.system_transport.request = replaced_wrapper
    if hidden and not same_cg:
        with pytest.raises(UncertainExecution) as failure:
            await leaf.open("", on_created=created, principal="chatgpt")
        assert failure.value.provider_error["cause_message"] == (
            "Detached own native identity is unconfirmed"
        )
    else:
        result = await leaf.open("", on_created=created, principal="chatgpt")
        proof = result["physical_window"]
        assert proof["ax_window_token"] == own_new_token
        assert proof["own_identity_basis"] == ("same_cg_window" if same_cg else "same_selected_tab")
        await leaf.verify_opened(result, principal="chatgpt")
    # An unconfirmed observation never causes a second detach or new creation.
    assert events == ["create", "receipt", "focus", "move"]
