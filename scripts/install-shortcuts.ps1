# Shortcuts for scripts/assist.ps1: "Assist Voice", "Assist Voice (Demo)", "Stop Assist Voice",
# on the desktop and in the Start menu (search "Assist Voice", right-click > Pin to taskbar).
#
#   powershell -ExecutionPolicy Bypass -File scripts/install-shortcuts.ps1           create them
#   powershell -ExecutionPolicy Bypass -File scripts/install-shortcuts.ps1 -Remove   remove them
#
# They run assist.ps1 through "conhost --headless", so no console window shows.
# The icon is the app's own (web/public/pwa-512x512.png), converted to .ico.
#
# For a proper taskbar button, install Assist as a Chrome app once (open
# http://localhost:8000 in Chrome > Install), then run this again: the "Assist Voice"
# shortcut takes the installed app's taskbar ID, so the pinned shortcut and the
# app window share one button with the Assist icon.

param([switch]$Remove)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
# Desktop, and the Start menu's Programs folder (searchable, pinnable)
$Folders = @([Environment]::GetFolderPath("Desktop"), [Environment]::GetFolderPath("Programs"))
$IconDir = Join-Path $env:LOCALAPPDATA "Assist"
$Icon = Join-Path $IconDir "assist.ico"
$Script = Join-Path $PSScriptRoot "assist.ps1"

$Shortcuts = [ordered]@{
    "Assist Voice"        = @{ Args = "-Mode real"; Note = "Assist Voice on your real accounts" }
    "Assist Voice (Demo)" = @{ Args = "-Mode demo"; Note = "Assist Voice on fake demo data" }
    "Stop Assist Voice"   = @{ Args = "-Stop";      Note = "Stop the Assist Voice API" }
}
# Earlier names, removed when the shortcuts are (re)made
$OldNames = "Assist", "Assist (Demo)", "Stop Assist"

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
    exit 0
}

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "No Python environment found. Run 'uv sync' first." }
New-Item -ItemType Directory -Force $IconDir | Out-Null
& $Python (Join-Path $PSScriptRoot "make_icon.py") $Icon
if ($LASTEXITCODE -ne 0) { throw "Couldn't convert the icon" }

$shell = New-Object -ComObject WScript.Shell
Add-Type -Path (Join-Path $PSScriptRoot "AssistShell.cs")

# Assist installed as a Chrome/Edge app: the browser made a Start menu shortcut
# for it ("Chrome Apps\Assist.lnk"). Save how to start it (the launcher opens that
# instead of a plain window) and copy its taskbar ID onto our "Assist Voice" shortcut.
$AppFile = Join-Path $IconDir "app.json"
$appUserModelId = ""
$appLink = Get-ChildItem ([Environment]::GetFolderPath("Programs")) -Filter "Assist*.lnk" -Recurse -ErrorAction SilentlyContinue |
    Where-Object { $shell.CreateShortcut($_.FullName).Arguments -match "--app-id=" } | Select-Object -First 1
if ($appLink) {
    $l = $shell.CreateShortcut($appLink.FullName)
    $appUserModelId = [AssistShell]::GetShortcutAppId($appLink.FullName)
    @{ Exe = $l.TargetPath; Arguments = $l.Arguments.Trim(); AppUserModelId = $appUserModelId } |
        ConvertTo-Json | Set-Content $AppFile -Encoding utf8
} elseif (Test-Path $AppFile) {
    # Chrome's own shortcuts may be deleted (they'd open the app without the API);
    # keep the saved app while it's still installed in that Chrome profile
    $saved = Get-Content $AppFile -Raw | ConvertFrom-Json
    $profileDir = if ($saved.Arguments -match '--profile-directory="?([^"]+?)"?(\s|$)') { $Matches[1] } else { "Default" }
    $appId = if ($saved.Arguments -match '--app-id=(\w+)') { $Matches[1] } else { "" }
    $userData = Split-Path (Split-Path $saved.Exe) -Parent | Split-Path -Leaf   # "Chrome" or "Edge"
    $vendor = if ($userData -eq "Edge") { "Microsoft\Edge" } else { "Google\Chrome" }
    $installed = $appId -and (Test-Path "$env:LOCALAPPDATA\$vendor\User Data\$profileDir\Web Applications\Manifest Resources\$appId")
    if ($installed -and $saved.AppUserModelId) { $appUserModelId = $saved.AppUserModelId }
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
        if ($name -eq "Assist Voice" -and $appUserModelId) {
            [AssistShell]::SetShortcutAppId($path, $appUserModelId)
        }
        Write-Host "Created $path"
    }
}

if ($appUserModelId) {
    Write-Host "Linked 'Assist Voice' to the installed app's taskbar button ($appUserModelId)."
} else {
    Write-Host "Tip: install Assist Voice as a Chrome app (open http://localhost:8000 in Chrome > Install),"
    Write-Host "then run this again, so its window shares the pinned shortcut's taskbar button."
}

# Windows caches shortcut icons: refresh so the new one shows right away
& (Join-Path $env:SystemRoot "System32\ie4uinit.exe") -show
