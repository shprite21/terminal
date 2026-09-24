param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$engine = Join-Path $PSScriptRoot 'apps\engine'
$runtime = Join-Path $engine '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $runtime)) {
    & $Python -c "import sys; assert sys.version_info >= (3,12), 'Python 3.12 or newer is required'"
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 or newer is required.' }
    & $Python -m venv (Join-Path $engine '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 or newer is required.' }
}
& $runtime -c "import sys; assert sys.version_info >= (3,12), 'Python 3.12 or newer is required'"
if ($LASTEXITCODE -ne 0) { throw 'Q requires a Python 3.12 or newer environment.' }
& $runtime -m pip install -r (Join-Path $engine 'requirements.lock.txt')
if ($LASTEXITCODE -ne 0) { throw 'Research dependency setup failed.' }
& $runtime -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Research dependency validation failed.' }
Write-Output 'Q research engine is ready. Start Q with start-q21.ps1.'
