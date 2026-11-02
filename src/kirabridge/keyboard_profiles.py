"""Private declarative keyboard profiles; no grants, resolution or execution.

Each <=64 KiB envelope atomically keeps current plus its immediate predecessor.
Profile payloads are <=24 KiB. Exact optional constraints are data, never inferred.
observed_menu actions remain candidates; storage never confirms or executes them.
"""

import hashlib
import json
import os
import re
import stat
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, ValidationError, model_validator

from kirabridge.bridge_core.models import BridgeError, Input, UncertainExecution, canonical
from kirabridge.keyboard_models import KeyboardKey, Modifier

try:
    import fcntl
except ImportError:
    fcntl = None

MAX_PAYLOAD = 24 * 1024
MAX_FILE = 64 * 1024
MAX_PROFILES = 64
SLUG = r"[a-z][a-z0-9_-]{0,63}"
Slug = Annotated[str, Field(pattern="^" + SLUG + "$")]
Revision = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Label = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.+-]+$")]


class ProfileApp(Input):
    bundle_id: str = Field(pattern=r"^[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$", max_length=255)
    version: Label | None = None
    build: Label | None = None
    signing_team_id: str | None = Field(default=None, pattern=r"^[A-Z0-9]{10}$")
    language: Label | None = None
    layout_id: Label | None = None
    keyboard_type: int | None = Field(default=None, ge=0, le=2**32 - 1)
    field_roles: list[Annotated[str, Field(pattern=r"^AX[A-Za-z0-9]{1,62}$")]] | None = Field(
        default=None, min_length=1, max_length=16
    )

    @model_validator(mode="after")
    def unique_roles(self):
        if self.field_roles and len(set(self.field_roles)) != len(self.field_roles):
            raise ValueError("Field roles must be unique")
        return self


class ProfileAction(Input):
    key: KeyboardKey
    modifiers: list[Modifier] = Field(default_factory=list, max_length=4)
    provenance: Literal["user", "confirmed_app", "observed_menu"]

    @model_validator(mode="after")
    def unique_modifiers(self):
        if len(set(self.modifiers)) != len(self.modifiers):
            raise ValueError("Modifiers must be unique")
        return self

    @property
    def candidate_only(self):
        return self.provenance == "observed_menu"


class KeyboardProfile(Input):
    schema_name: Literal["kirabridge.keyboard-profile.v1"] = Field(
        default="kirabridge.keyboard-profile.v1", alias="schema"
    )
    id: Slug
    app: ProfileApp
    actions: dict[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.-]{0,79}$")], ProfileAction] = (
        Field(min_length=1, max_length=512)
    )


class _Record(Input):
    profile: KeyboardProfile
    revision: Revision


class _Envelope(Input):
    current: _Record
    previous: _Record | None = None


@dataclass(frozen=True)
class ProfileSnapshot:
    id: str
    revision: str
    profile_json: bytes

    @property
    def document(self):
        """A new mutable copy; the stored snapshot itself is immutable."""
        return json.loads(self.profile_json)


def _payload(profile):
    value = profile.model_dump(mode="json", by_alias=True, exclude_none=True)
    raw = canonical(value).encode("utf-8")
    if len(raw) > MAX_PAYLOAD:
        raise BridgeError("keyboard_profile_limit", "Profile exceeds 24 KiB of UTF-8")
    return raw


def _pairs(items):
    value = {}
    for key, item in items:
        if key in value:
            raise ValueError("Duplicate JSON key")
        value[key] = item
    return value


