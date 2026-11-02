# Builds the Docker image Assist uses to test and run tools it writes itself.
# Docker Desktop must be running. Rebuild after changing sandbox/.
#   powershell -ExecutionPolicy Bypass -File scripts/build_sandbox.ps1

$ErrorActionPreference = "Stop"
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "Docker is not installed or not on PATH. Install Docker Desktop first." -ForegroundColor Yellow
    exit 1
}
docker build -t assist-sandbox "$PSScriptRoot\..\sandbox"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "Built assist-sandbox." -ForegroundColor Green
