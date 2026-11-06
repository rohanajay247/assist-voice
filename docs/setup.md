# Set it up for your own use

[← Back to the README](../README.md)

This guide takes you from nothing to Assist Voice running on your own computer, with your own calendar, email and tabs. Follow it from the top. Parts 1–3 are the basics (about 15 minutes). Part 4 adds the other features, one at a time: add only what you want.

**On this page**

1. [What you need](#1-what-you-need)
2. [Install it (Windows, one step)](#2-install-it-windows)
3. [Use it every day: turn on, turn off, restart, update](#3-use-it-every-day)
4. [Turn on every feature](#4-turn-on-every-feature)
5. [If something doesn't work](#5-if-something-doesnt-work)
6. [Mac and Linux](#6-mac-and-linux)
7. [All settings](#7-all-settings-env) · [Demo mode](#demo-mode-fake-data) · [For developers](#for-developers)

## 1. What you need

- **A computer** with Windows 10 or 11, and Chrome or Edge. (Mac and Linux work too: see [part 6](#6-mac-and-linux).)
- **A Gemini API key** (required, free). Open [aistudio.google.com/apikey](https://aistudio.google.com/apikey), sign in with a Google account and click **Create API key**. Create it in a project **without** a billing account: it then stays on the free tier and can never charge you.
- **A Groq key** (optional, free) to talk instead of type. Open [console.groq.com/keys](https://console.groq.com/keys), sign in and click **Create API Key**.

Copy both keys into a note for a moment; setup asks for them.

Assist Voice runs on your own computer. Your data goes only to your machine and to the services you connect.

## 2. Install it (Windows)

**Step 1. Download it.** On the [GitHub page](https://github.com/rohanajay247/assist-voice), click the green **Code** button > **Download ZIP**. Unzip it to a place where it can stay, for example `Documents\assist-voice`.
(If you use Git: `git clone https://github.com/rohanajay247/assist-voice.git`.)

**Step 2. Run setup.** Open the folder, then the `scripts` folder. Right-click **setup.ps1** > **Run with PowerShell**. If Windows asks whether to run it, choose **Open** or **Run once**.

Setup does the rest and tells you what it's doing:

| Setup step | What happens |
|---|---|
| 1. Tools | Installs uv (which brings Python) and Node.js if they're missing. Windows may ask for permission |
| 2. Packages | Downloads what Assist Voice needs. A few minutes the first time |
| 3. Your settings | Asks for your Gemini key, your Groq key (press Enter to skip) and your city (for the weather). Your timezone comes from your computer |
| 4. Build | Builds the app |
| 5. Shortcuts | Puts **Assist Voice** and **Assist Voice (Demo)** on your desktop and in the Start menu |

**If setup stops** with a red message, do what it says and run it again: it continues where it stopped. If it says a tool "can't see it yet", close the window and run setup again.

You can also run it from PowerShell inside the folder: `powershell -ExecutionPolicy Bypass -File scripts/setup.ps1`

**Step 3. Turn it on.** Click **Assist Voice** on the desktop. Say or type "What's the weather?" to check that it works.

## 3. Use it every day

| To... | Do this |
|---|---|
| **Turn it on** | Click **Assist Voice** on the desktop or in the Start menu. It starts in the background and opens in its own window (the first start takes about 10 seconds) |
| **Keep it in the taskbar** | Press Start, type "Assist Voice", right-click it > **Pin to taskbar**. Pin this shortcut, not the open window |
| **Talk to it** | Click the mic, speak, click it again. Or type. Replies are read aloud; pick the voice in the header |
| **Approve a change** | Anything that changes your data (an event, a draft, a note, closing tabs) shows a card first. Click **Approve** or **Reject** |
| **Undo** | Say "Undo that" |
| **Close the window** | Close it as normal. Assist Voice keeps running in the background, so your phone and the tabs extension keep working. Its icon sits next to the clock |
| **Open it again** | Click the shortcut again, or double-click the icon next to the clock |
| **Turn it off** | Right-click the icon next to the clock > **Stop Assist Voice**. The icon disappears once it has stopped. Restarting the computer also turns it off |
| **Restart it** (e.g. after changing settings) | Turn it off as above, then click the shortcut |
| **Change your keys or city** | Run setup again, or open `.env` in the folder with Notepad, change the line, save, and restart |
| **Try it on fake data** | Click **Assist Voice (Demo)**. Clicking the normal shortcut switches back |
| **Update to a new version** | Download the ZIP again and unzip it over the old folder (your `.env` and `secrets` folder stay), or run `git pull`. Then run setup again |
| **Remove it** | In the folder, run `powershell -ExecutionPolicy Bypass -File scripts/install-shortcuts.ps1 -Remove`, then delete the folder |

It doesn't start by itself when the computer starts: click the shortcut when you want it.

**More about the shortcuts**

- Clicking **Assist Voice** while it already runs only brings the window to the front. Clicking the other mode (Demo or normal) restarts it in that mode.
- It all runs as one program on http://localhost:8000. You can also open that address in any browser on this computer.
- **Sharper window (optional):** open http://localhost:8000 in Chrome, choose ⋮ > **Cast, save, and share** > **Install Assist Voice**, then run `scripts/install-shortcuts.ps1` again. The shortcut then opens the installed app.
- Logs: `logs/assist-real.log` (normal) and `logs/assist-demo.log` (demo).
- Without the shortcuts, from PowerShell in the folder: `scripts/assist.ps1 -Mode real` (or `-Mode demo`) to start, `scripts/assist.ps1 -Stop` to stop.

## 4. Turn on every feature

**Works straight after setup:** talking and typing, notes, memory ("remember I sign my emails as ..."), weather, photos of letters, undo, and "What did you do for me this week?".

**Needs one extra step each:**

| Feature | What you need | Time |
|---|---|---|
| [Calendar and email](#calendar-and-email-google) | Connect your Google account | 15 min, once |
| [Save my tabs](#save-my-tabs-chrome-extension) | Add the Chrome extension | 2 min |
| [Use it on your phone](#use-it-on-your-phone) | A Cloudflare tunnel | 5 min |
| [Let it write new tools](#let-it-write-new-tools-docker) | Docker Desktop | 10 min |
| [GitHub and your code](#github-and-your-code-for-developers) | A GitHub token and your code folders | 5 min |

### Calendar and email (Google)

Assist Voice signs in through your own small Google Cloud project, so your mail and calendar go only to you. It's free.

**A. Create the project and switch on the APIs**

1. Open [console.cloud.google.com](https://console.cloud.google.com/) and sign in with the Google account whose calendar and mail you want to use.
2. Top left, click the project picker > **New project**. Name it "Assist Voice" > **Create**. Make sure it's selected at the top.
3. Open the [Calendar API](https://console.cloud.google.com/apis/library/calendar-json.googleapis.com) page > **Enable**. Then the [Gmail API](https://console.cloud.google.com/apis/library/gmail.googleapis.com) page > **Enable**.

**B. Set up the sign-in screen**

4. Open [Google Auth Platform](https://console.cloud.google.com/auth/overview) > **Get started**.
5. Fill it in:
   - App name: "Assist Voice"; support email: yours > **Next**
   - Audience: **External** > **Next**
   - Contact email: yours > **Next**
   - Tick the agreement > **Create**
6. In the left menu, click **Audience**. Under **Test users**, click **Add users**, enter your own Gmail address > **Save**. Leave the status on **Testing**.

**C. Create the key file**

7. In the left menu, click **Clients** > **Create client**. Application type: **Desktop app**; name: "Assist Voice" > **Create**.
8. Click **Download JSON** (or the download icon next to the client).
9. In the Assist Voice folder, create a folder called `secrets` (if it isn't there yet). Save the downloaded file in it, named exactly **`gcp-oauth.keys.json`**.

**D. Sign in**

10. Run setup again: it offers to sign you in. (Or in the folder: `uv run python scripts/google_auth.py`.)
11. A browser opens. Choose your account. Google shows **"Google hasn't verified this app"**: that's expected, because it's your own private project. Click **Continue**, allow calendar and Gmail access, and click **Continue** again.
12. Restart Assist Voice, then ask "What's on today?"

**Once a week:** because the project stays in Testing (fine for personal use), Google ends the sign-in after 7 days. When Assist Voice says "Run scripts/google_auth.py", do step 10–11 again.

**What it can do with your account:** read, add and delete calendar events (not calendar settings or sharing); read and search mail; create and delete drafts. It cannot send email: drafts wait in Gmail for you to send.

To use a calendar other than your main one, set `GOOGLE_CALENDAR_ID` in `.env` (Google Calendar > Settings > the calendar > **Integrate calendar** > Calendar ID).

### Save my tabs (Chrome extension)

1. In Chrome, open `chrome://extensions` and turn on **Developer mode** (top right).
2. Click **Load unpacked** and choose the `extension` folder inside the Assist Voice folder.
3. Optional: pin it from the puzzle icon. If you set an `ASSIST_ACCESS_TOKEN` (for the phone), click the extension and paste it there.

Now say "Save my tabs": it sorts your open tabs into read-later and to-do, and closes them after you approve. Pinned tabs and Assist Voice itself are never closed, and you can ask for saved tabs later ("what did I save for later?") to reopen them. The extension talks only to Assist Voice on this computer, so Assist Voice has to be running.

### Use it on your phone

Your computer stays the server; your phone opens it through a private link. Assist Voice must be running on the computer.

1. Install Cloudflare's tunnel tool (once): `winget install --id Cloudflare.cloudflared`. Close and reopen PowerShell.
2. The link can be reached from the internet, so set a password first. Create one with
   `uv run python -c "import secrets; print(secrets.token_urlsafe(24))"`,
   put it in `.env` as `ASSIST_ACCESS_TOKEN=...`, and restart Assist Voice.
3. Start the tunnel in the folder: `powershell -ExecutionPolicy Bypass -File scripts/tunnel.ps1`. It prints a link like `https://something.trycloudflare.com`.
4. Open that link on your phone, enter the password, then choose **Add to Home Screen**.

The link works while that PowerShell window stays open, and it changes each time you start the tunnel: after a restart, open the new link on your phone and add it to the home screen again. Your phone needs the link because the mic and camera only work over HTTPS.

### Let it write new tools (Docker)

When you ask for something it can't do yet, Assist Voice can write itself a small new tool, test it in a locked sandbox, and install it only after you approve.

1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and start it.
2. Once, in the folder: `powershell -ExecutionPolicy Bypass -File scripts/build_sandbox.ps1`

How it stays safe: the new code is checked, then tested in a Docker sandbox with no network, no secrets and read-only files. You see the code and the test results on the approval card before anything is installed, and built tools always run inside the sandbox.

Docker has to be running when you use this. Don't want it? Set `TOOLBUILDER_ENABLED=false` in `.env`.

### GitHub and your code (for developers)

- **GitHub** ("Why did CI fail?"): create a [fine-grained token](https://github.com/settings/personal-access-tokens/new). Pick your repos, and set Contents, Issues, Pull requests and Actions to **Read-only**. Put it in `.env` as `GITHUB_PAT=...`. Assist Voice only reads, and refuses to start if GitHub offers it a tool that could write.
- **"What did I do yesterday?" / "Where was I?"**: set `STANDUP_REPOS` to your local code folders (separated by commas) and `GIT_AUTHOR_EMAIL` to your commit email.

Restart Assist Voice after changing `.env`.

## 5. If something doesn't work

| Problem | Fix |
|---|---|
| The window can't reach Assist Voice | It's still starting (give it 10 seconds) or it stopped. Click the shortcut again. Still not? Open `logs/assist-real.log` in the folder and look at the last lines |
| "Port 8000 is already used" | Assist Voice is already running in the other mode, or another program uses that port. Stop it from the tray icon and try again |
| The mic does nothing | No Groq key: run setup again (or add `GROQ_API_KEY` to `.env`) and restart. Also allow the microphone when the browser asks |
| Calendar or email says "Run scripts/google_auth.py" | The weekly Google sign-in ended. Run `uv run python scripts/google_auth.py`, then restart |
| "The browser extension isn't connected" | Install the extension (part 4), or reload it in `chrome://extensions` while Assist Voice is running |
| Times or "today" are wrong | Check your computer's timezone, or set `ASSIST_TIMEZONE` (e.g. `Asia/Kolkata`) in `.env` and restart |
| "The AI service isn't available right now" | The free Gemini tier reached its limit, or Google has an outage. Try again later; the daily limit resets the next day |

## 6. Mac and Linux

The setup script and shortcuts are for Windows; everything else works the same.

1. **Install the tools** (on Mac with [Homebrew](https://brew.sh/)): `brew install git uv node`
2. **Download and install:**
   ```bash
   git clone https://github.com/rohanajay247/assist-voice.git
   cd assist-voice
   uv sync
   cd web && npm install && npm run build && cd ..
   cp .env.example .env
   ```
3. **Add your settings:** open `.env` in a text editor and fill in `GEMINI_API_KEY`, `GROQ_API_KEY` (optional) and `HOME_CITY`.
4. **Turn it on:** in the folder, run `uv run uvicorn backend.assist.api:app`, then open http://localhost:8000 in Chrome.
   **Turn it off:** press Ctrl+C in that terminal.
5. **Update:** `git pull`, `uv sync`, then `cd web && npm install && npm run build`.

The features in [part 4](#4-turn-on-every-feature) work the same, except: for the phone, run `cloudflared tunnel --url http://127.0.0.1:8000` (install it from [Cloudflare's downloads](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)); for tool-building, run `docker build -t assist-sandbox sandbox`.

## 7. All settings (`.env`)

Open `.env` in the Assist Voice folder with a text editor. One setting per line, as `NAME=value`, without quotes. Restart Assist Voice after a change. Setup fills in the first three for you.

| Setting | Needed for | Where to get it |
|---|---|---|
| `GEMINI_API_KEY` | Everything (required) | [Google AI Studio](https://aistudio.google.com/apikey), free tier |
| `GROQ_API_KEY` | Talking (speech to text) | [console.groq.com/keys](https://console.groq.com/keys), free tier |
| `HOME_CITY` | Weather without a city, "start my day" | Your city, e.g. `Kochi`. Empty: it asks. Demo mode: Albstadt |
| `ASSIST_TIMEZONE` | Dates and calendar times | e.g. `Asia/Kolkata`. Empty: your computer's timezone. Demo mode: `Europe/Berlin` |
| `GITHUB_PAT` | GitHub questions | Fine-grained token, read-only (see part 4) |
| `STANDUP_REPOS` | "What did I do yesterday?", "Where was I?" | Paths to your local code folders, separated by commas |
| `GIT_AUTHOR_EMAIL` | Same | Your commit email, to count only your commits |
| `ASSIST_ACCESS_TOKEN` | Phone access | A long random password (see part 4). Empty: no password, for this computer only |
| `GOOGLE_CALENDAR_ID` | Optional | Which calendar to use. Default: your main one |
| `TOOLBUILDER_ENABLED` | Optional | `false` turns off tool-building. Default: on |
| `VISION_MODEL`, `TOOLBUILDER_MODEL` | Optional | A LiteLLM model name for photos / for writing tools. Default: Gemini Flash-Lite |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL` | Optional tracing | [Langfuse](https://cloud.langfuse.com) project settings |
| `DEMO_MODE` | Demo only | `true` for fake data. The Demo shortcut sets it for you |
| `ASSIST_NOW` | Demo and evals | A fixed local time, e.g. `2026-11-04T09:00` |
| `PUBLIC_DEMO` | Hosted demo only | `true` for the public demo (see [Public demo](public-demo.md)) |

### Demo mode (fake data)

To look around without connecting anything: on Windows, click **Assist Voice (Demo)**. Elsewhere, start it with `DEMO_MODE=true ASSIST_NOW=2026-11-04T09:00` in front of the start command (PowerShell: run `$env:DEMO_MODE="true"; $env:ASSIST_NOW="2026-11-04T09:00"` first). `ASSIST_NOW` fixes "today" at Wed 4 Nov 2026, the week the demo data is built around. Or skip all of this and use the [live demo](https://assist-voice-7560957086.europe-west1.run.app).

### For developers

Run the API and the web dev server separately, so UI changes reload instantly:

```bash
uv run uvicorn backend.assist.api:app --reload    # terminal 1
cd web && npm run dev                              # terminal 2, then open http://localhost:5173
```

Tests: `uv run python -m pytest tests` and `cd web && npm test`. Evals: [evals/README.md](../evals/README.md).
