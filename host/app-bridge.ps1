# JARVIS desktop bridge (host side).
#
# The backend runs inside a Linux container and cannot touch this desktop. It
# writes request files into workspace\.appbridge\req and this watcher performs
# the action, then writes the answer into ...\res. No ports, no listeners: the
# transport is a folder inside the sandboxed workspace.
#
#   open  : launch an alias from APPS_ALLOWLIST
#   close : polite CloseMainWindow, then terminate after the grace period
#   list  : windows that currently have a title
#
# Security: only allow-listed aliases can be launched; APPS_DENYLIST processes
# are never closed; targets may use %ENVIRONMENT_VARIABLES% and forward slashes.
#
# Start it with start-bridge.cmd and keep the window open.

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$busDir = Join-Path $root 'workspace\.appbridge'
$reqDir = Join-Path $busDir 'req'
$resDir = Join-Path $busDir 'res'

# ---------------------------------------------------------------------- settings
function Read-DotEnv([string]$path) {
    if (-not (Test-Path -LiteralPath $path)) { return }
    foreach ($line in Get-Content -LiteralPath $path -Encoding UTF8) {
        $text = $line.Trim()
        if (-not $text -or $text.StartsWith('#')) { continue }
        $split = $text.IndexOf('=')
        if ($split -lt 1) { continue }
        $key = $text.Substring(0, $split).Trim()
        $value = $text.Substring($split + 1).Trim()
        if (-not [Environment]::GetEnvironmentVariable($key, 'Process')) {
            [Environment]::SetEnvironmentVariable($key, $value, 'Process')
        }
    }
}

Read-DotEnv (Join-Path $root '.env')

function Get-Setting([string]$name, [string]$fallback) {
    $value = [Environment]::GetEnvironmentVariable($name, 'Process')
    if ([string]::IsNullOrWhiteSpace($value)) { return $fallback }
    return $value
}

$rawAllow = Get-Setting 'APPS_ALLOWLIST' 'notepad=notepad.exe'
$rawDeny = Get-Setting 'APPS_DENYLIST' 'explorer,winlogon,csrss,lsass,svchost,services,dwm,wininit,smss'
$graceMs = 2500
[int]::TryParse((Get-Setting 'APPS_CLOSE_GRACE_MS' '2500'), [ref]$graceMs) | Out-Null
$forceAfterGrace = ((Get-Setting 'APPS_FORCE_AFTER_GRACE' 'true').ToLower() -ne 'false')

# alias=target[|processName] ; semicolon separated
$allow = @{}
foreach ($entry in ($rawAllow -split ';')) {
    $item = $entry.Trim()
    if (-not $item) { continue }
    $eq = $item.IndexOf('=')
    if ($eq -lt 1) { continue }
    $alias = $item.Substring(0, $eq).Trim().ToLowerInvariant()
    $rest = $item.Substring($eq + 1).Trim()
    $bar = $rest.IndexOf('|')
    if ($bar -ge 0) {
        $target = $rest.Substring(0, $bar).Trim()
        $process = $rest.Substring($bar + 1).Trim()
    } else {
        $target = $rest
        $process = ''
    }
    if ($alias -and $target) {
        $allow[$alias] = @{ Target = $target; Process = $process }
    }
}

$deny = @{}
foreach ($name in ($rawDeny -split ',')) {
    $value = $name.Trim().ToLowerInvariant()
    if ($value) { $deny[$value] = $true }
}

# URI schemes the backend may ask the shell to open (WhatsApp deep links, …)
$uriSchemes = @{}
foreach ($name in ((Get-Setting 'APPS_URI_SCHEMES' 'whatsapp,ms-settings') -split ',')) {
    $value = $name.Trim().ToLowerInvariant()
    if ($value) { $uriSchemes[$value] = $true }
}

