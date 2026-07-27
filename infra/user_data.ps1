<powershell>
# ─── MitemsHub Trading Server Bootstrap Script ───────────────────────
# This script runs on first boot to set up the complete trading environment.

$ErrorActionPreference = "Continue"
$logFile = "C:\deploy\setup.log"

function Write-Log {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$timestamp - $Message" | Out-File -FilePath $logFile -Append
}

Write-Log "=== Starting MitemsHub Trading Server Setup ==="

# ─── 1. Create deployment directory ─────────────────────────────────
Write-Log "Creating deployment directory..."
New-Item -ItemType Directory -Path "C:\deploy" -Force | Out-Null

# ─── 2. Install Chocolatey (package manager) ───────────────────────
Write-Log "Installing Chocolatey..."
if (-not (Get-Command choco -ErrorAction SilentlyContinue)) {
    Set-ExecutionPolicy Bypass -Scope Process -Force
    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
    Invoke-Expression ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
}

# ─── 3. Install Node.js 20 ─────────────────────────────────────────
Write-Log "Installing Node.js 20..."
choco install nodejs-lts -y --version="20.18.0"
$env:PATH = "$env:PATH;C:\Program Files\nodejs"

# ─── 4. Install Python 3.12 ────────────────────────────────────────
Write-Log "Installing Python 3.12..."
choco install python -y --version="3.12.4"
$env:PATH = "$env:PATH;C:\Python312;C:\Python312\Scripts"

# ─── 5. Install Git ────────────────────────────────────────────────
Write-Log "Installing Git..."
choco install git -y
$env:PATH = "$env:PATH;C:\Program Files\Git\cmd"

# ─── 6. Install PM2 (process manager for Node.js) ──────────────────
Write-Log "Installing PM2..."
npm install -g pm2 pm2-windows-startup

# ─── 7. Clone the repository ────────────────────────────────────────
Write-Log "Cloning repository..."
if (-not (Test-Path "C:\app")) {
    git clone ${github_repo_url} C:\app
} else {
    Write-Log "Repository already exists, pulling latest..."
    cd C:\app
    git pull
}

# ─── 8. Install Python dependencies ─────────────────────────────────
Write-Log "Installing Python dependencies..."
cd C:\app
pip install -r requirements.txt

# ─── 9. Install Node.js dependencies and build ─────────────────────
Write-Log "Installing Node.js dependencies..."
cd C:\app\external\mitemshub-indices
npm install

Write-Log "Building Next.js app..."
npm run build

# ─── 10. Create .env.local for production ───────────────────────────
Write-Log "Creating production .env.local..."
$envContent = @"
SYNTHETIC_ENGINE_ROOT=C:\app
SYNTHETIC_ENGINE_MAX_LIVE_TICKS=15
SYNTHETIC_PROP_STARTING_BALANCE=100000
SYNTHETIC_MT5_SERVER=BlueberryMarketsSVG-Live
SYNTHETIC_MT5_LOGIN=5098680
SYNTHETIC_MT5_PASSWORD=REPLACE_WITH_YOUR_PASSWORD
"@
$envContent | Out-File -FilePath "C:\app\external\mitemshub-indices\.env.local" -Encoding UTF8

# ─── 11. Start the app with PM2 ────────────────────────────────────
Write-Log "Starting Next.js app with PM2..."
cd C:\app\external\mitemshub-indices
pm2 start npm --name "mitemshub" -- start
pm2 save
# On Windows, use PM2's built-in startup support
pm2-startup win

Write-Log "=== Setup Complete! ==="
Write-Log "Dashboard will be available at: http://localhost:3000"
Write-Log "After Cloudflare setup, access at: https://mitemshub-indices.com"
