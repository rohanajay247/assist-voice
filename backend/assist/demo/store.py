"""The demo DB: one SQLite file for everything demo mode can change.

Changeable data lives here (calendar, email, drafts, notes, open tabs, plus
the saved tabs, memories and undo log that the real modules keep in their
own tables). Read-only data (GitHub, git history) is read straight from
seed.json by the fake servers.
"""
import json
import sqlite3
from functools import lru_cache

from backend.assist import demo
from backend.assist.demo import SEED_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    n INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL, start TEXT NOT NULL, "end" TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '', location TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'confirmed'  -- deleted events stay as 'cancelled', like Google
);
CREATE TABLE IF NOT EXISTS emails (
    id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, sender TEXT NOT NULL, recipient TEXT NOT NULL,
    subject TEXT NOT NULL, date TEXT NOT NULL, body TEXT NOT NULL,
    unread INTEGER NOT NULL, category TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS drafts (
    n INTEGER PRIMARY KEY AUTOINCREMENT,
    recipient TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL,
    reply_to_message_id TEXT, thread_id TEXT
);
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS open_tabs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, url TEXT NOT NULL,
    pinned INTEGER NOT NULL DEFAULT 0
);
"""


def conn() -> sqlite3.Connection:
    # The shared demo.db, or in public demo the visitor's own file
    c = sqlite3.connect(demo.db_path(demo.DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    with conn() as c:
        c.executescript(SCHEMA)


if not demo.PUBLIC_DEMO:  # public demo: created per visitor, from a template
    init_db()


@lru_cache(maxsize=1)
def seed() -> dict:
    return json.loads(SEED_PATH.read_text(encoding="utf-8"))


def reset() -> None:
    """Back to the seed: data, open and saved tabs; empty undo log, memories and drafts.
    Runs in the API process, where browser/memory/actions have created their tables."""
    s = seed()
    with conn() as c:
        for table in ("events", "emails", "drafts", "notes", "open_tabs", "saved_tabs",
                      "memories", "actions"):
            c.execute(f"DELETE FROM {table}")
        # Restart ids, so every run sees the same event, draft and tab numbers
        c.execute("DELETE FROM sqlite_sequence")
        c.executemany(
            'INSERT INTO events (title, start, "end", description, location) VALUES (?, ?, ?, ?, ?)',
            [(e["title"], e["start"], e["end"], e.get("description", ""), e.get("location", ""))
             for e in s["events"]],
        )
        c.executemany(
            "INSERT INTO emails VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(m["id"], m["thread_id"], m["from"], m["to"], m["subject"], m["date"], m["body"],
              int(m["unread"]), m["category"]) for m in s["emails"]],
        )
        c.executemany("INSERT INTO notes (text, created_at) VALUES (?, ?)",
                      [(n["text"], n["created_at"]) for n in s["notes"]])
        c.executemany("INSERT INTO open_tabs (title, url) VALUES (?, ?)",
                      [(t["title"], t["url"]) for t in s["open_tabs"]])
        c.executemany(
            "INSERT INTO saved_tabs (batch, category, title, url, saved_at) VALUES ('seed', ?, ?, ?, ?)",
            [(t["category"], t["title"], t["url"], t["saved_at"]) for t in s["saved_tabs"]],
        )


def state() -> dict:
    """Counts the evals compare before and after a case."""
    queries = {
        "notes": "SELECT COUNT(*) FROM notes",
        "events": "SELECT COUNT(*) FROM events WHERE status = 'confirmed'",
        "drafts": "SELECT COUNT(*) FROM drafts",
        "saved_tabs": "SELECT COUNT(*) FROM saved_tabs WHERE category IN ('read_later', 'todo')",
        "saved_searches": "SELECT COUNT(*) FROM saved_tabs WHERE category = 'search'",
        "done_tabs": "SELECT COUNT(*) FROM saved_tabs WHERE done_at IS NOT NULL",
        "memories": "SELECT COUNT(*) FROM memories",
    }
    with conn() as c:
        return {key: c.execute(sql).fetchone()[0] for key, sql in queries.items()}
