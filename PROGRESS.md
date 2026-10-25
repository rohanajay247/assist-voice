# Progress

Learning journal (Journal + Code walkthrough tabs): https://claude.ai/artifact/5aZckGZhATJqt65BPTNe4q

## Day 0 — Sat 24 Oct (setup)

- Keys set up (Gemini, Groq, Langfuse EU); stored in .env only
- Tools checked: Python 3.12, uv, Node 22, Git, Docker
- Repo created with CLAUDE.md, .env.example, Claude attribution off

## Day 1 — Sat 24 – Sun 25 Oct (skeleton)

**Done**
- uv project (`pyproject.toml`, `uv.lock`, Python 3.12 pinned)
- Notes MCP server (`mcp_servers/notes/`): add, list, search, delete over SQLite; add returns the id, delete returns the deleted note (for undo)
- Weather MCP server (`mcp_servers/weather/`): `get_weather(city, days)` via Open-Meteo, no key
- LangGraph agent (`backend/assist/graph/agent.py`): `build_graph()` = agent node (Gemini Flash-Lite via LiteLLM) + ToolNode + `tools_condition`; terminal chat in `main()`; system prompt (short voice replies, default city Albstadt-Ebingen, never invent user data)
- FastAPI `POST /chat` (`backend/assist/api.py`): graph built once at startup, returns reply + this turn's tool calls, Langfuse tracing, CORS for 5173
- React + TS UI (`web/`): chat, tool-call labels, empty state with example prompts, blue logo mark, Source Serif headings, light/dark, disabled mic placeholder
- Langfuse traces visible (agent → tools → agent)

**Broken / skipped**
- Tool calls take ~2.3s: the MCP adapter starts a new server process per call. Fix later with persistent sessions
- UI sends only text history, so tool results from earlier turns are lost ("delete it" has to search again). Fixed by a checkpointer on Day 2
- Langfuse shows no token/cost numbers for LiteLLM calls
- Cursor uses the wrong Python interpreter (import warnings); select `.venv`

**Decisions**
- litellm pinned `>=1.101,<1.106` (1.106 needs mcp 2.x; langchain-mcp-adapters needs mcp <2). Remove once the adapters support mcp 2
- One `text` field for notes; no `update_note` until undo can store old versions
- Graph built by hand (not prebuilt) so Day 2 can add an approval node
- Local DB and `.claude/` are gitignored

**How to run**
- API: `uv run uvicorn backend.assist.api:app --reload`
- UI: `cd web; npm run dev` → http://localhost:5173
- Terminal chat: `uv run python backend/assist/graph/agent.py`
- Test a server: `uv run mcp dev mcp_servers/notes/server.py`

**First task Day 2**
- Brief on checkpointers + `interrupt()`, then add a `MemorySaver` checkpointer and a `thread_id` to `/chat` so history lives on the server
