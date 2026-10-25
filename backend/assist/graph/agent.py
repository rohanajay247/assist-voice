import asyncio
import uuid

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_litellm import ChatLiteLLM
from langgraph.checkpoint.memory import MemorySaver  # NEW (Day 2)
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

load_dotenv()  # loads GEMINI_API_KEY from .env

# Standing instruction sent in front of every call to Gemini
SYSTEM = SystemMessage(
    "You are Assist, a voice assistant. Keep answers to 1-2 short sentences. "
    "The user lives in Albstadt, Germany; use that when no city is given. "
    "Use tools for the user's notes and weather; never invent their data. "
    "For general questions, answer briefly from your own knowledge."
)

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
    g.add_node("tools", ToolNode(tools))   # hands: runs whatever tool Gemini asked for
    g.add_edge(START, "agent")             # always start with the brain
    g.add_conditional_edges("agent", tools_condition)  # tool call → "tools", else → END
    g.add_edge("tools", "agent")           # after a tool runs, back to the brain

    # NEW (Day 2): the checkpointer saves the full state after every step,
    # keyed by thread_id. Same thread_id next call = conversation continues.
    # Also required for interrupt(): a paused graph resumes from this saved state.
    # MemorySaver keeps it in RAM, so a restart (or --reload) wipes it.
    return g.compile(checkpointer=MemorySaver())


async def main():
    """Terminal chat for testing the graph."""
    graph = await build_graph()

    # NEW: one thread per terminal session. No local `messages` list anymore,
    # the checkpointer remembers the conversation.
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    while True:
        text = input("\n> ")
        if text.strip().lower() in {"exit", "quit"}:
            break

        # Send only the new message; add_messages appends it to the saved history
        result = await graph.ainvoke({"messages": [HumanMessage(text)]}, config)
        messages = result["messages"]  # the whole thread

        # Print only this turn's tool calls: everything after the last user message
        start = max(i for i, m in enumerate(messages) if isinstance(m, HumanMessage))
        for m in messages[start + 1:]:
            for tc in getattr(m, "tool_calls", None) or []:
                print(f"  → {tc['name']}({tc['args']})")
        print(messages[-1].content)


if __name__ == "__main__":
    asyncio.run(main())  # MCP is async, so run main() in an event loop