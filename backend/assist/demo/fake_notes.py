"""Demo notes server: same tools, arguments and results as mcp_servers/notes, on the demo DB."""
from datetime import timezone

from mcp.server.fastmcp import FastMCP

from backend.assist import clock
from backend.assist.demo.store import conn

mcp = FastMCP("notes")


@mcp.tool()
def add_note(text: str) -> dict:
    """Save a new note. Use when the user wants to remember, jot down
    or note something. Returns the saved note including its id."""
    created_at = clock.now().astimezone(timezone.utc).isoformat()
    with conn() as c:
        cur = c.execute("INSERT INTO notes (text, created_at) VALUES (?, ?)", (text, created_at))
        return {"id": cur.lastrowid, "text": text, "created_at": created_at}


@mcp.tool()
def list_notes(limit: int = 10) -> list[dict]:
    """List the most recent notes, newest first. Use when the user asks what notes they have. For finding a specific note, use search_notes instead."""
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM notes ORDER BY id DESC LIMIT ?", (limit,))]


@mcp.tool()
def search_notes(query: str, limit: int = 10) -> list[dict]:
    """Search for notes containing the given keyword or phrase, newest
    first. Use when the user asks to find a specific note. Returns an
    empty list if nothing matches. For an overview, use list_notes."""
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM notes WHERE text LIKE ? ORDER BY id DESC LIMIT ?", (f"%{query}%", limit)
        )
        return [dict(r) for r in rows]


@mcp.tool()
def delete_note(id: int) -> dict:
    """Delete a note by its id. Use when the user asks to remove or
    delete a note. If you don't know the id, use search_notes or
    list_notes first. Returns the deleted note so it can be restored."""
    with conn() as c:
        row = c.execute("SELECT * FROM notes WHERE id = ?", (id,)).fetchone()
        if row is None:
            return {"deleted": False, "error": f"No note with id {id}"}
        c.execute("DELETE FROM notes WHERE id = ?", (id,))
        return {"deleted": True, **dict(row)}


if __name__ == "__main__":
    mcp.run()
