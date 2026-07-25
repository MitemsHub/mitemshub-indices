$ErrorActionPreference = "Continue"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$appDir = $scriptDir
$pidFile = Join-Path $appDir ".data\launcher-app.pid"
$url = "http://localhost:3006"
$nodeDir = "C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node"
$npmCmd = Join-Path $nodeDir "npm.cmd"

# MT5 Terminal Configuration
$envFile = Join-Path $scriptDir ".env.local"
$mt5TerminalPath = $null
if (Test-Path $envFile) {
  $envContent = Get-Content $envFile -Raw
  if ($envContent -match 'SYNTHETIC_MT5_TERMINAL_PATH\s*=\s*(.+?)(\r?\n|$)') {
    $rawPath = $matches[1].Trim()
    $rawPath = $rawPath -replace '^["'']|["'']$', ''
    if ($rawPath -and (Test-Path $rawPath)) {
      $mt5TerminalPath = $rawPath
    }
  }
}
if (-not $mt5TerminalPath) {
  $mt5TerminalPath = "C:\Program Files\MetaTrader 5 Terminal\terminal64.exe"
}
Write-Host "MT5 terminal path: $mt5TerminalPath" -ForegroundColor Cyan
$mt5ProcessName = "terminal64"

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

function Start-MT5Terminal {
  param(
    [string]$TerminalPath,
    [string]$ProcessName
  )

  Write-Host "Checking MetaTrader 5 terminal..." -ForegroundColor Cyan

  # Check if MT5 terminal is already running
  $existingProcess = Get-Process -Name $ProcessName -ErrorAction SilentlyContinue
  if ($existingProcess) {
    Write-Host "MetaTrader 5 terminal is already running (PID: $($existingProcess.Id))" -ForegroundColor Green
    return $true
  }

  # Check if terminal executable exists
  if (-not (Test-Path $TerminalPath)) {
    Write-Host "MetaTrader 5 terminal not found at: $TerminalPath" -ForegroundColor Red
    Write-Host "Please install MetaTrader 5 or update SYNTHETIC_MT5_TERMINAL_PATH in .env.local" -ForegroundColor Yellow
    return $false
  }

  Write-Host "Starting MetaTrader 5 terminal..." -ForegroundColor Cyan
  try {
    $process = Start-Process -FilePath $TerminalPath -PassThru -WindowStyle Normal
    if (-not $process) {
      Write-Host "Failed to start MetaTrader 5 terminal" -ForegroundColor Red
      return $false
    }

    Write-Host "MetaTrader 5 terminal started (PID: $($process.Id))" -ForegroundColor Green
    Write-Host "Waiting for terminal to initialize..." -ForegroundColor Cyan

    # Wait for terminal to fully initialize (MT5 needs time to load)
    Start-Sleep -Seconds 10

    # Verify it's running
    $verifyProcess = Get-Process -Name $ProcessName -ErrorAction SilentlyContinue
    if ($verifyProcess) {
      Write-Host "MetaTrader 5 terminal is ready" -ForegroundColor Green
      return $true
    } else {
      Write-Host "MetaTrader 5 terminal may not have started properly" -ForegroundColor Yellow
      return $false
    }
  } catch {
    Write-Host "Error starting MetaTrader 5 terminal: $_" -ForegroundColor Red
    return $false
  }
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

  # Start MT5 Terminal first
  $mt5Started = Start-MT5Terminal -TerminalPath $mt5TerminalPath -ProcessName $mt5ProcessName
  if (-not $mt5Started) {
    Write-Host "Warning: MT5 terminal may not be ready. Continuing anyway..." -ForegroundColor Yellow
  }

  # Check if port 3006 is already serving — if it's our app, just open browser and exit cleanly
  if (Test-LauncherServerReady -TargetUrl $url) {
    Write-Host "MitemsHub Indices is already running at $url" -ForegroundColor Yellow
    Start-Process $url
    exit 0
  }

  $existingPid = if (Test-Path $pidFile) { Get-Content $pidFile -ErrorAction SilentlyContinue } else { $null }
  if ($existingPid) {
    try {
      $existingProcess = Get-Process -Id $existingPid -ErrorAction Stop
      if ($existingProcess -and -not $existingProcess.HasExited) {
        Stop-Process -Id $existingPid -Force -ErrorAction SilentlyContinue
        Write-Host "Stopped stale server process (PID: $existingPid)" -ForegroundColor Yellow
      }
    } catch {}
    Remove-Item $pidFile -ErrorAction SilentlyContinue
  }

  & $runner run build

  # Start the Next.js dev server (preferred for local development)
  $env:Path = "$nodeDir;$env:Path"
  $env:PORT = '3006'
  $serverProcess = Start-Process $runner -ArgumentList "run", "dev", "--", "--port", "3006" -WorkingDirectory $appDir -PassThru -WindowStyle Hidden

  $serverReady = $false
  $listeningProcessId = $null
  for ($attempt = 0; $attempt -lt 15; $attempt++) {
    Start-Sleep -Seconds 1

    if ($serverProcess.HasExited) {
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
    Write-Host "Check that 'npm run dev' can start without errors." -ForegroundColor Yellow
    exit 1
  }

  if (-not $listeningProcessId) {
    Write-Host "The local app became reachable, but the launcher could not identify its process." -ForegroundColor Red
    try {
      Stop-Process -Id $serverProcess.Id -Force -ErrorAction Stop
    } catch {}
    exit 1
  }

  Set-Content -Path $pidFile -Value $listeningProcessId

  Start-Process $url
  Write-Host "MitemsHub Indices started at $url" -ForegroundColor Green
} finally {
  Pop-Location
}