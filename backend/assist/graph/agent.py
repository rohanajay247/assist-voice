import asyncio

from dotenv import load_dotenv
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_litellm import ChatLiteLLM
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

load_dotenv()  # loads GEMINI_API_KEY from .env

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


async def main():
    tools = await client.get_tools()
    print("Tools:", [t.name for t in tools])

    # The brain: Gemini, told which tools exist (their names, docstrings, schemas)
    model = ChatLiteLLM(model="gemini/gemini-3.1-flash-lite").bind_tools(tools)

    # Node 1, "agent": send the conversation to Gemini, add its reply to the state
    async def agent(state: MessagesState):
        response = await model.ainvoke(state["messages"])
        return {"messages": [response]}

    # Build the graph
    g = StateGraph(MessagesState)          # state = a list of messages
    g.add_node("agent", agent)             # brain
    g.add_node("tools", ToolNode(tools))   # hands: runs whatever tool Gemini asked for
    g.add_edge(START, "agent")             # always start with the brain
    g.add_conditional_edges("agent", tools_condition)  # tool call → "tools", else → END
    g.add_edge("tools", "agent")           # after a tool runs, back to the brain
    graph = g.compile()                    # turn the drawing into something runnable

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