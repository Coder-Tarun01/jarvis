<#
.SYNOPSIS
    Store your OpenRouter API key in .env and switch JARVIS to the free model.

.DESCRIPTION
    Asks for the key with hidden input (so it never lands in the terminal scrollback,
    your shell history or this chat), writes OPENROUTER_API_KEY + LLM_PROVIDER=openrouter
    into .env, then optionally restarts the backend and checks /api/health.

    Get a key at https://openrouter.ai/settings/keys (free).

.PARAMETER Key
    Pass the key directly instead of being prompted (useful for scripting).

.PARAMETER Restart
    Recreate the backend container afterwards and print the resulting provider state.

.EXAMPLE
    .\host\set-openrouter-key.ps1 -Restart

.EXAMPLE
    .\host\set-openrouter-key.ps1 -Key sk-or-v1-... -Restart
#>
param(
    [string]$Key,
    [switch]$Restart
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $root '.env'

if (-not (Test-Path -LiteralPath $envPath)) {
    throw "no .env found at $envPath - copy .env.example to .env first"
}

if (-not $Key) {
    Write-Host 'Open a key at https://openrouter.ai/settings/keys (free tier).' -ForegroundColor Cyan
    $secure = Read-Host -Prompt 'Paste your OpenRouter API key (input hidden)' -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $Key = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}

$Key = "$Key".Trim()
if (-not $Key) { throw 'no key entered' }
if ($Key -notmatch '^sk-or-') {
    Write-Warning 'that does not look like an OpenRouter key (they usually start with sk-or-v1-)'
}

# rewrite only the two lines we own; every other line is preserved verbatim
$lines = Get-Content -LiteralPath $envPath -Encoding UTF8
$seenKey = $false
$seenProvider = $false
$updated = foreach ($line in $lines) {
    if ($line -match '^\s*OPENROUTER_API_KEY\s*=') {
        $seenKey = $true
        "OPENROUTER_API_KEY=$Key"
    } elseif ($line -match '^\s*LLM_PROVIDER\s*=') {
        $seenProvider = $true
        'LLM_PROVIDER=openrouter'
    } else {
        $line
    }
}
$updated = @($updated)
if (-not $seenProvider) { $updated += 'LLM_PROVIDER=openrouter' }
if (-not $seenKey) { $updated += "OPENROUTER_API_KEY=$Key" }

# UTF-8 without BOM: a BOM would corrupt the first key for python-dotenv
[System.IO.File]::WriteAllText($envPath, (($updated -join "`n") + "`n"), (New-Object System.Text.UTF8Encoding($false)))
Write-Host "saved to .env (LLM_PROVIDER=openrouter, key ...$($Key.Substring([Math]::Max(0, $Key.Length - 4))))" -ForegroundColor Green

if (-not $Restart) {
    Write-Host 'restart the backend to pick it up:  docker compose up -d --force-recreate backend'
    return
}

Push-Location -LiteralPath $root
try {
    docker compose up -d --force-recreate backend | Out-Null
    Write-Host 'waiting for the backend to become healthy...'
    $deadline = (Get-Date).AddSeconds(90)
    $token = ((Get-Content -LiteralPath $envPath | Select-String '^JARVIS_AUTH_TOKEN=').Line -split '=', 2)[1].Trim()
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 3
        try {
            $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/health' `
                -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 5
            if ($health.status -eq 'ok') { break }
        } catch {
            continue
        }
    }
    if (-not $health) { throw 'the backend did not answer - check docker compose logs backend' }

    Write-Host ''
    Write-Host ("provider       : {0}" -f $health.provider)
    Write-Host ("model          : {0}" -f $health.model)
    Write-Host ("llm_configured : {0}" -f $health.llm_configured)
    if ($health.provider -ne 'openrouter' -or -not $health.llm_configured) {
        Write-Warning 'the backend is not on the free model yet - check .env and the container logs'
    } else {
        Write-Host 'ready - say "hey jarvis, what time is it?"' -ForegroundColor Green
    }
} finally {
    Pop-Location
}
