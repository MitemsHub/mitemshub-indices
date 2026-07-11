# One-Click Local Launcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a one-click Windows launcher that starts the verified local `mitemshub-indices` app in production-style mode, opens the browser automatically, and provides a safe stop script.

**Architecture:** Use a PowerShell launcher for the real startup logic, a `.bat` file as the double-click entry point, and a second PowerShell stop script that only stops the launcher-started app process via a tracked PID file. Keep the app logic unchanged by only automating the same local build-and-start commands already verified in this workspace.

**Tech Stack:** Windows PowerShell, batch scripting, Next.js 15, npm, existing local `.env.local` workflow

---

## File Structure

All paths below are relative to:

- `c:\Users\USER\Desktop\Projects\Synthetic Indices Bot\external\mitemshub-indices`

Primary files:

- `launch-mitemshub-indices.ps1`
  - Main startup logic for one-click local launch.
- `launch-mitemshub-indices.bat`
  - Double-click Windows entry point that invokes the PowerShell launcher.
- `stop-mitemshub-indices.ps1`
  - Stops only the launcher-started local app process.
- `README.md`
  - Add short daily-use instructions for one-click start/stop.

### Task 1: Add The Launcher Scripts

**Files:**
- Create: `launch-mitemshub-indices.ps1`
- Create: `launch-mitemshub-indices.bat`
- Create: `stop-mitemshub-indices.ps1`

- [ ] **Step 1: Create the PowerShell launcher**

```powershell
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$appDir = $scriptDir
$pidFile = Join-Path $appDir ".data\launcher-app.pid"
$url = "http://localhost:3006"
$nodeDir = "C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node"
$npmCmd = Join-Path $nodeDir "npm.cmd"

if (-not (Test-Path (Join-Path $appDir ".env.local"))) {
  Write-Host "Missing .env.local. Copy .env.example to .env.local and fill in your local settings first." -ForegroundColor Red
  Read-Host "Press Enter to exit"
  exit 1
}

if (Test-Path $nodeDir) {
  $env:Path = "$nodeDir;$env:Path"
}

if (-not (Get-Command npm -ErrorAction SilentlyContinue) -and -not (Test-Path $npmCmd)) {
  Write-Host "Node runtime not found. Install Node or restore the bundled Node toolchain path." -ForegroundColor Red
  Read-Host "Press Enter to exit"
  exit 1
}

$runner = if (Test-Path $npmCmd) { $npmCmd } else { "npm" }

New-Item -ItemType Directory -Force -Path (Join-Path $appDir ".data") | Out-Null

Push-Location $appDir
try {
  if (-not (Test-Path (Join-Path $appDir "node_modules"))) {
    & $runner install
  }

  & $runner run build

  $existingPid = if (Test-Path $pidFile) { Get-Content $pidFile -ErrorAction SilentlyContinue } else { $null }
  if ($existingPid) {
    try {
      $existingProcess = Get-Process -Id $existingPid -ErrorAction Stop
      if ($existingProcess) {
        Write-Host "App is already running at $url" -ForegroundColor Yellow
        Start-Process $url
        exit 0
      }
    } catch {}
  }

  $process = Start-Process powershell -ArgumentList @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-Command",
    "Set-Location '$appDir'; `$env:Path = '$nodeDir;' + `$env:Path; & '$runner' run start -- --port 3006"
  ) -WorkingDirectory $appDir -PassThru

  Set-Content -Path $pidFile -Value $process.Id
  Start-Sleep -Seconds 4
  Start-Process $url
  Write-Host "MitemsHub Indices started at $url" -ForegroundColor Green
} finally {
  Pop-Location
}
```

- [ ] **Step 2: Create the batch double-click entry point**

```bat
@echo off
set SCRIPT_DIR=%~dp0
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%launch-mitemshub-indices.ps1"
```

- [ ] **Step 3: Create the stop script**

