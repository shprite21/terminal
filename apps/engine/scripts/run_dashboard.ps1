# Start only the frontend. Run the Python API in a separate terminal.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$dashboardRoot = Join-Path $projectRoot 'apps\portfolio_dashboard'
$runtimeRoot = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies'
$previousPath = $env:Path

try {
    if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
        $nodeDirectory = Join-Path $runtimeRoot 'node\bin'
        if (-not (Test-Path -LiteralPath (Join-Path $nodeDirectory 'node.exe'))) {
            throw 'Install Node.js 22.13+ and pnpm, then retry.'
        }
        $env:Path = $nodeDirectory + ';' + $env:Path
    }
    $pnpmCommand = Get-Command pnpm.cmd -ErrorAction SilentlyContinue
    if ($pnpmCommand) {
        $pnpmPath = $pnpmCommand.Source
    } else {
        $pnpmPath = Join-Path $runtimeRoot 'bin\fallback\pnpm.cmd'
        if (-not (Test-Path -LiteralPath $pnpmPath)) {
            throw 'Install pnpm, run pnpm install in apps\portfolio_dashboard, then retry.'
        }
    }
    Push-Location $dashboardRoot
    try {
        & $pnpmPath run dev
        if ($LASTEXITCODE -ne 0) { throw "Dashboard exited with code $LASTEXITCODE." }
    } finally { Pop-Location }
} finally { $env:Path = $previousPath }
