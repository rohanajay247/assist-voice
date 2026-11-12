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
import logging
import re
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import WebSocket, WebSocketDisconnect
from langchain_core.tools import tool

from backend.assist import clock, demo

log = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "tabs.db"  # *.db is gitignored; demo mode uses the demo DB
TIMEOUT = 10  # seconds to wait for the extension
NOT_CONNECTED = (
    "The browser extension isn't connected. Open Chrome with the Assist Voice extension "
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


class _Listing:
    """The last list_open_tabs result. One per visitor in public demo, else just one."""

    def __init__(self):
        # short number (1, 2, 3...) -> tab. The model works with these numbers;
        # Chrome's own ids are 10 digits and it garbles them.
        self.listed: dict[int, dict] = {}
        self.searches: list[dict] = []  # search tabs from the same list: never shown to the model


_listings: dict[str, _Listing] = {}


def _listing() -> _Listing:
    return _listings.setdefault(demo.session_key(), _Listing())


async def serve(ws: WebSocket) -> None:
    """Run one extension connection until it closes. A new one replaces the old."""
    global _socket
    await ws.accept()
    _socket = ws
    log.info("Browser extension connected")
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
            log.info("Browser extension disconnected")


def connected() -> bool:
    return (demo.DEMO_MODE and not demo.REAL_BROWSER) or _socket is not None


def reset_listing() -> None:
    """Forget the last list_open_tabs numbering (demo reset: the tabs changed)."""
    _listings.pop(demo.session_key(), None)


def forget_listing(key: str) -> None:
    """Public demo: a visitor's session ended."""
    _listings.pop(key, None)


async def _ask(cmd: str, **payload) -> dict:
    """Send one command to the extension and wait for its answer."""
    if demo.DEMO_MODE and not demo.REAL_BROWSER:
        from backend.assist.demo import fake_browser  # demo: fake tabs instead of Chrome
        return await fake_browser.ask(cmd, **payload)
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
    conn = sqlite3.connect(demo.db_path(DB_PATH))  # per call: public demo has one DB per visitor
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _conn() as c:
        c.execute(
            "CREATE TABLE IF NOT EXISTS saved_tabs ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "batch TEXT NOT NULL, "
            "category TEXT NOT NULL, "  # read_later | todo | search | closed (kept so undo can reopen)
            "title TEXT NOT NULL, "
            "url TEXT NOT NULL, "
            "saved_at TEXT NOT NULL, "  # local time (clock.TZ), ISO
            "opened_at TEXT)"
        )
        # Day 6: a saved tab can be finished ("I applied to that job"), so lists don't go stale
        if "done_at" not in {r["name"] for r in c.execute("PRAGMA table_info(saved_tabs)")}:
            c.execute("ALTER TABLE saved_tabs ADD COLUMN done_at TEXT")


if not demo.PUBLIC_DEMO:  # public demo: created per visitor, from a template
    init_db()


def _now() -> str:
    return clock.now().isoformat(timespec="seconds")

# ---------- tools ----------

@tool
async def list_open_tabs() -> str:
    """List the tabs open in the user's browser, numbered 1, 2, 3...
    Call this first for 'save my tabs' or 'clean up my browser'."""
    listing = _listing()
    try:
        tabs = await _open_tabs()
    except ConnectionError as e:
        return json.dumps({"error": str(e)})
    rest = [t for t in tabs.values() if not _protected(t)]
    # Searches are sorted by the server, not the model: always closed and remembered
    listing.searches = [t for t in rest if SEARCH_URL.match(t["url"])]
    listing.listed = {n: t for n, t in enumerate([t for t in rest if t not in listing.searches], start=1)}
    return json.dumps({
        "tabs": [
            {"n": n, "title": t.get("title", "")[:90], "url": t["url"][:150]}
            for n, t in listing.listed.items()
        ],
        "searches_closed_and_remembered_automatically": len(listing.searches),
        "always_kept_open": len(tabs) - len(rest),  # pinned tabs and Assist itself
    })


def _plan(read_later: list[int], todo: list[int], keep_open: list[int]) -> dict[str, list[dict]]:
    """Which listed tab goes where. Every listed tab not saved or kept is closed."""
    listing = _listing()
    picked: dict[int, str] = {}
    for category, numbers in (("keep_open", keep_open), ("todo", todo), ("read_later", read_later)):
        for n in numbers:
            if n in listing.listed:
                picked.setdefault(n, category)  # first list wins: keep > todo > read_later
    plan = {"read_later": [], "todo": [], "keep_open": [], "close": [], "search": list(listing.searches)}
    for n, tab in listing.listed.items():
        plan[picked.get(n, "close")].append(tab)
    return plan


@tool
async def save_tabs(read_later: list[int], todo: list[int], keep_open: list[int] | None = None) -> str:
    """Save and close the user's tabs in one step, using the numbers from list_open_tabs.
    `read_later`: articles, docs, videos worth reading later (saved, then closed).
    `todo`: pages that need an action, like forms, applications, job posts (saved, then closed).
    `keep_open`: tabs the user is still working in (left open, not saved).
    Every other listed tab (searches, finished pages) is closed without saving."""
    if not _listing().listed and not _listing().searches:
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
async def search_saved_tabs(
    query: str = "", category: str = "", day: str = "", max_age_days: int = 0,
    include_done: bool = False,
) -> str:
    """Find tabs the user saved earlier with 'save my tabs' (saved, not open in the browser).
    `query`: words in the title or link, e.g. 'langgraph' ('' = all).
    `category`: 'read_later', 'todo', 'search' (web searches the user had open) or '' for all.
    `day`: 'YYYY-MM-DD' (local) to only show tabs saved that day, or ''.
    `max_age_days`: only tabs saved in the last N days (0 = any age).
    `include_done`: also show tabs the user marked as done."""
    sql, params = "SELECT * FROM saved_tabs WHERE category != 'closed'", []
    if not include_done:
        sql += " AND done_at IS NULL"
    if max_age_days > 0:
        sql += " AND saved_at >= ?"
        params.append((clock.now() - timedelta(days=max_age_days)).isoformat(timespec="seconds"))
    for word in query.split():
        sql += " AND (title LIKE ? OR url LIKE ?)"
        params += [f"%{word}%", f"%{word}%"]
    if category in CATEGORIES:
        sql += " AND category = ?"
        params.append(category)
    if day:
        try:
            start = datetime.fromisoformat(day).replace(tzinfo=clock.TZ)
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
         "saved_at": r["saved_at"], **({"opened_at": r["opened_at"]} if r["opened_at"] else {}),
         **({"done_at": r["done_at"]} if r["done_at"] else {})}
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


