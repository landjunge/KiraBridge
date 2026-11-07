"""Captured /resume completion needs bound CWD and thread-title metadata."""

import json
from types import SimpleNamespace

import pytest

from kirabridge.literal_session_input import insertion_observed
from kirabridge.platform_adapters.codex_metadata import read_thread_title
from kirabridge.slash_commands import bound_thread_title, resume_insertion_observed

# Extracted current-widget geometry from E2E06 inside-task frames at
# 1793450194.237609 / 1793450199.037567. Private path and title are substituted.
HOME = "/Users/fixture"
CWD = HOME + "/owned/macOS/native-e2e/workspace"
TITLE = "Prüfe KiraBridge-Eingabe"
BEFORE = (
    "› Ask Codex to do anything\n \n"
    "  GPT-6.1-Sol high · ~/owned/macOS/native-…  ⚠ 2 warnings · f2 to view\n"
)
AFTER = (
    "› /resume  resume a saved chat                                      \n \n"
    "› /resume\n \n"
    "  GPT-6.1-Sol high · ~/owned/macOS/native-e2e/workspace · Prüfe Kir…\n"
)


def test_captured_resume_suggestion_binds_new_footer_title_and_cwd():
    assert not insertion_observed("codex", AFTER, "/resume", BEFORE, cwd=CWD, home=HOME)
    assert resume_insertion_observed(
        "codex", AFTER, "/resume", BEFORE, cwd=CWD, home=HOME, title=TITLE
    )


@pytest.mark.parametrize(
    "after,before,payload,cwd,title",
    [
        (AFTER, BEFORE, "/resume", None, TITLE),
        (AFTER, BEFORE, "/resume", CWD, None),
        (AFTER, BEFORE, "/resume", CWD, "Unrelated thread"),
        (AFTER, BEFORE, "/resume", HOME + "/another/project", TITLE),
        (AFTER, BEFORE, "/help", CWD, TITLE),
        (AFTER.replace("› /resume\n", "› /resume EXTRA\n"), BEFORE, "/resume", CWD, TITLE),
        (AFTER.replace("resume a saved chat", "approve a command"), BEFORE, "/resume", CWD, TITLE),
        (AFTER.replace("GPT-6.1-Sol", "GPT-OTHER"), BEFORE, "/resume", CWD, TITLE),
        (AFTER + "Approve something else?\n", BEFORE, "/resume", CWD, TITLE),
        (AFTER.replace("Prüfe Kir…", "Unknown…"), BEFORE, "/resume", CWD, TITLE),
        ("› /approve  unknown suggestion\n" + AFTER, BEFORE, "/resume", CWD, TITLE),
        ("Approval required\n" + AFTER, BEFORE, "/resume", CWD, TITLE),
        (AFTER, BEFORE.replace("  ⚠ 2 warnings · f2 to view", ""), "/resume", CWD, TITLE),
        (
            AFTER.replace("\n \n› /resume", "\n Approval required\n› /resume"),
            BEFORE,
            "/resume",
            CWD,
            TITLE,
        ),
    ],
)
def test_resume_special_case_preserves_model_payload_dialog_and_metadata_guards(
    after, before, payload, cwd, title
):
    assert not resume_insertion_observed(
        "codex", after, payload, before, cwd=cwd, home=HOME, title=title
    )


def metadata(tmp_path, content):
    rollout = tmp_path / "sessions/2026/10/31/rollout.jsonl"
    rollout.parent.mkdir(parents=True)
    index = tmp_path / "session_index.jsonl"
    index.write_text(content)
    return rollout, index


def test_title_reader_returns_only_the_exact_bound_thread_and_latest_record(tmp_path):
    rollout, _ = metadata(
        tmp_path,
        json.dumps({"id": "foreign", "thread_name": "PRIVATE OTHER TITLE"})
        + "\n"
        + json.dumps({"id": "selected", "thread_name": "old"})
        + "\n"
        + json.dumps({"id": "selected", "thread_name": TITLE})
        + "\n",
    )
    assert read_thread_title(str(rollout), "selected") == TITLE
    assert read_thread_title(str(rollout), "missing") is None


@pytest.mark.parametrize(
    "failure", ["symlink", "budget", "partial", "json", "control", "directory"]
)
def test_untrusted_or_incomplete_title_index_never_supplies_a_proof(tmp_path, failure):
    content = json.dumps({"id": "selected", "thread_name": TITLE}) + "\n"
    rollout, index = metadata(tmp_path, content)
    if failure == "symlink":
        target = tmp_path / "target"
        index.rename(target)
        index.symlink_to(target)
    elif failure == "budget":
        index.write_bytes(b"x" * 1048577)
    elif failure == "partial":
        index.write_text(content.rstrip("\n"))
    elif failure == "json":
        index.write_text(content + "bad JSON\n")
    elif failure == "control":
        index.write_text(json.dumps({"id": "selected", "thread_name": "bad\nname"}) + "\n")
    else:
        index.unlink()
        index.mkdir()
    assert read_thread_title(str(rollout), "selected") is None


def test_title_domain_adapter_requires_current_matching_agent_selection(tmp_path):
    rollout, _ = metadata(tmp_path, json.dumps({"id": "selected", "thread_name": TITLE}) + "\n")
    binding = SimpleNamespace(
        agent_pid=43, codex_thread_id="selected", codex_rollout_path=str(rollout)
    )
    sessions = SimpleNamespace(current_selection=lambda: ("codex", binding, {43: "identity"}))
    assert bound_thread_title(sessions, binding) == TITLE
    sessions.current_selection = lambda: ("codex", binding, {44: "another agent"})
    assert bound_thread_title(sessions, binding) is None
    sessions.current_selection = lambda: None
    assert bound_thread_title(sessions, binding) is None
