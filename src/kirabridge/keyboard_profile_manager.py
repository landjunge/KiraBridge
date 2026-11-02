"""Core-local profile CRUD and caller-only preview; never native input authority."""

from typing import Annotated

from pydantic import Field, model_validator

from kirabridge.bridge_core.models import BridgeError, EmptyInput, Input
from kirabridge.keyboard_profiles import (
    KeyboardProfile,
    KeyboardProfileStore,
    Label,
    Revision,
    Slug,
)

ActionName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.-]{0,79}$")]


class ProfileGetInput(Input):
    profile_id: Slug
    previous: bool = False


class ProfilePutInput(Input):
    profile: KeyboardProfile
    expected_revision: Revision | None = None


class ProfileDeleteInput(Input):
    profile_id: Slug
    expected_revision: Revision


class ProfilePreviewContext(Input):
    bundle_id: str = Field(pattern=r"^[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$", max_length=255)
    version: Label | None = None
    build: Label | None = None
    signing_team_id: str | None = Field(default=None, pattern=r"^[A-Z0-9]{10}$")
    language: Label | None = None
    layout_id: Label | None = None
    keyboard_type: int | None = Field(default=None, ge=0, le=2**32 - 1)
    field_role: str | None = Field(default=None, pattern=r"^AX[A-Za-z0-9]{1,62}$")


class ProfileResolveInput(Input):
    action: ActionName
    context: ProfilePreviewContext
    profile_id: Slug | None = None
    expected_revision: Revision | None = None

    @model_validator(mode="after")
    def revision_requires_id(self):
        if self.expected_revision is not None and self.profile_id is None:
            raise ValueError("A profile revision requires its explicit profile ID")
        return self


PROFILE_INPUTS = {
    "keyboard.profiles.list": EmptyInput,
    "keyboard.profiles.get": ProfileGetInput,
    "keyboard.profiles.put": ProfilePutInput,
    "keyboard.profiles.delete": ProfileDeleteInput,
    "keyboard.profiles.resolve": ProfileResolveInput,
}
PROFILE_WRITES = frozenset({"keyboard.profiles.put", "keyboard.profiles.delete"})
RANK = {"user": 3, "confirmed_app": 2, "observed_menu": 1}


def _view(snapshot):
    return {"profile_id": snapshot.id, "revision": snapshot.revision, "profile": snapshot.document}


def _summary(snapshot):
    profile = snapshot.document
    return {
        "profile_id": snapshot.id,
        "revision": snapshot.revision,
        "app": profile["app"],
        "action_count": len(profile["actions"]),
    }


def resolve_preview(snapshots, args):
    """Match immutable local snapshots to untrusted caller claims; no observations."""
    snapshots = tuple(s for s in snapshots if args.profile_id in {None, s.id})
    if args.profile_id is not None:
        if not snapshots:
            raise BridgeError("keyboard_profile_not_found", "Profile not found")
        if args.expected_revision is not None and snapshots[0].revision != args.expected_revision:
            raise BridgeError("keyboard_profile_conflict", "Profile revision changed")
    context = args.context.model_dump(exclude_none=True)
    matches, unknown, reasons = [], [], []
    for snapshot in snapshots:
        profile = KeyboardProfile.model_validate(snapshot.document)
        action = profile.actions.get(args.action)
        if action is None:
            reasons.append({"profile_id": snapshot.id, "reason": "action_missing"})
            continue
        missing, mismatch = [], []
        for name, wanted in profile.app.model_dump(exclude_none=True).items():
            actual = context.get("field_role" if name == "field_roles" else name)
            if actual is None:
                missing.append(name)
            elif (name == "field_roles" and actual not in wanted) or (
                name != "field_roles" and actual != wanted
            ):
                mismatch.append(name)
        if mismatch:
            reasons.append(
                {"profile_id": snapshot.id, "reason": "context_mismatch", "fields": mismatch}
            )
            continue
        entry = {
            "profile_id": snapshot.id,
            "revision": snapshot.revision,
            "provenance": action.provenance,
            "key": action.key.model_dump(exclude_none=True),
            "modifiers": list(action.modifiers),
        }
        if missing:
            unknown.append(entry)
            reasons.append(
                {"profile_id": snapshot.id, "reason": "context_missing", "fields": missing}
            )
        else:
            matches.append(entry)
    result = {
        "effect": "none",
        "input_attempted": False,
        "context_verified": False,
        "context_source": "caller_preview",
        "preview_only": True,
        "execution_authorized": False,
        "action": args.action,
        "reasons": reasons,
    }
    best = max((RANK[entry["provenance"]] for entry in matches), default=0)
    blocking = [entry["profile_id"] for entry in unknown if RANK[entry["provenance"]] >= best]
    if blocking:
        return {**result, "status": "context_unknown", "profiles": blocking}
    preferred = [entry for entry in matches if RANK[entry["provenance"]] == best]
    if len(preferred) > 1:
        return {
            **result,
            "status": "ambiguous",
            "profiles": [entry["profile_id"] for entry in preferred],
        }
    if not preferred:
        return {**result, "status": "not_found"}
    selected = preferred[0]
    candidate = selected["provenance"] == "observed_menu"
    return {
        **result,
        "status": "candidate_only" if candidate else "resolved",
        "candidate_only": candidate,
        "selection": selected,
    }


class KeyboardProfileManager:
    def __init__(self, data_dir, authorize, desktop_input):
        self.data_dir, self.authorize, self.desktop_input = data_dir, authorize, desktop_input
        self._store = None  # No startup IO; even directory creation requires authorization.

    def authorized_snapshot(self, principal, profile_id, expected_revision):
        """Internal action binding; always recheck read authorization and exact CAS."""
        self.authorize(principal, "keyboard.profiles.get")
        if self._store is None:
            self._store = KeyboardProfileStore(self.data_dir)
        snapshot = self._store.get(profile_id)
        if snapshot.revision != expected_revision:
            raise BridgeError("keyboard_profile_conflict", "Profile revision changed")
        return snapshot

    async def execute(self, task, args, running):
        operation, principal = task["operation"], task["principal"]
        self.authorize(principal, operation)

        async def perform(turn=None):
            await running(
                {
                    "evidence_type": "keyboard_profile_operation",
                    "operation": operation,
                    "input_attempted": False,
                    "automatic_retry": False,
                }
            )
            self.authorize(principal, operation)
            if turn is not None:
                turn.mark_attempted()
            if self._store is None:
                self._store = KeyboardProfileStore(self.data_dir)
            store = self._store
            common = {"input_attempted": False, "automatic_retry": False}
            if operation == "keyboard.profiles.list":
                return {**common, "effect": "none", "profiles": [_summary(s) for s in store.list()]}
            if operation == "keyboard.profiles.get":
                snapshot = store.get(args.profile_id, previous=args.previous)
                return {**common, "effect": "none", "previous": args.previous, **_view(snapshot)}
            if operation == "keyboard.profiles.put":
                snapshot = store.put(args.profile, expected_revision=args.expected_revision)
                return {**common, "effect": "profile_updated", **_view(snapshot)}
            if operation == "keyboard.profiles.delete":
                store.delete(args.profile_id, expected_revision=args.expected_revision)
                return {
                    **common,
                    "effect": "profile_deleted",
                    "profile_id": args.profile_id,
                    "revision": args.expected_revision,
                    "deleted": True,
                }
            snapshots = (store.get(args.profile_id),) if args.profile_id else store.list()
            return resolve_preview(snapshots, args)

        if operation in PROFILE_WRITES:
            async with self.desktop_input.transaction() as turn:
                return await perform(turn)
        return await perform()
