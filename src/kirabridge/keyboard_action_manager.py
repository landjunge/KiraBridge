"""Execute one explicitly revision-bound profile key/chord; never caller preview."""

from kirabridge.bridge_core.models import BridgeError, UncertainExecution
from kirabridge.keyboard_models import KeyboardActionInput
from kirabridge.keyboard_profiles import KeyboardProfile

ACTION_INPUTS = {"keyboard.action": KeyboardActionInput}


class KeyboardActionManager:
    def __init__(self, *, keyboard, profiles, desktop_input, authorize):
        self.keyboard, self.profiles = keyboard, profiles
        self.desktop_input, self.authorize = desktop_input, authorize

    async def execute(self, task, args, running, progress=None):
        principal = task["principal"]

        def authorize():
            self.authorize(principal, "keyboard.action")
            self.authorize(principal, "keyboard.profiles.get")

        authorize()
        async with self.desktop_input.transaction() as turn:
            authorize()
            snapshot = self.profiles.authorized_snapshot(
                principal, args.profile_id, args.expected_revision
            )
            profile = KeyboardProfile.model_validate(snapshot.document)
            action = profile.actions.get(args.action)
            if action is None:
                raise BridgeError("keyboard_profile_action_missing", "Profile action not found")
            if action.candidate_only:
                raise BridgeError(
                    "keyboard_profile_candidate_only", "Observed menu candidates cannot execute"
                )
            binding = {"id": snapshot.id, "revision": snapshot.revision, "action": args.action}
            payload = {
                "target": args.target.model_dump(),
                "key": action.key.model_dump(exclude_none=True),
                "profile_context": {**binding, "app": profile.app.model_dump(exclude_none=True)},
            }
            operation = "keyboard.profile.chord" if action.modifiers else "keyboard.profile.key"
            if action.modifiers:
                payload["modifiers"] = list(action.modifiers)
            evidence = {
                "evidence_type": "keyboard_profile_snapshot_bound",
                "profile_binding": dict(binding),
                "profile_snapshot": snapshot.document,
                "input_attempted": False,
                "automatic_retry": False,
            }
            # The complete immutable source survives later profile updates/deletion.
            await (progress(evidence) if progress is not None else running(evidence))
            await running(
                {
                    "evidence_type": "native_keyboard_profile_attempt",
                    "profile_binding": dict(binding),
                    "automatic_retry": False,
                }
            )

            def before_send():
                authorize()
                current = self.profiles.authorized_snapshot(
                    principal, args.profile_id, args.expected_revision
                )
                if current != snapshot:
                    raise BridgeError("keyboard_profile_conflict", "Bound profile snapshot changed")

            result = await self.keyboard.send_pair_in_turn(
                principal, operation, payload, turn, before_send=before_send
            )
            if (
                result.get("profile_binding_verified") is not True
                or result.get("profile_binding") != binding
            ):
                raise UncertainExecution(
                    "keyboard_profile_action_unknown",
                    "Native profile binding is unverified; no replay",
                )
            return {
                **result,
                "profile_id": snapshot.id,
                "profile_revision": snapshot.revision,
                "action": args.action,
                "automatic_retry": False,
            }
