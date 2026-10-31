"""A local reply needs independent process/file ownership and one exact new turn."""

import asyncio
import copy
import json
from types import SimpleNamespace

import pytest

from kirabridge.bridge_core.config import VisibleTerminalBinding
from kirabridge.bridge_core.models import BridgeError
from kirabridge.platform_adapters import codex_reply

THREAD = "01a192b9-64f2-7d22-8429-cabd5faf13b6"
TURN = "new-turn"
BODY = "Authorized body\nincluding this exact line"
ANSWER = "Observed final answer"
IDENTITY = "501 ttys001 Sat Oct 31 17:00:00 2026 100 /usr/local/bin/codex"


def events(body=BODY, answer=ANSWER, turn=TURN):
    return [
        {"type": "event_msg", "payload": {"type": "task_started", "turn_id": turn}},
        {
            "type": "event_msg",
            "payload": {
                "type": "item_completed",
                "thread_id": THREAD,
                "turn_id": turn,
                "item": {
                    "type": "UserMessage",
                    "id": "new-user",
                    "content": [{"type": "text", "text": body, "text_elements": []}],
                },
            },
        },
        {
            "type": "event_msg",
            "payload": {
                "type": "item_completed",
                "thread_id": THREAD,
                "turn_id": turn,
                "item": {
                    "type": "AgentMessage",
                    "id": "new-final",
                    "phase": "final_answer",
                    "content": [{"type": "Text", "text": answer}],
                },
            },
        },
        {
            "type": "event_msg",
            "payload": {
                "type": "task_complete",
                "turn_id": turn,
                "last_agent_message": answer,
            },
        },
    ]


def append(path, rows):
    with path.open("a") as stream:
        for row in rows:
            stream.write(json.dumps(row) + "\n")


class Pipe:
    def __init__(self, raw):
        self.raw = raw

    async def read(self, limit):
        part, self.raw = self.raw[:limit], self.raw[limit:]
        return part


@pytest.fixture
def bound(tmp_path, monkeypatch):
    root = tmp_path / "sessions"
    root.mkdir()
    path = root / "explicit-rollout.jsonl"
    append(
        path,
        [
            {
                "type": "session_meta",
                "payload": {"id": THREAD, "originator": "codex-tui", "cwd": str(tmp_path)},
            }
        ]
        + events(body="OLD unrelated input", answer="OLD final", turn="old-turn"),
    )
    binding = VisibleTerminalBinding(
        pane_id="terminal:101:ttys001",
        expected_pid=100,
        agent_pid=101,
        ready_pattern=r"(?m)^›\s*$",
        codex_thread_id=THREAD,
        codex_rollout_path=str(path),
    )
    fixture = SimpleNamespace(
        root=root,
        path=path,
        binding=binding,
        processes=[],
        reaped=[],
        identity=IDENTITY,
        writer_access="w",
        exit_code=0,
        raw_override=None,
    )

    async def process_identity(pid, *, detailed):
        assert pid == 101 and detailed is True
        return fixture.identity

    async def process_factory(*argv, **options):
        assert argv[:5] == ("/usr/sbin/lsof", "-a", "-p", "101", "-F0pfaDint")
        assert argv[5:] in [(), (str(path),)]
        assert options["stderr"] == asyncio.subprocess.DEVNULL
        metadata = path.stat()
        raw = (
            f"p101\0\nfcwd\0tDIR\0n{tmp_path}\0\nf15\0a{fixture.writer_access}\0tREG\0D0x{metadata.st_dev:x}\0"
            f"i{metadata.st_ino}\0n{path}\0\n"
        ).encode()
        child = SimpleNamespace(
            stdout=Pipe(raw if fixture.raw_override is None else fixture.raw_override)
        )
        child.returncode = fixture.exit_code

        async def wait():
            return child.returncode

        child.wait = wait
        fixture.processes.append(child)
        return child

    async def reap(child, *, process_group):
        assert process_group is False
        fixture.reaped.append(child)

    monkeypatch.setattr(codex_reply, "reap_process", reap)
    fixture.observe_identity = process_identity
    fixture.observer = codex_reply.CodexReplyObserver(root, process_factory=process_factory)
    return fixture


async def prepared(bound):
    result = await bound.observer.prepare(
        bound.binding,
        process_identity=bound.observe_identity,
        expected_identity=IDENTITY,
        body=BODY,
    )
    assert result["state"] == "ready", result
    return result["cursor"]


async def observe(bound, cursor):
    return await bound.observer.observe(
        cursor, bound.binding, body=BODY, process_identity=bound.observe_identity
    )


