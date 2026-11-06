"""Public demo (PUBLIC_DEMO=true): sandboxes per visitor, expiry, limits, what's off.

A scripted chat model stands in for Gemini, so these run the real API, graph,
approvals, checkpointer and fake servers without any model calls:
  "note: X"  -> add_note(X)        "notes"   -> list_notes()
  "event: X" -> create_event(X)    "events"  -> list_events(7 days)
  "draft: X" -> create_draft(X)    anything else -> "hello"
After a tool ran, the reply is the tool's output, so tests can read the data back.

Run: uv run pytest tests/test_public_demo.py
"""
import json
import os
import sqlite3
import sys
import uuid

import pytest

if "backend.assist.demo" in sys.modules and not sys.modules["backend.assist.demo"].PUBLIC_DEMO:
    pytest.skip("needs a fresh process (another test imported Assist without PUBLIC_DEMO)",
                allow_module_level=True)

# Before Assist is imported: the flags are read once, on import
os.environ.update({
    "PUBLIC_DEMO": "true", "ASSIST_NOW": "2026-11-04T09:00",
    "ASSIST_ACCESS_TOKEN": "a-token-visitors-never-send",
    "LANGFUSE_PUBLIC_KEY": "", "LANGFUSE_SECRET_KEY": "",
})

from fastapi.testclient import TestClient  # noqa: E402
from langchain_core.callbacks import BaseCallbackHandler  # noqa: E402
from langchain_core.language_models.chat_models import BaseChatModel  # noqa: E402
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage  # noqa: E402
from langchain_core.outputs import ChatGeneration, ChatResult  # noqa: E402

from backend.assist import api  # noqa: E402
from backend.assist.demo import public  # noqa: E402
from backend.assist.graph import agent  # noqa: E402


def _text(content) -> str:
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in content if isinstance(b, dict))


class ScriptedModel(BaseChatModel):
    """Gemini stand-in: turns a few fixed phrases into tool calls."""
    model: str = "scripted"
    request_timeout: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=self._reply(messages))])

    def _reply(self, messages) -> AIMessage:
        if isinstance(messages[0], SystemMessage) and messages[0].content.startswith("Pick the tool"):
            return AIMessage("[]")  # router: no groups needed, the agent binds nothing anyway
        last = messages[-1]
        if isinstance(last, ToolMessage):
            return AIMessage(_text(last.content))
        text = _text(last.content) if isinstance(last, HumanMessage) else ""
        name, _, arg = text.partition(": ")
        calls = {
            "note": ("add_note", {"text": arg}),
            "notes": ("list_notes", {"limit": 50}),
            "event": ("create_event", {"title": arg, "start": "2026-11-05T16:00",
                                       "end": "2026-11-05T17:00"}),
            "events": ("list_events", {"days_ahead": 7}),
            "draft": ("create_draft", {"subject": arg, "body": "Hi,\n\nTest.\n\nRohan"}),
        }
        if name not in calls:
            return AIMessage("hello")
        tool, args = calls[name]
        return AIMessage("", tool_calls=[{"name": tool, "args": args, "id": uuid.uuid4().hex}])


@pytest.fixture(scope="module")
def app():
    agent.ChatLiteLLM = ScriptedModel  # build_graph() makes its models from this name
    api.langfuse_handler = BaseCallbackHandler()  # no traces from tests
    with TestClient(api.app) as client:  # runs the lifespan: template, in-process fakes, graph
        yield client


def visitor(app) -> TestClient:
    """A new browser: its own cookie jar, so its own sandbox."""
    client = TestClient(api.app)
    client.get("/")  # first request sets the cookie
    return client


def chat(client, message, thread="t1", **extra) -> dict:
    res = client.post("/chat", json={"thread_id": thread, "message": message, **extra})
    assert res.status_code == 200, res.text
    return res.json()


def approved(client, message, thread="t1") -> dict:
    """A write: chat pauses for approval, then approve it."""
    first = chat(client, message, thread)
    assert first["pending"], first
    res = client.post("/approve", json={"thread_id": thread, "approved": True})
    assert res.status_code == 200, res.text
    return res.json()


def session_of(client) -> public.Session:
    return public._sessions[client.cookies[public.COOKIE]]


def rows(client, sql) -> list:
    c = sqlite3.connect(session_of(client).db)
    try:
        return [r[0] for r in c.execute(sql)]
    finally:
        c.close()


