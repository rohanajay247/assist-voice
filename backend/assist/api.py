"""Assist API: POST /chat and POST /approve.

Day 2:
- History lives on the server. LangGraph's checkpointer stores the full state
  per thread_id; the UI sends only the new message.
- Approvals. When the graph pauses at interrupt() (a tool that changes data),
  /chat returns `pending` instead of a reply. The UI shows Approve/Deny and
  calls /approve, which resumes the same thread with Command(resume=...).
- Voice. /transcribe turns a push-to-talk recording into text with Groq Whisper.
"""
import base64
import binascii
import json
import os
import re
import secrets
from contextlib import asynccontextmanager
from typing import Literal

import httpx
import litellm
from dotenv import load_dotenv
from fastapi import (
    Depends, FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketException,
)
from starlette.requests import HTTPConnection
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langfuse.langchain import CallbackHandler
from langgraph.types import Command
from pydantic import BaseModel

from backend.assist import browser, demo
from backend.assist.graph.agent import DENIED, UNDOABLE, build_graph, needs_approval
from backend.assist.toolbuilder import registry

load_dotenv()

graph = None
langfuse_handler = CallbackHandler()

GROQ_STT_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
STT_MODEL = "whisper-large-v3-turbo"
MAX_AUDIO_BYTES = 25 * 1024 * 1024  # Groq's upload limit on the free tier
MAX_IMAGE_BYTES = 4 * 1024 * 1024    # the browser resizes to ~1600px JPEG, far below this
IMAGE_DATA_URL = re.compile(r"^data:image/(jpeg|png);base64,(.+)$", re.S)
DEFAULT_IMAGE_QUESTION = "What is this, and what do I need to do?"

# The tunnel URL is public, so every request must carry this token.
# Unset (local dev): no check.
ACCESS_TOKEN = os.getenv("ASSIST_ACCESS_TOKEN", "")


def require_token(conn: HTTPConnection) -> None:
    """Reject requests without the right X-Assist-Token header.

    The browser extension's WebSocket can't set headers, so ?token= works too.
    """
    if not ACCESS_TOKEN:
        return
    given = conn.headers.get("x-assist-token") or conn.query_params.get("token", "")
    # Constant-time compare, so response timing doesn't leak the token
    if not secrets.compare_digest(given.encode(), ACCESS_TOKEN.encode()):
        if conn.scope["type"] == "websocket":
            raise WebSocketException(code=1008, reason="Missing or wrong access token")
        raise HTTPException(401, "Missing or wrong access token")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Built once at startup. The checkpointer lives inside the compiled graph,
    # so it lives as long as the server process (RAM only, wiped by --reload).
    global graph
    if demo.DEMO_MODE:  # every start is a clean demo
        from backend.assist.demo import store
        store.reset()
    graph = await build_graph()
    yield


app = FastAPI(lifespan=lifespan, dependencies=[Depends(require_token)])
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    thread_id: str  # which saved conversation to continue
    message: str    # only the latest user text, no history
    image: str | None = None  # optional photo as a data URL (JPEG or PNG)


class ApproveRequest(BaseModel):
    thread_id: str
    approved: bool


class ToolCall(BaseModel):
    name: str
    args: dict  # the UI shows these as "get_weather · Albstadt · 2"
    preview: dict | None = None  # approval card detail, e.g. a built tool's code and tests


class Step(BaseModel):
    # One line in the UI's step panel: what Assist did this turn, in order
    kind: Literal["plan", "approval", "tool", "undo_log"]
    label: str
    status: Literal["ok", "denied", "error", "waiting"]


class ChatResponse(BaseModel):
    reply: str
    tool_calls: list[ToolCall]          # calls that actually ran this turn
    pending: list[ToolCall] | None = None  # NEW: calls waiting for approval
    steps: list[Step] = []              # what happened this turn, for the step panel


class TranscribeResponse(BaseModel):
    text: str


def make_config(thread_id: str) -> dict:
    return {
        # The key the checkpointer uses to save and load state.
        "configurable": {"thread_id": thread_id},
        "callbacks": [langfuse_handler],
        # Langfuse groups all traces of one conversation into a session.
        "metadata": {"langfuse_session_id": thread_id},
    }


def returned_error(m: ToolMessage) -> bool:
    """True if the tool failed: an exception, or a result like {"error": "..."}."""
    if m.status == "error":
        return True
    content = m.content
    if isinstance(content, list):  # MCP results can arrive as content blocks
        content = "".join(b.get("text", "") for b in content if isinstance(b, dict))
    try:
        data = json.loads(content)
    except (TypeError, ValueError):
        return False
    return isinstance(data, dict) and "error" in data


