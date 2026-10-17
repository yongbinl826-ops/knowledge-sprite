$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$settingsPath = Join-Path $projectRoot 'deploy/searxng/settings.yml'
if (-not (Test-Path -LiteralPath $settingsPath)) {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes)
    $rng.Dispose()
    $secret = [BitConverter]::ToString($bytes).Replace('-', '').ToLowerInvariant()
    $template = Get-Content -LiteralPath (Join-Path $projectRoot 'deploy/searxng/settings.example.yml') -Raw
    [IO.File]::WriteAllText($settingsPath, $template.Replace('REPLACED_BY_SETUP_SCRIPT', $secret), (New-Object Text.UTF8Encoding($false)))
    Write-Host 'Created local SearXNG settings with a random secret (not printed).'
}
Push-Location $projectRoot
try {
    docker compose up -d searxng
    if ($LASTEXITCODE -ne 0) { throw 'SearXNG failed to start. Check Docker Desktop and image access.' }
    Write-Host 'SearXNG: http://127.0.0.1:18780; set SEARXNG_URL in your server .env.'
} finally { Pop-Location }