```powershell
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $scriptDir ".data\launcher-app.pid"

if (-not (Test-Path $pidFile)) {
  Write-Host "No launcher-started app process is currently recorded." -ForegroundColor Yellow
  Read-Host "Press Enter to exit"
  exit 0
}

$pid = Get-Content $pidFile -ErrorAction SilentlyContinue

if (-not $pid) {
  Remove-Item $pidFile -ErrorAction SilentlyContinue
  Write-Host "No launcher-started app process is currently recorded." -ForegroundColor Yellow
  Read-Host "Press Enter to exit"
  exit 0
}

try {
  Stop-Process -Id $pid -Force -ErrorAction Stop
  Write-Host "MitemsHub Indices stopped." -ForegroundColor Green
} catch {
  Write-Host "The recorded app process is no longer running." -ForegroundColor Yellow
}

Remove-Item $pidFile -ErrorAction SilentlyContinue
Read-Host "Press Enter to exit"
```

- [ ] **Step 4: Verify the files exist**

Run:

```powershell
Get-Item .\launch-mitemshub-indices.ps1, .\launch-mitemshub-indices.bat, .\stop-mitemshub-indices.ps1
```

Expected: all three files exist

### Task 2: Document The One-Click Workflow

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a daily-use launcher section**

```md
## One-click local startup

After the first-time setup is complete, you can start the app with:

- `launch-mitemshub-indices.bat`

This launcher:

- checks that `.env.local` exists
- installs dependencies only if needed
- builds the app
- starts the local server on `http://localhost:3006`
- opens the browser automatically

To stop the locally launched app, run:

- `stop-mitemshub-indices.ps1`
```

- [ ] **Step 2: Verify the README change renders cleanly**

Run:

```powershell
Get-Content .\README.md
```

Expected: the new one-click startup section appears clearly

### Task 3: Run The Launcher End-To-End

**Files:**
- Modify: `launch-mitemshub-indices.ps1`
- Modify: `launch-mitemshub-indices.bat`
- Modify: `stop-mitemshub-indices.ps1`
- Modify: `README.md`

- [ ] **Step 1: Stop any existing local server before launcher verification**

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\stop-mitemshub-indices.ps1
```

Expected: either stops the tracked app or reports none is recorded

- [ ] **Step 2: Run the launcher script directly**

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\launch-mitemshub-indices.ps1
```

Expected:

- builds successfully
- starts the app on `http://localhost:3006`
- opens the browser
- writes a PID file to `.data\launcher-app.pid`

- [ ] **Step 3: Verify the app responds**

Run:

```powershell
Invoke-WebRequest http://localhost:3006 | Select-Object -ExpandProperty StatusCode
```

Expected: `200`

- [ ] **Step 4: Run the stop script and verify shutdown**

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\stop-mitemshub-indices.ps1
```

Expected: stops the launcher-started app and removes the PID file

- [ ] **Step 5: Verify shutdown**

Run:

```powershell
Test-Path .\.data\launcher-app.pid
```

Expected: `False`

### Task 4: Final Verification And Commit

**Files:**
- Modify: `launch-mitemshub-indices.ps1`
- Modify: `launch-mitemshub-indices.bat`
- Modify: `stop-mitemshub-indices.ps1`
- Modify: `README.md`

- [ ] **Step 1: Run the app test suite to confirm the launcher did not disturb the app**

Run:

```powershell
$env:PATH='C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:PATH
& 'C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' run test
```

Expected: PASS

- [ ] **Step 2: Run a production build one final time**

Run:

```powershell
$env:PATH='C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node;' + $env:PATH
& 'C:\Users\USER\AppData\Roaming\TRAE SOLO\ModularData\ai-agent\vm\tools\node\npm.cmd' run build
```

Expected: PASS

- [ ] **Step 3: Commit the launcher work**

```powershell
git add launch-mitemshub-indices.ps1 launch-mitemshub-indices.bat stop-mitemshub-indices.ps1 README.md
git commit -m "feat: add one-click local launcher"
```
