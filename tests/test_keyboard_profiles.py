"""Private profile contracts using temporary files only; no desktop or worker."""

import dataclasses
import json
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from kirabridge import keyboard_profiles as profiles
from kirabridge.bridge_core.models import BridgeError
from kirabridge.keyboard_profiles import MAX_FILE, KeyboardProfile, KeyboardProfileStore

pytestmark = pytest.mark.skipif(profiles.fcntl is None, reason="POSIX profile store required")


@pytest.fixture
def tmp_path(tmp_path):
    return tmp_path.resolve()  # Store refuses symlink ancestors, including macOS /var.


def profile(identifier="editor", character="a", **action):
    return {
        "id": identifier,
        "app": {"bundle_id": "org.example.Editor"},
        "actions": {
            "select_all": {
                "key": {"character": character},
                "modifiers": ["command"],
                "provenance": "observed_menu",
                **action,
            }
        },
    }


def test_cas_previous_restart_and_frozen_snapshot(tmp_path):
    store = KeyboardProfileStore(tmp_path / "state")
    first = store.put(profile())
    assert store.get(first.id) == first
    copied = first.document
    copied["actions"]["select_all"]["provenance"] = "user"
    assert first.document["actions"]["select_all"]["provenance"] == "observed_menu"
    assert KeyboardProfile.model_validate(first.document).actions["select_all"].candidate_only
    with pytest.raises(dataclasses.FrozenInstanceError):
        first.revision = "f" * 64
    second = store.put(profile(character="b"), expected_revision=first.revision)
    with pytest.raises(BridgeError, match="revision changed"):
        store.put(profile(character="c"), expected_revision=first.revision)
    restarted = KeyboardProfileStore(tmp_path / "state")
    assert restarted.get(first.id) == second
    assert restarted.get(first.id, previous=True) == first
    assert restarted.list() == (second,)
    third = restarted.put(profile(character="c"), expected_revision=second.revision)
    assert restarted.put(profile(character="c"), expected_revision=third.revision) == third
    assert restarted.get(first.id, previous=True) == second
    with pytest.raises(BridgeError):
        restarted.delete(first.id, expected_revision=second.revision)
    restarted.delete(first.id, expected_revision=third.revision)
    assert restarted.list() == ()


def test_optional_constraints_and_plain_key_remain_declarative(tmp_path):
    value = profile(modifiers=[], provenance="user")
    value["app"].update(
        version="1.2.3",
        build="42",
        signing_team_id="ABCD123456",
        language="de-DE",
        layout_id="com.apple.keylayout.German",
        keyboard_type=40,
        field_roles=["AXTextArea"],
    )
    stored = KeyboardProfileStore(tmp_path / "state").put(value)
    assert stored.document["actions"]["select_all"]["modifiers"] == []
    assert stored.document["app"] == value["app"]


@pytest.mark.parametrize(
    "change",
    [
        {"id": "../outside"},
        {"text": "forbidden"},
        {"pid": 123},
        {
            "actions": {
                "run": {
                    "key": {"named": "enter"},
                    "modifiers": ["shift", "shift"],
                    "provenance": "user",
                }
            }
        },
        {
            "actions": {
                "run": {"key": {"named": "enter"}, "provenance": "observed_menu", "confirmed": True}
            }
        },
    ],
)
def test_invalid_definition_never_changes_active_file(tmp_path, change):
    store = KeyboardProfileStore(tmp_path / "state")
    first = store.put(profile())
    path = tmp_path / "state/keyboard/profiles/editor.json"
    before = path.read_bytes()
    with pytest.raises(BridgeError):
        store.put({**profile(), **change}, expected_revision=first.revision)
    assert path.read_bytes() == before and store.get("editor") == first


def test_utf8_payload_file_and_profile_count_limits(tmp_path):
    store = KeyboardProfileStore(tmp_path / "state")
    huge = profile()
    huge["actions"] = {
        "action_" + str(i) + "x" * 60: {
            "key": {"character": "😀"},
            "modifiers": ["command", "shift", "control", "option"],
            "provenance": "user",
        }
        for i in range(200)
    }
    with pytest.raises(BridgeError, match="24 KiB"):
        store.put(huge)
    assert store.list() == ()
    for i in range(64):
        store.put(profile(identifier="p" + str(i)))
    with pytest.raises(BridgeError, match="64 active"):
        store.put(profile(identifier="overflow"))
    path = tmp_path / "state/keyboard/profiles/p0.json"
    path.write_bytes(b"x" * (MAX_FILE + 1))
    with pytest.raises(BridgeError, match="64 KiB"):
        store.get("p0")


