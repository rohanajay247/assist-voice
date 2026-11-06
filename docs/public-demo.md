# Public demo (hosting)

[← Back to the README](../README.md)

`PUBLIC_DEMO=true` is the mode for the hosted demo, open to strangers. It implies `DEMO_MODE` and changes this:

- **A sandbox per visitor.** The first request sets a random session cookie (httpOnly, SameSite=Lax, Secure on https). Each session gets its own copy of the seed data: calendar, mail, drafts, notes, open and saved tabs, memories and the undo log. Conversation threads are stored under the session on the server, so nobody can read, resume or approve another visitor's thread.
- **Sandboxes expire** after 60 minutes without a message: their data and threads are deleted. At most 200 exist at once; when full, the oldest idle one goes.
- **Off:** tool-building, the browser extension socket (`/ext/ws`, tabs are fake), the real Google/GitHub/notes/standup servers, and `/demo/reset` and `/demo/state`. Weather stays live. No access token is needed.
- **Limits**, answered with a friendly reply instead of an error. The Gemini spending cap stays the hard stop.

| Variable | Default | Limit |
|---|---|---|
| `PUBLIC_DEMO_SESSION_MESSAGES` | 25 | Messages per visitor (typed or spoken) |
| `PUBLIC_DEMO_SESSION_PHOTOS` | 5 | Photos per visitor |
| `PUBLIC_DEMO_IP_MESSAGES` | 60 | Messages per IP per day (UTC) |
| `PUBLIC_DEMO_DAILY_MESSAGES` | 1000 | Messages per day, everyone together |
| `PUBLIC_DEMO_MAX_VOICE_SECONDS` | 30 | Length of one voice message |
| `PUBLIC_DEMO_MAX_PHOTO_MB` | 5 | Size of one photo |
| `PUBLIC_DEMO_MAX_CHARS` | 1000 | Length of one typed message |
| `PUBLIC_DEMO_SESSION_MINUTES` | 60 | Idle time before a sandbox is deleted |
| `PUBLIC_DEMO_MAX_SESSIONS` | 200 | Sandboxes at once |
| `PUBLIC_DEMO_DATA_DIR` | system temp | Where the sandbox files live (wiped at start) |

The UI shows a banner ("Live demo with fake data. Your changes reset after an hour.") and example prompts.

Sessions and counters live in memory, so run **one** worker. Behind a reverse proxy, start uvicorn with `--proxy-headers --forwarded-allow-ips="*"` (or the proxy's address) so the per-IP limit sees the visitor's IP. Leave `ASSIST_NOW` empty to use today's date, or set it to `2026-11-04T09:00` so the seeded calendar lines up with "today".

Try it locally (build the UI first: `cd web && npm run build`):

```powershell
$env:PUBLIC_DEMO="true"; uv run uvicorn backend.assist.api:app --port 8001
```

Open http://localhost:8001; a private window is a second visitor. Tests: `uv run python -m pytest tests/test_public_demo.py`.
