"""Route explicit input intent without owning approvals, native IO or retries."""

from kirabridge.slash_commands import command_name


def input_kind(args):
    if args.key is not None:
        return "observed_return"
    return "slash_command" if command_name(args.text) is not None else "literal_text"


async def execute(bridge, task, args, target, binding, running, progress):
    kind = input_kind(args)
    if kind == "observed_return":
        from kirabridge.session_return import execute as return_execute

        result = await return_execute(bridge, task, args, running, progress)
    elif kind == "slash_command":
        from kirabridge.slash_commands import execute as slash_execute

        result = await slash_execute(bridge, task, args, target, binding, running, progress)
    else:
        from kirabridge.literal_session_input import execute as literal_execute

        result = await literal_execute(bridge, task, args, target, binding, running, progress)
    return {**result, "input_kind": result.get("input_kind", kind)}
