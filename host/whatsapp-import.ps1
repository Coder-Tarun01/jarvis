<#
.SYNOPSIS
    Bulk-import WhatsApp name -> number aliases into data\whatsapp_aliases.json.

.DESCRIPTION
    Wraps backend/scripts/import_whatsapp_contacts.py, so the run uses the backend's
    own settings and writes the bind-mounted data\whatsapp_aliases.json that JARVIS
    reads live (no restart, no rebuild).

    Sources:
      -Contacts   every Google contact that has a phone number (data\contacts_cache.json)
      -File PATH  any exported list: "Name=+91…", "Name,+91…", TSV, vCard or JSON
      -Stdin      pipe a list in, e.g. Get-Content list.txt | .\host\whatsapp-import.ps1 -Stdin

    Existing aliases are never replaced unless -Overwrite is passed.

.EXAMPLE
    .\host\whatsapp-import.ps1 -Contacts -DryRun

.EXAMPLE
    .\host\whatsapp-import.ps1 -File .\workspace\contacts.csv

.EXAMPLE
    .\host\whatsapp-import.ps1 -Contacts -Overwrite
#>
param(
    [string]$File,
    [switch]$Contacts,
    [switch]$Stdin,
    [switch]$Overwrite,
    [switch]$DryRun,
    [int]$Limit = 0
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $root

try {
    if (-not $Contacts -and -not $Stdin -and -not $File) {
        throw "nothing to import: pass -Contacts, -File PATH or -Stdin"
    }
    if ($File -and -not (Test-Path -LiteralPath $File)) {
        throw "no such file: $File"
    }

    $cliArgs = @(
        'compose', 'exec', '-T', 'backend',
        'python', 'scripts/import_whatsapp_contacts.py'
    )
    if ($Contacts) { $cliArgs += '--contacts' }
    if ($Overwrite) { $cliArgs += '--overwrite' }
    if ($DryRun) { $cliArgs += '--dry-run' }
    if ($Limit -gt 0) { $cliArgs += @('--limit', "$Limit") }
    if ($Stdin -or $File) { $cliArgs += @('--file', '-') }

    # Prefer the running container (same settings, bind-mounted data dir). Fall back
    # to the repo venv when Docker is not up, which resolves to the same file.
    $dockerUp = $false
    try {
        $null = docker compose ps --status running --services 2>$null
        $dockerUp = ($LASTEXITCODE -eq 0) -and ((docker compose ps --status running --services) -match 'backend')
    } catch {
        $dockerUp = $false
    }

    if ($dockerUp) {
        if ($Stdin) {
            [Console]::In.ReadToEnd() | docker @cliArgs
        } elseif ($File) {
            Get-Content -LiteralPath $File -Raw -Encoding UTF8 | docker @cliArgs
        } else {
            docker @cliArgs
        }
    } else {
        Write-Host 'docker backend is not running — using the local venv instead' -ForegroundColor DarkYellow
        $python = Join-Path $root '.venv\Scripts\python.exe'
        if (-not (Test-Path -LiteralPath $python)) {
            throw "docker backend is down and .venv is missing; start the stack with .\run.ps1"
        }
        $localArgs = @('backend\scripts\import_whatsapp_contacts.py')
        $tail = @()
        for ($i = 6; $i -lt $cliArgs.Count; $i++) { $tail += $cliArgs[$i] }
        if ($Stdin) {
            [Console]::In.ReadToEnd() | & $python ($localArgs + $tail)
        } elseif ($File) {
            Get-Content -LiteralPath $File -Raw -Encoding UTF8 | & $python ($localArgs + $tail)
        } else {
            & $python ($localArgs + $tail)
        }
    }
} finally {
    Pop-Location
}
