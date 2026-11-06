# Public HTTPS URL for the web app, so Assist works on your phone.
#
# Start the backend and `npm run dev` (in web/) first, then:
#   powershell -ExecutionPolicy Bypass -File scripts/tunnel.ps1
#
# Uses a Cloudflare quick tunnel: no account needed, a new random
# *.trycloudflare.com URL every run. Anyone with the URL can load the page,
# so set ASSIST_ACCESS_TOKEN in .env. Stop with Ctrl+C.

$ErrorActionPreference = "Stop"
$target = "http://localhost:5173"

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
