$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$runtimePython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'

if (Test-Path -LiteralPath $runtimePython) {
    $python = $runtimePython
} else {
    $pythonCommand = Get-Command py, python -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $pythonCommand) {
        throw 'Python was not found. Install Python 3.10 or newer, then run this script again.'
    }
    $python = $pythonCommand.Source
}

$listener = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    Write-Host 'The Delta dashboard is already running at http://127.0.0.1:8765'
    exit 0
}

Set-Location -LiteralPath $projectRoot
Write-Host 'Starting the Delta dashboard at http://127.0.0.1:8765'
Write-Host 'Keep this PowerShell window open. Press Ctrl+C to stop the server.'
& $python -u (Join-Path $projectRoot 'server.py')
