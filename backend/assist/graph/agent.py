import asyncio
import uuid
from typing import Literal

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_litellm import ChatLiteLLM
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.types import Command, interrupt  # NEW (Day 2): approvals

load_dotenv()  # loads GEMINI_API_KEY from .env

# Standing instruction sent in front of every call to Gemini
SYSTEM = SystemMessage(
    "You are Assist, a voice assistant. Keep answers to 1-2 short sentences. "
    "The user lives in Albstadt, Germany; use that when no city is given. "
    "Use tools for the user's notes and weather; never invent their data. "
    "For general questions, answer briefly from your own knowledge. "
    "If the user denies an action, acknowledge it and do not retry."
)

# NEW: tools that change data. These wait for the user's OK; all others run directly.
WRITE_TOOLS = {"add_note", "delete_note"}
DENIED = "User denied this action."

# One entry per MCP server: how to start it and how to talk to it
client = MultiServerMCPClient(
    {
        "notes": {
            "command": "uv",
            "args": ["run", "python", "mcp_servers/notes/server.py"],
            "transport": "stdio",  # talk over stdin/stdout, like the Inspector
        },
        "weather": {
            "command": "uv",
            "args": ["run", "python", "mcp_servers/weather/server.py"],
            "transport": "stdio",
        },
    }
)


async def approval(state: MessagesState) -> Command[Literal["tools", "agent"]]:
    """NEW: the safety layer. Sits between the brain and the hands.

    Read-only calls pass straight through. Calls that change data pause the
    graph with interrupt() until the user approves or denies.
    On resume this node runs again from the top, so nothing before
    interrupt() may have side effects (here: it only reads state).
    """
    calls = state["messages"][-1].tool_calls

    # Only reading? No need to ask.
    if not any(c["name"] in WRITE_TOOLS for c in calls):
        return Command(goto="tools")

    # Pause. The payload is what the UI shows; the return value is the user's answer.
    decision = interrupt([{"name": c["name"], "args": c["args"]} for c in calls])

    if decision == "approve":
        return Command(goto="tools")

    # Denied: every tool call needs an answer, or Gemini errors on the next call.
    # Tell the model "no" and let it reply to the user.
    return Command(
        goto="agent",
        update={
            "messages": [
                ToolMessage(content=DENIED, tool_call_id=c["id"]) for c in calls
            ]
        },
    )


async def build_graph():
    """Connect to the MCP servers, attach their tools to Gemini, return the compiled graph."""
    tools = await client.get_tools()
    print("Tools:", [t.name for t in tools])

    # The brain: Gemini, told which tools exist (their names, docstrings, schemas)
    model = ChatLiteLLM(model="gemini/gemini-3.1-flash-lite").bind_tools(tools)

    # Node 1, "agent": send the conversation to Gemini, add its reply to the state
    async def agent(state: MessagesState):
        response = await model.ainvoke([SYSTEM] + state["messages"])
        return {"messages": [response]}

    # Build the graph
    g = StateGraph(MessagesState)          # state = a list of messages
    g.add_node("agent", agent)             # brain
    g.add_node("approval", approval)       # NEW: safety layer
    g.add_node("tools", ToolNode(tools))   # hands: runs whatever tool Gemini asked for
    g.add_edge(START, "agent")             # always start with the brain
    # CHANGED: a tool call now goes to "approval" first, not straight to "tools".
    # approval routes itself with Command(goto=...), so it needs no edges.
    g.add_conditional_edges("agent", tools_condition, {"tools": "approval", END: END})
    g.add_edge("tools", "agent")           # after a tool runs, back to the brain

    # The checkpointer saves state per thread_id; interrupt() needs it to resume.
    return g.compile(checkpointer=MemorySaver())


async def main():
    """Terminal chat for testing the graph."""
    graph = await build_graph()
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    while True:
        text = input("\n> ")
        if text.strip().lower() in {"exit", "quit"}:
            break

        result = await graph.ainvoke({"messages": [HumanMessage(text)]}, config)

        # NEW: the graph paused for approval → ask, then resume the same thread
        while "__interrupt__" in result:
            for p in result["__interrupt__"][0].value:
                print(f"  ? {p['name']}({p['args']})")
            answer = input("  Approve? [y/n] ").strip().lower()
            decision = "approve" if answer == "y" else "deny"
            result = await graph.ainvoke(Command(resume=decision), config)

        messages = result["messages"]  # the whole thread

        # Print only this turn's tool calls: everything after the last user message
        start = max(i for i, m in enumerate(messages) if isinstance(m, HumanMessage))
        for m in messages[start + 1:]:
            for tc in getattr(m, "tool_calls", None) or []:
                print(f"  → {tc['name']}({tc['args']})")
        print(messages[-1].content)


if __name__ == "__main__":
    asyncio.run(main())  # MCP is async, so run main() in an event loop