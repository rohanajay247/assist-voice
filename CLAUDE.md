# Assist: notes for Claude Code

Open-source voice assistant that works across tools via MCP. Portfolio project,
7-day build. Source of truth for scope: the product document (owner has it).

## Stack

Python 3.12 + uv · FastAPI · LangGraph · langchain-mcp-adapters · MCP SDK (FastMCP)
· LiteLLM → Gemini (Flash-Lite default, Flash for multi-step/vision, Pro only for
tool-building) · Groq Whisper (STT) · browser TTS · React + TypeScript PWA (Vite)
· SQLite (later Supabase) · Langfuse (EU) · Docker · Azure. Keep costs near zero.

## Layout (planned)

- backend/assist/ FastAPI app, LangGraph graph, routing
- mcp_servers/<name>/ one folder per MCP server
- web/ React + TS PWA
- evals/ 40-command test suite
- PROGRESS.md daily handoff log

## Who writes what. IMPORTANT

The owner writes these by hand. Do NOT create or edit them unless explicitly asked:

- mcp_servers/notes/ (first MCP server)
- backend/assist/graph/ (LangGraph graph, approvals, undo)
- backend/assist/routing/ (tool routing)
- evals/ (test suite)
- backend/assist/toolbuilder/ (tool-building flow)
  Claude Code builds: UI, setup, OAuth, Docker, config, wiring existing MCP servers.

## Rules

- Before changing files, say in 2–3 lines what you'll change and why.
- Secrets live only in .env (gitignored). Never hardcode keys, not even as defaults.
  Add every new variable to .env.example with an empty value.
- Use uv for Python deps (uv add …), npm for web/.
- Small commits with clear messages. Don't push unless asked.
- Every change to a write action must keep the approve-before-change and undo rules.
- Commits are authored by the owner only. Never add Co-Authored-By trailers,
  "Generated with Claude Code" lines, or any AI attribution to commits or PRs.
