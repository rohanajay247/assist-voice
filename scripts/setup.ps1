# One-time setup of Assist Voice on Windows: tools, packages, your keys, shortcuts.
#
#   Right-click this file > "Run with PowerShell", or:
#   powershell -ExecutionPolicy Bypass -File scripts/setup.ps1
#
# Safe to run again: it skips what is already done and only asks for what is missing.
# Afterwards, click "Assist Voice" on the desktop or in the Start menu.
#
# -GeminiKey, -GroqKey, -HomeCity fill in .env without asking (e.g. for testing).
# -NoShortcuts skips the shortcuts. -NoPause doesn't wait for Enter at the end.

param(
    [string]$GeminiKey = "",
    [string]$GroqKey = "",
    [string]$HomeCity = "",
    [switch]$NoShortcuts,
    [switch]$NoPause
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$EnvFile = Join-Path $Root ".env"

function Step($text) { Write-Host ""; Write-Host "== $text" -ForegroundColor Cyan }
function Done($text) { Write-Host "   $text" -ForegroundColor Green }

function Refresh-Path {
    # winget installs update PATH for new windows only; pick the change up here too
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
}

function Ensure-Tool($command, $wingetId, $name) {
    if (Get-Command $command -ErrorAction SilentlyContinue) { Done "$name is installed"; return }
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "$name is missing and winget isn't available. Install $name by hand, then run this again."
    }
    Write-Host "   Installing $name ..."
    winget install --id $wingetId -e
    Refresh-Path
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "$name was installed, but this window can't see it yet. Close it, open a new PowerShell and run setup again."
    }
    Done "$name installed"
}

function Run($what, [scriptblock]$block) {
    & $block
    if ($LASTEXITCODE -ne 0) { throw "$what failed (see the messages above)." }
}

function Get-EnvValue($key) {
    $line = Get-Content $EnvFile | Where-Object { $_ -match "^$key=" } | Select-Object -First 1
    if ($line) { return ($line -replace "^$key=", "").Trim() }
    return ""
}

function Set-EnvValue($key, $value) {
    $lines = @(Get-Content $EnvFile)
    if ($lines -match "^$key=") { $lines = $lines -replace "^$key=.*", "$key=$value" }
    else { $lines += "$key=$value" }
    # UTF-8 without BOM: a BOM would become part of the first variable's name
    [IO.File]::WriteAllLines($EnvFile, [string[]]$lines, (New-Object Text.UTF8Encoding $false))
}

function Ask-Secret($prompt) {
    $secure = Read-Host $prompt -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr).Trim() }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}

