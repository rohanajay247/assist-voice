# Set it up for your own use

[← Back to the README](../README.md)

Assist Voice runs on your computer with your own keys. About 15 minutes for the basics; Google Calendar and Gmail take another 15.

## 1. Install the tools

You need Git, [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 for you) and Node 22 or newer, plus Chrome or Edge.

**Windows** (PowerShell):

```powershell
winget install Git.Git
winget install astral-sh.uv
winget install OpenJS.NodeJS.LTS
```

**Mac** (with [Homebrew](https://brew.sh/)):

```bash
brew install git uv node
```

Close the terminal and open a new one, so it finds the new tools.

## 2. Download Assist Voice

```bash
git clone https://github.com/rohanajay247/assist-voice.git
cd assist-voice
uv sync
cd web && npm install && cd ..
```

## 3. Add your keys

Copy the settings template (Windows: `Copy-Item .env.example .env`; Mac/Linux: `cp .env.example .env`) and open `.env` in a text editor. Two keys are enough to start:

- `GEMINI_API_KEY`: from [Google AI Studio](https://aistudio.google.com/apikey). Create it in a project **without** a billing account and it stays on the free tier, so it can never charge you.
- `GROQ_API_KEY`: from [console.groq.com/keys](https://console.groq.com/keys), free. Needed for the mic; without it you type.

Leave `DEMO_MODE` and `ASSIST_NOW` empty. All the other settings are in the [table below](#all-settings-env).

## 4. Start it

**Windows:** create the shortcuts once:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install-shortcuts.ps1
```

Then click **Assist Voice** on the desktop or in the Start menu. It opens in its own window, with an icon next to the clock to stop it. More in [Use it every day (Windows)](windows.md).

**Mac / Linux:** build the web app once (and again after updating), then start the API:

```bash
cd web && npm run build && cd ..
uv run uvicorn backend.assist.api:app
```

Open http://localhost:8000. Stop it with Ctrl+C.

It already works for weather, notes, memories and photos. Each account below is optional: tools without credentials are skipped at startup. Restart Assist Voice after adding one.

To update later: `git pull`, `uv sync`, and `cd web && npm install`.

## All settings (`.env`)

| Variable | Needed for | Where to get it |
|---|---|---|
| `GEMINI_API_KEY` | Everything (required) | [Google AI Studio](https://aistudio.google.com/apikey), free tier |
| `GROQ_API_KEY` | Voice input (Whisper) | [console.groq.com/keys](https://console.groq.com/keys), free tier |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL` | Optional tracing | [Langfuse](https://cloud.langfuse.com) project settings; EU base URL `https://cloud.langfuse.com` |
| `GITHUB_PAT` | GitHub tools | Fine-grained token, read-only (see below) |
| `STANDUP_REPOS` | "What did I do yesterday?", "Where was I?" | Comma-separated paths to local git repos |
| `GIT_AUTHOR_EMAIL` | Standup | Your commit email, to count only your commits |
| `ASSIST_ACCESS_TOKEN` | Phone access through the tunnel | Any long random string (see [Phone access](phone.md)). Empty = no check, for local use only |
| `VISION_MODEL` | Optional | A LiteLLM model name for photos. Default: Flash-Lite |
| `TOOLBUILDER_MODEL` | Optional | A LiteLLM model name for writing tools. Default: Flash-Lite |
| `TOOLBUILDER_ENABLED` | Optional | `false` hides tool-building. Default: on |
| `DEMO_MODE` | Demo only | `true` for fake data |
| `ASSIST_NOW` | Demo and evals | Fixed Berlin time, e.g. `2026-11-04T09:00` |
| `PUBLIC_DEMO` | Hosted demo only | `true` for the public demo: a sandbox per visitor, limits (see [Public demo](public-demo.md)) |
| `GOOGLE_CALENDAR_ID` | Optional | Calendar the event tools use. Default: your main calendar (`primary`). For another one: Google Calendar > Settings > the calendar > **Integrate calendar** > Calendar ID |

**GitHub token.** Create a [fine-grained personal access token](https://github.com/settings/personal-access-tokens/new). Pick the repos, then set these repository permissions to **Read-only**: Contents, Issues, Pull requests, Actions (Metadata is read-only by default). Assist Voice also sends GitHub's `X-MCP-Readonly` header and refuses to start if the server offers a tool that looks like a write.

## Google Calendar and Gmail

Assist Voice signs in with your own Google Cloud OAuth client, so your data goes only to your project.

1. Open the [Google Cloud Console](https://console.cloud.google.com/) and create a new project.
2. Under **APIs & Services > Library**, enable **Google Calendar API** and **Gmail API**.
3. Open **Google Auth Platform** (formerly "OAuth consent screen"). Choose **External**, enter an app name and your email.
4. Under **Audience**, keep the publishing status **Testing** and add your own Google account as a **test user**.
5. Under **Clients**, create a client of type **Desktop app**. Download its JSON.
6. Save that file as `secrets/gcp-oauth.keys.json`. The `secrets/` folder is gitignored.
7. Sign in once. A browser window opens, you allow access, and the script writes `secrets/google-token.json`:

```bash
uv run python scripts/google_auth.py
```

8. Restart Assist Voice. The Google tools load only when the token exists.

The server refreshes the token by itself. In Testing mode Google expires it after 7 days. When that happens, the tools reply "Run scripts/google_auth.py", and you run the script again.

**Scopes used:**

- `calendar.events`: read, create and delete events. No calendar settings or sharing.
- `gmail.readonly`: search and read mail.
- `gmail.compose`: create and delete drafts. The scope would also allow sending, but Assist Voice has no send tool. Drafts wait in Gmail for you to send.

## Try it on fake data (demo mode)

To look around without connecting anything: on Windows, click **Assist Voice (Demo)**. Elsewhere, start the API with `DEMO_MODE=true ASSIST_NOW=2026-11-04T09:00` in front of the command (PowerShell: `$env:DEMO_MODE="true"; $env:ASSIST_NOW="2026-11-04T09:00"` first). `ASSIST_NOW` fixes "today" at Wed 4 Nov 2026, the week the demo data is built around. Or skip all of this and use the [live demo](https://assist-voice-7560957086.europe-west1.run.app).

## For development

Run the API and the web dev server separately, so UI changes reload instantly:

```bash
uv run uvicorn backend.assist.api:app --reload    # terminal 1
cd web && npm run dev                              # terminal 2, then open http://localhost:5173
```
