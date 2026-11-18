# Start Chirayu Power Outreach and open the dashboard, already unlocked.
# Safe to run any time: it only starts what isn't already running.
#   - the dashboard (http://127.0.0.1:5555)
#   - the main loop (sellbird run), which finds prospects, writes and sends
# The unlock token is read from data/dashboard-token at run time; it is never
# stored in this script.

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$exe = Join-Path $root '.venv\Scripts\sellbird.exe'
if (-not (Test-Path $exe)) { Write-Host "Can't find $exe. Run 'pip install -e .' in the project's .venv first."; Read-Host 'Press Enter to close'; exit 1 }

# The loop needs the Claude CLI on PATH.
$env:Path = "$env:USERPROFILE\.local\bin;" + $env:Path
$env:PYTHONIOENCODING = 'utf-8'

function Test-Dashboard {
    try { (Invoke-WebRequest 'http://127.0.0.1:5555/' -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200 } catch { $false }
}

# 1. Dashboard
if (Test-Dashboard) {
    Write-Host 'Dashboard already running.'
} else {
    Write-Host 'Starting the dashboard...'
    Start-Process -FilePath $exe -ArgumentList 'dashboard' -WorkingDirectory $root -WindowStyle Minimized
    for ($i = 0; $i -lt 30 -and -not (Test-Dashboard); $i++) { Start-Sleep -Milliseconds 500 }
    if (-not (Test-Dashboard)) { Write-Host 'The dashboard did not start. Run ".venv\Scripts\sellbird.exe dashboard" to see why.'; Read-Host 'Press Enter to close'; exit 1 }
}

# 2. Main loop
$loopRunning = $false
$pidFile = Join-Path $root 'data\sellbird.pid'
if (Test-Path $pidFile) {
    $loopPid = 0
    if ([int]::TryParse((Get-Content $pidFile -Raw).Trim(), [ref]$loopPid)) {
        $p = Get-Process -Id $loopPid -ErrorAction SilentlyContinue
        $loopRunning = [bool]($p -and $p.ProcessName -match 'python|sellbird')
    }
}
if ($loopRunning) {
    Write-Host 'Main loop already running.'
} else {
    Write-Host 'Starting the main loop...'
    Start-Process -FilePath $exe -ArgumentList 'run' -WorkingDirectory $root -WindowStyle Minimized
}

# 3. Open the dashboard, unlocked
$token = (Get-Content (Join-Path $root 'data\dashboard-token') -Raw).Trim()
Start-Process "http://127.0.0.1:5555/#token=$token"
Write-Host 'Dashboard opened in your browser.'
Start-Sleep -Seconds 2