def build_steps(turn: list, interrupted: bool) -> list[Step]:
    """Walk this turn's messages in order and describe each thing that happened.

    `turn` must include the last AIMessage even when the graph is interrupted,
    because its calls are the ones still waiting for approval.
    """
    results = {m.tool_call_id: m for m in turn if isinstance(m, ToolMessage)}
    names = {
        tc["id"]: tc["name"]
        for m in turn
        if isinstance(m, AIMessage)
        for tc in m.tool_calls
    }
    steps: list[Step] = []

    for m in turn:
        if isinstance(m, AIMessage):
            for tc in m.tool_calls:
                steps.append(Step(kind="plan", label=f"Decided to call {tc['name']}", status="ok"))
                if not needs_approval(tc):
                    continue  # safe tools skip approval
                result = results.get(tc["id"])
                if result is not None:
                    status = "denied" if result.content == DENIED else "ok"
                elif interrupted:
                    status = "waiting"
                else:
                    continue  # no answer and no interrupt: nothing to report
                steps.append(Step(kind="approval", label=f"Approval for {tc['name']}", status=status))

        elif isinstance(m, ToolMessage) and m.content != DENIED:
            name = m.name or names.get(m.tool_call_id, "tool")
            failed = returned_error(m)
            steps.append(Step(kind="tool", label=f"Ran {name}", status="error" if failed else "ok"))
            # The graph's record node logs successful writes so they can be undone
            if name in UNDOABLE and not failed:
                steps.append(Step(kind="undo_log", label="Saved for undo", status="ok"))

    return steps


def to_response(result: dict) -> ChatResponse:
    """Turn the graph result into what the UI needs.

    The result holds the WHOLE thread, so we cut it to this turn
    (everything after the latest user message).
    """
    messages = result["messages"]
    interrupts = result.get("__interrupt__")

    start = max(i for i, m in enumerate(messages) if isinstance(m, HumanMessage))
    turn = messages[start + 1:]
    steps = build_steps(turn, interrupted=bool(interrupts))  # before the cut below
    if interrupts:
        turn = turn[:-1]  # the last message holds the calls still waiting, not run yet

    # Denied calls never ran, so don't show them as tool labels
    denied = {
        m.tool_call_id
        for m in turn
        if isinstance(m, ToolMessage) and m.content == DENIED
    }
    tool_calls = [
        ToolCall(name=tc["name"], args=tc["args"])
        for m in turn
        if isinstance(m, AIMessage)
        for tc in m.tool_calls
        if tc["id"] not in denied
    ]

    if interrupts:
        pending = [ToolCall(**p) for p in interrupts[0].value]
        return ChatResponse(reply="", tool_calls=tool_calls, pending=pending, steps=steps)

    return ChatResponse(reply=messages[-1].content, tool_calls=tool_calls, steps=steps)


@app.get("/auth/check")
async def auth_check() -> dict:
    # The app-wide require_token dependency does the work: reaching this
    # line means the token is valid (or none is configured).
    # `demo` tells the UI to show its "Demo mode" badge.
    return {"ok": True, "demo": demo.DEMO_MODE}


if demo.DEMO_MODE:
    from backend.assist.demo import store

    # Only exist in demo mode; behind the same token check as everything else

    @app.post("/demo/reset")
    async def demo_reset() -> dict:
        """Back to the seed data; empty undo log, memories and drafts."""
        store.reset()
        browser.reset_listing()
        return {"ok": True, "state": store.state()}

    @app.get("/demo/state")
    async def demo_state() -> dict:
        """Counts the evals compare before and after a case."""
        return store.state()


def check_image(image: str) -> None:
    """Accept only a JPEG/PNG data URL with valid base64, up to MAX_IMAGE_BYTES."""
    match = IMAGE_DATA_URL.match(image)
    if not match:
        raise HTTPException(400, "Image must be a JPEG or PNG data URL")
    try:
        data = base64.b64decode(match.group(2), validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(400, "Image data is not valid base64")
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "Image is larger than 4 MB")


async def rebuild_if_tools_changed() -> None:
    """A built tool was installed or removed (or undone): rebuild the graph so
    the next message sees the new tool list. Same checkpointer, so every
    conversation and pending approval carries over."""
    global graph
    if registry.consume_changed():
        graph = await build_graph(checkpointer=graph.checkpointer)


# Gemini (via LiteLLM) unavailable: quota or rate limit, timeout, 5xx, no
# connection. Anything else is a real bug and still fails loudly.
MODEL_ERRORS = (
    litellm.RateLimitError,
    litellm.Timeout,
    litellm.ServiceUnavailableError,
    litellm.InternalServerError,
    litellm.BadGatewayError,
    litellm.APIConnectionError,
)
MODEL_DOWN = (
    "The AI service isn't available right now (quota or outage). "
    "Nothing was changed, try again in a few minutes."
)
# The approved change ran, then the model failed while writing its reply
MODEL_DOWN_AFTER_CHANGE = (
    "The AI service isn't available right now (quota or outage), so I couldn't finish "
    "my reply. The change you approved did go through (see the steps), try again in a "
    "few minutes."
)