async def test_exact_new_bound_turn_returns_observed_final_without_mailbox_claim(bound):
    cursor = await prepared(bound)
    before_submit = await bound.observer.before_submit(cursor, bound.binding, body=BODY)
    assert before_submit == {"state": "ready", "cursor": cursor}
    append(bound.path, events())
    result = await observe(bound, cursor)
    assert result["state"] == "completed" and result["text"] == ANSWER
    assert result["turn_id"] == TURN
    assert result["reply_source"] == "bound_local_codex_rollout"
    assert result["agent_confirmed"] is False
    assert result["evidence"]["process_writer_verified"] is True
    assert "reply_id" not in result["evidence"]
    assert "authenticated_principal" not in result["evidence"]
    assert bound.processes == bound.reaped


async def test_preexisting_final_is_never_a_new_reply(bound):
    cursor = await prepared(bound)
    result = await observe(bound, cursor)
    assert result["state"] == "pending"
    assert len(bound.processes) == 1


async def test_a_turn_before_our_return_disables_local_attribution(bound):
    cursor = await prepared(bound)
    append(bound.path, events())
    result = await bound.observer.before_submit(cursor, bound.binding, body=BODY)
    assert result["state"] == "unavailable"
    assert result["reason"] == "turn_observed_before_our_return"


@pytest.mark.parametrize("missing", ["codex_thread_id", "codex_rollout_path"])
async def test_no_thread_or_path_guessing_without_explicit_binding(bound, missing):
    result = await bound.observer.prepare(
        bound.binding.model_copy(update={missing: None}),
        process_identity=bound.observe_identity,
        expected_identity=IDENTITY,
        body=BODY,
    )
    assert result["state"] == "unavailable" and bound.processes == []


@pytest.mark.parametrize("access", ["r", ""])
async def test_readable_file_and_matching_header_do_not_prove_process_writer(bound, access):
    bound.writer_access = access
    result = await bound.observer.prepare(
        bound.binding,
        process_identity=bound.observe_identity,
        expected_identity=IDENTITY,
        body=BODY,
    )
    assert result["state"] == "unavailable"
    assert result["reason"] == "process_does_not_own_bound_rollout_writer"
    assert bound.processes == bound.reaped


@pytest.mark.parametrize("field,value", [("p", "999"), ("D", "0x0"), ("i", "0"), ("n", "/wrong")])
async def test_independent_writer_identity_requires_exact_process_device_inode_path(
    bound, field, value
):
    stat = bound.path.stat()
    fields = {
        "p": "101",
        "f": "15",
        "a": "w",
        "t": "REG",
        "D": hex(stat.st_dev),
        "i": str(stat.st_ino),
        "n": str(bound.path),
    }
    fields[field] = value
    bound.raw_override = b"".join((k + v).encode() + b"\0" for k, v in fields.items())
    result = await bound.observer.prepare(
        bound.binding,
        process_identity=bound.observe_identity,
        expected_identity=IDENTITY,
        body=BODY,
    )
    assert result["state"] == "unavailable"
    assert bound.processes == bound.reaped


async def test_changed_process_identity_never_returns_final(bound):
    cursor = await prepared(bound)
    append(bound.path, events())
    bound.identity = "different process incarnation"
    result = await observe(bound, cursor)
    assert result["state"] == "unavailable" and result["reason"] == "process_binding_changed"


@pytest.mark.parametrize("changed", ["rewrite", "truncate", "replace", "symlink"])
async def test_replaced_rewritten_or_truncated_session_cannot_supply_a_reply(bound, changed):
    cursor = await prepared(bound)
    if changed == "rewrite":
        raw = bound.path.read_text().replace("OLD unrelated input", "NEW unrelated input")
        bound.path.write_text(raw)
        append(bound.path, events())
    elif changed == "truncate":
        bound.path.write_text(bound.path.read_text().splitlines()[0] + "\n")
    else:
        raw = bound.path.read_bytes()
        old = bound.path.with_suffix(".previous")
        bound.path.rename(old)
        if changed == "replace":
            bound.path.write_bytes(raw)
            append(bound.path, events())
        else:
            bound.path.symlink_to(old)
    result = await observe(bound, cursor)
    assert result["state"] == "unavailable", result


@pytest.mark.parametrize(
    "mutation",
    [
        lambda e: e[1]["payload"]["item"]["content"][0].update(text=BODY + " EXTRA"),
        lambda e: e[1]["payload"].update(thread_id="other-thread"),
        lambda e: e[2]["payload"].update(turn_id="other-turn"),
        lambda e: e[2]["payload"]["item"].update(phase="commentary"),
        lambda e: e[3]["payload"].update(turn_id="other-turn"),
        lambda e: e[3]["payload"].update(last_agent_message="different text"),
        lambda e: e[0]["payload"].update(root_turn_id="parent-turn"),
        lambda e: e.insert(2, copy.deepcopy(e[1])),
        lambda e: e.insert(3, copy.deepcopy(e[2])),
        lambda e: e.append(copy.deepcopy(e[0])),
        lambda e: e.insert(2, {"type": "event_msg", "payload": {"type": "turn_aborted"}}),
    ],
)
async def test_mismatched_or_ambiguous_protocol_never_completes(bound, mutation):
    cursor = await prepared(bound)
    records = events()
    mutation(records)
    append(bound.path, records)
    assert (await observe(bound, cursor))["state"] == "unavailable"


