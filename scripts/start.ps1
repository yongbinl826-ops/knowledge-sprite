param([switch]$SkipInstall, [switch]$NoBuild)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    if (-not (Test-Path -LiteralPath '.env')) {
        Copy-Item -LiteralPath '.env.example' -Destination '.env'
    }
    if (-not $SkipInstall) {
        uv sync --frozen
        if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
    }
    if (-not $NoBuild) {
        Push-Location frontend
        try {
            npm.cmd ci
            if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
            npm.cmd run build
            if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
        } finally { Pop-Location }
    }
    Write-Host 'Application: http://127.0.0.1:8000 (single worker; Ctrl+C to stop)'
    uv run --frozen uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --workers 1
} finally { Pop-Location }
