param([switch]$SkipInstall, [switch]$NoBuild)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$defaultedFeatures = @()
Push-Location $projectRoot
try {
    # Normal restarts retain the approved discovery policy even with an old
    # .env. An explicit process setting (including false) still takes priority.
    foreach ($feature in @('OPEN_WEB_SEARCH_ENABLED', 'PARALLEL_PLATFORM_SEARCH',
            'TEACHING_MATCH_ENABLED', 'SHARED_COURSE_LIBRARY_ENABLED',
            'MOOC_GAP_SEARCH_ENABLED', 'MOOC_REFRESH_ENABLED')) {
        if ($null -eq [Environment]::GetEnvironmentVariable($feature, 'Process')) {
            [Environment]::SetEnvironmentVariable($feature, 'true', 'Process')
            $defaultedFeatures += $feature
        }
    }
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
    uv run --frozen uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-proxy-headers --no-access-log
} finally {
    foreach ($feature in $defaultedFeatures) {
        Remove-Item -LiteralPath "Env:$feature" -ErrorAction SilentlyContinue
    }
    Pop-Location
}
