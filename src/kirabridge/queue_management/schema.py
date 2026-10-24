"""Additive delivery holds; immutable source records and audit remain intact."""

SPECS = {
    "tasks": ("tasks", "id", "task.read"),
    "messages": ("messages", "id", "message.read"),
    "handoffs": ("visible_handoffs", "id", "task.read"),
    "completions": ("completion_notices", "id", None),
    "team-work": ("team_work", "id", "team.read"),
    "team-messages": ("team_messages", "id", "team.read"),
    "voice-buffers": ("voice_message_buffers", "id", "message.read"),
    "session-input": ("session_input_buffers", "task_id", "task.read"),
}
TERMINAL = {"completed", "failed", "cancelled", "blocked", "interrupted", "expired", "released"}


def install_schema(store):
    store.db.execute(
        "CREATE TABLE IF NOT EXISTS queue_holds (queue_id TEXT NOT NULL,item_id TEXT NOT NULL,"
        "actor TEXT NOT NULL,created REAL NOT NULL,reason TEXT NOT NULL,"
        "PRIMARY KEY(queue_id,item_id))"
    )