@pytest.fixture(autouse=True)
def clean_limits():
    """Every test starts with fresh counters and default limits."""
    public._by_ip.clear()
    public._by_day.clear()
    yield


# ---------- isolation ----------

def test_sessions_cannot_see_each_others_data(app):
    a, b = visitor(app), visitor(app)
    assert a.cookies[public.COOKIE] != b.cookies[public.COOKIE]

    assert "alpha-secret" in approved(a, "note: alpha-secret")["reply"]
    approved(a, "event: Alpha meeting")
    approved(a, "draft: Alpha draft")

    # B: none of it, through the tools or in its own file
    assert "alpha-secret" not in chat(b, "notes")["reply"]
    assert "Alpha meeting" not in chat(b, "events")["reply"]
    assert "Alpha draft" not in rows(b, "SELECT subject FROM drafts")
    # A: all of it
    assert "alpha-secret" in chat(a, "notes")["reply"]
    assert "Alpha meeting" in chat(a, "events")["reply"]
    assert rows(a, "SELECT subject FROM drafts") == ["Alpha draft"]
    assert session_of(a).db != session_of(b).db
    # Both started from the same seed
    assert len(rows(b, "SELECT id FROM notes")) == len(rows(a, "SELECT id FROM notes")) - 1


def test_sessions_cannot_read_resume_or_approve_each_others_threads(app):
    a, b = visitor(app), visitor(app)
    pending = chat(a, "note: only-for-a", thread="shared-id")
    assert pending["pending"]

    # B uses the very same thread id: it's a different, empty thread
    assert b.get("/threads/shared-id").json() == {
        "reply": "", "tool_calls": [], "pending": None, "steps": []}
    assert b.post("/approve", json={"thread_id": "shared-id", "approved": True}).status_code == 409
    assert "only-for-a" not in chat(b, "notes", thread="shared-id")["reply"]

    # A's approval is still waiting and still A's
    assert a.get("/threads/shared-id").json()["pending"]
    assert a.post("/approve", json={"thread_id": "shared-id", "approved": True}).status_code == 200
    assert "only-for-a" not in chat(b, "notes")["reply"]


def test_undo_log_is_per_session(app):
    a, b = visitor(app), visitor(app)
    approved(a, "note: undo-me")
    chat(b, "hi")  # sandboxes are made on first use
    assert rows(a, "SELECT tool FROM actions") == ["add_note"]
    assert rows(b, "SELECT tool FROM actions") == []


def test_forged_cookie_gets_a_new_session(app):
    res = TestClient(api.app).get("/auth/check", headers={"cookie": f"{public.COOKIE}=made-up.0000"})
    issued = res.cookies[public.COOKIE]
    assert issued != "made-up.0000" and public.valid_cookie(issued)
    assert not public.valid_cookie("made-up.0000")


def test_cookie_flags(app):
    res = TestClient(api.app).get("/auth/check")
    cookie = res.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie and "Secure" not in cookie
    https = TestClient(api.app).get("/auth/check", headers={"x-forwarded-proto": "https"})
    assert "Secure" in https.headers["set-cookie"]


# ---------- expiry and the cap ----------

def test_expired_session_data_and_threads_are_gone(app):
    a = visitor(app)
    approved(a, "note: will-expire", thread="old")
    s = session_of(a)
    threads = set(s.threads)
    assert s.db.exists() and threads

    s.last_seen -= public.SESSION_MINUTES * 60 + 1
    app.portal.call(public.expire)  # on the app's own event loop

    assert not s.db.exists()
    assert a.cookies[public.COOKIE] not in public._sessions
    for thread in threads:  # gone from the checkpointer too
        assert not list(api.graph.checkpointer.list({"configurable": {"thread_id": thread}}))
    # Same browser comes back: a fresh sandbox, seed data only
    assert "will-expire" not in chat(a, "notes")["reply"]
    assert a.get("/threads/old").json()["reply"] == ""


def test_full_demo_drops_the_oldest_idle_session(app, monkeypatch):
    for token in list(public._sessions):  # start empty, so "oldest" means `first`
        app.portal.call(public._drop, token)
    monkeypatch.setattr(public, "MAX_SESSIONS", 2)
    first, second = visitor(app), visitor(app)
    chat(first, "hi")
    chat(second, "hi")
    first_db = session_of(first).db
    third = visitor(app)
    chat(third, "hi")
    assert first.cookies[public.COOKIE] not in public._sessions
    assert not first_db.exists()
    assert second.cookies[public.COOKIE] in public._sessions


# ---------- limits ----------

