# Phone access (Cloudflare Tunnel)

[← Back to the README](../README.md)

The app is an installable PWA. A Cloudflare quick tunnel gives it a public HTTPS URL, which the phone also needs for the mic and camera.

1. Install cloudflared:

```powershell
winget install --id Cloudflare.cloudflared
```

   On macOS or Linux, see [Cloudflare's downloads](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/).

2. The URL is public, so set an access token in `.env` as `ASSIST_ACCESS_TOKEN`. To generate one:

```bash
uv run python -c "import secrets; print(secrets.token_urlsafe(24))"
```

3. Start Assist Voice (click the shortcut), then the tunnel:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/tunnel.ps1
```

   It connects to the app on port 8000 (the shortcut), or to the dev server on 5173 if that's what runs. On macOS or Linux: `cloudflared tunnel --url http://127.0.0.1:8000`.

4. Open the printed `https://….trycloudflare.com` URL on your phone. Enter the token on the lock screen, then choose "Add to Home Screen".

The quick-tunnel URL changes every time you start it, and your computer has to stay on.
