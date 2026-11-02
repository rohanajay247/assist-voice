"""Save my tabs (Day 5): the bridge to the browser extension, plus saved tabs.

The extension (extension/) keeps a WebSocket open to /ext/ws. Assist sends
it small commands and waits for the answer:

    {"id": "...", "cmd": "list"}                       -> {"id", "tabs": [...]}
    {"id": "...", "cmd": "close", "ids": [12, 13]}     -> {"id", "closed": 2}
    {"id": "...", "cmd": "open", "urls": ["https://"]} -> {"id", "opened": 1}

Saved tabs live in SQLite (tabs.db, gitignored) so "what did I save about
LangGraph?" works days later. The tools below are local LangChain tools, like
undo_last_action: the connection lives in the API process, and an MCP server
started per call couldn't hold it.
"""
import asyncio
import json
import re
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import WebSocket, WebSocketDisconnect
from langchain_core.tools import tool

BERLIN = ZoneInfo("Europe/Berlin")
DB_PATH = Path(__file__).parent / "tabs.db"  # *.db is gitignored
TIMEOUT = 10  # seconds to wait for the extension
NOT_CONNECTED = (
    "The browser extension isn't connected. Open Chrome with the Assist extension "
    "installed and the API running."
)
# Never closed: Assist's own app (closing it would end the conversation)
PROTECTED_PREFIXES = ("http://localhost:5173", "https://localhost:5173")
PROTECTED_HOSTS = (".trycloudflare.com",)
CATEGORIES = ("read_later", "todo", "search")
# Web searches: closed like any finished page, but remembered as "search" so
# "what was I searching yesterday?" works. Matched by URL, not by the model.
SEARCH_URL = re.compile(
    r"^https?://(www\.)?(google\.[a-z.]+/search|bing\.com/search|duckduckgo\.com/\?"
    r"|search\.brave\.com/search|ecosia\.org/search|perplexity\.ai/search)"
)

# ---------- connection ----------

_socket: WebSocket | None = None
_waiting: dict[str, asyncio.Future] = {}
# Last list_open_tabs result: short number (1, 2, 3...) -> tab. The model works
# with these numbers; Chrome's own ids are 10 digits and it garbles them.
_listed: dict[int, dict] = {}
_searches: list[dict] = []  # search tabs from the same list: never shown to the model


async def serve(ws: WebSocket) -> None:
    """Run one extension connection until it closes. A new one replaces the old."""
    global _socket
    await ws.accept()
    _socket = ws
    print("Browser extension connected")
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            if msg.get("type") == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
                continue
            future = _waiting.pop(str(msg.get("id")), None)
            if future and not future.done():
                future.set_result(msg)
    except (WebSocketDisconnect, json.JSONDecodeError, RuntimeError):
        pass
    finally:
        if _socket is ws:
            _socket = None
            print("Browser extension disconnected")


def connected() -> bool:
    return _socket is not None


async def _ask(cmd: str, **payload) -> dict:
    """Send one command to the extension and wait for its answer."""
    if _socket is None:
        raise ConnectionError(NOT_CONNECTED)
    rid = uuid.uuid4().hex
    future = asyncio.get_running_loop().create_future()
    _waiting[rid] = future
    try:
        await _socket.send_text(json.dumps({"id": rid, "cmd": cmd, **payload}))
        reply = await asyncio.wait_for(future, TIMEOUT)
    except asyncio.TimeoutError:
        raise ConnectionError("The browser extension didn't answer in time.")
    except RuntimeError:  # socket closed mid-send
        raise ConnectionError(NOT_CONNECTED)
    finally:
        _waiting.pop(rid, None)
    if "error" in reply:
        raise ConnectionError(f"Browser: {reply['error']}")
    return reply


def _protected(tab: dict) -> bool:
    url = tab.get("url", "")
    host = url.split("/")[2] if url.count("/") >= 2 else ""
    return tab.get("pinned") or url.startswith(PROTECTED_PREFIXES) or host.endswith(PROTECTED_HOSTS)


async def _open_tabs() -> dict[int, dict]:
    tabs = (await _ask("list"))["tabs"]
    return {t["id"]: t for t in tabs if str(t.get("url", "")).startswith(("http://", "https://"))}

# ---------- storage ----------

def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


with _conn() as c:
    c.execute(
        "CREATE TABLE IF NOT EXISTS saved_tabs ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "batch TEXT NOT NULL, "
        "category TEXT NOT NULL, "  # read_later | todo | search | closed (kept so undo can reopen)
        "title TEXT NOT NULL, "
        "url TEXT NOT NULL, "
        "saved_at TEXT NOT NULL, "  # Berlin time, ISO
        "opened_at TEXT)"
    )