def _set_done(ids: list[int], value: str | None) -> list[dict]:
    """Mark saved tabs done (value = now) or not done (None). Same link saved twice: all copies."""
    if not ids:
        return []
    with _conn() as c:
        rows = c.execute(
            f"SELECT id, title, url FROM saved_tabs WHERE category != 'closed' "
            f"AND id IN ({','.join('?' * len(ids))})", ids
        ).fetchall()
        urls = [r["url"] for r in rows]
        if urls:
            c.execute(
                f"UPDATE saved_tabs SET done_at = ? WHERE category != 'closed' "
                f"AND url IN ({','.join('?' * len(urls))})", [value, *urls]
            )
    return [dict(r) for r in rows]


@tool
async def mark_tabs_done(ids: list[int]) -> str:
    """Mark saved tabs as done so they stop showing up in briefs and searches,
    e.g. 'I applied to that job', 'done with the EggAI one', 'clear my tab to-dos'.
    `ids` come from search_saved_tabs."""
    rows = _set_done(ids, _now())
    if not rows:
        return json.dumps({"error": "no saved tabs with those ids"})
    return json.dumps({"done": [r["title"] for r in rows], "ids": [r["id"] for r in rows]})


@tool
async def unmark_tabs_done(ids: list[int]) -> str:
    """Undo a mark_tabs_done. Only used by undo_last_action."""
    rows = _set_done(ids, None)
    return json.dumps({"restored": len(rows)})


