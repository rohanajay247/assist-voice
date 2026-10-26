"""Assist API: POST /chat and POST /approve.

Day 2:
- History lives on the server. LangGraph's checkpointer stores the full state
  per thread_id; the UI sends only the new message.
- Approvals. When the graph pauses at interrupt() (a tool that changes data),
  /chat returns `pending` instead of a reply. The UI shows Approve/Deny and
  calls /approve, which resumes the same thread with Command(resume=...).
- Voice. /transcribe turns a push-to-talk recording into text with Groq Whisper.
"""
import os
from contextlib import asynccontextmanager

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langfuse.langchain import CallbackHandler
from langgraph.types import Command
from pydantic import BaseModel

from backend.assist.graph.agent import DENIED, build_graph

load_dotenv()

graph = None
langfuse_handler = CallbackHandler()

GROQ_STT_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
STT_MODEL = "whisper-large-v3-turbo"
MAX_AUDIO_BYTES = 25 * 1024 * 1024  # Groq's upload limit on the free tier


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Built once at startup. The checkpointer lives inside the compiled graph,
    # so it lives as long as the server process (RAM only, wiped by --reload).
    global graph
    graph = await build_graph()
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    thread_id: str  # which saved conversation to continue
    message: str    # only the latest user text, no history


class ApproveRequest(BaseModel):
    thread_id: str
    approved: bool


class ToolCall(BaseModel):
    name: str
    args: dict  # the UI shows these as "get_weather · Albstadt · 2"


class ChatResponse(BaseModel):
    reply: str
    tool_calls: list[ToolCall]          # calls that actually ran this turn
    pending: list[ToolCall] | None = None  # NEW: calls waiting for approval


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


def to_response(result: dict) -> ChatResponse:
    """Turn the graph result into what the UI needs.

    The result holds the WHOLE thread, so we cut it to this turn
    (everything after the latest user message).
    """
    messages = result["messages"]
    interrupts = result.get("__interrupt__")

    start = max(i for i, m in enumerate(messages) if isinstance(m, HumanMessage))
    turn = messages[start + 1:]
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
        return ChatResponse(reply="", tool_calls=tool_calls, pending=pending)

    return ChatResponse(reply=messages[-1].content, tool_calls=tool_calls)


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    # Send only the new message; add_messages appends it to the saved history.
    result = await graph.ainvoke(
        {"messages": [HumanMessage(req.message)]}, make_config(req.thread_id)
    )
    return to_response(result)


@app.post("/approve", response_model=ChatResponse)
async def approve(req: ApproveRequest) -> ChatResponse:
    # Resume the paused graph. interrupt() inside the approval node
    # returns this value, and the graph continues from there.
    decision = "approve" if req.approved else "deny"
    result = await graph.ainvoke(Command(resume=decision), make_config(req.thread_id))
    return to_response(result)

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