try {
    Write-Host "Assist Voice setup" -ForegroundColor Cyan
    # Files from a downloaded ZIP are marked as "from the internet"; allow this project's scripts
    Get-ChildItem (Join-Path $Root "scripts") -File | Unblock-File

    Step "1/5 Tools"
    Ensure-Tool "uv" "astral-sh.uv" "uv (Python)"
    Ensure-Tool "node" "OpenJS.NodeJS.LTS" "Node.js"
    $nodeMajor = [int]((node --version) -replace "^v(\d+).*", '$1')
    if ($nodeMajor -lt 22) { throw "Node.js $nodeMajor is too old; Assist Voice needs 22 or newer. Update it with: winget upgrade OpenJS.NodeJS.LTS" }

    Step "2/5 Packages (a few minutes the first time)"
    Run "uv sync" { uv sync }
    Push-Location (Join-Path $Root "web")
    try { Run "npm install" { npm install --no-fund --no-audit } } finally { Pop-Location }
    Done "Packages installed"

    Step "3/5 Your settings (.env)"
    if (-not (Test-Path $EnvFile)) { Copy-Item (Join-Path $Root ".env.example") $EnvFile; Done "Created .env" }

    if ($GeminiKey) { Set-EnvValue "GEMINI_API_KEY" $GeminiKey }
    while (-not (Get-EnvValue "GEMINI_API_KEY")) {
        Write-Host "   Assist Voice needs a free Gemini API key: https://aistudio.google.com/apikey"
        Write-Host "   (Create it in a project without billing, so it stays free.)"
        $key = Ask-Secret "   Paste your Gemini API key"
        if ($key) { Set-EnvValue "GEMINI_API_KEY" $key }
    }
    Done "Gemini key saved"

    if ($GroqKey) { Set-EnvValue "GROQ_API_KEY" $GroqKey }
    if (-not (Get-EnvValue "GROQ_API_KEY") -and -not $NoPause) {
        Write-Host "   For the microphone, add a free Groq key: https://console.groq.com/keys"
        $key = Ask-Secret "   Paste your Groq key (or just press Enter to type instead of talking)"
        if ($key) { Set-EnvValue "GROQ_API_KEY" $key }
    }
    if (Get-EnvValue "GROQ_API_KEY") { Done "Groq key saved: the mic works" } else { Write-Host "   No Groq key: you'll type instead of talking. Run setup again to add one." }

    if ($HomeCity) { Set-EnvValue "HOME_CITY" $HomeCity }
    if (-not (Get-EnvValue "HOME_CITY") -and -not $NoPause) {
        $city = (Read-Host "   Your city, for the weather (e.g. Kochi)").Trim()
        if ($city) { Set-EnvValue "HOME_CITY" $city }
    }
    if (Get-EnvValue "HOME_CITY") { Done "Home city: $(Get-EnvValue 'HOME_CITY')" }

    $zone = Get-EnvValue "ASSIST_TIMEZONE"
    if (-not $zone) { $zone = (& uv run python -c "from tzlocal import get_localzone_name; print(get_localzone_name())").Trim() + " (from this computer)" }
    Done "Timezone: $zone"

    Step "4/5 Building the app"
    Push-Location (Join-Path $Root "web")
    try { Run "npm run build" { npm run build *> (Join-Path $env:TEMP "assist-voice-build.log") } } finally { Pop-Location }
    Done "App built"

    Step "5/5 Shortcuts"
    if ($NoShortcuts) { Write-Host "   Skipped (-NoShortcuts)" }
    else {
        Run "Creating the shortcuts" { powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "install-shortcuts.ps1") }
    }

    # Google sign-in, if the user already saved their OAuth client file (docs/setup.md)
    $client = Join-Path $Root "secrets\gcp-oauth.keys.json"
    $token = Join-Path $Root "secrets\google-token.json"
    if ((Test-Path $client) -and -not (Test-Path $token) -and -not $NoPause) {
        if ((Read-Host "   Sign in to Google now for calendar and email? (y/n)") -match "^y") {
            Run "Google sign-in" { uv run python scripts/google_auth.py }
        }
    }

    Write-Host ""
    Write-Host "Assist Voice is set up." -ForegroundColor Green
    Write-Host "Click 'Assist Voice' on your desktop or in the Start menu. Right-click it there > Pin to taskbar."
    Write-Host ""
    Write-Host "Works now: talking/typing, notes, memory, weather, photos, undo."
    Write-Host "More features, each optional (guide: docs/setup.md, 'Turn on every feature'):"
    if (-not (Test-Path $token)) { Write-Host "  - Calendar and email: connect your Google account (about 15 minutes)" }
    Write-Host "  - Save my tabs: add the Chrome extension (2 minutes)"
    Write-Host "  - Use it on your phone: Cloudflare tunnel (5 minutes)"
    Write-Host "  - Let it write new tools: install Docker Desktop"
    Write-Host "  - GitHub questions: a read-only GitHub token"
}
catch {
    Write-Host ""
    Write-Host "Setup stopped: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Fix that, then run setup again; it continues where it stopped."
    if (-not $NoPause) { Read-Host "Press Enter to close" | Out-Null }
    exit 1
}
if (-not $NoPause) { Read-Host "Press Enter to close" | Out-Null }