COLUMNS = ("id", "batch", "category", "title", "url", "saved_at", "opened_at", "done_at")


def _forget_rows(ids: list[int], all_done: bool, everything: bool = False) -> list[sqlite3.Row]:
    if everything:  # full flush, including the closed-only rows kept for undo
        return _conn().execute("SELECT * FROM saved_tabs").fetchall()
    sql = "SELECT * FROM saved_tabs WHERE category != 'closed' AND "
    if all_done:
        return _conn().execute(sql + "done_at IS NOT NULL").fetchall()
    if not ids:
        return []
    with _conn() as c:
        urls = [r["url"] for r in c.execute(
            sql + f"id IN ({','.join('?' * len(ids))})", ids).fetchall()]
        if not urls:
            return []
        # the same link saved in several rounds goes with it, or it would pop up again
        return c.execute(sql + f"url IN ({','.join('?' * len(urls))})", urls).fetchall()


@tool
async def forget_saved_tabs(
    ids: list[int] | None = None, all_done: bool = False, everything: bool = False,
) -> str:
    """Delete saved tabs for good, e.g. 'forget the EggAI tab', 'clear my done tabs',
    'forget all my saved tabs'. The user approves first; undo brings them back.
    `ids` from search_saved_tabs, `all_done`=true for every tab marked done, or
    `everything`=true to flush every saved tab and search."""
    rows = _forget_rows(ids or [], all_done, everything)
    if not rows:
        return json.dumps({"error": "no saved tabs matched"})
    with _conn() as c:
        c.execute(f"DELETE FROM saved_tabs WHERE id IN ({','.join('?' * len(rows))})",
                  [r["id"] for r in rows])
    return json.dumps({
        "forgotten": list(dict.fromkeys(r["title"] for r in rows)),
        "rows": [{k: r[k] for k in COLUMNS} for r in rows],  # kept for undo
    })


@tool
async def restore_forgotten_tabs(rows: list[dict]) -> str:
    """Undo a forget_saved_tabs. Only used by undo_last_action."""
    with _conn() as c:
        c.executemany(
            f"INSERT OR IGNORE INTO saved_tabs ({', '.join(COLUMNS)}) "
            f"VALUES ({', '.join('?' * len(COLUMNS))})",
            [[r.get(k) for k in COLUMNS] for r in rows],
        )
    return json.dumps({"restored": len(rows)})


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


def forget_preview(args: dict) -> dict:
    """Approval card for forget_saved_tabs: the titles that will be deleted."""
    rows = _forget_rows(args.get("ids") or [], bool(args.get("all_done")), bool(args.get("everything")))
    return {"kind": "tabs", "forget": list(dict.fromkeys(
        r["title"] for r in rows if r["category"] != "closed"))}


def preview(args: dict) -> dict:
    """Approval card for save_tabs: every listed tab and where it goes."""
    plan = _plan(args.get("read_later") or [], args.get("todo") or [], args.get("keep_open") or [])
    titles = lambda key: [t.get("title") or t["url"] for t in plan[key]]
    return {"kind": "tabs", "read_later": titles("read_later"), "todo": titles("todo"),
            "search": titles("search"), "close": titles("close"), "keep_open": titles("keep_open")}


SAFE = {"list_open_tabs", "search_saved_tabs", "open_saved_tabs", "mark_tabs_done"}
WRITES = {"save_tabs", "forget_saved_tabs"}
# Run without approval but still go in the undo log ("undo that" after "open it")
UNDOABLE_SAFE = {"open_saved_tabs", "mark_tabs_done"}
UNDO_ONLY = [restore_tabs, close_reopened_tabs, unmark_tabs_done, restore_forgotten_tabs]  # called by undo, never shown to the model
TOOLS = [list_open_tabs, save_tabs, search_saved_tabs, open_saved_tabs, mark_tabs_done,
         forget_saved_tabs]