# ---------------------------------------------------------------------- helpers
function Resolve-Target([string]$target) {
    $expanded = [Environment]::ExpandEnvironmentVariables($target)
    return $expanded.Replace('/', '\')
}

function Get-ProcessNameFor([string]$target, [string]$override) {
    if ($override) { return $override }
    $leaf = Split-Path -Leaf (Resolve-Target $target)
    if ($leaf.Contains('.')) { return ($leaf -split '\.')[0] }
    return $leaf
}

function New-Response([string]$id, [string]$action, [string]$app) {
    return @{
        ok      = $true
        id      = $id
        action  = $action
        app     = $app
        pids    = @()
        closed  = 0
        forced  = $false
        apps    = @()
        message = ''
    }
}

function Invoke-Open($request) {
    $alias = ([string]$request.app).Trim().ToLowerInvariant()
    $response = New-Response $request.id 'open' $alias

    if (-not $alias) { throw 'no app alias was given' }
    if (-not $allow.ContainsKey($alias)) {
        throw "'$alias' is not in APPS_ALLOWLIST (available: $($allow.Keys -join ', '))"
    }

    $target = Resolve-Target $allow[$alias].Target
    $processName = Get-ProcessNameFor $allow[$alias].Target $allow[$alias].Process
    $arguments = @()
    if ($request.args) { $arguments = @($request.args | ForEach-Object { [string]$_ }) }

    # Real files can be started with -PassThru; shell targets (ms-settings:,
    # shell:AppsFolder\..., app protocols) must be handed to the shell without it,
    # otherwise Start-Process fails with "cannot find all the information required".
    $isFile = $false
    try { $isFile = Test-Path -LiteralPath $target -PathType Leaf } catch { $isFile = $false }

    if ($isFile) {
        if ($arguments.Count -gt 0) {
            $started = Start-Process -FilePath $target -ArgumentList $arguments -PassThru
        } else {
            $started = Start-Process -FilePath $target -PassThru
        }
    } else {
        if ($arguments.Count -gt 0) {
            Start-Process -FilePath $target -ArgumentList $arguments
        } else {
            Start-Process -FilePath $target
        }
        $started = $null
    }

    # Electron / packaged apps spawn helpers; give them a moment, then report
    # every process carrying the expected name.
    Start-Sleep -Milliseconds 900
    $pids = @(Get-Process -Name $processName -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty Id)
    if (-not $pids -and $started) { $pids = @($started.Id) }

    $response.target = $target
    $response.pids = $pids
    $response.message = "launched $alias ($target)"
    return $response
}

function Get-ProtectedProcessIds {
    # The bridge itself plus every ancestor: the watcher must never kill the
    # chain it runs inside (closing 'powershell' would otherwise kill this loop).
    $ids = New-Object System.Collections.Generic.HashSet[int]
    [void]$ids.Add($PID)
    $current = $PID
    for ($i = 0; $i -lt 8; $i++) {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$current" -ErrorAction SilentlyContinue
        if (-not $proc -or -not $proc.ParentProcessId) { break }
        $parent = [int]$proc.ParentProcessId
        if ($parent -le 4 -or $ids.Contains($parent)) { break }
        [void]$ids.Add($parent)
        $current = $parent
    }
    return $ids
}

function Invoke-Close($request) {
    $alias = ([string]$request.app).Trim().ToLowerInvariant()
    $response = New-Response $request.id 'close' $alias

    if (-not $alias) { throw 'no app alias was given' }
    if (-not $allow.ContainsKey($alias)) {
        throw "'$alias' is not in the app allowlist, so I will not close it"
    }

    $processName = Get-ProcessNameFor $allow[$alias].Target $allow[$alias].Process
    $response.process = $processName

    if ($deny.ContainsKey($processName.ToLowerInvariant())) {
        throw "'$processName' is protected (APPS_DENYLIST) and will not be closed"
    }

    $protected = Get-ProtectedProcessIds

    $victims = @(Get-Process -Name $processName -ErrorAction SilentlyContinue |
        Where-Object { -not $protected.Contains([int]$_.Id) })
    if ($victims.Count -eq 0) {
        $response.message = "no closable '$processName' process was running (bridge and its parents are protected)"
        return $response
    }

    foreach ($proc in $victims) {
        try { $proc.CloseMainWindow() | Out-Null } catch { }
    }

    # Polite close first: wait for the windows to go away.
    $deadline = (Get-Date).AddMilliseconds($graceMs)
    while ((Get-Date) -lt $deadline) {
        $alive = @(Get-Process -Name $processName -ErrorAction SilentlyContinue |
            Where-Object { -not $protected.Contains([int]$_.Id) })
        if ($alive.Count -eq 0) { break }
        Start-Sleep -Milliseconds 150
    }

    $force = [bool]$request.force -or $forceAfterGrace
    $remaining = @(Get-Process -Name $processName -ErrorAction SilentlyContinue |
        Where-Object { -not $protected.Contains([int]$_.Id) })
    if ($remaining.Count -gt 0 -and $force) {
        foreach ($proc in $remaining) {
            try { Stop-Process -Id $proc.Id -Force -ErrorAction Stop } catch { }
        }
        $response.forced = $true
        Start-Sleep -Milliseconds 250
    }

    $still = @(Get-Process -Name $processName -ErrorAction SilentlyContinue |
        Where-Object { -not $protected.Contains([int]$_.Id) })
    $closed = $victims.Count - $still.Count
    $response.closed = $closed
    if ($still.Count -gt 0) {
        $response.ok = $false
        $response.message = "closed $closed of $($victims.Count) '$alias' process(es); $($still.Count) still running"
    } else {
        $response.message = "closed $closed of $($victims.Count) '$alias' process(es)"
    }
    return $response
}

function Invoke-List($request) {
    $response = New-Response $request.id 'list' ''
    $windows = @()
    foreach ($proc in (Get-Process -ErrorAction SilentlyContinue)) {
        $title = ''
        try { $title = $proc.MainWindowTitle } catch { continue }
        if ([string]::IsNullOrWhiteSpace($title)) { continue }
        $windows += @{
            process = $proc.ProcessName
            id      = $proc.Id
            title   = $title
        }
    }
    $response.apps = @($windows | Sort-Object { $_.process })
    $response.message = "$($response.apps.Count) window(s) open"
    return $response
}

# ---------------------------------------------------------------------- input
$inputReady = $false
try {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName Microsoft.VisualBasic
    if (-not ('JarvisWin32' -as [type])) {
        Add-Type -Namespace '' -Name 'JarvisWin32' -MemberDefinition @'
[DllImport("user32.dll")] public static extern System.IntPtr GetForegroundWindow();
[DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(System.IntPtr hWnd, out uint pid);
[DllImport("user32.dll")] public static extern bool SetForegroundWindow(System.IntPtr hWnd);
[DllImport("user32.dll")] public static extern bool ShowWindow(System.IntPtr hWnd, int nCmdShow);
[DllImport("user32.dll")] public static extern bool IsIconic(System.IntPtr hWnd);
[DllImport("user32.dll")] public static extern bool AttachThreadInput(uint idAttach, uint idAttachTo, bool fAttach);
'@
    }
    $inputReady = $true
} catch {
    Write-Host "  keyboard automation unavailable: $($_.Exception.Message)" -ForegroundColor Yellow
}

function Get-ForegroundProcessId {
    $handle = [JarvisWin32]::GetForegroundWindow()
    $ownerPid = [uint32]0
    [void][JarvisWin32]::GetWindowThreadProcessId($handle, [ref]$ownerPid)
    return [int]$ownerPid
}

function Set-WindowForeground([int]$targetPid) {
    # Windows refuses SetForegroundWindow from a background process, so attach to
    # the current foreground thread first — the standard workaround.
    $proc = Get-Process -Id $targetPid -ErrorAction SilentlyContinue
    if (-not $proc -or $proc.MainWindowHandle -eq 0) { return $false }
    $handle = $proc.MainWindowHandle

    if ([JarvisWin32]::IsIconic($handle)) { [void][JarvisWin32]::ShowWindow($handle, 9) }  # SW_RESTORE

    $foregroundPid = [uint32]0
    $foregroundThread = [JarvisWin32]::GetWindowThreadProcessId([JarvisWin32]::GetForegroundWindow(), [ref]$foregroundPid)
    $targetThread = [JarvisWin32]::GetWindowThreadProcessId($handle, [ref]$foregroundPid)

    $attached = $false
    if ($foregroundThread -ne 0 -and $targetThread -ne 0 -and $foregroundThread -ne $targetThread) {
        $attached = [JarvisWin32]::AttachThreadInput($foregroundThread, $targetThread, $true)
    }
    try {
        [void][JarvisWin32]::SetForegroundWindow($handle)
    } finally {
        if ($attached) { [void][JarvisWin32]::AttachThreadInput($foregroundThread, $targetThread, $false) }
    }
    return $true
}

function Send-EnterToWindow([string]$processLike, [string]$exactTitle) {
    # Only ever presses a key when the target window is verifiably in front:
    # an Enter aimed at the wrong window would type into whatever has focus.
    # Matching is by process name (and an *exact* title), never a substring:
    # "whatsapp_test.py - tor - Visual Studio Code" must not look like WhatsApp.
    if (-not $inputReady) { return @{ ok = $false; reason = 'keyboard automation is not available' } }

    $candidates = @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
        $_.MainWindowTitle -and (
            ($processLike -and $_.ProcessName -like $processLike) -or
            ($exactTitle -and $_.MainWindowTitle -eq $exactTitle)
        )
    })
    if ($candidates.Count -eq 0) {
        return @{ ok = $false; reason = "no '$processLike' window with a title is open" }
    }

    # prefer the app's own process over a WebView host window
    $target = $candidates | Sort-Object {
        $score = 5
        if ($processLike -and $_.ProcessName -like $processLike) { $score = 0 }
        elseif ($processLike -and $_.ProcessName -like ($processLike.TrimEnd('*') + '*')) { $score = 2 }
        $score
    } | Select-Object -First 1

    [void](Set-WindowForeground $target.Id)
    Start-Sleep -Milliseconds 450

    if ((Get-ForegroundProcessId) -ne $target.Id) {
        return @{
            ok     = $false
            reason = "the '$($target.MainWindowTitle)' window ($($target.ProcessName)) did not come to the foreground"
        }
    }

    [System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
    return @{ ok = $true; window = $target.MainWindowTitle; process = $target.ProcessName; pid = $target.Id }
}

function Invoke-OpenUri($request) {
    $uri = ([string]$request.uri).Trim()
    $response = New-Response $request.id 'open-uri' ''

    if (-not $uri) { throw 'no uri was given' }
    if ($uri -notmatch '^(?<scheme>[a-z][a-z0-9+.\-]*):') {
        throw "not a usable URI: $uri"
    }
    $scheme = $matches['scheme'].ToLowerInvariant()
    if (-not $uriSchemes.ContainsKey($scheme)) {
        throw "scheme '$scheme' is not allowed (APPS_URI_SCHEMES: $((($uriSchemes.Keys) | Sort-Object) -join ', '))"
    }

    # ShellExecute: this is what turns whatsapp://send?... into the right window
    Start-Process -FilePath $uri
    $response.uri = $uri
    $response.opened = $true
    $response.enter_sent = $false

    if ([bool]$request.press_enter) {
        $delay = 2000
        if ($request.delay_ms) { [int]::TryParse([string]$request.delay_ms, [ref]$delay) | Out-Null }
        if ($delay -lt 0) { $delay = 0 }

        # let the app come up and focus the compose box before typing
        Start-Sleep -Milliseconds $delay

        $processLike = [string]$request.window_process
        $exactTitle = [string]$request.window_title
        if (-not $processLike -and -not $exactTitle) {
            if ($scheme -eq 'whatsapp') {
                $processLike = 'WhatsApp*'
                $exactTitle = 'WhatsApp'
            } else {
                $response.message = "opened $scheme link (no window to confirm, Enter not sent)"
                return $response
            }
        }

        $press = Send-EnterToWindow $processLike $exactTitle
        $response.enter_sent = [bool]$press.ok
        $response.window = $press.window
        $response.window_process = $press.process
        if ($press.ok) {
            $response.message = "opened $scheme link and pressed Enter in '$($press.window)'"
        } else {
            $response.ok = $false
            $response.message = "opened $scheme link but did not send: $($press.reason)"
        }
        return $response
    }

    $response.message = "opened $scheme link"
    return $response
}

function Complete-Request($file) {
    $id = [System.IO.Path]::GetFileNameWithoutExtension($file.Name)
    $response = $null
    try {
        $raw = Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8
        $request = $raw | ConvertFrom-Json
        if ($request.id) { $id = [string]$request.id }

        switch ([string]$request.action) {
            'open'     { $response = Invoke-Open $request }
            'close'    { $response = Invoke-Close $request }
            'list'     { $response = Invoke-List $request }
            'open-uri' { $response = Invoke-OpenUri $request }
            default {
                $response = New-Response $id ([string]$request.action) ([string]$request.app)
                $response.ok = $false
                $response.message = "unknown action '$($request.action)'"
            }
        }
    } catch {
        $response = New-Response $id 'error' ''
        $response.ok = $false
        $response.message = $_.Exception.Message
    }

    $body = $response | ConvertTo-Json -Depth 6 -Compress
    $outFile = Join-Path $resDir "$id.json"
    Set-Content -LiteralPath $outFile -Value $body -Encoding UTF8
    Remove-Item -LiteralPath $file.FullName -Force -ErrorAction SilentlyContinue
}

# ---------------------------------------------------------------------- start up
$mutex = New-Object System.Threading.Mutex($false, 'Local\JARVISAppBridge')
if (-not $mutex.WaitOne(0)) {
    Write-Host 'JARVIS desktop bridge is already running in another window.' -ForegroundColor Yellow
    Start-Sleep -Seconds 3
    exit 0
}

foreach ($dir in @($busDir, $reqDir, $resDir)) {
    if (-not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
}

Write-Host ''
Write-Host '  JARVIS desktop bridge' -ForegroundColor Cyan
Write-Host "  root       : $root"
Write-Host "  queue      : $reqDir"
Write-Host "  apps       : $((($allow.Keys) | Sort-Object) -join ', ')"
Write-Host "  protected  : $((($deny.Keys) | Sort-Object) -join ', ')"
Write-Host "  uri schemes: $((($uriSchemes.Keys) | Sort-Object) -join ', ')"
Write-Host "  close      : grace ${graceMs}ms, force after grace = $forceAfterGrace"
Write-Host '  waiting for requests - keep this window open, Ctrl+C to stop'
Write-Host ''

while ($true) {
    try {
        $files = @(Get-ChildItem -LiteralPath $reqDir -Filter '*.json' -File -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime)
        foreach ($file in $files) {
            Write-Host ("{0:HH:mm:ss}  {1}" -f (Get-Date), $file.Name) -NoNewline
            try {
                Complete-Request $file
                Write-Host '  -> OK' -ForegroundColor Green
            } catch {
                Write-Host "  -> FAILED: $($_.Exception.Message)" -ForegroundColor Red
            }
        }
    } catch {
        Write-Host "bridge loop error: $($_.Exception.Message)" -ForegroundColor Red
    }
    Start-Sleep -Milliseconds 180
}