def test_session_message_limit(app, monkeypatch):
    monkeypatch.setattr(public, "SESSION_MESSAGES", 2)
    a = visitor(app)
    assert chat(a, "hi")["reply"] == "hello"
    assert chat(a, "hi")["reply"] == "hello"
    assert chat(a, "hi")["reply"] == public.SESSION_LIMIT
    assert chat(visitor(app), "hi")["reply"] == "hello"  # someone else still can


def test_ip_daily_limit(app, monkeypatch):
    monkeypatch.setattr(public, "IP_MESSAGES", 3)
    a, b = visitor(app), visitor(app)  # same IP (testclient)
    for _ in range(2):
        chat(a, "hi")
    chat(b, "hi")
    assert chat(b, "hi")["reply"] == public.IP_LIMIT
    assert chat(visitor(app), "hi")["reply"] == public.IP_LIMIT  # a new cookie doesn't help


def test_global_daily_limit(app, monkeypatch):
    monkeypatch.setattr(public, "DAILY_MESSAGES", 1)
    chat(visitor(app), "hi")
    assert chat(visitor(app), "hi")["reply"] == public.DAILY_LIMIT


PHOTO = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="


def test_photo_limits(app, monkeypatch):
    monkeypatch.setattr(public, "SESSION_PHOTOS", 0)  # no model call needed to see the limit
    a = visitor(app)
    assert chat(a, "what is this?", image=PHOTO)["reply"] == public.PHOTO_LIMIT
    monkeypatch.setattr(public, "MAX_PHOTO_BYTES", 10)
    assert chat(a, "what is this?", image=PHOTO)["reply"] == public.PHOTO_TOO_BIG
    assert chat(a, "x" * (public.MAX_CHARS + 1))["reply"] == public.TOO_LONG


def test_voice_limits(app, monkeypatch):
    a = visitor(app)
    big = b"\0" * (public.MAX_AUDIO_BYTES + 1)
    res = a.post("/transcribe", files={"audio": ("speech.webm", big, "audio/webm")})
    assert res.status_code == 200 and res.json() == {"text": "", "notice": public.VOICE_TOO_LONG}

    monkeypatch.setattr(public, "SESSION_MESSAGES", 1)
    chat(a, "hi")  # the one message is used up
    res = a.post("/transcribe", files={"audio": ("speech.webm", b"\0" * 100, "audio/webm")})
    assert res.json() == {"text": "", "notice": public.SESSION_LIMIT}


def test_voice_duration_from_whisper(app, monkeypatch):
    async def long_recording(audio, data):
        return "a long ramble", public.MAX_VOICE_SECONDS + 5
    monkeypatch.setattr(api, "whisper", long_recording)
    res = visitor(app).post("/transcribe", files={"audio": ("speech.webm", b"\0" * 100, "audio/webm")})
    assert res.json() == {"text": "", "notice": public.VOICE_TOO_LONG}


# ---------- what's off ----------

def test_no_token_needed_and_demo_flags(app):
    res = TestClient(api.app).get("/auth/check")
    assert res.status_code == 200
    body = res.json()
    assert body["demo"] is True and body["public"] is True
    assert body["limits"]["messages"] == public.SESSION_MESSAGES


def test_extension_socket_and_demo_endpoints_are_off(app):
    client = visitor(app)
    assert client.get("/ext/ws").status_code == 404
    with pytest.raises(Exception):
        with client.websocket_connect("/ext/ws"):
            pass
    assert client.post("/demo/reset").status_code in (404, 405)
    assert client.get("/demo/state").status_code == 404


def test_tool_building_is_off(app):
    assert agent.TOOLBUILDER_ENABLED is False
    tool_names = set(api.graph.nodes["tools"].bound.tools_by_name)
    assert not tool_names & {"build_tool", "install_tool", "remove_tool", "list_built_tools"}
    assert {"add_note", "create_event", "create_draft", "list_open_tabs"} <= tool_names


def test_real_servers_are_never_loaded(app):
    for name in ("notes", "google", "github", "standup"):
        cfg = agent.SERVERS[name]
        assert cfg.get("args", [None, None])[1] == public.demo.FAKES[name], cfg  # the fake module
    assert isinstance(agent.MultiServerMCPClient, type)
    assert agent.MultiServerMCPClient is public.InProcessClient


def test_data_access_outside_a_session_fails_closed(app):
    from backend.assist.demo import store
    with pytest.raises(RuntimeError):
        store.conn()
