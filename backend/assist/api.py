"""Assist API: POST /chat.

Day 2 change: the conversation history now lives on the server.

Before: the UI sent the whole conversation as plain text on every request.
Tool results (for example the id returned by add_note) were not part of that
text, so "delete it" in the next turn had to search for the note again.

Now: LangGraph's checkpointer saves the full graph state (every message,
including tool calls and tool results) under a thread_id. The UI sends only
the new message and its thread_id; LangGraph loads the rest.
This is also the base for interrupt() later today: a paused graph needs a
saved state to resume from.
"""
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import AIMessage, HumanMessage
from langfuse.langchain import CallbackHandler
from pydantic import BaseModel

from backend.assist.graph.agent import build_graph

load_dotenv()

graph = None
langfuse_handler = CallbackHandler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Built once at startup. The checkpointer lives inside the compiled graph,
    # so it also lives as long as the server process (RAM only, wiped by --reload).
    global graph
    graph = await build_graph()  # keep your own Day 1 line here if it differs
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    thread_id: str  # NEW: which saved conversation to continue
    message: str    # NEW: only the latest user text, no history


class ToolCall(BaseModel):
    name: str
    args: dict  # the UI shows these as "get_weather · Albstadt · 2"


class ChatResponse(BaseModel):
    reply: str
    tool_calls: list[ToolCall]


def this_turn(messages: list) -> list:
    """Messages produced after the latest user message.

    The graph now returns the WHOLE thread, not just this request.
    Without this slice, the UI would show every tool call ever made.
    """
    start = max(i for i, m in enumerate(messages) if isinstance(m, HumanMessage))
    return messages[start + 1:]


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    config = {
        # The key the checkpointer uses to save and load state.
        "configurable": {"thread_id": req.thread_id},
        "callbacks": [langfuse_handler],
        # Bonus: Langfuse groups all traces of one conversation into a session.
        "metadata": {"langfuse_session_id": req.thread_id},
    }

    # Send only the new message. The add_messages reducer appends it
    # to the saved history for this thread_id.
    result = await graph.ainvoke({"messages": [HumanMessage(req.message)]}, config)
    messages = result["messages"]

    tool_calls = [
        ToolCall(name=tc["name"], args=tc["args"])
        for m in this_turn(messages)
        if isinstance(m, AIMessage)
        for tc in m.tool_calls
    ]
    return ChatResponse(reply=messages[-1].content, tool_calls=tool_calls)