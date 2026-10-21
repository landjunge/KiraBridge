"""Read-only SQLite component tests, not a live macOS handoff acceptance test."""

import ast
import json
import sqlite3
import unittest
from pathlib import Path
from types import SimpleNamespace

from kirabridge.visible_message_evidence import visible_message_evidence


class BridgeError(Exception):
    pass


def reader_method():
    # Exercise the actual product method without importing/starting other services.
    path = Path(__file__).resolve().parents[1] / "src/kirabridge/message_manager/__init__.py"
    source = ast.parse(path.read_text())
    cls = next(n for n in source.body if isinstance(n, ast.ClassDef) and n.name == "MessageManager")
    node = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "get")
    namespace = {"json": json, "BridgeError": BridgeError}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    return namespace["get"]


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE messages(id TEXT PRIMARY KEY, sender TEXT, recipient TEXT,
                conversation_id TEXT, idem TEXT, request_hash TEXT, request_reply INTEGER);
            CREATE TABLE message_jobs(message_id TEXT, state TEXT, run_id TEXT, evidence TEXT);
            CREATE TABLE visible_handoffs(id TEXT PRIMARY KEY, principal TEXT, target TEXT,
                message_id TEXT, state TEXT, updated REAL, evidence TEXT);
            CREATE TABLE visible_handoff_events(seq INTEGER PRIMARY KEY, id TEXT,
                state TEXT, at REAL, evidence TEXT);
        """)
        self.db.execute("INSERT INTO messages VALUES(?,?,?,?,?,?,?)",
                        ("msg", "chatgpt", "codex", "conversation", "idem", "hash", 1))
        self.db.execute("INSERT INTO message_jobs VALUES(?,?,?,?)",
                        ("msg", "unknown", "run", json.dumps({"last_observation": {}})))
        self.db.execute("INSERT INTO visible_handoffs VALUES(?,?,?,?,?,?,?)",
                        ("run", "chatgpt", "codex", "msg", "unknown", 10.0,
                         json.dumps({"reason": "visible_insert_unknown", "prompt": "SECRET"})))
        for seq, state in enumerate(("planned", "inserting", "unknown"), 1):
            self.db.execute("INSERT INTO visible_handoff_events VALUES(?,?,?,?,?)",
                            (seq, "run", state, float(seq), '{"prompt":"SECRET"}'))
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def read(self, principal="chatgpt", message="msg", run="run"):
        before = list(self.db.iterdump())
        allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}
        self.db.set_authorizer(lambda action, *unused:
                               sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY)
        try:
            result = visible_message_evidence(self.db, principal, message, run)
        finally:
            self.db.set_authorizer(None)
        self.assertEqual(before, list(self.db.iterdump()))
        return result

    def test_original_reason_is_available_without_resending(self):
        result = self.read()
        self.assertEqual(result["recorded_reason"], "visible_insert_unknown")
        self.assertEqual(result["state"], "unknown")
        self.assertFalse(result["automatic_retry_permitted"])
        self.assertFalse(result["reconciliation_performed"])
        self.assertEqual(result["scope"], "stored_handoff_evidence_not_live_terminal")

    def test_recipient_can_read_own_handoff(self):
        self.assertIsNotNone(self.read(principal="codex"))

    def test_nonparticipant_cannot_read(self):
        self.assertIsNone(self.read(principal="grok"))

    def test_wrong_message_cannot_read(self):
        self.assertIsNone(self.read(message="other"))

    def test_wrong_run_cannot_read(self):
        self.assertIsNone(self.read(run="other"))

    def test_null_run_is_not_a_match(self):
        self.assertIsNone(self.read(run=None))

    def test_sql_injection_does_not_expand_scope(self):
        self.assertIsNone(self.read(run="run' OR 1=1 --"))

    def test_cross_linked_principal_is_not_a_match(self):
        self.db.execute("UPDATE visible_handoffs SET principal='someone_else'")
        self.assertIsNone(self.read())

    def test_cross_linked_target_is_not_a_match(self):
        self.db.execute("UPDATE visible_handoffs SET target='grok'")
        self.assertIsNone(self.read(principal="grok"))

    def test_absent_handoff_table_is_compatible(self):
        self.db.execute("DROP TABLE visible_handoffs")
        self.assertIsNone(self.read())

    def test_absent_event_table_is_not_an_empty_verified_history(self):
        self.db.execute("DROP TABLE visible_handoff_events")
        result = self.read()
        self.assertFalse(result["history_available"])
        self.assertEqual(result["events"], [])

    def test_unknown_reason_does_not_leak_payload(self):
        self.db.execute("UPDATE visible_handoffs SET evidence=?",
                        (json.dumps({"reason": "SECRET_TOKEN", "body": "SECRET"}),))
        result = self.read()
        self.assertEqual(result["recorded_reason"], "other_recorded_reason")
        self.assertNotIn("SECRET", json.dumps(result))

    def test_raw_evidence_is_not_exposed(self):
        self.assertNotIn("SECRET", json.dumps(self.read()))

    def test_missing_reason_is_labelled(self):
        self.db.execute("UPDATE visible_handoffs SET evidence='{}'")
        self.assertEqual(self.read()["recorded_reason"], "not_recorded")

    def test_invalid_json_is_not_a_positive_observation(self):
        self.db.execute("UPDATE visible_handoffs SET evidence='{' ")
        result = self.read()
        self.assertEqual(result["evidence_status"], "invalid")
        self.assertEqual(result["recorded_reason"], "unavailable")

    def test_non_object_json_is_invalid(self):
        self.db.execute("UPDATE visible_handoffs SET evidence='[]'")
        self.assertEqual(self.read()["evidence_status"], "invalid")

    def test_unhashable_reason_is_redacted(self):
        self.db.execute("UPDATE visible_handoffs SET evidence=?", ('{"reason":[]}',))
        self.assertEqual(self.read()["recorded_reason"], "other_recorded_reason")

    def test_large_evidence_is_bounded(self):
        self.db.execute("UPDATE visible_handoffs SET evidence=?",
                        (json.dumps({"reason": "visible_insert_unknown", "raw": "a" * 9000}),))
        result = self.read()
        self.assertEqual(result["evidence_status"], "unavailable_or_over_limit")
        self.assertEqual(result["recorded_reason"], "unavailable")

    def test_utf8_is_bounded_in_bytes(self):
        self.db.execute("UPDATE visible_handoffs SET evidence=?",
                        (json.dumps({"raw": "💡" * 3000}, ensure_ascii=False),))
        self.assertEqual(self.read()["evidence_status"], "unavailable_or_over_limit")

    def test_deep_json_is_handled_without_crashing(self):
        self.db.execute("UPDATE visible_handoffs SET evidence=?", ('[' * 2000 + ']' * 2000,))
        self.assertEqual(self.read()["evidence_status"], "invalid")

    def test_event_history_has_a_hard_limit(self):
        self.db.executemany("INSERT INTO visible_handoff_events VALUES(?,?,?,?,?)",
                            [(i, "run", "unknown", float(i), '{}') for i in range(4, 105)])
        result = self.read()
        self.assertTrue(result["history_truncated"])
        self.assertEqual(len(result["events"]), 32)
        self.assertEqual(result["events"][0]["seq"], 73)
        self.assertEqual(result["events"][-1]["seq"], 104)

    def test_event_history_is_chronological(self):
        self.assertEqual([e["state"] for e in self.read()["events"]],
                         ["planned", "inserting", "unknown"])

    def test_unknown_stays_unknown_after_read(self):
        self.read()
        self.assertEqual(self.db.execute("SELECT state FROM visible_handoffs").fetchone()[0],
                         "unknown")
        self.assertEqual(self.db.execute("SELECT state FROM message_jobs").fetchone()[0], "unknown")

    def test_unsupported_state_and_timestamp_are_sanitized(self):
        self.db.execute("UPDATE visible_handoffs SET state='SECRET',updated='SECRET'")
        self.db.execute("UPDATE visible_handoff_events SET state='SECRET',at='SECRET'")
        result = self.read()
        self.assertEqual(result["state"], "unknown")
        self.assertIsNone(result["updated"])
        self.assertNotIn("SECRET", json.dumps(result))

    def manager(self, task_read=True, message_read=True, shared=False, pending=None):
        manager = SimpleNamespace(
            store=SimpleNamespace(db=self.db),
            config=SimpleNamespace(visible_handoffs=SimpleNamespace(enabled=True)),
            voice_policy=SimpleNamespace(get=lambda *args: pending),
        )
        def identity(principal, capability):
            if capability == "message.read" and not message_read:
                raise BridgeError("forbidden")
            if capability == "task.read" and not task_read:
                raise BridgeError("forbidden")
        def row(principal, message_id):
            found = self.db.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
            if not found or (not shared and principal not in {found['sender'], found['recipient']}):
                raise BridgeError("not_found")
            return found
        manager._identity, manager._row = identity, row
        return manager

    def test_product_reader_attaches_diagnostic(self):
        result = reader_method()(self.manager(), "chatgpt", "msg")
        self.assertEqual(result["processing"]["handoff"]["recorded_reason"],
                         "visible_insert_unknown")
        self.assertEqual(result["processing"]["state"], "unknown")
        self.assertEqual(result["processing_route"], "existing_visible_terminal")

    def test_product_reader_honors_message_permission(self):
        with self.assertRaises(BridgeError):
            reader_method()(self.manager(message_read=False), "chatgpt", "msg")

    def test_product_reader_does_not_expand_task_permission(self):
        result = reader_method()(self.manager(task_read=False), "chatgpt", "msg")
        self.assertNotIn("handoff", result["processing"])

    def test_product_reader_does_not_expand_shared_membership(self):
        result = reader_method()(self.manager(shared=True), "grok", "msg")
        self.assertNotIn("handoff", result["processing"])

    def test_product_reader_preserves_pending_buffer(self):
        pending = {"transport": "team", "message_buffer": {"state": "waiting"}}
        self.assertEqual(reader_method()(self.manager(pending=pending), "chatgpt", "msg"),
                         pending)

    def test_product_reader_preserves_messages_without_jobs(self):
        self.db.execute("DELETE FROM message_jobs")
        result = reader_method()(self.manager(), "chatgpt", "msg")
        self.assertIsNone(result["processing"])
        self.assertEqual(result["processing_route"], "external_client_inbox")

    def test_product_reader_preserves_unknown_reason_and_read_only_database(self):
        self.db.commit()
        self.db.execute("PRAGMA query_only=ON")
        result = reader_method()(self.manager(), "chatgpt", "msg")
        self.assertFalse(result["processing"]["handoff"]["automatic_retry_permitted"])
        self.assertEqual(self.db.execute("SELECT state FROM visible_handoffs").fetchone()[0],
                         "unknown")


if __name__ == "__main__":
    unittest.main()
