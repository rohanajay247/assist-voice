from contextlib import asynccontextmanager
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langfuse import get_client
from langfuse.langchain import CallbackHandler
from pydantic import BaseModel

load_dotenv()  # Langfuse keys (LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_BASE_URL)

from backend.assist.graph.agent import build_graph  # noqa: E402


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    messages: list[Message]


class ToolCall(BaseModel):
    name: str
    args: dict


class ChatResponse(BaseModel):
    reply: str
    tool_calls: list[ToolCall]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Build once: starts the MCP servers and compiles the graph
    app.state.graph = await build_graph()
    yield
    get_client().flush()  # send any buffered traces before exit


app = FastAPI(title="Assist", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    history = [(m.role, m.content) for m in req.messages]
    result = await app.state.graph.ainvoke(
        {"messages": history},
        config={"callbacks": [CallbackHandler()]},
    )

    # Only messages added this turn, so earlier tool calls aren't repeated
    new_messages = result["messages"][len(history):]
    tool_calls = [
        ToolCall(name=tc["name"], args=tc["args"])
        for m in new_messages
        for tc in getattr(m, "tool_calls", None) or []
    ]
    return ChatResponse(reply=result["messages"][-1].content, tool_calls=tool_calls)
