import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "analyze_keyboard_latency.py"
SPEC = importlib.util.spec_from_file_location("keyboard_latency_analysis", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
analysis = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analysis)


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "bridge.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            "CREATE TABLE tasks (id TEXT, principal TEXT, operation TEXT, state TEXT, "
            "created REAL, accepted REAL, started REAL, finished REAL, error TEXT, result TEXT);"
            "CREATE TABLE events (seq INTEGER, task_id TEXT, at REAL, state TEXT, evidence TEXT);"
            "CREATE TABLE completion_notices (seq INTEGER, source TEXT, source_id TEXT, "
            "created REAL, delivered REAL, acknowledged REAL);"
            "CREATE TABLE audit (kind TEXT, at REAL);"
        )
        for identifier, created in (("probe_a_0", 100), ("probe_a_1", 110), ("probeXa_2", 120)):
            connection.execute(
                "INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    identifier,
                    "chatgpt",
                    "keyboard.control",
                    "completed",
                    created,
                    created + 0.01,
                    created + 0.02,
                    created + 0.20,
                    None,
                    json.dumps(
                        {
                            "text": "PRIVATE INPUT",
                            "automatic_retry": False,
                            "app_processing_confirmed": False,
                            "post_calls_returned": 2,
                        }
                    ),
                ),
            )
            connection.execute(
                "INSERT INTO events VALUES (1,?,?,?,?)",
                (
                    identifier,
                    created + 0.03,
                    "running",
                    json.dumps(
                        {
                            "evidence_type": "automatic_keyboard_target_bound",
                            "text": "PRIVATE INPUT",
                        }
                    ),
                ),
            )
            connection.execute(
                "INSERT INTO events VALUES (2,?,?,?,?)",
                (
                    identifier,
                    created + 0.04,
                    "running",
                    json.dumps(
                        {"evidence_type": "native_keyboard_attempt", "token": "PRIVATE SECRET"}
                    ),
                ),
            )
    return path


def test_literal_prefix_and_privacy_without_mutating_source(database):
    before = database.read_bytes()
    report = analysis.analyze(database, "probe_a_", ["missing"])
    assert report["task_count"] == 2
    assert [task["id"] for task in report["tasks"]] == ["probe_a_0", "probe_a_1"]
    assert "PRIVATE" not in json.dumps(report)
    assert report["additional_tasks"] == [{"id": "missing", "exists": False}]
    assert database.read_bytes() == before


def test_stage_times_and_external_gap_are_separate(database):
    report = analysis.analyze(database, "probe_a_")
    assert report["first_created_to_last_finished_ms"] == pytest.approx(10200)
    stats = report["statistics"]
    assert stats["created_to_finished"]["sum_ms"] == pytest.approx(400)
    assert stats["previous_finished_to_created"]["p50_ms"] == pytest.approx(9800)
    assert stats["target_bound_to_native_attempt"]["min_ms"] == pytest.approx(10)
    assert stats["native_attempt_to_finished"]["max_ms"] == pytest.approx(160)


def test_missing_database_is_not_created_and_empty_prefix_rejected(tmp_path, database):
    missing = tmp_path / "absent.sqlite3"
    with pytest.raises(sqlite3.OperationalError):
        analysis.analyze(missing, "probe")
    assert not missing.exists()
    with pytest.raises(ValueError, match="nonempty"):
        analysis.analyze(database, "")
