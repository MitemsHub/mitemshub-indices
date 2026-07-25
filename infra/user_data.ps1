# PowerShell user_data script for Windows Server 2022
# Runs on first boot to set up the trading system

$ErrorActionPreference = "Continue"
$logFile = "C:\UserData\setup.log"

function Log($msg) {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$timestamp - $msg" | Out-File -FilePath $logFile -Append
}

Log "=== Starting setup ==="

# ── 1. Install Chocolatey ──────────────────────────────────────
Log "Installing Chocolatey..."
Set-ExecutionPolicy Bypass -Scope Process -Force
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Invoke-Expression ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))

# Refresh PATH
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

# ── 2. Install Node.js 20 ─────────────────────────────────────
Log "Installing Node.js 20..."
choco install nodejs-lts -y --version 20.16.0

# Refresh PATH
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

Log "Node.js version: $(node --version)"
Log "npm version: $(npm --version)"

# ── 3. Install Python 3.10 ────────────────────────────────────
Log "Installing Python 3.10..."
choco install python -y --version 3.10.11

# Refresh PATH
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

Log "Python version: $(python --version)"

# ── 4. Install Git ─────────────────────────────────────────────
Log "Installing Git..."
choco install git -y

# Refresh PATH
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

Log "Git version: $(git --version)"

# ── 5. Install PM2 ────────────────────────────────────────────
Log "Installing PM2..."
npm install -g pm2

# ── 6. Create application directory ────────────────────────────
$appDir = "C:\SyntheticIndicesBot"
New-Item -ItemType Directory -Force -Path $appDir | Out-Null

# ── 7. Clone the repository ────────────────────────────────────
Log "Cloning repository..."
cd $appDir
git clone --branch ${github_branch} ${github_repo} .

# ── 8. Set up Python environment ──────────────────────────────
Log "Setting up Python environment..."
cd "$appDir"
python -m venv venv

# Use full python path (not activation — doesn't work in SYSTEM context)
$pip = "$appDir\venv\Scripts\pip.exe"
$python = "$appDir\venv\Scripts\python.exe"

& $pip install MetaTrader5 2>$null
Log "MetaTrader5 package installed"

# Install project dependencies if requirements.txt exists
if (Test-Path "$appDir\requirements.txt") {
    & $pip install -r "$appDir\requirements.txt"
    Log "requirements.txt installed"
}

# Install project in editable mode if setup.py/pyproject.toml exists
if (Test-Path "$appDir\setup.py" -or Test-Path "$appDir\pyproject.toml") {
    & $pip install -e "$appDir"
    Log "Project installed in editable mode"
}

# ── 9. Set up .env.local with MT5 credentials ─────────────────
Log "Configuring environment variables..."
$envLocal = @"
SYNTHETIC_ENGINE_ROOT=$appDir
SYNTHETIC_ENGINE_MAX_LIVE_TICKS=15
SYNTHETIC_PROP_STARTING_BALANCE=100000
SYNTHETIC_MT5_SERVER=${mt5_server}
SYNTHETIC_MT5_LOGIN=${mt5_login}
SYNTHETIC_MT5_PASSWORD=${mt5_password}
SYNTHETIC_MT5_TERMINAL_PATH=C:\Program Files\Blueberry Markets MetaTrader 5\terminal64.exe
"@
$envLocal | Out-File -FilePath "$appDir\external\mitemshub-indices\.env.local" -Encoding UTF8
Log "Environment configured"

# ── 10. Install Next.js dependencies ──────────────────────────
Log "Installing Next.js dependencies..."
cd "$appDir\external\mitemshub-indices"
npm install
Log "Dependencies installed"

# ── 11. Create PM2 ecosystem config ───────────────────────────
Log "Creating PM2 ecosystem config..."
$ecosystem = @"
module.exports = {
  apps: [
    {
      name: 'mitemshub-nextjs',
      cwd: '$($appDir -replace '\\', '\\')\\external\\mitemshub-indices',
      script: 'node_modules\\.bin\\next',
      args: 'start -p 3000',
      env: {
        NODE_ENV: 'production',
        PORT: 3000
      }
    }
  ]
};
"@
$ecosystem | Out-File -FilePath "$appDir\external\mitemshub-indices\ecosystem.config.js" -Encoding UTF8

# ── 12. Create startup script ─────────────────────────────────
Log "Creating startup script..."
$startupScript = @"
# Auto-start script for the trading system
# Runs on Windows boot

`$ErrorActionPreference = "Continue"
`$appDir = "$appDir"
`$logFile = "C:\SyntheticIndicesBot\startup.log"

function Log(`$msg) {
    `$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "`$timestamp - `$msg" | Out-File -FilePath `$logFile -Append
}

Log "=== Trading system starting ==="

# Start Next.js via PM2
cd "`$appDir\external\mitemshub-indices"
pm2 start ecosystem.config.js
pm2 save

Log "=== Trading system started ==="
"@
$startupScript | Out-File -FilePath "$appDir\start.ps1" -Encoding UTF8

# ── 13. Register as Windows scheduled task (auto-start on boot) ──
Log "Registering startup task..."
$action = New-ScheduledTaskAction -Execute "PowerShell.exe" -Argument "-ExecutionPolicy Bypass -File `$appDir\start.ps1"
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName "MitemsHubTradingSystem" -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force
Log "Startup task registered"

# ── 14. Configure Windows Firewall ─────────────────────────────
Log "Configuring Windows Firewall..."
New-NetFirewallRule -DisplayName "HTTP (Next.js)" -Direction Inbound -Protocol TCP -LocalPort 3000 -Action Allow -ErrorAction SilentlyContinue
New-NetFirewallRule -DisplayName "MT5 MCP (local)" -Direction Inbound -Protocol TCP -LocalPort 22346 -Action Allow -ErrorAction SilentlyContinue

# ── 15. Initial start ─────────────────────────────────────────
Log "Starting services..."
cd "$appDir\external\mitemshub-indices"
pm2 start ecosystem.config.js
pm2 save

Log "=== Setup complete ==="
Log "Next.js dashboard: http://localhost:3000"
Log "Public access: http://<ALB-DNS> or http://<PUBLIC-IP>:3000"
