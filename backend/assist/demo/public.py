"""Public demo (PUBLIC_DEMO=true): the hosted demo, safe for strangers.

Every visitor gets a sandbox:
- A random session token in an httpOnly cookie (signed, so only tokens this
  server issued count). Nothing else identifies them.
- Their own SQLite file, copied from a seeded template on first use: calendar,
  mail, drafts, notes, open and saved tabs, memories, undo log. Every DB access
  goes through demo.db_path(), which reads the visitor's file from a ContextVar
  set per request; outside a visitor's request it raises instead of falling back.
- The fake MCP servers run in-process (not as stdio subprocesses), so a tool call
  runs in the request's context and sees that file. A subprocess per call
  couldn't: its environment is fixed when the graph is built.
- Their conversation threads are stored under a server-side key
  "<session key>:<thread id>", so a thread id from another visitor finds nothing.
- 60 minutes idle: the file, the threads (checkpointer) and the tab listing go.
  At most PUBLIC_DEMO_MAX_SESSIONS sandboxes; when full, the oldest idle one goes.

Limits (env, see .env.example) answer with a friendly reply, not an error.
Single process only: sessions and counters live in RAM.
"""
import asyncio
import gc
import hashlib
import hmac
import itertools
import json
import logging
import os
import secrets
import shutil
import tempfile
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from importlib import import_module
from pathlib import Path

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from mcp import types

from backend.assist import demo


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


SESSION_MESSAGES = _int("PUBLIC_DEMO_SESSION_MESSAGES", 25)   # chat + voice, per visitor
SESSION_PHOTOS = _int("PUBLIC_DEMO_SESSION_PHOTOS", 5)
IP_MESSAGES = _int("PUBLIC_DEMO_IP_MESSAGES", 60)             # per IP per day (UTC)
DAILY_MESSAGES = _int("PUBLIC_DEMO_DAILY_MESSAGES", 1000)     # everyone together, per day
MAX_VOICE_SECONDS = _int("PUBLIC_DEMO_MAX_VOICE_SECONDS", 30)
MAX_PHOTO_BYTES = _int("PUBLIC_DEMO_MAX_PHOTO_MB", 5) * 1024 * 1024
MAX_CHARS = _int("PUBLIC_DEMO_MAX_CHARS", 1000)               # one typed message
SESSION_MINUTES = _int("PUBLIC_DEMO_SESSION_MINUTES", 60)     # idle time before a sandbox goes
MAX_SESSIONS = _int("PUBLIC_DEMO_MAX_SESSIONS", 200)
LOG_FORWARDED_FOR = os.getenv("LOG_FORWARDED_FOR", "").strip().lower() in ("1", "true", "yes")
# Generous for opus/webm at browser bitrates; the real check is Whisper's duration
MAX_AUDIO_BYTES = MAX_VOICE_SECONDS * 32 * 1024
DATA_DIR = Path(os.getenv("PUBLIC_DEMO_DATA_DIR", "").strip()
                or Path(tempfile.gettempdir()) / "assist-public-demo")
TEMPLATE = DATA_DIR / "template.db"

COOKIE = "assist_demo"
_SECRET = secrets.token_bytes(32)  # new per start: sandboxes don't survive a restart anyway

# ---------- friendly replies ----------

SESSION_LIMIT = (
    f"That's the end of this demo session: {SESSION_MESSAGES} messages per visitor. "
    "Thanks for trying Assist Voice! To keep going, run your own copy from GitHub."
)
PHOTO_LIMIT = (f"This demo takes up to {SESSION_PHOTOS} photos per visitor. "
               "You can still type or talk to me.")
IP_LIMIT = ("You've used today's demo messages from this network. "
            "Come back tomorrow, or run your own copy of Assist Voice from GitHub.")
DAILY_LIMIT = ("The live demo has reached today's limit. "
               "Please try again tomorrow, or run your own copy of Assist Voice from GitHub.")
PHOTO_TOO_BIG = f"That photo is over {MAX_PHOTO_BYTES // (1024 * 1024)} MB. Try a smaller one."
TOO_LONG = f"That message is a bit long for the demo. Keep it under {MAX_CHARS} characters."
VOICE_TOO_LONG = f"Voice messages in the demo can be up to {MAX_VOICE_SECONDS} seconds. Try a shorter one."
FULL = "The demo is busy right now. Please try again in a few minutes."


# ---------- sessions ----------

@dataclass
class Session:
    key: str            # internal, non-secret: names the DB file and prefixes thread ids
    db: Path
    last_seen: float
    messages: int = 0
    photos: int = 0
    voice: int = 0
    active: int = 0     # requests running right now: never expired mid-request
    order: int = 0      # last use, as a sequence: the clock can tie (15 ms steps on Windows)
    threads: set[str] = field(default_factory=set)


