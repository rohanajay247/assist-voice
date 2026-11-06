# Assist Voice

**Say what you need, and it handles it across your calendar, email, notes, GitHub and browser tabs, but only after you say yes.**

https://github.com/user-attachments/assets/4a06be70-2cf8-4245-8d5b-322bd651a8c4

<p align="center">
  <b><a href="https://assist-voice-7560957086.europe-west1.run.app">▶ Try it live</a></b> (fake data, nothing to install)
</p>

---

## What it is

Chatbots tell you what to do, and then you do it yourself. Autonomous agents do it for you, but you can't see what they're about to change. **Assist Voice sits in between.** You talk to it, it prepares the work, shows you exactly what it will do, and waits for your OK. Anything it changes can be undone.

## What you can ask

| Say | What happens |
|---|---|
| "Start my day" | A short brief: today's events, mail that needs you, weather, your saved to-dos |
| "Add lunch with Anna on Friday at noon" | It shows the event and adds it to your calendar after you approve |
| "What needs a reply from me?" → "Tell Anna Thursday works" | It finds the emails and drafts the reply. It never sends; the draft waits in Gmail |
| *(photo of a letter)* "What does this letter want?" | Sender, what they want, deadline, in English even if the letter is German, and it offers a calendar reminder |
| "Why did CI fail?" / "Where was I?" | Reads your GitHub repo and CI log (read-only) and your recent commits |
| "Save my tabs" | Sorts your open Chrome tabs into read-later and to-do, saves them and closes them |
| "What did you do for me this week?" | A receipt of every change it made, and what you undid |
| "Undo that" | Reverts the last change |

It also remembers preferences ("sign my emails as Rohan"), reads replies aloud, and can even write itself a small new tool, tested in a sandbox before you approve it.

## Safe by design

- **Nothing changes without your OK.** Only read-only tools run on their own; everything else waits on an approval card.
- **Everything can be undone.** Each approved change is saved together with its reverse.
- **Email is draft-only, GitHub is read-only.** There is no send tool and no write access.
- **It can't be tricked by what it reads.** Emails, tabs and photos are treated as information, not orders. 10 trick attempts are part of the tests.

## Tested

41 test commands, including the 10 tricks, run 3 times each against fake data: **41/41 passed every time.** [How it's measured](docs/evals.md)

## Run it yourself

The quickest way is **demo mode** on fake data. You need Python 3.12 with [uv](https://docs.astral.sh/uv/), Node 22, and a free [Gemini API key](https://aistudio.google.com/apikey).

```bash
git clone https://github.com/rohanajay247/assist-voice.git
cd assist-voice
uv sync
cd web && npm install && cd ..
cp .env.example .env    # then set GEMINI_API_KEY in .env (Windows: Copy-Item .env.example .env)
```

Start the API (terminal 1). `ASSIST_NOW` fixes "today" at Wed 4 Nov 2026, the week the demo data is built around:

```bash
DEMO_MODE=true ASSIST_NOW=2026-11-04T09:00 uv run uvicorn backend.assist.api:app
```

On Windows PowerShell: `$env:DEMO_MODE="true"; $env:ASSIST_NOW="2026-11-04T09:00"` and then `uv run uvicorn backend.assist.api:app`.

Start the UI (terminal 2), then open http://localhost:5173:

```bash
cd web
npm run dev
```

The mic needs a free `GROQ_API_KEY` in `.env`; without it, type instead. To use your own calendar, Gmail and GitHub, see [setup](docs/setup.md).

## Documentation

| | |
|---|---|
| [Use it with your own accounts](docs/setup.md) | Settings, GitHub token, Google Calendar and Gmail sign-in |
| [Use it every day (Windows)](docs/windows.md) | One-click shortcuts, tray icon, pinning |
| [Phone access](docs/phone.md) | A private HTTPS link through Cloudflare Tunnel |
| [Save my tabs](docs/extension.md) | The Chrome extension |
| [Tool-building](docs/tool-building.md) | Letting it write new tools, tested in a Docker sandbox |
| [Public demo](docs/public-demo.md) | How the live demo is hosted: sandboxes, limits, costs |
| [How it works](docs/architecture.md) | Routing, approvals, undo, routines |
| [Evals](docs/evals.md) | How it's tested and what the tests found |
| [Known limitations](docs/limitations.md) | What doesn't work yet |

Built with Python, FastAPI, LangGraph, MCP servers, Gemini Flash-Lite (via LiteLLM), Groq Whisper and a React PWA. MIT licensed.
