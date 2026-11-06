# Shortcuts for scripts/assist.ps1: "Assist Voice" and "Assist Voice (Demo)",
# on the desktop and in the Start menu (search "Assist Voice", right-click > Pin to taskbar).
# Stopping is in the tray icon that shows while it runs (scripts/tray.ps1).
#
#   powershell -ExecutionPolicy Bypass -File scripts/install-shortcuts.ps1           create them
#   powershell -ExecutionPolicy Bypass -File scripts/install-shortcuts.ps1 -Remove   remove them
#
# They run assist.ps1 through "conhost --headless", so no console window shows.
# The icon is the app's own (web/public/pwa-512x512.png), converted to .ico.
#
# Pin "Assist Voice" from the Start menu (it starts the API first). Each shortcut
# has its own taskbar ID. Don't give it the installed Chrome app's ID: Windows then
# shows a blank icon for the app window, and pinning the window pins Chrome's entry.
#
# If Assist Voice is installed as a Chrome app (Chrome menu > Install), the
# launcher opens that installed app (sharp icon, own window); run this again after
# installing so it knows how to start it.

param([switch]$Remove)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
# Desktop, and the Start menu's Programs folder (searchable, pinnable)
$Folders = @([Environment]::GetFolderPath("Desktop"), [Environment]::GetFolderPath("Programs"))
$IconDir = Join-Path $env:LOCALAPPDATA "Assist"
# The icon lives in the project (gitignored), not in %LOCALAPPDATA%: Start menu search
# and the taskbar run sandboxed and can't read files there, so they'd show a blank page.
$Icon = Join-Path $PSScriptRoot "assist.ico"
$Script = Join-Path $PSScriptRoot "assist.ps1"

$Shortcuts = [ordered]@{
    "Assist Voice"        = @{ Args = "-Mode real"; Note = "Assist Voice on your real accounts"; AppId = "AssistVoice" }
    "Assist Voice (Demo)" = @{ Args = "-Mode demo"; Note = "Assist Voice on fake demo data"; AppId = "AssistVoice.DemoData" }
}
# Earlier names, removed when the shortcuts are (re)made (stopping is in the tray now)
$OldNames = "Assist", "Assist (Demo)", "Stop Assist", "Stop Assist Voice"

if ($Remove) {
    foreach ($folder in $Folders) {
        foreach ($name in $Shortcuts.Keys) {
            $path = Join-Path $folder "$name.lnk"
            if (Test-Path $path) { Remove-Item $path -Force; Write-Host "Removed $path" }
        }
        foreach ($name in $OldNames) {
            $path = Join-Path $folder "$name.lnk"
            if (Test-Path $path) { Remove-Item $path -Force }
        }
    }
    if (Test-Path $IconDir) { Remove-Item $IconDir -Recurse -Force }
    if (Test-Path $Icon) { Remove-Item $Icon -Force }
    exit 0
}

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "No Python environment found. Run 'uv sync' first." }
New-Item -ItemType Directory -Force $IconDir | Out-Null
& $Python (Join-Path $PSScriptRoot "make_icon.py") $Icon
if ($LASTEXITCODE -ne 0) { throw "Couldn't convert the icon" }

$shell = New-Object -ComObject WScript.Shell
Add-Type -Path (Join-Path $PSScriptRoot "AssistShell.cs")

# Assist Voice installed as a Chrome/Edge app: the browser made a Start menu shortcut
# for it ("Chrome Apps\Assist Voice.lnk"). Save how to start it: the launcher opens
# that instead of a plain window.
$AppFile = Join-Path $IconDir "app.json"
$installedApp = $false
$appLink = Get-ChildItem ([Environment]::GetFolderPath("Programs")) -Filter "Assist*.lnk" -Recurse -ErrorAction SilentlyContinue |
    Where-Object { $shell.CreateShortcut($_.FullName).Arguments -match "--app-id=" } | Select-Object -First 1
if ($appLink) {
    $l = $shell.CreateShortcut($appLink.FullName)
    @{ Exe = $l.TargetPath; Arguments = $l.Arguments.Trim() } |
        ConvertTo-Json | Set-Content $AppFile -Encoding utf8
    $installedApp = $true
} elseif (Test-Path $AppFile) {
    # Chrome's own shortcuts may be deleted (they'd open the app without the API);
    # keep the saved app while it's still installed in that Chrome profile
    $saved = Get-Content $AppFile -Raw | ConvertFrom-Json
    $profileDir = if ($saved.Arguments -match '--profile-directory="?([^"]+?)"?(\s|$)') { $Matches[1] } else { "Default" }
    $appId = if ($saved.Arguments -match '--app-id=(\w+)') { $Matches[1] } else { "" }
    $userData = Split-Path (Split-Path $saved.Exe) -Parent | Split-Path -Leaf   # "Chrome" or "Edge"
    $vendor = if ($userData -eq "Edge") { "Microsoft\Edge" } else { "Google\Chrome" }
    $installed = $appId -and (Test-Path "$env:LOCALAPPDATA\$vendor\User Data\$profileDir\Web Applications\Manifest Resources\$appId")
    if ($installed) { $installedApp = $true }
    else { Remove-Item $AppFile }   # uninstalled since: back to the plain window
}

$conhost = Join-Path $env:SystemRoot "System32\conhost.exe"
$powershell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
foreach ($folder in $Folders) {
    foreach ($name in $OldNames) {
        $path = Join-Path $folder "$name.lnk"
        if (Test-Path $path) { Remove-Item $path -Force; Write-Host "Removed old $path" }
    }
    foreach ($name in $Shortcuts.Keys) {
        $path = Join-Path $folder "$name.lnk"
        $link = $shell.CreateShortcut($path)
        $link.TargetPath = $conhost
        $link.Arguments = "--headless `"$powershell`" -NoProfile -ExecutionPolicy Bypass -File `"$Script`" $($Shortcuts[$name].Args)"
        $link.WorkingDirectory = $Root
        $link.IconLocation = "$Icon,0"
        $link.Description = $Shortcuts[$name].Note
        $link.WindowStyle = 7  # minimized, in case conhost ever shows anything
        $link.Save()
        [AssistShell]::SetShortcutAppId($path, $Shortcuts[$name].AppId)
        Write-Host "Created $path"
    }
}

Write-Host ""
Write-Host "To pin: press Start, type 'Assist Voice', right-click it > Pin to taskbar."
if ($installedApp) {
    Write-Host "The launcher opens the installed Assist Voice app."
} else {
    Write-Host "Optional: install it as a Chrome app (Chrome menu > Install), then run this again."
}

# Windows caches shortcut icons: refresh so the new one shows right away
& (Join-Path $env:SystemRoot "System32\ie4uinit.exe") -show
