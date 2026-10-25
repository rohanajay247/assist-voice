import asyncio

from dotenv import load_dotenv
from langchain_core.messages import SystemMessage  # NEW
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_litellm import ChatLiteLLM
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

load_dotenv()  # loads GEMINI_API_KEY from .env

# NEW: standing instruction sent in front of every call to Gemini
SYSTEM = SystemMessage(
    "You are Assist, a voice assistant. Keep answers to 1-2 short sentences. "
    "The user lives in Albstadt Ebingen, Germany; use that when no city is given. "
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
        response = await model.ainvoke([SYSTEM] + state["messages"])  # NEW: system prompt first
        return {"messages": [response]}

    # Build the graph
    g = StateGraph(MessagesState)          # state = a list of messages
    g.add_node("agent", agent)             # brain
    g.add_node("tools", ToolNode(tools))   # hands: runs whatever tool Gemini asked for
    g.add_edge(START, "agent")             # always start with the brain
    g.add_conditional_edges("agent", tools_condition)  # tool call → "tools", else → END
    g.add_edge("tools", "agent")           # after a tool runs, back to the brain
    return g.compile()                     # turn the drawing into something runnable


async def main():
    """Terminal chat for testing the graph."""
    graph = await build_graph()

    messages = []  # the conversation, kept across turns
    while True:
        text = input("\n> ")
        if text.strip().lower() in {"exit", "quit"}:
            break
        messages.append(("user", text))

        # Run the whole loop for this turn
        result = await graph.ainvoke({"messages": messages})

        # Print only this turn's tool calls, then the final answer
        for m in result["messages"][len(messages):]:
            for tc in getattr(m, "tool_calls", None) or []:
                print(f"  → {tc['name']}({tc['args']})")
        print(result["messages"][-1].content)

        # Save the full history so "delete it" knows what "it" is
        messages = result["messages"]


if __name__ == "__main__":
    asyncio.run(main())  # MCP is async, so run main() in an event loop