_sessions: dict[str, Session] = {}   # cookie token -> sandbox
_by_ip: dict[tuple[str, str], int] = {}
_by_day: dict[str, int] = {}
_lock = asyncio.Lock()
_uses = itertools.count(1)
_undeletable: list[Path] = []  # dropped sandboxes whose file couldn't be deleted yet
# Set by the API: deletes a thread from the checkpointer
_delete_thread = None


def _sign(token: str) -> str:
    return hmac.new(_SECRET, token.encode(), hashlib.sha256).hexdigest()[:32]


def new_cookie() -> str:
    token = secrets.token_urlsafe(24)
    return f"{token}.{_sign(token)}"


def valid_cookie(value: str | None) -> bool:
    if not value or value.count(".") != 1:
        return False
    token, sig = value.split(".")
    return hmac.compare_digest(sig, _sign(token))


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def _drop(token: str) -> None:
    """End a sandbox: its DB file, its threads, its tab listing."""
    s = _sessions.pop(token, None)
    if s is None:
        return
    from backend.assist import browser
    browser.forget_listing(str(s.db))
    if _delete_thread is not None:
        for thread in s.threads:
            await _delete_thread(thread)
    _undeletable.append(s.db)
    _delete_files()


def _delete_files() -> None:
    """Delete dropped sandbox files. Windows refuses while a SQLite connection is
    still open (the modules close theirs on garbage collection): retried later."""
    gc.collect()
    for db in list(_undeletable):
        try:
            for suffix in ("", "-journal", "-wal", "-shm"):
                Path(f"{db}{suffix}").unlink(missing_ok=True)
            _undeletable.remove(db)
        except PermissionError:
            pass


async def expire() -> None:
    """Drop every sandbox idle for SESSION_MINUTES."""
    if _undeletable:
        _delete_files()
    cutoff = time.monotonic() - SESSION_MINUTES * 60
    for token, s in list(_sessions.items()):
        if s.active == 0 and s.last_seen < cutoff:
            await _drop(token)
    today = _today()
    for key in [k for k in _by_ip if k[0] != today]:
        del _by_ip[key]
    for day in [d for d in _by_day if d != today]:
        del _by_day[day]


async def _session(token: str) -> Session | None:
    """The visitor's sandbox, created from the template on first use.
    None when every slot is busy with a running request."""
    async with _lock:
        await expire()
        s = _sessions.get(token)
        if s is None:
            if len(_sessions) >= MAX_SESSIONS:
                idle = [(v.order, k) for k, v in _sessions.items() if v.active == 0]
                if not idle:
                    return None
                await _drop(min(idle)[1])
            key = secrets.token_hex(8)
            db = DATA_DIR / f"{key}.db"
            shutil.copyfile(TEMPLATE, db)
            s = _sessions[token] = Session(key=key, db=db, last_seen=time.monotonic())
        s.last_seen, s.order = time.monotonic(), next(_uses)
        return s


class Visit:
    """One request inside a visitor's sandbox (see visit())."""

    def __init__(self, session: Session | None, ip: str):
        self.session = session
        self.ip = ip

    def thread(self, thread_id: str) -> str:
        """The server-side thread key: this visitor's threads only."""
        if self.session is None:
            return thread_id
        key = f"{self.session.key}:{thread_id}"
        self.session.threads.add(key)
        return key

    def message_limit(self, *, photo: bool = False, count: bool = True) -> str | None:
        """A friendly reply if this message is over a limit, else None (and it's counted)."""
        s = self.session
        if s is None:
            return FULL
        day = _today()
        if _by_day.get(day, 0) >= DAILY_MESSAGES:
            return DAILY_LIMIT
        if _by_ip.get((day, self.ip), 0) >= IP_MESSAGES:
            return IP_LIMIT
        if s.messages >= SESSION_MESSAGES:
            return SESSION_LIMIT
        if photo and s.photos >= SESSION_PHOTOS:
            return PHOTO_LIMIT
        if count:
            s.messages += 1
            s.photos += photo
            _by_day[day] = _by_day.get(day, 0) + 1
            _by_ip[(day, self.ip)] = _by_ip.get((day, self.ip), 0) + 1
        return None

    def voice_limit(self) -> str | None:
        """Transcribing: allowed while messages are left (the text then counts as one),
        and at most SESSION_MESSAGES recordings, so it can't be hammered on its own."""
        problem = self.message_limit(count=False)
        if problem:
            return problem
        if self.session.voice >= SESSION_MESSAGES:
            return SESSION_LIMIT
        self.session.voice += 1
        return None


log = logging.getLogger(__name__)


