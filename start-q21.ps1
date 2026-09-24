param([int]$Port = 5173)
$ErrorActionPreference = 'Stop'
$appPath = Join-Path $PSScriptRoot 'apps\web'
$nodeExecutable = (Get-Command node -ErrorAction SilentlyContinue).Source
if (-not $nodeExecutable) {
  throw 'Install Node.js 22.13 or newer before starting Q21.'
}
$cliPath = Join-Path $appPath 'node_modules\vinext\dist\cli.js'
if (-not (Test-Path -LiteralPath $cliPath)) {
  throw 'Dependencies are missing. Run npm run install:ci in apps/web first.'
}
Push-Location -LiteralPath $appPath
$integrationProcess = $null
try {
  if (-not (Get-NetTCPConnection -LocalPort 5174 -State Listen -ErrorAction SilentlyContinue)) {
    $gatewayScript = Join-Path $PSScriptRoot 'apps\gateway\server.mjs'
    $env:Q21_WEB_PORT = [string]$Port
    $integrationProcess = Start-Process -FilePath $nodeExecutable -ArgumentList @('"' + $gatewayScript + '"') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru
  }
  & $nodeExecutable $cliPath dev --port $Port
}
finally {
  if ($integrationProcess -and -not $integrationProcess.HasExited) { Stop-Process -Id $integrationProcess.Id -ErrorAction SilentlyContinue }
  Pop-Location
}
