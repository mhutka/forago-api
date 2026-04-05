Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$pythonExe = Join-Path $repoRoot 'venv\Scripts\python.exe'

if (-not (Test-Path $pythonExe)) {
    throw "Python venv not found at $pythonExe"
}

Set-Location $repoRoot

Write-Host '1) Running backend tests...' -ForegroundColor Cyan
& $pythonExe -m pytest -q

Write-Host '2) Starting temporary backend instance for health check...' -ForegroundColor Cyan
$job = Start-Process -FilePath $pythonExe -ArgumentList '-m','uvicorn','main:app','--host','127.0.0.1','--port','8010' -PassThru -WindowStyle Hidden

try {
    $maxAttempts = 20
    $healthy = $false

    for ($i = 0; $i -lt $maxAttempts; $i++) {
        Start-Sleep -Milliseconds 500
        try {
            $response = Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8010/api/health' -TimeoutSec 2
            if ($response.StatusCode -eq 200) {
                $healthy = $true
                break
            }
        } catch {
            # Keep polling until timeout.
        }
    }

    if (-not $healthy) {
        throw 'Health check did not pass within timeout.'
    }

    Write-Host '3) Health check OK.' -ForegroundColor Green
    Write-Host 'Backend predeploy check passed.' -ForegroundColor Green
}
finally {
    if ($job -and -not $job.HasExited) {
        Stop-Process -Id $job.Id -Force
    }
}
