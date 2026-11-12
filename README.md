# Assist Voice

[![CI](https://github.com/rohanajay247/assist-voice/actions/workflows/ci.yml/badge.svg)](https://github.com/rohanajay247/assist-voice/actions/workflows/ci.yml)

**Say what you need, and it handles it across your calendar, email, notes, GitHub and browser tabs, but only after you say yes.**

<div align="center">
  <video src="https://github.com/user-attachments/assets/4a06be70-2cf8-4245-8d5b-322bd651a8c4" width="100%" controls></video>
</div>

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
| "Why did CI fail?" / "Where was I?" | Reads your GitHub repo and CI log (read-only) and your recent commits. Needs a GitHub token |
| "Save my tabs" | Sorts your open Chrome tabs into read-later and to-do, saves them and closes them. Needs the [Chrome extension](docs/setup.md#save-my-tabs-chrome-extension) |
| "What did you do for me this week?" | A receipt of every change it made, and what you undid |
| "Undo that" | Reverts the last change |

Calendar and email work once you [connect your Google account](docs/setup.md#calendar-and-email-google).

It also remembers preferences ("sign my emails as Rohan"), reads replies aloud, and can even write itself a small new tool, tested in a sandbox before you approve it.

## Safe by design

- **Nothing changes without your OK.** Only read-only tools run on their own; everything else waits on an approval card.
- **Everything can be undone.** Each approved change is saved together with its reverse.
- **Email is draft-only, GitHub is read-only.** There is no send tool and no write access.
- **It can't be tricked by what it reads.** Emails, tabs and photos are treated as information, not orders. 10 trick attempts are part of the tests.

## Tested

41 test commands, including the 10 tricks, run 3 times each against fake data: **41/41 passed every time.** [How it's measured](docs/evals.md)

## Use it yourself

Assist Voice runs on your own computer, with your own free keys. Your data goes only to your machine and the services you connect.

**On Windows it's one step:** download the ZIP (green **Code** button > **Download ZIP**), unzip it, and right-click `scripts/setup.ps1` > **Run with PowerShell**. Setup installs what's needed, asks for a free [Gemini key](https://aistudio.google.com/apikey) and your city, and puts an **Assist Voice** shortcut on your desktop. Click it to start; stop it from the icon next to the clock.

Then add the features you want: calendar and email (connect Google, 15 minutes once), the tabs extension, your phone, tool-building. Mac and Linux take a few commands.

**Step by step, with everything: [Set it up for your own use](docs/setup.md)**

## Documentation

| | |
|---|---|
| [Set it up for your own use](docs/setup.md) | Install, daily use (on, off, update), and every feature: Google, tabs extension, phone, tool-building, GitHub |
| [Public demo](docs/public-demo.md) | How the live demo is hosted: sandboxes, limits, costs |
| [How it works](docs/architecture.md) | Routing, approvals, undo, routines |
| [Evals](docs/evals.md) | How it's tested and what the tests found |
| [Known limitations](docs/limitations.md) | What doesn't work yet |

Built with Python, FastAPI, LangGraph, MCP servers, Gemini Flash-Lite (via LiteLLM), Groq Whisper and a React PWA. MIT licensed.
