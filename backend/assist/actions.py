"""Action log for undo.

Every change Assist makes is stored together with its reverse,
e.g. add_note(text) -> delete_note(id). "Undo that" runs the reverse
of the newest action that isn't undone yet.

Stored in SQLite (not in graph state) so it survives restarts and can
later answer "what did you do for me this week?".
"""
import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "actions.db"  # *.db is gitignored


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # rows behave like dicts
    return conn


# Runs once on import
with get_conn() as conn:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS actions ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "thread_id TEXT NOT NULL, "
        "tool TEXT NOT NULL, "
        "args TEXT NOT NULL, "
        "reverse_tool TEXT NOT NULL, "
        "reverse_args TEXT NOT NULL, "
        "undone INTEGER NOT NULL DEFAULT 0, "
        "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )


def log_action(
    thread_id: str, tool: str, args: dict, reverse_tool: str, reverse_args: dict
) -> int:
    """Store one action and how to reverse it. Returns the action id."""
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO actions (thread_id, tool, args, reverse_tool, reverse_args) "
            "VALUES (?, ?, ?, ?, ?)",
            (thread_id, tool, json.dumps(args), reverse_tool, json.dumps(reverse_args)),
        )
        return cur.lastrowid


def last_action(thread_id: str) -> dict | None:
    """Newest action in this thread that hasn't been undone, or None."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM actions WHERE thread_id = ? AND undone = 0 "
            "ORDER BY id DESC LIMIT 1",
            (thread_id,),
        ).fetchone()
    if row is None:
        return None
    action = dict(row)
    action["args"] = json.loads(action["args"])
    action["reverse_args"] = json.loads(action["reverse_args"])
    return action


def mark_undone(action_id: int) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE actions SET undone = 1 WHERE id = ?", (action_id,))