class KeyboardProfileStore:
    def __init__(self, data_dir):
        if fcntl is None:
            raise BridgeError(
                "keyboard_profile_unsupported", "Profile storage requires POSIX locks"
            )
        self.data_dir = Path(data_dir).absolute()
        if ".." in self.data_dir.parts:
            raise BridgeError("keyboard_profile_storage_unsafe", "Unsafe directory anchor")
        with self._directory(create=True) as folder:
            lock = os.open(
                ".lock",
                os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,
                0o600,
                dir_fd=folder,
            )
            try:
                self._regular(lock)
            finally:
                os.close(lock)

    @staticmethod
    def _regular(fd):
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
        ):
            raise BridgeError("keyboard_profile_storage_unsafe", "Owner-only regular file required")
        if info.st_size > MAX_FILE:
            raise BridgeError("keyboard_profile_limit", "Profile file exceeds 64 KiB")
        return info

    @contextmanager
    def _directory(self, *, create=False):
        folder = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        parts = [*self.data_dir.parts[1:], "keyboard", "profiles"]
        try:
            for index, name in enumerate(parts):
                if create and index >= len(parts) - 3:
                    try:
                        os.mkdir(name, 0o700, dir_fd=folder)
                    except FileExistsError:
                        pass
                child = os.open(
                    name,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK,
                    dir_fd=folder,
                )
                os.close(folder)
                folder = child
                info = os.fstat(folder)
                if index >= len(parts) - 3 and (
                    info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700
                ):
                    raise BridgeError(
                        "keyboard_profile_storage_unsafe", "Private directory required"
                    )
            yield folder
        except OSError as error:
            raise BridgeError(
                "keyboard_profile_storage_unsafe", "Profile storage access refused"
            ) from error
        finally:
            os.close(folder)

    @contextmanager
    def _locked(self, *, shared=False):
        with self._directory() as folder:
            lock = os.open(".lock", os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=folder)
            try:
                self._regular(lock)
                try:
                    fcntl.flock(lock, (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB)
                except BlockingIOError as error:
                    raise BridgeError("keyboard_profile_busy", "Profile storage is busy") from error
                yield folder
            finally:
                os.close(lock)

    @staticmethod
    def _id(identifier):
        if not isinstance(identifier, str) or re.fullmatch(SLUG, identifier) is None:
            raise BridgeError("keyboard_profile_invalid", "Invalid profile ID")
        return identifier + ".json"

    def _read(self, folder, identifier):
        try:
            fd = os.open(
                self._id(identifier), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=folder
            )
        except FileNotFoundError:
            return None
        try:
            before = self._regular(fd)
            raw = os.read(fd, MAX_FILE + 1)
            after = os.fstat(fd)
            if len(raw) != before.st_size or (before.st_size, before.st_mtime_ns) != (
                after.st_size,
                after.st_mtime_ns,
            ):
                raise ValueError("Profile changed during read")
            envelope = _Envelope.model_validate(
                json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
            )
            for record in (envelope.current, envelope.previous):
                if record is not None and (
                    record.profile.id != identifier
                    or hashlib.sha256(_payload(record.profile)).hexdigest() != record.revision
                ):
                    raise ValueError("Profile content revision differs")
            return envelope
        except (ValueError, UnicodeError, TypeError, RecursionError) as error:
            raise BridgeError("keyboard_profile_invalid", "Invalid stored profile") from error
        finally:
            os.close(fd)

    @staticmethod
    def _snapshot(record):
        if record is None:
            raise BridgeError("keyboard_profile_not_found", "Profile version not found")
        return ProfileSnapshot(record.profile.id, record.revision, _payload(record.profile))

    def get(self, identifier, *, previous=False):
        self._id(identifier)
        with self._locked(shared=True) as folder:
            envelope = self._read(folder, identifier)
            if envelope is None:
                raise BridgeError("keyboard_profile_not_found", "Profile not found")
            return self._snapshot(envelope.previous if previous else envelope.current)

    def list(self):
        with self._locked(shared=True) as folder:
            names = []
            with os.scandir(folder) as entries:
                for entry in entries:
                    if re.fullmatch(SLUG + r"\.json", entry.name):
                        names.append(entry.name[:-5])
                        if len(names) > MAX_PROFILES:
                            raise BridgeError("keyboard_profile_limit", "Too many active profiles")
            return tuple(self._snapshot(self._read(folder, name).current) for name in sorted(names))

    def put(self, profile, *, expected_revision=None):
        try:
            value = (
                profile.model_dump(by_alias=True)
                if isinstance(profile, KeyboardProfile)
                else profile
            )
            # Round-trip primitive data so mutated model instances cannot bypass validation.
            definition = KeyboardProfile.model_validate(json.loads(canonical(value)))
            raw = _payload(definition)
        except (ValidationError, ValueError, UnicodeError, TypeError, RecursionError) as error:
            raise BridgeError("keyboard_profile_invalid", "Invalid profile definition") from error
        current = _Record(profile=definition, revision=hashlib.sha256(raw).hexdigest())
        with self._locked() as folder:
            old = self._read(folder, definition.id)
            if (old.current.revision if old else None) != expected_revision:
                raise BridgeError("keyboard_profile_conflict", "Profile revision changed")
            if old and old.current.revision == current.revision:
                return self._snapshot(old.current)
            if old is None:
                count = sum(
                    re.fullmatch(SLUG + r"\.json", name) is not None for name in os.listdir(folder)
                )
                if count >= MAX_PROFILES:
                    raise BridgeError("keyboard_profile_limit", "64 active profiles permitted")
            envelope = _Envelope(current=current, previous=old.current if old else None)
            encoded = canonical(
                envelope.model_dump(mode="json", by_alias=True, exclude_none=True)
            ).encode("utf-8")
            if len(encoded) > MAX_FILE:
                raise BridgeError("keyboard_profile_limit", "Profile envelope exceeds 64 KiB")
            name, temporary = (
                self._id(definition.id),
                "." + definition.id + "-" + uuid.uuid4().hex + ".tmp",
            )
            fd = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=folder,
            )
            try:
                with os.fdopen(fd, "wb") as stream:
                    self._regular(stream.fileno())
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
                try:
                    os.replace(temporary, name, src_dir_fd=folder, dst_dir_fd=folder)
                    os.fsync(folder)
                except OSError as error:
                    raise UncertainExecution(
                        "keyboard_profile_commit_unknown",
                        "Reconcile profile revision; never retry automatically",
                    ) from error
            finally:
                try:
                    os.unlink(temporary, dir_fd=folder)
                except FileNotFoundError:
                    pass
            return self._snapshot(current)

    def delete(self, identifier, *, expected_revision):
        name = self._id(identifier)
        with self._locked() as folder:
            old = self._read(folder, identifier)
            if old is None:
                raise BridgeError("keyboard_profile_not_found", "Profile not found")
            if old.current.revision != expected_revision:
                raise BridgeError("keyboard_profile_conflict", "Profile revision changed")
            try:
                os.unlink(name, dir_fd=folder)
                os.fsync(folder)
            except OSError as error:
                raise UncertainExecution(
                    "keyboard_profile_commit_unknown",
                    "Reconcile profile deletion; never retry automatically",
                ) from error