@pytest.mark.parametrize("kind", ["symlink", "fifo", "public_file"])
def test_unsafe_profile_files_refused_before_read(tmp_path, kind):
    store = KeyboardProfileStore(tmp_path / "state")
    path = tmp_path / "state/keyboard/profiles/editor.json"
    outside = tmp_path / "outside.json"
    outside.write_text("protected")
    if kind == "symlink":
        path.symlink_to(outside)
    elif kind == "fifo":
        os.mkfifo(path, 0o600)
    else:
        path.write_text("{}")
        path.chmod(0o644)
    with pytest.raises(BridgeError):
        store.get("editor")
    assert outside.read_text() == "protected"


def test_private_modes_anchor_and_lock_symlinks(tmp_path):
    store = KeyboardProfileStore(tmp_path / "state")
    store.put(profile())
    folder = tmp_path / "state/keyboard/profiles"
    assert all(
        (p.stat().st_mode & 0o777) == 0o700 for p in [tmp_path / "state", folder.parent, folder]
    )
    assert all((p.stat().st_mode & 0o777) == 0o600 for p in folder.iterdir())
    (folder / ".lock").unlink()
    target = tmp_path / "lock-target"
    target.write_text("untouched")
    (folder / ".lock").symlink_to(target)
    with pytest.raises(BridgeError):
        store.get("editor")
    assert target.read_text() == "untouched"
    (tmp_path / "alias").symlink_to(tmp_path / "state", target_is_directory=True)
    with pytest.raises(BridgeError):
        KeyboardProfileStore(tmp_path / "alias")


def test_content_tampering_and_interrupted_temp_write_preserve_active(tmp_path, monkeypatch):
    store = KeyboardProfileStore(tmp_path / "state")
    first = store.put(profile())
    path = tmp_path / "state/keyboard/profiles/editor.json"
    before = path.read_bytes()
    original = os.fsync

    def fail_file(fd):
        raise OSError("synthetic fsync failure before replace")

    monkeypatch.setattr(os, "fsync", fail_file)
    with pytest.raises(BridgeError):
        store.put(profile(character="b"), expected_revision=first.revision)
    assert path.read_bytes() == before
    monkeypatch.setattr(os, "fsync", original)
    value = json.loads(before)
    value["current"]["profile"]["app"]["bundle_id"] = "org.example.Other"
    path.write_text(json.dumps(value))
    with pytest.raises(BridgeError, match="Invalid stored"):
        store.get("editor")


def test_two_thread_writers_have_exactly_one_cas_winner(tmp_path):
    root = tmp_path / "state"
    first = KeyboardProfileStore(root).put(profile())
    barrier = Barrier(2)

    def writer(character):
        store = KeyboardProfileStore(root)
        barrier.wait(timeout=5)
        try:
            return store.put(profile(character=character), expected_revision=first.revision)
        except BridgeError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as threads:
        results = list(threads.map(writer, ["b", "c"]))
    errors = [result for result in results if isinstance(result, str)]
    assert len(errors) == 1 and errors[0] in {"keyboard_profile_conflict", "keyboard_profile_busy"}
    winner = next(result for result in results if not isinstance(result, str))
    store = KeyboardProfileStore(root)
    assert store.get("editor") == winner and store.get("editor", previous=True) == first


@pytest.mark.parametrize("operation", ["read", "put"])
def test_independently_held_writer_lock_refuses_before_io(tmp_path, operation):
    store = KeyboardProfileStore(tmp_path / "state")
    first = store.put(profile())
    folder = tmp_path / "state/keyboard/profiles"
    before = (folder / "editor.json").read_bytes()
    lock = os.open(folder / ".lock", os.O_RDWR)
    profiles.fcntl.flock(lock, profiles.fcntl.LOCK_EX | profiles.fcntl.LOCK_NB)

    def request():
        try:
            if operation == "read":
                store.get("editor")
            else:
                store.put(profile(character="b"), expected_revision=first.revision)
        except BridgeError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=1) as thread:
        future = thread.submit(request)
        try:
            assert future.result(timeout=1) == "keyboard_profile_busy"
        finally:
            profiles.fcntl.flock(lock, profiles.fcntl.LOCK_UN)
            os.close(lock)
    assert (folder / "editor.json").read_bytes() == before


def test_unsupported_lock_platform_leaves_no_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(profiles, "fcntl", None)
    assert KeyboardProfile.model_validate(profile()).id == "editor"
    with pytest.raises(BridgeError) as error:
        KeyboardProfileStore(tmp_path / "uncreated")
    assert error.value.code == "keyboard_profile_unsupported"
    assert not (tmp_path / "uncreated").exists()
