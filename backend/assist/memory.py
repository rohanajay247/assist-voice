"""Memory (Day 6): preferences the user asked Assist to keep.

"Remember I sign emails as Rohan Ajay Varghese" is stored here and added to
the system prompt on every call, so every tool use follows it: drafts get
the signature, weather uses the right city. Notes are things to look up;
memories change how Assist behaves.

Saving and forgetting need approval (a memory changes every future answer,
and an email or photo must never be able to plant one) and can be undone.
"""
import json
import sqlite3
from pathlib import Path

from langchain_core.tools import tool

from backend.assist import clock, demo

DB_PATH = demo.db_path(Path(__file__).parent / "memory.db")  # *.db is gitignored
MAX_MEMORIES = 50       # all of them ride along in every prompt, so keep it small
MAX_CHARS = 300


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


with _conn() as c:
    c.execute(
        "CREATE TABLE IF NOT EXISTS memories ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "text TEXT NOT NULL, "
        "created_at TEXT NOT NULL)"
    )


def all_memories() -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT id, text FROM memories ORDER BY id")]


def prompt_block() -> str:
    """The memories as a system-prompt paragraph ('' when there are none)."""
    items = all_memories()
    if not items:
        return ""
    lines = " ".join(f"({m['id']}) {m['text']}" for m in items)
    return (
        " The user asked you to remember these preferences; follow them in every answer "
        "and tool call, and they override the defaults above: " + lines
    )


@tool
async def remember(text: str) -> str:
    """Save a lasting preference or fact the user wants Assist to follow, e.g.
    'Sign emails as Rohan Ajay Varghese' or 'My uni is Hochschule Albstadt-Sigmaringen in
    Albstadt'. Use only when the user asks you to remember something. Write `text` as one
    short, self-contained sentence. Never store passwords, codes or card numbers."""
    text = " ".join(text.split())[:MAX_CHARS]
    if not text:
        return json.dumps({"error": "nothing to remember"})
    with _conn() as c:
        if c.execute("SELECT COUNT(*) FROM memories").fetchone()[0] >= MAX_MEMORIES:
            return json.dumps({"error": f"memory is full ({MAX_MEMORIES}); forget something first"})
        cur = c.execute(
            "INSERT INTO memories (text, created_at) VALUES (?, ?)",
            (text, clock.now().isoformat(timespec="seconds")),
        )
    return json.dumps({"id": cur.lastrowid, "text": text})


@tool
async def forget_memory(id: int) -> str:
    """Delete one remembered preference. `id` is the number from list_memories."""
    with _conn() as c:
        row = c.execute("SELECT id, text FROM memories WHERE id = ?", (id,)).fetchone()
        if row is None:
            return json.dumps({"error": f"no memory {id}"})
        c.execute("DELETE FROM memories WHERE id = ?", (id,))
    return json.dumps({"forgotten": True, "id": row["id"], "text": row["text"]})


@tool
async def list_memories() -> str:
    """List everything the user asked Assist to remember, with ids.
    Use for 'what do you remember about me?' or before forgetting one."""
    return json.dumps(all_memories())


TOOLS = [remember, forget_memory, list_memories]
SAFE = {"list_memories"}
WRITES = {"remember", "forget_memory"}
