"""Demo stand-in for the browser extension: answers browser.py's three commands
from the open_tabs table instead of a live Chrome."""
from backend.assist.demo.store import conn


async def ask(cmd: str, **payload) -> dict:
    """Same request/answer shapes as the extension (see browser.py)."""
    with conn() as c:
        if cmd == "list":
            rows = c.execute("SELECT * FROM open_tabs ORDER BY id").fetchall()
            return {"tabs": [{"id": r["id"], "title": r["title"], "url": r["url"],
                              "pinned": bool(r["pinned"])} for r in rows]}
        if cmd == "close":
            ids = [int(i) for i in payload.get("ids", [])]
            if ids:
                c.execute(f"DELETE FROM open_tabs WHERE id IN ({','.join('?' * len(ids))})", ids)
            return {"closed": len(ids)}
        if cmd == "open":
            urls = payload.get("urls", [])
            for url in urls:
                # Reopened tabs get their saved title back, like the page loading again
                known = c.execute("SELECT title FROM saved_tabs WHERE url = ? ORDER BY id DESC LIMIT 1",
                                  (url,)).fetchone()
                c.execute("INSERT INTO open_tabs (title, url) VALUES (?, ?)",
                          (known["title"] if known else url, url))
            return {"opened": len(urls)}
    return {"error": f"unknown command {cmd!r}"}
