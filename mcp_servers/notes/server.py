import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from mcp.server.fastmcp import FastMCP

DB_PATH = Path(__file__).parent / "notes.db"
mcp = FastMCP("notes")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # rows behave like dicts
    return conn


# Runs once when the server starts
with get_conn() as conn:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS notes ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "text TEXT NOT NULL, "
        "created_at TEXT NOT NULL)"
    )


@mcp.tool()
def add_note(text: str) -> dict:
    """Save a new note. Use when the user wants to remember, jot down
    or note something. Returns the saved note including its id."""
    created_at = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO notes (text, created_at) VALUES (?, ?)",
            (text, created_at),
        )
        return {"id": cur.lastrowid, "text": text, "created_at": created_at}


@mcp.tool()
def list_notes(limit: int = 10) -> list[dict]:
    """List the most recent notes, newest first. Use when the user asks what notes they have. For finding a specific note, use search_notes instead."""
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM notes ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(row) for row in rows]


@mcp.tool()
def search_notes(query: str, limit: int = 10) -> list[dict]:
    """Search for notes containing the given keyword or phrase, newest
    first. Use when the user asks to find a specific note. Returns an
    empty list if nothing matches. For an overview, use list_notes."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM notes WHERE text LIKE ? ORDER BY id DESC LIMIT ?",
            (f"%{query}%", limit),
        )
        return [dict(row) for row in rows]


@mcp.tool()
def delete_note(id: int) -> dict:
    """Delete a note by its id. Use when the user asks to remove or
    delete a note. If you don't know the id, use search_notes or
    list_notes first. Returns the deleted note so it can be restored."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM notes WHERE id = ?", (id,)).fetchone()
        if row is None:
            return {"deleted": False, "error": f"No note with id {id}"}
        conn.execute("DELETE FROM notes WHERE id = ?", (id,))
        return {"deleted": True, **dict(row)}

if __name__ == "__main__":
    mcp.run()