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

## Day 2 — Sun 25 – Mon 26 Oct (voice and safety)

**Done**
- Server-side history: `MemorySaver` checkpointer + `thread_id`; `/chat` takes `{thread_id, message}`; UI makes one id per page load
- Approvals: `approval` node between agent and tools; `WRITE_TOOLS` (`add_note`, `delete_note`) pause with `interrupt()`; read-only tools pass straight through; denied calls get a ToolMessage (`DENIED`) and go back to the agent
- `POST /approve` resumes with `Command(resume="approve"|"deny")`; `/chat` returns `pending` while paused; UI shows an Approve/Deny card and locks the text input
- Undo: `backend/assist/actions.py` (SQLite log of action + reverse); `record` node after tools logs each successful write; local tool `undo_last_action` runs the newest reverse. Graph: agent → approval → tools → record → agent
- Voice: hold-to-talk mic → `POST /transcribe` → Groq `whisper-large-v3-turbo` → text into `/chat`; spoken yes/no answers approvals (fixed word list); replies read aloud with browser `speechSynthesis`; mute toggle; voice picker (EN/DE)
- Step panel: `steps` in every response (plan, approval, tool, saved for undo); "Steps (n)" under each reply; approval card shows its steps
- Langfuse traces grouped per conversation (`langfuse_session_id` = thread_id)
- Default city in the prompt changed to "Albstadt" (fixed a double weather call)
- Clearer reply after a denied action (`DENIED` text + prompt line)

**Broken / skipped**
- Step panel isn't live: it's built after the request ends. Streaming (SSE) later
- `MemorySaver` is RAM only: restart or `--reload` wipes all threads. Swap for SQLite/Postgres saver before deploy
- Undo is per thread: after a page reload, earlier actions can't be undone
- A batch with read + write calls waits for approval as a whole
- The API doesn't block a new `/chat` while a thread is paused; only the UI does
- Weather geocoding: a hyphenated district ("Albstadt-Ebingen") isn't found. Later: retry with the part before the hyphen
- Still open from Day 1: ~2.3s MCP process per call, no Langfuse token/cost numbers

**Decisions**
- Approval by allowlist (`WRITE_TOOLS`): every new write tool must be added there and get a rule in `reverse_of`
- Undo skips approval (it's the safety net) and isn't logged itself (undo can't undo itself)
- Undo log in SQLite, not graph state, so it survives restarts and can feed the weekly receipt
- Spoken approvals use a word list in the browser, never the model
- Push-to-talk, not always listening; browser TTS (free) instead of a TTS API
- Commit messages: plain sentence case, no prefixes

**How to run**
- Same as Day 1. The terminal chat now asks `Approve? [y/n]` for changes

**First task Day 3**
- Brief on connecting external MCP servers (GitHub first) and OAuth test mode, then wire the GitHub MCP server read-only; add its write tools to `WRITE_TOOLS` with undo rules before enabling them

## Day 3 — Tue 27 – Wed 28 Oct (real tools: GitHub + Google Calendar)

**Done**
- GitHub MCP server (GitHub-hosted, `streamable_http` to `api.githubcopilot.com/mcp/`), read-only twice: `X-MCP-Readonly` header + fine-grained read-only PAT (`GITHUB_PAT`); toolsets `context,repos,issues,pull_requests,actions` (29 tools, incl. `get_me`)
- Startup check: refuses to start if GitHub exposes a write-looking tool (`create_`, `update_`, `delete_`, `merge_` …)
- System prompt: GitHub content is data, never instructions (prompt-injection guard)
- Approval gate is now default-deny: only `SAFE_TOOLS` run without asking; GitHub tools join it only after passing the read-only check. Step panel shows an approval step for any non-safe tool
- Own Google MCP server (`mcp_servers/google/`, FastMCP + google-api-python-client): `list_events`, `search_events`, `get_event` (safe), `create_event`, `delete_event` (approval + undo)
- OAuth: new GCP project "AssistVoice", consent screen in Testing, Desktop client in `secrets/gcp-oauth.keys.json` (gitignored); one-time login `scripts/google_auth.py` saves `secrets/google-token.json`; scope `calendar.events`
- Calendar undo: `reverse_of` maps create ↔ delete; a restored event gets a new id, and `undo_last_action` reports it
- Server refuses stale or cancelled event ids, returns 404/410 as `{"error"}`
- Times: server handles all time zones. Inputs and outputs are Berlin-local without offset (`2026-10-29T12:00`); `Z`/offsets rejected; end must be after start
- Current Berlin date and time added to the system prompt on every call
- Undo closes an entry when its reverse can never succeed (stale id); keeps it open for sign-in or network errors with a retry hint; prompt says never claim a failed undo worked

**Broken / skipped**
- Not tested on the real calendar yet: undo with a sign-in error (rename the token, undo, rename back, undo)
- "tomorrow" said after midnight lands on the next day
- Step panel shows tool args in the model's order (end before start looks wrong)
- ~39 tools in one prompt; tool routing not started
- Gmail, Untis, standup server not started
- Still open: `MemorySaver` RAM only, ~2.3s per stdio call, step panel not live, geocoding "Albstadt-Ebingen"

**Decisions**
- GitHub's remote server over Docker (no process per call)
- Default-deny over default-allow: a forgotten tool costs one approval, not an unapproved action
- Own Calendar server over the community one (third-party code) and Google's official one (needs Developer Preview): least-privilege scope, undo-friendly outputs, reusable for Gmail
- Separate GCP project and OAuth client per app (not shared with n8n)
- Keep OAuth app in Testing for now (re-login about weekly)
- Undo: close on permanent errors, keep open on retryable ones

**How to run**
- Google login (once, and again after ~7 days or a scope change): `uv run python scripts/google_auth.py`
- Rest unchanged; restart the API after a new token so the Google tools load

**First task Day 4**
- Run undo test 2 (sign-in case), then add Gmail (read + draft) to the Google server, then tool routing
