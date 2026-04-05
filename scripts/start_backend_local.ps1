Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$pythonExe = Join-Path $repoRoot 'venv\Scripts\python.exe'

if (-not (Test-Path $pythonExe)) {
    throw "Python venv not found at $pythonExe"
}

Set-Location $repoRoot
& $pythonExe -m uvicorn main:app --host 127.0.0.1 --port 8000
