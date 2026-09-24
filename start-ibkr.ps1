$ErrorActionPreference = 'Stop'
$gatewayPath = Join-Path $PSScriptRoot '.tools\ibkr-gateway'
$runtimePath = Join-Path $PSScriptRoot '.tools\java'
$javaExecutable = Get-ChildItem -LiteralPath $runtimePath -Directory -ErrorAction SilentlyContinue | ForEach-Object { Join-Path $_.FullName 'bin\java.exe' } | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $javaExecutable) { $javaExecutable = (Get-Command java -ErrorAction SilentlyContinue).Source }
if (-not $javaExecutable -or -not (Test-Path -LiteralPath (Join-Path $gatewayPath 'root\conf.yaml'))) { throw 'The local IBKR gateway or Java runtime is missing.' }
if (Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue) { Write-Host 'A service is already listening on port 5000. Use the existing IBKR gateway or stop it before starting another.'; return }
$gatewayArgs = @('-server','-Dvertx.disableDnsResolver=true','-Djava.net.preferIPv4Stack=true','-Dvertx.logger-delegate-factory-class-name=io.vertx.core.logging.SLF4JLogDelegateFactory','-classpath','root;dist\ibgroup.web.core.iblink.router.clientportal.gw.jar;build\lib\runtime\*','ibgroup.web.core.clientportal.gw.GatewayStart')
Write-Host 'Starting the local IBKR gateway. Complete your account login at https://localhost:5000.'
Push-Location -LiteralPath $gatewayPath
try { & $javaExecutable @gatewayArgs }
finally { Pop-Location }
