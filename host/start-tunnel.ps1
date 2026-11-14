<#
.SYNOPSIS
    Publish JARVIS through ngrok so a phone can talk to it.

.DESCRIPTION
    Runs the official ngrok/ngrok container pointed at the frontend (port 8080), which
    also proxies /api and /ws — one tunnel is enough for the whole app, including the
    WebSocket chat and browser speech.

    The agent runs as a container (no host binary) on purpose: Windows Defender
    quarantines the ngrok.exe download, and the container is unaffected.

    The ngrok authtoken is read from NGROK_AUTHTOKEN in .env; if it is missing you are
    prompted once with hidden input and it is saved there (.env is git-ignored).

.PARAMETER Domain
    Your reserved ngrok domain (default: the one in .env / the parameter default).

.PARAMETER Port
    Local port to expose. 8080 = frontend (serves the SPA and proxies the API + WS).

.PARAMETER Stop
    Remove the tunnel container instead of starting it.

.EXAMPLE
    .\host\start-tunnel.ps1

.EXAMPLE
    .\host\start-tunnel.ps1 -Port 8080 -Domain shiela-interbrigade-unfraudulently.ngrok-free.dev

.EXAMPLE
    .\host\start-tunnel.ps1 -Stop
#>
param(
    [string]$Domain = 'shiela-interbrigade-unfraudulently.ngrok-free.dev',
    [int]$Port = 8080,
    [switch]$Stop
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $root '.env'
$name = 'jarvis-ngrok'

function Get-Token {
    $token = ''
    if (Test-Path -LiteralPath $envPath) {
        $line = (Get-Content -LiteralPath $envPath | Select-String '^NGROK_AUTHTOKEN=').Line
        if ($line) { $token = ($line -split '=', 2)[1].Trim() }
    }
    if ($token) { return $token }

    Write-Host 'Get the authtoken from https://dashboard.ngrok.com/get-started/your-authtoken' -ForegroundColor Cyan
    $secure = Read-Host -Prompt 'Paste your ngrok authtoken (input hidden)' -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
    $token = "$token".Trim()
    if (-not $token) { throw 'no authtoken entered' }

    $lines = @(Get-Content -LiteralPath $envPath)
    if ($lines -match '^\s*#?\s*NGROK_AUTHTOKEN\s*=') {
        $lines = $lines | ForEach-Object {
            if ($_ -match '^\s*#?\s*NGROK_AUTHTOKEN\s*=') { "NGROK_AUTHTOKEN=$token" } else { $_ }
        }
    } else {
        $lines += "NGROK_AUTHTOKEN=$token"
    }
    [System.IO.File]::WriteAllText($envPath, (($lines -join "`n") + "`n"), (New-Object System.Text.UTF8Encoding($false)))
    Write-Host "saved NGROK_AUTHTOKEN to .env (…$($token.Substring([Math]::Max(0, $token.Length - 4))))" -ForegroundColor Green
    return $token
}

Push-Location -LiteralPath $root
try {
    docker rm -f $name 2>$null | Out-Null

    if ($Stop) {
        Write-Host 'tunnel stopped (container removed)' -ForegroundColor Yellow
        return
    }

    $token = Get-Token
    if (-not (Get-Process -Name docker -ErrorAction SilentlyContinue)) {
        Write-Warning 'Docker does not look like it is running'
    }

    docker run -d --name $name --restart unless-stopped `
        -e "NGROK_AUTHTOKEN=$token" `
        -p 4040:4040 `
        ngrok/ngrok:latest http "--url=$Domain" "host.docker.internal:$Port" | Out-Null

    Write-Host 'starting the tunnel...'
    $url = $null
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Seconds 2
        try {
            $info = Invoke-RestMethod -Uri 'http://127.0.0.1:4040/api/tunnels' -TimeoutSec 4
            $url = ($info.tunnels | Where-Object { $_.public_url -like 'https://*' } | Select-Object -First 1).public_url
            if ($url) { break }
        } catch {
            if ((docker ps -a --filter "name=$name" --format '{{.Status}}') -match 'Exited') { break }
        }
    }

    if (-not $url) {
        Write-Host ''
        Write-Host 'the tunnel did not come up. ngrok says:' -ForegroundColor Red
        docker logs $name 2>&1 | Select-Object -Last 15 | ForEach-Object { Write-Host "  $_" }
        Write-Host ''
        Write-Host 'common causes: authtoken wrong, or the domain is not reserved on this account' -ForegroundColor Yellow
        return
    }

    $token403 = ''
    if (Test-Path -LiteralPath $envPath) {
        $line = (Get-Content -LiteralPath $envPath | Select-String '^JARVIS_AUTH_TOKEN=').Line
        if ($line) { $token403 = ($line -split '=', 2)[1].Trim() }
    }

    Write-Host ''
    Write-Host 'JARVIS is reachable from anywhere:' -ForegroundColor Green
    Write-Host ("  URL   : {0}" -f $url) -ForegroundColor Green
    Write-Host ("  token : {0}… (the value of JARVIS_AUTH_TOKEN in .env)" -f $token403.Substring(0, [Math]::Min(4, $token403.Length)))
    Write-Host ''
    Write-Host 'On the phone: open the URL, accept ngrok''s "Visit Site" prompt, paste the token, send.' -ForegroundColor Cyan
    Write-Host '  - browser speech (mic) works because the tunnel is HTTPS' -ForegroundColor DarkGray
    Write-Host '  - anyone with the URL + token controls this machine, so stop it when done:' -ForegroundColor DarkYellow
    Write-Host '        .\host\start-tunnel.ps1 -Stop' -ForegroundColor DarkGray
} finally {
    Pop-Location
}
