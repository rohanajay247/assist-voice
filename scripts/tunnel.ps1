# Public HTTPS URL for the web app, so Assist Voice works on your phone.
#
# Start Assist Voice first (the shortcut, on port 8000; or the dev setup with
# `npm run dev` on 5173), then:
#   powershell -ExecutionPolicy Bypass -File scripts/tunnel.ps1
#
# Uses a Cloudflare quick tunnel: no account needed, a new random
# *.trycloudflare.com URL every run. Anyone with the URL can load the page,
# so set ASSIST_ACCESS_TOKEN in .env. Stop with Ctrl+C.

$ErrorActionPreference = "Stop"
# The app started from the shortcut (8000) if it runs, else the dev server (5173)
function Test-Listening($port) {
    $null -ne (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}
if (Test-Listening 8000) { $target = "http://127.0.0.1:8000" }  # the launcher listens on 127.0.0.1 only
elseif (Test-Listening 5173) { $target = "http://localhost:5173" }
else {
    Write-Host "Assist Voice isn't running. Start it first (click the Assist Voice shortcut), then run this again." -ForegroundColor Yellow
    exit 1
}

if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
    Write-Host "cloudflared is not installed. Install it with:" -ForegroundColor Yellow
    Write-Host "  winget install --id Cloudflare.cloudflared"
    Write-Host "then open a new terminal and run this script again."
    exit 1
}

Write-Host "Starting tunnel to $target ..."

# cloudflared logs to stderr; merge it in and pick out the URL and any errors.
# Native stderr lines arrive as ErrorRecords in PowerShell 5.1, so stop
# treating them as terminating errors.
$ErrorActionPreference = "Continue"
& cloudflared tunnel --no-autoupdate --url $target 2>&1 | ForEach-Object {
    $line = "$_"
    if ($line -match "https://[a-z0-9-]+\.trycloudflare\.com") {
        Write-Host ""
        Write-Host "  Assist Voice is live at: $($Matches[0])" -ForegroundColor Green
        Write-Host "  Open it on your phone, then use 'Add to Home Screen' to install it."
        Write-Host ""
    }
    elseif ($line -match " ERR ") {
        Write-Host $line -ForegroundColor Red
    }
}
