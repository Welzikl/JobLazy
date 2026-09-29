param([ValidateRange(1,65535)][int]$Port = 8765, [switch]$NoOpen)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
try {
    $venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $venvPython)) { throw 'Run Setup.cmd first.' }
    $preflightJson = & $venvPython (Join-Path $PSScriptRoot 'preflight.py') --json
    if ($LASTEXITCODE -ne 0) { Write-Host ($preflightJson -join "`n"); throw 'Fix the missing prerequisites before launching.' }
    $preflight = ($preflightJson -join "`n") | ConvertFrom-Json
    foreach ($warning in $preflight.warnings) { Write-Host $warning }
    Write-Host 'Opening JobLazy with Luna only. Keep this window open while using the app.'
    $launchArguments = @('-m','joblazy','dashboard','--preset','friend','--browser-channel',$preflight.browser,'--port',"$Port")
    if ($NoOpen) { $launchArguments += '--no-open' }
    & $venvPython @launchArguments
    if ($LASTEXITCODE -ne 0) { throw 'JobLazy could not start or stopped unexpectedly. If port 8765 is occupied, close the other JobLazy window and retry.' }
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
