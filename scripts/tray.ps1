# The Assist Voice icon next to the clock, while the API that assist.ps1 started runs.
#
#   tray.ps1 -Port 8000 -Mode real|demo     (started by assist.ps1, hidden)
#
# Closing the app window leaves the API running (the phone and the tabs extension
# use it too); this icon shows that it's on. Right-click: Open Assist Voice, Stop.
# Double-click: open. The icon goes away by itself when the API ends, however it
# ended (Stop here, assist.ps1 -Stop, a restart in the other mode, a crash).

param(
    [int]$Port = 8000,
    [ValidateSet("real", "demo")]
    [string]$Mode = "real"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Logs = Join-Path $Root "logs"
$PidFile = Join-Path $Logs "assist-$Port.pid"      # the API: "<pid> <mode>" (assist.ps1)
$TrayPidFile = Join-Path $Logs "tray-$Port.pid"    # this icon, so assist.ps1 starts only one
$Launcher = Join-Path $PSScriptRoot "assist.ps1"
$IconFile = Join-Path $PSScriptRoot "assist.ico"   # made by install-shortcuts.ps1

# The API this icon belongs to; without one there's nothing to show
if (-not (Test-Path $PidFile)) { exit 0 }
$apiPid = [int]((Get-Content $PidFile -Raw).Trim() -split "\s+")[0]
if (-not (Get-Process -Id $apiPid -ErrorAction SilentlyContinue)) { exit 0 }
Set-Content -Path $TrayPidFile -Value $PID -Encoding ascii

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# assist.ps1 again, without a console (the way the shortcuts run it)
function Invoke-Launcher([string]$arguments) {
    $conhost = Join-Path $env:SystemRoot "System32\conhost.exe"
    $powershell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    Start-Process $conhost -WindowStyle Hidden -ArgumentList (
        "--headless `"$powershell`" -NoProfile -ExecutionPolicy Bypass -File `"$Launcher`" -Port $Port $arguments")
}

$tray = New-Object System.Windows.Forms.NotifyIcon
$tray.Icon = if (Test-Path $IconFile) { New-Object System.Drawing.Icon $IconFile }
             else { [System.Drawing.SystemIcons]::Application }
$tray.Text = if ($Mode -eq "demo") { "Assist Voice is running (demo data)" } else { "Assist Voice is running" }

$menu = New-Object System.Windows.Forms.ContextMenuStrip
$open = $menu.Items.Add("Open Assist Voice")
$open.Font = New-Object System.Drawing.Font($open.Font, [System.Drawing.FontStyle]::Bold)
$stop = $menu.Items.Add("Stop Assist Voice")
$tray.ContextMenuStrip = $menu

$open.add_Click({ Invoke-Launcher "-Mode $Mode" })      # already running: just the window
$tray.add_DoubleClick({ Invoke-Launcher "-Mode $Mode" })
$stop.add_Click({
    $tray.Text = "Assist Voice is stopping..."
    Invoke-Launcher "-Stop"          # the timer below removes the icon once the API is gone
})

# Every 2 s: is the API still there?
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 2000
$timer.add_Tick({
    if (-not (Get-Process -Id $apiPid -ErrorAction SilentlyContinue)) {
        $timer.Stop()
        [System.Windows.Forms.Application]::Exit()
    }
})

$tray.Visible = $true
$timer.Start()
try {
    [System.Windows.Forms.Application]::Run()
} finally {
    $tray.Visible = $false
    $tray.Dispose()
    if ((Test-Path $TrayPidFile) -and ((Get-Content $TrayPidFile -Raw).Trim() -eq "$PID")) {
        Remove-Item $TrayPidFile -Force -ErrorAction SilentlyContinue
    }
}