async def test_response_item_mirrors_and_quoted_task_complete_are_not_authority(bound):
    cursor = await prepared(bound)
    append(
        bound.path,
        [{"type": "response_item", "payload": {"role": "assistant", "content": events()}}],
    )
    assert (await observe(bound, cursor))["state"] == "pending"


async def test_partial_append_waits_without_replay_and_later_exact_completion_can_finish(bound):
    cursor = await prepared(bound)
    raw = "".join(json.dumps(row) + "\n" for row in events()).encode()
    with bound.path.open("ab") as stream:
        stream.write(raw[:-3])
    assert (await observe(bound, cursor))["state"] == "pending"
    with bound.path.open("ab") as stream:
        stream.write(raw[-3:])
    assert (await observe(bound, cursor))["state"] == "completed"


@pytest.mark.parametrize(
    "change",
    [
        {"version": True},
        {"body_sha256": "0" * 64},
        {"agent_pid": 999},
        {"thread_id": "other"},
        {"path": "/other"},
    ],
)
async def test_cursor_cannot_be_rebound_to_another_task_body_or_target(bound, change):
    cursor = await prepared(bound)
    append(bound.path, events())
    assert (await observe(bound, {**cursor, **change}))["state"] == "unavailable"


async def test_excessive_lsof_output_is_bounded_and_child_is_reaped(bound):
    bound.raw_override = b"x" * (codex_reply.MAX_LSOF_BYTES + 1)
    result = await bound.observer.prepare(
        bound.binding,
        process_identity=bound.observe_identity,
        expected_identity=IDENTITY,
        body=BODY,
    )
    assert result["state"] == "unavailable" and bound.processes == bound.reaped


async def test_cancellation_during_lsof_reaps_only_its_child(bound):
    entered = asyncio.Event()
    child = SimpleNamespace(returncode=None)

    async def blocked_read(limit):
        entered.set()
        await asyncio.Event().wait()

    child.stdout = SimpleNamespace(read=blocked_read)

    async def factory(*args, **kwargs):
        return child

    bound.observer.process_factory = factory
    task = asyncio.create_task(
        bound.observer.prepare(
            bound.binding,
            process_identity=bound.observe_identity,
            expected_identity=IDENTITY,
            body=BODY,
        )
    )
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert bound.reaped == [child]


def auto_binding(bound):
    return bound.binding.model_copy(update={"codex_thread_id": None, "codex_rollout_path": None})


def writer_row(path, descriptor=15):
    info = path.stat()
    return (f"f{descriptor}\0aw\0tREG\0D{hex(info.st_dev)}\0i{info.st_ino}\0n{path}\0\n").encode()


def writer_catalog(bound, *paths):
    return f"p101\0\nfcwd\0tDIR\0n{bound.root.parent}\0\n".encode() + b"".join(
        writer_row(path, 15 + index) for index, path in enumerate(paths)
    )


async def auto_prepare(bound, *, cwd=None, identity=None):
    return await bound.observer.prepare(
        auto_binding(bound),
        process_identity=identity or bound.observe_identity,
        expected_identity=IDENTITY,
        body=BODY,
        cwd=str(bound.root.parent) if cwd is None else cwd,
    )


async def test_one_exact_process_writer_discovers_only_a_task_local_protocol_binding(bound):
    original = auto_binding(bound)
    result = await auto_prepare(bound)
    assert result["state"] == "ready", result
    cursor = result["cursor"]
    assert cursor["binding_origin"] == "process_writer_discovery"
    assert cursor["binding"] == original.model_dump()
    assert cursor["thread_id"] == THREAD and cursor["path"] == str(bound.path)
    assert original.codex_thread_id is None and original.codex_rollout_path is None
    before = await bound.observer.before_submit(cursor, original, body=BODY)
    assert before["state"] == "ready"
    append(bound.path, events())
    answer = await bound.observer.observe(
        cursor, original, body=BODY, process_identity=bound.observe_identity
    )
    assert answer["state"] == "completed" and answer["text"] == ANSWER
    protocol = answer["evidence"]["protocol_binding"]
    assert protocol["origin"] == "process_writer_discovery"
    assert protocol["thread_id"] == THREAD
    assert bound.processes == bound.reaped