async def model_unavailable(config: dict) -> ChatResponse:
    """A normal reply instead of a 500 when the model fails mid-turn.

    The checkpointer kept everything up to the failed model call, so the
    steps and tool labels still show what ran this turn, and the reply
    says honestly whether anything changed.
    """
    messages = (await graph.aget_state(config)).values.get("messages", [])
    if not any(isinstance(m, HumanMessage) for m in messages):
        return ChatResponse(reply=MODEL_DOWN, tool_calls=[])
    start = max(i for i, m in enumerate(messages) if isinstance(m, HumanMessage))
    changed = any(
        isinstance(m, ToolMessage) and m.name in UNDOABLE
        and m.content != DENIED and not returned_error(m)
        for m in messages[start + 1:]
    )
    # The reply stands in for the model's missing last message (only in this
    # response; the saved thread is untouched). No __interrupt__: never pending.
    reply = AIMessage(MODEL_DOWN_AFTER_CHANGE if changed else MODEL_DOWN)
    return to_response({"messages": [*messages, reply]})


async def run_graph(payload, thread_id: str) -> ChatResponse:
    """Run one turn (a new message or an approval answer) and shape the response."""
    config = make_config(thread_id)
    try:
        result = await graph.ainvoke(payload, config)
    except MODEL_ERRORS as e:
        print(f"Model unavailable ({e.__class__.__name__}): {str(e)[:200]}")
        response = await model_unavailable(config)
        await rebuild_if_tools_changed()  # a tool install may have run before the failure
        return response
    await rebuild_if_tools_changed()
    return to_response(result)


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    # Send only the new message; add_messages appends it to the saved history.
    if req.image:
        check_image(req.image)
        text = req.message.strip() or DEFAULT_IMAGE_QUESTION
        # Text + image in one message; the graph sends it to the vision model
        message = HumanMessage([
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": req.image}},
        ])
    else:
        message = HumanMessage(req.message)
    return await run_graph({"messages": [message]}, req.thread_id)


async def waiting_approval(thread_id: str) -> list:
    """The interrupts this thread is paused at ([] if it isn't waiting for approval)."""
    snapshot = await graph.aget_state(make_config(thread_id))
    return list(snapshot.interrupts)


@app.post("/approve", response_model=ChatResponse)
async def approve(req: ApproveRequest) -> ChatResponse:
    # Resume the paused graph. interrupt() inside the approval node
    # returns this value, and the graph continues from there.
    # Only while it's really paused: a stale or second click (e.g. Deny after the
    # Approve already went through) must not resume anything.
    if not await waiting_approval(req.thread_id):
        raise HTTPException(409, "Nothing is waiting for approval")
    decision = "approve" if req.approved else "deny"
    return await run_graph(Command(resume=decision), req.thread_id)


@app.get("/threads/{thread_id}", response_model=ChatResponse)
async def thread_state(thread_id: str) -> ChatResponse:
    """The latest turn of a thread as the server has it: pending approval,
    tool calls, steps and the last reply. The UI reloads this when an
    /approve answer got lost, instead of trusting its own buttons."""
    snapshot = await graph.aget_state(make_config(thread_id))
    messages = snapshot.values.get("messages", [])
    if not any(isinstance(m, HumanMessage) for m in messages):
        return ChatResponse(reply="", tool_calls=[])
    if snapshot.interrupts:
        return to_response({"messages": messages, "__interrupt__": list(snapshot.interrupts)})
    last = messages[-1]
    if isinstance(last, AIMessage) and isinstance(last.content, str):
        return to_response({"messages": messages})
    # The turn ended without a reply (e.g. the model failed after a tool ran)
    return to_response({"messages": [*messages, AIMessage("")]})

@app.websocket("/ext/ws")
async def extension_socket(ws: WebSocket) -> None:
    # The Save-my-tabs extension stays connected here; tab tools send it commands
    await browser.serve(ws)


@app.get("/ext/status")
async def extension_status() -> dict:
    return {"connected": browser.connected()}


@app.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(audio: UploadFile = File(...)) -> TranscribeResponse:
    # One push-to-talk recording (webm/ogg from MediaRecorder) -> text.
    # No language is sent, so Whisper auto-detects English or German.
    data = await audio.read()
    if not data:
        raise HTTPException(400, "Empty audio")
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "Audio is larger than 25 MB")

    key = os.getenv("GROQ_API_KEY")
    if not key:
        raise HTTPException(500, "GROQ_API_KEY is not set")

    # Groq reads the format from the file extension, so keep the browser's name
    filename = audio.filename or "speech.webm"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.post(
                GROQ_STT_URL,
                headers={"Authorization": f"Bearer {key}"},
                files={"file": (filename, data, audio.content_type or "audio/webm")},
                data={"model": STT_MODEL, "response_format": "json"},
            )
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Could not reach Groq: {e.__class__.__name__}")

    if res.status_code != 200:
        try:
            detail = res.json()["error"]["message"]
        except Exception:
            detail = res.text[:200]
        # 400 from Groq means it couldn't use the audio; anything else is on their side
        status = 422 if res.status_code == 400 else 502
        raise HTTPException(status, f"Groq error {res.status_code}: {detail}")

    return TranscribeResponse(text=res.json().get("text", "").strip())