def client_ip(request) -> str:
    """The visitor's IP for the per-IP limit.
    uvicorn runs with --forwarded-allow-ips='*', so request.client.host is the FIRST
    X-Forwarded-For entry, which the visitor can set. Cloud Run appends the real
    client IP, so the LAST entry is the one to trust."""
    raw = ", ".join(request.headers.getlist("x-forwarded-for"))
    if LOG_FORWARDED_FOR:
        log.info("X-Forwarded-For: %r", raw)
    last = raw.rsplit(",", 1)[-1].strip()
    if last:
        return last
    return request.client.host if request.client else "unknown"


@asynccontextmanager
async def visit(request):
    """Run a request in the visitor's sandbox: their DB for every tool and module.
    Outside public demo: does nothing (Visit with no session, thread ids unchanged)."""
    if not demo.PUBLIC_DEMO:
        yield Visit(None, "")
        return
    ip = client_ip(request)
    token = request.scope.get("assist_demo_cookie", "")
    session = await _session(token)
    if session is None:
        yield Visit(None, ip)
        return
    session.active += 1
    try:
        with demo.use_db(session.db):
            yield Visit(session, ip)
    finally:
        session.active -= 1
        session.last_seen, session.order = time.monotonic(), next(_uses)


class CookieMiddleware:
    """Pure ASGI: makes sure every visitor has a valid session cookie.
    httpOnly, SameSite=Lax, Secure on https (also behind a TLS proxy)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        jar = SimpleCookie()
        try:
            jar.load(headers.get("cookie", ""))
        except Exception:
            pass
        value = jar[COOKIE].value if COOKIE in jar else None
        fresh = None
        if not valid_cookie(value):
            value = fresh = new_cookie()
        scope["assist_demo_cookie"] = value
        if fresh is None or scope["type"] != "http":
            return await self.app(scope, receive, send)

        https = scope.get("scheme") == "https" or headers.get("x-forwarded-proto", "") == "https"
        cookie = f"{COOKIE}={fresh}; Path=/; HttpOnly; SameSite=Lax" + ("; Secure" if https else "")

        async def send_with_cookie(message):
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                message["headers"] = [*message["headers"], (b"set-cookie", cookie.encode())]
            await send(message)

        await self.app(scope, receive, send_with_cookie)


# ---------- setup ----------

def build_template() -> None:
    """Fresh data dir with one seeded DB that every sandbox is copied from."""
    from backend.assist import actions, browser, memory
    from backend.assist.demo import store

    shutil.rmtree(DATA_DIR, ignore_errors=True)  # leftovers from the last run
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with demo.use_db(TEMPLATE):
        store.init_db()
        memory.init_db()
        actions.init_db()
        browser.init_db()
        store.reset()


async def sweep_forever() -> None:
    """Expire idle sandboxes even when nobody new arrives."""
    while True:
        await asyncio.sleep(60)
        async with _lock:
            await expire()


async def shutdown() -> None:
    for token in list(_sessions):
        await _drop(token)
    shutil.rmtree(DATA_DIR, ignore_errors=True)


# ---------- the fake servers, in-process ----------

class _LocalSession:
    """Enough of an MCP ClientSession for langchain-mcp-adapters, calling a FastMCP
    server directly in the caller's task. Results and errors are shaped like the
    MCP server's own (lowlevel call_tool), so the tools behave as over stdio."""

    def __init__(self, server):
        self.server = server

    async def list_tools(self, cursor=None, **_):
        return types.ListToolsResult(tools=await self.server.list_tools())

    async def call_tool(self, name, arguments=None, **_):
        try:
            result = await self.server.call_tool(name, arguments or {})
        except Exception as e:  # FastMCP wraps tool errors in ToolError
            return types.CallToolResult(content=[types.TextContent(type="text", text=str(e))],
                                        isError=True)
        if isinstance(result, tuple) and len(result) == 2:
            content, structured = result
        elif isinstance(result, dict):
            content = [types.TextContent(type="text", text=json.dumps(result, indent=2))]
            structured = result
        else:
            content, structured = result, None
        return types.CallToolResult(content=list(content), structuredContent=structured)


class InProcessClient(MultiServerMCPClient):
    """MultiServerMCPClient whose fake servers (notes, standup, github, google)
    run in-process; anything else (weather) still goes over its transport."""

    async def get_tools(self, *, server_name: str | None = None):
        if server_name in demo.FAKES:
            server = import_module(demo.FAKES[server_name]).mcp
            return await load_mcp_tools(_LocalSession(server), server_name=server_name,
                                        handle_tool_errors=self.handle_tool_errors)
        return await super().get_tools(server_name=server_name)


def install(agent_module, delete_thread) -> None:
    """Before build_graph(): seed the template, swap in the in-process client,
    and tell expiry how to delete a thread."""
    global _delete_thread
    _delete_thread = delete_thread
    build_template()
    agent_module.MultiServerMCPClient = InProcessClient
