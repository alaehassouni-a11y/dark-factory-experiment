# Start the Virtual Agent service and the developer console on this machine, for testing.
#
#   powershell -ExecutionPolicy Bypass -File tools\dev-console\start.ps1          real providers (needs app\.env with OPENROUTER_API_KEY)
#   powershell -ExecutionPolicy Bypass -File tools\dev-console\start.ps1 -Stubs   stub providers: no key, no network, canned answers
#
# Opens http://localhost:8080 in the default browser once the service reports healthy.
# Stops anything already listening on the two ports first, so it is safe to run twice.
# Chrome or Edge for the microphone; every browser speaks.

param(
    [switch]$Stubs,
    [int]$ServicePort = 8000,
    [int]$ConsolePort = 8080
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$console = Join-Path $root "tools\dev-console"

# Prefer a real python over the Microsoft Store stub, which prints "Python est introuvable".
$python = (Get-Command python -ErrorAction SilentlyContinue | Where-Object { $_.Source -notmatch "WindowsApps" } | Select-Object -First 1).Source
if (-not $python) {
    $candidate = Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"
    if (Test-Path $candidate) { $python = $candidate } else { throw "No Python 3.11 found. Install it from python.org and re-run." }
}
$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $uv) { $candidate = Join-Path $env:USERPROFILE ".local\bin\uv.exe"; if (Test-Path $candidate) { $uv = $candidate } else { throw "uv is not installed (https://docs.astral.sh/uv/)." } }

$children = @()
function Stop-Children {
    foreach ($p in $script:children) {
        if ($p -and -not $p.HasExited) {
            try { Stop-Process -Id $p.Id -Force -ErrorAction Stop; Write-Host "stopped process $($p.Id)" } catch {}
        }
    }
    $script:children = @()
}

function Stop-Port([int]$port) {
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { try { Stop-Process -Id $_.OwningProcess -Force -ErrorAction Stop; Write-Host "stopped process $($_.OwningProcess) on port $port" } catch {} }
}
Stop-Port $ServicePort
Stop-Port $ConsolePort
Start-Sleep -Seconds 1

$env:CORS_ORIGINS = "http://localhost:$ConsolePort,http://127.0.0.1:$ConsolePort"

try {
    if ($Stubs) {
        # Stub providers, but the REAL wiki folder: harness/serve.py exists for the gate and
        # pins the fixture wiki, whereas a person testing wants to see their own documents
        # turn up as sources. The model's answers are canned sentences; the language, the
        # source badge and the document named under each answer are real.
        $stubPort = 8765
        Stop-Port $stubPort
        Write-Host "Starting stub providers on :$stubPort (a canned model, a canned search)..."
        # harness/stubs.py's `--port` command line is a contract this script depends on.
        $stub = Start-Process -FilePath $python -ArgumentList "harness/stubs.py", "--port", "$stubPort" -WorkingDirectory $root -PassThru -WindowStyle Minimized
        $children += $stub

        # Wait for the stubs to actually answer. Without this a stub that died on import
        # surfaces 90 s later as "check the key and the network", which is a lie: there is
        # no key and no network in this mode.
        $stubReady = $false
        for ($i = 0; $i -lt 20; $i++) {
            if ($stub.HasExited) { throw "harness/stubs.py exited immediately (code $($stub.ExitCode)). Run it by hand to see why: $python harness\stubs.py --port $stubPort" }
            try { $c = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$stubPort/_calls" -TimeoutSec 2; if ($c.StatusCode -eq 200) { $stubReady = $true; break } } catch {}
            Start-Sleep -Milliseconds 500
        }
        if (-not $stubReady) { throw "harness/stubs.py is not answering on http://127.0.0.1:$stubPort/_calls after 10 s. Nothing else is wrong yet: start there." }
        Write-Host "  stubs ready (PID $($stub.Id))"

        $env:OPENROUTER_API_KEY = "stub"
        $env:OPENROUTER_BASE_URL = "http://127.0.0.1:$stubPort/v1"
        # Pinned, not inherited: the stubs are Brave-shaped, and a WEB_SEARCH_PROVIDER in
        # app\.env (perplexity is the example's default) would silently turn the console's
        # web fallback off - every uncovered question would show "none" with no hint why.
        $env:WEB_SEARCH_PROVIDER = "brave"
        $env:BRAVE_SEARCH_API_KEY = "stub"
        $env:WEB_SEARCH_BASE_URL = "http://127.0.0.1:$stubPort"
        $env:WIKI_RESOURCES_DIR = Join-Path $root "virtualagent\resources"
        Write-Host "Starting the service on :$ServicePort against the stubs, indexing $($env:WIKI_RESOURCES_DIR)..."
        Write-Host "  web fallback: WEB_SEARCH_PROVIDER=$($env:WEB_SEARCH_PROVIDER) against the stub on :$stubPort"
        Write-Host "  (answers are canned stub sentences; the source badge and the document named are real)"
        $svc = Start-Process -FilePath $uv -ArgumentList "--project", "backend", "run", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "$ServicePort" -WorkingDirectory (Join-Path $root "app") -PassThru -WindowStyle Minimized
        $children += $svc
    } else {
        $envFile = Join-Path $root "app\.env"
        if (-not (Test-Path $envFile)) { throw "app\.env is missing. Copy app\backend\.env.example to app\.env and paste your OPENROUTER_API_KEY, or run with -Stubs." }
        $key = (Get-Content $envFile | Where-Object { $_ -match '^OPENROUTER_API_KEY=(.+)$' } | Select-Object -First 1)
        if (-not $key) { throw "OPENROUTER_API_KEY is empty in app\.env. Paste your key after the '=' or run with -Stubs." }
        Write-Host "Starting the service on :$ServicePort against the REAL providers (app\.env)..."
        $svc = Start-Process -FilePath $uv -ArgumentList "--project", "backend", "run", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "$ServicePort" -WorkingDirectory (Join-Path $root "app") -PassThru -WindowStyle Minimized
        $children += $svc
    }

    Write-Host "Starting the console on :$ConsolePort..."
    $web = Start-Process -FilePath $python -ArgumentList "-m", "http.server", "$ConsolePort", "--directory", $console, "--bind", "127.0.0.1" -WorkingDirectory $root -PassThru -WindowStyle Minimized
    $children += $web

    $healthy = $false
    for ($i = 0; $i -lt 90; $i++) {
        if ($svc.HasExited) { throw "The service exited early (code $($svc.ExitCode)). Look at its window for the reason; a bad or missing key fails at startup on purpose." }
        if ($Stubs -and $stub.HasExited) { throw "harness/stubs.py died while the service was starting (code $($stub.ExitCode)); the service cannot reach a model." }
        try { $r = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$ServicePort/api/health" -TimeoutSec 2; if ($r.StatusCode -eq 200) { $healthy = $true; break } } catch {}
        Start-Sleep -Seconds 1
    }
    if (-not $healthy) {
        if ($Stubs) { throw "The service did not become healthy in 90 s against the stubs. Look at its window: the key and the network are not the problem in this mode." }
        throw "The service did not become healthy in 90 s. Indexing the wiki calls the embeddings API; check the key and the network."
    }

    Write-Host "Service: $($r.Content)"
    Write-Host "Console: http://localhost:$ConsolePort   (service PID $($svc.Id), console PID $($web.Id))"
    Start-Process "http://localhost:$ConsolePort"
} catch {
    # Nothing half-started is left behind for the next run to trip over.
    Write-Host "Startup failed; stopping what was started."
    Stop-Children
    throw
}