async def test_multiple_process_owned_rollouts_are_ambiguous_regardless_of_newest_time(bound):
    second = bound.root / "newer-rollout.jsonl"
    append(
        second,
        [
            {
                "type": "session_meta",
                "payload": {
                    "id": "01a192b9-64f2-7d22-8429-cabd5faf9999",
                    "originator": "codex-tui",
                    "cwd": str(bound.root.parent),
                },
            }
        ],
    )
    bound.raw_override = writer_catalog(bound, bound.path, second)
    result = await auto_prepare(bound)
    assert result["state"] == "unavailable"
    assert result["reason"] == "ambiguous_process_rollout_writers"


async def test_duplicate_descriptors_to_the_same_file_are_one_candidate(bound):
    bound.raw_override = writer_catalog(bound, bound.path, bound.path)
    assert (await auto_prepare(bound))["state"] == "ready"


@pytest.mark.parametrize("wrong", ["process_cwd", "header_cwd", "header_thread", "read_only"])
async def test_automatic_candidate_requires_matching_cwd_valid_thread_and_write_access(
    bound, wrong
):
    cwd = str(bound.root.parent)
    if wrong == "process_cwd":
        cwd = str(bound.root / "other-workspace")
    elif wrong.startswith("header_"):
        rows = [json.loads(line) for line in bound.path.read_text().splitlines()]
        rows[0]["payload"]["cwd" if wrong == "header_cwd" else "id"] = "wrong"
        bound.path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    else:
        bound.writer_access = "r"
    result = await auto_prepare(bound, cwd=cwd)
    assert result["state"] == "unavailable"
    if wrong == "process_cwd":
        assert result["reason"] == "process_cwd_mismatch"


async def test_foreign_path_writer_is_not_read_or_used_as_a_reply_source(bound, monkeypatch):
    outside = bound.root.parent / "foreign-rollout.jsonl"
    outside.write_bytes(bound.path.read_bytes())
    bound.raw_override = writer_catalog(bound, outside)

    def must_not_read(*args, **kwargs):
        raise AssertionError("An outside-root process descriptor is not source authorization")

    monkeypatch.setattr(bound.observer, "_snapshot", must_not_read)
    result = await auto_prepare(bound)
    assert result["state"] == "unavailable"
    assert result["reason"] == "process_rollout_writer_unavailable"


async def test_non_owned_session_file_is_not_an_automatic_candidate(bound, monkeypatch):
    real_uid = codex_reply.os.getuid()
    monkeypatch.setattr(codex_reply.os, "getuid", lambda: real_uid + 1)
    assert (await auto_prepare(bound))["state"] == "unavailable"


async def test_process_replacement_during_discovery_cannot_bind_a_thread(bound):
    calls = 0

    async def stale(pid, *, detailed):
        nonlocal calls
        calls += 1
        return IDENTITY if calls == 1 else "replaced process"

    result = await auto_prepare(bound, identity=stale)
    assert result["state"] == "unavailable" and result["reason"] == "process_binding_changed"


async def test_candidate_count_limit_does_not_search_or_open_every_possible_log(bound, monkeypatch):
    paths = [
        bound.root / f"candidate-{index}.jsonl" for index in range(codex_reply.MAX_CANDIDATES + 1)
    ]
    for path in paths:
        path.write_bytes(bound.path.read_bytes())
    bound.raw_override = writer_catalog(bound, *paths)

    def must_not_read(*args, **kwargs):
        raise AssertionError("Candidate count must be checked before reading any log")

    monkeypatch.setattr(bound.observer, "_snapshot", must_not_read)
    result = await auto_prepare(bound)
    assert result["state"] == "unavailable"
    assert result["reason"] == "too_many_rollout_writer_candidates"


def test_root_ancestor_changed_to_a_symlink_cannot_escape_after_resolve(tmp_path):
    parent = tmp_path / "replaceable"
    root = parent / "sessions"
    root.mkdir(parents=True)
    selected = root / "explicit.jsonl"
    selected.write_text("inside")
    observer = codex_reply.CodexReplyObserver(root)
    foreign = tmp_path / "foreign"
    (foreign / "sessions").mkdir(parents=True)
    (foreign / "sessions" / selected.name).write_text("outside")
    parent.rename(tmp_path / "preserved-parent")
    parent.symlink_to(foreign, target_is_directory=True)
    # Simulate the race after _snapshot's resolve check but before opening.
    with pytest.raises(BridgeError):
        observer._open_session(selected)


async def test_cancellation_during_process_creation_adopts_and_reaps_late_handle(bound):
    entered, release = asyncio.Event(), asyncio.Event()
    child = SimpleNamespace(returncode=None)

    async def factory(*args, **kwargs):
        entered.set()
        await release.wait()
        return child

    bound.observer.process_factory = factory
    task = asyncio.create_task(
        bound.observer.prepare(
            bound.binding,
            process_identity=bound.observe_identity,
            expected_identity=IDENTITY,
            body=BODY,
        )
    )
    await entered.wait()
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert bound.reaped == [child]
