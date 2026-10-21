param([string]$PythonExecutable, [switch]$AgentMode)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
try {
    $pythonArguments = @()
    if (-not $PythonExecutable) {
        $pythonLauncher = Get-Command py -ErrorAction SilentlyContinue
        $pythonDirect = Get-Command python -ErrorAction SilentlyContinue
        if ($pythonLauncher) { $PythonExecutable = $pythonLauncher.Source; $pythonArguments = @('-3') }
        elseif ($pythonDirect) { $PythonExecutable = $pythonDirect.Source }
        else { throw 'Install Python 3.12 or later from python.org, including the Python launcher, then run Setup.cmd again.' }
    }
    & $PythonExecutable @pythonArguments -c "import sys; raise SystemExit(0 if sys.version_info >= (3,12) else 1)"
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 or later is required.' }
    $venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $venvPython)) {
        & $PythonExecutable @pythonArguments -m venv (Join-Path $projectRoot '.venv')
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the local Python environment. Extract the ZIP to a writable folder and retry.' }
    }
    & $venvPython -m pip --isolated install --disable-pip-version-check --no-input -r (Join-Path $projectRoot 'requirements.lock.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check your internet connection, then run Setup.cmd again.' }
    $preflightArguments = @((Join-Path $PSScriptRoot 'preflight.py'))
    if ($AgentMode) { $preflightArguments += '--agent' }
    & $venvPython @preflightArguments
    if ($LASTEXITCODE -ne 0) { throw 'Complete the missing prerequisites listed above, then run Setup.cmd again.' }
    if ($AgentMode) { Write-Host 'Ready. Continue in your Codex or Claude Code chat with the JobLazy skill.' }
    else { Write-Host 'Ready. Start JobLazy.cmd always selects the Luna-only friend preset.' }
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
