$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$appDir = $scriptDir
$pidFile = Join-Path $appDir ".data\launcher-app.pid"
$url = "http://localhost:3006"
$nodeDir = "C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node"
$npmCmd = Join-Path $nodeDir "npm.cmd"

function Get-NpmRunner {
  if (Test-Path $npmCmd) {
    $env:Path = "$nodeDir;$env:Path"
    return $npmCmd
  }

  if (Get-Command npm -ErrorAction SilentlyContinue) {
    return "npm"
  }

  return $null
}

function Test-LauncherServerReady {
  param(
    [string]$TargetUrl
  )

  try {
    $null = Invoke-WebRequest -Uri $TargetUrl -UseBasicParsing -TimeoutSec 2
    return $true
  } catch {
    return $false
  }
}

function Get-ListeningProcessId {
  param(
    [int]$Port
  )

  try {
    $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop
    $processIds = $connections | Select-Object -ExpandProperty OwningProcess -Unique
    if ($processIds.Count -eq 1) {
      return [int]$processIds[0]
    }
  } catch {}

  return $null
}

if (-not (Test-Path (Join-Path $appDir ".env.local"))) {
  Write-Host "Missing .env.local. Copy .env.example to .env.local and fill in your local settings first." -ForegroundColor Red
  exit 1
}

$runner = Get-NpmRunner
if (-not $runner) {
  Write-Host "Node runtime not found. Install Node or restore the bundled Node toolchain path." -ForegroundColor Red
  exit 1
}

New-Item -ItemType Directory -Force -Path (Join-Path $appDir ".data") | Out-Null

Push-Location $appDir
try {
  if (-not (Test-Path (Join-Path $appDir "node_modules"))) {
    & $runner install
  }

  $existingPid = if (Test-Path $pidFile) { Get-Content $pidFile -ErrorAction SilentlyContinue } else { $null }
  if ($existingPid) {
    try {
      $existingProcess = Get-Process -Id $existingPid -ErrorAction Stop
      if ($existingProcess -and -not $existingProcess.HasExited -and (Test-LauncherServerReady -TargetUrl $url)) {
        Write-Host "MitemsHub Indices is already running at $url" -ForegroundColor Yellow
        Start-Process $url
        exit 0
      }
    } catch {}

    Remove-Item $pidFile -ErrorAction SilentlyContinue
  }

  if (Test-LauncherServerReady -TargetUrl $url) {
    Write-Host "Port 3006 is already serving an app that this launcher did not start." -ForegroundColor Red
    Write-Host "Stop that existing server first, then run the launcher again." -ForegroundColor Red
    exit 1
  }

  & $runner run build

  $startCommand = @"
Set-Location '$appDir'
`$env:Path = '$nodeDir;' + `$env:Path
& '$runner' run start -- --port 3006
"@

  $process = Start-Process powershell -ArgumentList @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-Command", $startCommand
  ) -WorkingDirectory $appDir -PassThru

  $serverReady = $false
  $listeningProcessId = $null
  for ($attempt = 0; $attempt -lt 15; $attempt++) {
    Start-Sleep -Seconds 1

    if ($process.HasExited) {
      break
    }

    if (Test-LauncherServerReady -TargetUrl $url) {
      $serverReady = $true
      $listeningProcessId = Get-ListeningProcessId -Port 3006
      break
    }
  }

  if (-not $serverReady) {
    Write-Host "The local app did not become ready at $url." -ForegroundColor Red
    exit 1
  }

  if (-not $listeningProcessId) {
    Write-Host "The local app became reachable, but the launcher could not identify its process." -ForegroundColor Red
    try {
      Stop-Process -Id $process.Id -Force -ErrorAction Stop
    } catch {}
    exit 1
  }

  Set-Content -Path $pidFile -Value $listeningProcessId

  Start-Process $url
  Write-Host "MitemsHub Indices started at $url" -ForegroundColor Green
} finally {
  Pop-Location
}
