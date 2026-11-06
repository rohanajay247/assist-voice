# One-click Assist for daily use on Windows.
#
#   assist.ps1 [-Mode real|demo]   start the API hidden (if needed) and open the app window
#   assist.ps1 -Stop               stop the API this script started
#
# While the API runs, an icon next to the clock (scripts/tray.ps1) shows it's on,
# with Open / Stop. Closing the window leaves the API running, e.g. for the phone.
#
# The API serves the built web app (web/dist), so everything runs as one
# process on http://localhost:8000. Logs: logs/assist-<mode>.log.
# The desktop shortcuts (scripts/install-shortcuts.ps1) call this script.
#
# -Port picks another port (default 8000), e.g. to try it next to a dev server.

param(
    [ValidateSet("real", "demo")]
    [string]$Mode = "real",
    [switch]$Stop,
    [int]$Port = 8000,
    [switch]$NoWindow  # start the API but don't open the app window (for testing)
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Logs = Join-Path $Root "logs"
$PidFile = Join-Path $Logs "assist-$Port.pid"   # "<pid> <mode>"
$Url = "http://localhost:$Port"
$Python = Join-Path $Root ".venv\Scripts\python.exe"
New-Item -ItemType Directory -Force $Logs | Out-Null

# The shortcuts run without a console, so problems are shown in a message box
function Fail([string]$message) {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show($message, "Assist Voice", "OK", "Error") | Out-Null
    exit 1
}

# The API this script started, or $null: { Pid, Mode }
function Get-Started {
    if (-not (Test-Path $PidFile)) { return $null }
    $parts = (Get-Content $PidFile -Raw).Trim() -split "\s+"
    $proc = Get-Process -Id ([int]$parts[0]) -ErrorAction SilentlyContinue
    if ($null -eq $proc) {
        Remove-Item $PidFile -Force   # stale: the API ended on its own
        return $null
    }
    return @{ Pid = [int]$parts[0]; Mode = $parts[1] }
}

function Test-PortUsed {
    $null -ne (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Stop-Started($started) {
    # The PID is the hidden cmd.exe that runs uvicorn; /T takes its python child too
    & taskkill.exe /PID $started.Pid /T /F 2>&1 | Out-Null
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    foreach ($i in 1..40) {
        if (-not (Test-PortUsed)) { return }
        Start-Sleep -Milliseconds 250
    }
}

# GET /auth/check with the access token from .env, or $null if nothing answers
function Get-AuthCheck {
    $headers = @{}
    $envFile = Join-Path $Root ".env"
    if (Test-Path $envFile) {
        $line = Get-Content $envFile | Where-Object { $_ -match "^\s*ASSIST_ACCESS_TOKEN\s*=" } | Select-Object -First 1
        if ($line) {
            $token = ($line -split "=", 2)[1].Trim().Trim('"').Trim("'")
            if ($token) { $headers["X-Assist-Token"] = $token }
        }
    }
    try {
        return Invoke-RestMethod -Uri "$Url/auth/check" -Headers $headers -TimeoutSec 3
    } catch {
        if ($_.Exception.Response) { return @{ ok = $false } }  # answered, e.g. 401
        return $null
    }
}

# web/dist missing or older than the web sources: build it (npm ci first if needed)
function Update-WebBuild {
    $web = Join-Path $Root "web"
    $index = Join-Path $web "dist\index.html"
    $sources = @(Get-ChildItem (Join-Path $web "src"), (Join-Path $web "public") -Recurse -File) +
        @(Get-Item (Join-Path $web "index.html"), (Join-Path $web "vite.config.ts"), (Join-Path $web "package.json"))
    $newest = ($sources | Measure-Object LastWriteTime -Maximum).Maximum
    if ((Test-Path $index) -and (Get-Item $index).LastWriteTime -ge $newest) { return }

    $log = Join-Path $Logs "build.log"
    $steps = @()
    if (-not (Test-Path (Join-Path $web "node_modules"))) { $steps += "npm ci" }
    $steps += "npm run build"
    foreach ($step in $steps) {
        $p = Start-Process cmd.exe -ArgumentList "/c $step > `"$log`" 2>&1" -WorkingDirectory $web `
            -WindowStyle Hidden -Wait -PassThru
        if ($p.ExitCode -ne 0) { Fail "Building the web app failed ($step). See $log" }
    }
}

function Start-Api([string]$mode) {
    if (-not (Test-Path $Python)) { Fail "No Python environment found. Run 'uv sync' in $Root first." }
    Update-WebBuild
    $log = Join-Path $Logs "assist-$mode.log"
    # Explicit values win over .env (load_dotenv never overrides). A single space
    # means "unset": Windows can't pass an empty variable, and Assist strips it.
    $env:DEMO_MODE = if ($mode -eq "demo") { "true" } else { "false" }
    $env:ASSIST_NOW = " "        # demo uses today, not the evals' fixed day
    $env:PUBLIC_DEMO = "false"   # never the public sandbox mode from here
    $env:PYTHONUNBUFFERED = "1"
    $env:PYTHONUTF8 = "1"        # the log file gets UTF-8, whatever the console code page
    $cmd = "/c `"`"$Python`" -m uvicorn backend.assist.api:app --host 127.0.0.1 --port $Port > `"$log`" 2>&1`""
    $p = Start-Process cmd.exe -ArgumentList $cmd -WorkingDirectory $Root -WindowStyle Hidden -PassThru
    Set-Content -Path $PidFile -Value "$($p.Id) $mode" -Encoding ascii

    # Building the graph starts every MCP server once, which takes a while
    foreach ($i in 1..120) {
        if ($p.HasExited) { Remove-Item $PidFile -Force; Fail "Assist stopped while starting. See $log" }
        if ($null -ne (Get-AuthCheck)) { return }
        Start-Sleep -Milliseconds 500
    }
    Fail "Assist didn't answer within a minute. See $log"
}

# The tray icon (scripts/tray.ps1) for the API this script started, if it isn't there yet.
# It shows the API is on after the window closes and offers Open / Stop.
function Start-Tray([string]$mode) {
    if ($NoWindow) { return }
    $trayPidFile = Join-Path $Logs "tray-$Port.pid"
    if (Test-Path $trayPidFile) {
        $trayPid = [int](Get-Content $trayPidFile -Raw).Trim()
        if (Get-Process -Id $trayPid -ErrorAction SilentlyContinue) { return }
    }
    $conhost = Join-Path $env:SystemRoot "System32\conhost.exe"
    $powershell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    $tray = Join-Path $PSScriptRoot "tray.ps1"
    Start-Process $conhost -WindowStyle Hidden -ArgumentList (
        "--headless `"$powershell`" -NoProfile -STA -ExecutionPolicy Bypass -File `"$tray`" -Port $Port -Mode $mode")
}

# Assist installed as a Chrome/Edge app: install-shortcuts.ps1 saves how the
# browser starts it (app.json). That window has its own taskbar button and sharp
# icons, and our "Assist Voice" shortcut shares its taskbar ID.
$AppFile = Join-Path $env:LOCALAPPDATA "Assist\app.json"

Add-Type -Path (Join-Path $PSScriptRoot "AssistShell.cs")
$WindowTitle = "Assist Voice"   # the page title, which is an app window's title

function Open-Window {
    if ($NoWindow) { return }
    # Already open: bring it to the front instead of opening a second window
    $open = [AssistShell]::FindAppWindows($WindowTitle)
    if ($open.Count) { [AssistShell]::Focus($open[0]); return }
    if (Test-Path $AppFile) {
        $app = Get-Content $AppFile -Raw | ConvertFrom-Json
        if (Test-Path $app.Exe) { Start-Process $app.Exe -ArgumentList $app.Arguments; return }
    }
    # Not installed: a plain app window
    $candidates = @()
    foreach ($exe in "chrome.exe", "msedge.exe") {
        foreach ($hive in "HKCU:", "HKLM:") {
            $key = "$hive\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\$exe"
            $path = (Get-ItemProperty $key -ErrorAction SilentlyContinue).'(default)'
            if ($path) { $candidates += $path }
        }
    }
    $candidates += "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
        "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
        "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe",
        "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
        "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
    $browser = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
    if (-not $browser) { Start-Process $Url; return }   # no Chrome or Edge: default browser
    Start-Process $browser -ArgumentList "--app=$Url"
}

# ---------- main ----------

$started = Get-Started

if ($Stop) {
    if ($started) { Stop-Started $started }
    # The app window can't do anything without the API, so close it too
    foreach ($w in [AssistShell]::FindAppWindows($WindowTitle)) { [AssistShell]::Close($w) }
    exit 0
}

if ($started -and $started.Mode -eq $Mode) {
    Start-Tray $Mode     # (in case the icon was closed)
    Open-Window          # already running in this mode: just the window
    exit 0
}
if ($started) {
    Stop-Started $started   # running in the other mode: restart in this one
}
elseif (Test-PortUsed) {
    # Something this script didn't start (e.g. a dev uvicorn). Use it if it's Assist in this mode.
    $check = Get-AuthCheck
    if ($check -and $check.ok -and ([bool]$check.demo -eq ($Mode -eq "demo"))) { Open-Window; exit 0 }
    Fail "Port $Port is already used by another program (maybe Assist started by hand in the other mode). Stop it first."
}

Start-Api $Mode
Start-Tray $Mode
Open-Window