def _now() -> str:
    return datetime.now(BERLIN).isoformat(timespec="seconds")

# ---------- tools ----------

@tool
async def list_open_tabs() -> str:
    """List the tabs open in the user's browser, numbered 1, 2, 3...
    Call this first for 'save my tabs' or 'clean up my browser'."""
    global _listed, _searches
    try:
        tabs = await _open_tabs()
    except ConnectionError as e:
        return json.dumps({"error": str(e)})
    rest = [t for t in tabs.values() if not _protected(t)]
    # Searches are sorted by the server, not the model: always closed and remembered
    _searches = [t for t in rest if SEARCH_URL.match(t["url"])]
    _listed = {n: t for n, t in enumerate([t for t in rest if t not in _searches], start=1)}
    return json.dumps({
        "tabs": [
            {"n": n, "title": t.get("title", "")[:90], "url": t["url"][:150]}
            for n, t in _listed.items()
        ],
        "searches_closed_and_remembered_automatically": len(_searches),
        "always_kept_open": len(tabs) - len(rest),  # pinned tabs and Assist itself
    })


def _plan(read_later: list[int], todo: list[int], keep_open: list[int]) -> dict[str, list[dict]]:
    """Which listed tab goes where. Every listed tab not saved or kept is closed."""
    picked: dict[int, str] = {}
    for category, numbers in (("keep_open", keep_open), ("todo", todo), ("read_later", read_later)):
        for n in numbers:
            if n in _listed:
                picked.setdefault(n, category)  # first list wins: keep > todo > read_later
    plan = {"read_later": [], "todo": [], "keep_open": [], "close": [], "search": list(_searches)}
    for n, tab in _listed.items():
        plan[picked.get(n, "close")].append(tab)
    return plan


@tool
async def save_tabs(read_later: list[int], todo: list[int], keep_open: list[int] | None = None) -> str:
    """Save and close the user's tabs in one step, using the numbers from list_open_tabs.
    `read_later`: articles, docs, videos worth reading later (saved, then closed).
    `todo`: pages that need an action, like forms, applications, job posts (saved, then closed).
    `keep_open`: tabs the user is still working in (left open, not saved).
    Every other listed tab (searches, finished pages) is closed without saving."""
    if not _listed and not _searches:
        return json.dumps({"error": "call list_open_tabs first"})
    plan = _plan(read_later, todo, keep_open or [])
    try:
        live = await _open_tabs()
    except ConnectionError as e:
        return json.dumps({"error": str(e)})

    def still_open(tab):  # the user may have closed or navigated it since the list
        now = live.get(tab["id"])
        return now is not None and now["url"] == tab["url"]

    batch, now = uuid.uuid4().hex[:8], _now()
    closing, gone = [], 0
    with _conn() as c:
        for category in ("read_later", "todo", "search", "close"):
            for tab in plan[category]:
                if not still_open(tab):
                    gone += 1
                    continue
                stored = "closed" if category == "close" else category
                c.execute(
                    "INSERT INTO saved_tabs (batch, category, title, url, saved_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (batch, stored,
                     tab.get("title", "") or tab["url"], tab["url"], now),
                )
                closing.append(tab)

    try:
        if closing:
            await _ask("close", ids=[t["id"] for t in closing])
    except ConnectionError as e:
        with _conn() as c:  # nothing closed: don't keep a half-done save
            c.execute("DELETE FROM saved_tabs WHERE batch = ?", (batch,))
        return json.dumps({"error": str(e)})

    closed_ids = {t["id"] for t in closing}
    return json.dumps({
        "batch": batch,
        "saved_read_later": [t.get("title", "") for t in plan["read_later"] if t["id"] in closed_ids],
        "saved_todo": [t.get("title", "") for t in plan["todo"] if t["id"] in closed_ids],
        "searches_remembered": [t.get("title", "") for t in plan["search"] if t["id"] in closed_ids],
        "closed_total": len(closing),
        "kept_open": len(live) - len(closing),
        **({"already_gone": gone} if gone else {}),
    })


@tool
async def restore_tabs(batch: str) -> str:
    """Undo a save_tabs: reopen the tabs it closed and forget what it saved.
    Only used by undo_last_action."""
    with _conn() as c:
        rows = c.execute("SELECT url FROM saved_tabs WHERE batch = ?", (batch,)).fetchall()
    urls = list(dict.fromkeys(r["url"] for r in rows))
    try:
        open_now = {t["url"] for t in (await _open_tabs()).values()}
        urls = [u for u in urls if u not in open_now]  # e.g. reopened earlier: no duplicates
        if urls:
            await _ask("open", urls=urls)
    except ConnectionError as e:
        return json.dumps({"error": str(e)})
    with _conn() as c:
        c.execute("DELETE FROM saved_tabs WHERE batch = ?", (batch,))
    return json.dumps({"restored": True, "reopened": len(urls)})


