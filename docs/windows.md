# Use it every day (Windows)

[← Back to the README](../README.md)

One click starts Assist Voice in its own window, without terminals. The API serves the built web app, so it all runs as one process on http://localhost:8000.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install-shortcuts.ps1
```

This puts two shortcuts on your desktop and in the Start menu (search "Assist Voice", then right-click > **Pin to taskbar**):

- **Assist Voice**: starts the API on your real accounts (hidden, no console) and opens it as an app window in Chrome (or Edge).
- **Assist Voice (Demo)**: the same on fake data, with today's date.

While it runs, an Assist Voice icon sits next to the clock. Closing the window leaves it running, so your phone and the tabs extension keep working. Right-click the icon for **Open Assist Voice** or **Stop Assist Voice**; the icon goes away once it has stopped.

Clicking Assist Voice while it already runs only opens the window; clicking the other mode restarts it in that mode. The web app is rebuilt first when `web/src` changed. Logs go to `logs/assist-real.log` / `logs/assist-demo.log`. If `ASSIST_ACCESS_TOKEN` is set, the window asks for it once.

**To pin it**, press Start, type "Assist Voice", right-click it > **Pin to taskbar**. Pin that shortcut, not the open window: the shortcut starts the API first, the window's own pin doesn't.

**Sharper window (optional):** install Assist Voice as a Chrome app: open http://localhost:8000 in Chrome and choose ⋮ > Cast, save, and share > **Install Assist Voice**, then run `install-shortcuts.ps1` again. The launcher then opens the installed app in its own window.

Code changes: the launcher rebuilds the web app when `web/src` changed, but only when it starts the API. After changing backend or web code, stop it from the tray icon, then click **Assist Voice**.

Remove the shortcuts with `scripts/install-shortcuts.ps1 -Remove`. Without shortcuts: `scripts/assist.ps1 -Mode real|demo` or `scripts/assist.ps1 -Stop`. `npm run dev` on :5173 keeps working for development.