@tool
async def search_saved_tabs(query: str = "", category: str = "", day: str = "") -> str:
    """Find tabs the user saved earlier with 'save my tabs'.
    `query`: words in the title or link, e.g. 'langgraph' ('' = all).
    `category`: 'read_later', 'todo', 'search' (web searches the user had open) or '' for all.
    `day`: 'YYYY-MM-DD' (Berlin) to only show tabs saved that day, or ''."""
    sql, params = "SELECT * FROM saved_tabs WHERE category != 'closed'", []
    for word in query.split():
        sql += " AND (title LIKE ? OR url LIKE ?)"
        params += [f"%{word}%", f"%{word}%"]
    if category in CATEGORIES:
        sql += " AND category = ?"
        params.append(category)
    if day:
        try:
            start = datetime.fromisoformat(day).replace(tzinfo=BERLIN)
        except ValueError:
            return json.dumps({"error": "day must look like 2026-11-02"})
        sql += " AND saved_at >= ? AND saved_at < ?"
        params += [start.isoformat(), (start + timedelta(days=1)).isoformat()]
    with _conn() as c:
        rows = c.execute(sql + " ORDER BY id DESC LIMIT 200", params).fetchall()
    # The same page saved in several rounds shows once (its newest save)
    seen, unique = set(), []
    for r in rows:
        if r["url"] not in seen:
            seen.add(r["url"])
            unique.append(r)
    rows = unique[:20]
    return json.dumps([
        {"id": r["id"], "category": r["category"], "title": r["title"], "url": r["url"],
         "saved_at": r["saved_at"], **({"opened_at": r["opened_at"]} if r["opened_at"] else {})}
        for r in rows
    ])


@tool
async def open_saved_tabs(ids: list[int]) -> str:
    """Reopen saved tabs in the user's browser. `ids` come from search_saved_tabs.
    Only saved tabs can be opened, never other links."""
    with _conn() as c:
        rows = c.execute(
            f"SELECT * FROM saved_tabs WHERE category != 'closed' "
            f"AND id IN ({','.join('?' * len(ids))})", ids
        ).fetchall() if ids else []
    if not rows:
        return json.dumps({"error": "no saved tabs with those ids"})
    try:
        await _ask("open", urls=[r["url"] for r in rows])
    except ConnectionError as e:
        return json.dumps({"error": str(e)})
    with _conn() as c:
        c.executemany("UPDATE saved_tabs SET opened_at = ? WHERE id = ?",
                      [(_now(), r["id"]) for r in rows])
    return json.dumps({"opened": [r["title"] for r in rows], "urls": [r["url"] for r in rows]})


@tool
async def close_reopened_tabs(urls: list[str]) -> str:
    """Undo an open_saved_tabs: close the tabs it opened (one per link, newest first).
    Only used by undo_last_action."""
    try:
        tabs = await _open_tabs()
        ids = []
        for url in urls:
            matches = sorted((t["id"] for t in tabs.values() if t["url"] == url and t["id"] not in ids),
                             reverse=True)  # Chrome ids grow: the newest tab is the reopened one
            ids += matches[:1]
        if ids:
            await _ask("close", ids=ids)
    except ConnectionError as e:
        return json.dumps({"error": str(e)})
    return json.dumps({"closed": len(ids)})


def preview(args: dict) -> dict:
    """Approval card for save_tabs: every listed tab and where it goes."""
    plan = _plan(args.get("read_later") or [], args.get("todo") or [], args.get("keep_open") or [])
    titles = lambda key: [t.get("title") or t["url"] for t in plan[key]]
    return {"kind": "tabs", "read_later": titles("read_later"), "todo": titles("todo"),
            "search": titles("search"), "close": titles("close"), "keep_open": titles("keep_open")}


SAFE = {"list_open_tabs", "search_saved_tabs", "open_saved_tabs"}
WRITES = {"save_tabs"}
# Run without approval but still go in the undo log ("undo that" after "open it")
UNDOABLE_SAFE = {"open_saved_tabs"}
UNDO_ONLY = [restore_tabs, close_reopened_tabs]  # called by undo, never shown to the model
TOOLS = [list_open_tabs, save_tabs, search_saved_tabs, open_saved_tabs]
