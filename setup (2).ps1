# ==============================================================================
# setup.ps1  -  Email Compliance AI Agent  |  Windows 11 Setup Script
# ==============================================================================
# What this script does:
#   1. Validates Python 3.10+
#   2. Creates & activates a virtual environment
#   3. Installs all Python dependencies
#   4. Prompts the user for Azure OpenAI credentials interactively
#   5. Prompts the user to choose the default log mode (INFO or DEBUG)
#   6. Writes a .env file with all settings including LOG_LEVEL
#   7. Creates all required application folders
#   8. Prints a usage summary
# ==============================================================================

$Banner = @"

  +----------------------------------------------------------+
  |        Email Compliance AI Agent  -  Setup               |
  |        Windows 11  |  Azure OpenAI  |  LangChain         |
  +----------------------------------------------------------+

"@
Write-Host $Banner -ForegroundColor Cyan

# -- Helper: section header ----------------------------------------------------
function Write-Step([int]$n, [int]$total, [string]$msg) {
    Write-Host ""
    Write-Host "  [$n/$total] $msg" -ForegroundColor Yellow
}

# -- Helper: status indicators -------------------------------------------------
function Write-OK([string]$msg)   { Write-Host "        [OK]  $msg" -ForegroundColor Green   }
function Write-ERR([string]$msg)  { Write-Host "        [ERR] $msg" -ForegroundColor Red     }
function Write-NOTE([string]$msg) { Write-Host "        [i]   $msg" -ForegroundColor Magenta }

$TOTAL_STEPS = 7

# ==============================================================================
# STEP 1 - Python check
# ==============================================================================
Write-Step 1 $TOTAL_STEPS "Checking Python installation ..."

# ── Strategy 1: find the full resolved path for python / python3 ────────────
# Get-Command returns a CommandInfo object; .Source gives the full .exe path.
# Using the full path avoids any shell-alias or PATH-ordering issues that occur
# when PowerShell is launched by an IDE like PyCharm.
$pythonExe = $null
foreach ($candidate in @("python", "python3", "py")) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($cmd) {
        $pythonExe = $cmd.Source   # e.g. C:\Python314\python.exe
        break
    }
}

# ── Strategy 2: search common installation directories if strategy 1 failed ─
if (-not $pythonExe) {
    $commonPaths = @(
        "$env:LOCALAPPDATA\Programs\Python",
        "C:\Python*",
        "C:\Program Files\Python*",
        "C:\Program Files (x86)\Python*",
        "$env:USERPROFILE\AppData\Local\Programs\Python\Python*"
    )
    foreach ($pattern in $commonPaths) {
        $hits = Get-Item $pattern -ErrorAction SilentlyContinue |
                Sort-Object Name -Descending
        foreach ($dir in $hits) {
            $candidate = Join-Path $dir.FullName "python.exe"
            if (Test-Path $candidate) {
                $pythonExe = $candidate
                break
            }
        }
        if ($pythonExe) { break }
    }
}

if (-not $pythonExe) {
    Write-ERR "Python not found. Install Python 3.10+ from https://python.org and re-run."
    Write-ERR "If Python is installed in a non-standard location, add it to your PATH."
    exit 1
}

Write-Host "        Using Python executable: $pythonExe" -ForegroundColor DarkGray

# ── Version detection: avoid f-strings (PowerShell corrupts {} before Python sees them)
# Write version to a temp file so stdout capture issues cannot produce empty strings.
$tmpVer = [System.IO.Path]::GetTempFileName()
try {
    $verScript = "import sys; open(r'" + $tmpVer + "', 'w').write(str(sys.version_info.major) + '.' + str(sys.version_info.minor))"
    & $pythonExe -c $verScript 2>$null
    $pyVerRaw = (Get-Content $tmpVer -Raw -ErrorAction SilentlyContinue).Trim()
} finally {
    Remove-Item $tmpVer -ErrorAction SilentlyContinue
}

# ── Fallback: try reading from python --version output directly ─────────────
if ([string]::IsNullOrWhiteSpace($pyVerRaw) -or -not $pyVerRaw.Contains('.')) {
    # "python --version" outputs to stderr on Python 2, stdout on Python 3
    $verOutput = (& $pythonExe --version 2>&1)
    # Output looks like: "Python 3.14.0"
    if ($verOutput -match 'Python\s+(\d+)\.(\d+)') {
        $pyVerRaw = "$($Matches[1]).$($Matches[2])"
    }
}

# ── Final guard ──────────────────────────────────────────────────────────────
if ([string]::IsNullOrWhiteSpace($pyVerRaw) -or -not $pyVerRaw.Contains('.')) {
    Write-ERR "Could not determine Python version from: $pythonExe"
    Write-ERR "Try running manually:  & '$pythonExe' --version"
    exit 1
}

$pyMajor = [int]($pyVerRaw.Split('.')[0])
$pyMinor = [int]($pyVerRaw.Split('.')[1])

if ($pyMajor -lt 3 -or ($pyMajor -eq 3 -and $pyMinor -lt 10)) {
    Write-ERR "Python $pyVerRaw found but 3.10+ is required. Please upgrade Python."
    exit 1
}
Write-OK "Python $pyVerRaw detected at: $pythonExe"

# ==============================================================================
# STEP 2 - Virtual environment
# ==============================================================================
Write-Step 2 $TOTAL_STEPS "Setting up virtual environment ..."

if (-Not (Test-Path "venv")) {
    & $pythonExe -m venv venv | Out-Null
    Write-OK "Virtual environment created."
} else {
    Write-OK "Virtual environment already exists - skipping creation."
}

# Activate virtual environment
$activateScript = Join-Path $PSScriptRoot "venv\Scripts\Activate.ps1"
if (Test-Path $activateScript) {
    & $activateScript
    Write-OK "Virtual environment activated."
} else {
    Write-ERR "Could not find venv activation script at: $activateScript"
    exit 1
}

# ==============================================================================
# STEP 3 - Install Python dependencies
# ==============================================================================
Write-Step 3 $TOTAL_STEPS "Installing Python dependencies ..."

pip install --upgrade pip --quiet

$packages = @(
    "openai==1.30.1",
    "langchain==0.2.5",
    "langchain-openai==0.1.13",
    "langchain-community==0.2.5",
    "langchain-core==0.2.9",
    "python-dotenv==1.0.1",
    "pydantic==2.7.4",
    "PyMuPDF==1.24.5",
    "openpyxl==3.1.4",
    "pandas==2.2.2",
    "flask==3.0.3",
    "flask-cors==4.0.1",
    "PyYAML==6.0.1",
    "tiktoken==0.7.0",
    "colorlog==6.8.2",
    "reportlab==4.2.2"
)

foreach ($pkg in $packages) {
    pip install $pkg --quiet
    if ($LASTEXITCODE -ne 0) {
        Write-ERR "Failed to install $pkg"
        exit 1
    }
}
Write-OK "All $($packages.Count) packages installed successfully."

# ==============================================================================
# STEP 4 - Azure OpenAI credentials (interactive)
# ==============================================================================
Write-Step 4 $TOTAL_STEPS "Configuring Azure OpenAI connection ..."
Write-Host ""
Write-Host "        Enter your Azure OpenAI credentials." -ForegroundColor White
Write-Host "        (Press ENTER to keep the placeholder and edit .env later)" -ForegroundColor DarkGray
Write-Host ""

$defaultEndpoint   = "https://<YOUR_RESOURCE>.openai.azure.com/"
$defaultApiKey     = "<YOUR_API_KEY>"
$defaultApiVersion = "2024-02-15-preview"
$defaultDeployment = "gpt-4o"

$inputEndpoint = Read-Host "        Azure OpenAI Endpoint   [$defaultEndpoint]"
if ([string]::IsNullOrWhiteSpace($inputEndpoint)) { $inputEndpoint = $defaultEndpoint }

$inputApiKey = Read-Host "        Azure OpenAI API Key    [$defaultApiKey]"
if ([string]::IsNullOrWhiteSpace($inputApiKey)) { $inputApiKey = $defaultApiKey }

$inputApiVersion = Read-Host "        API Version            [$defaultApiVersion]"
if ([string]::IsNullOrWhiteSpace($inputApiVersion)) { $inputApiVersion = $defaultApiVersion }

$inputDeployment = Read-Host "        Deployment Name        [$defaultDeployment]"
if ([string]::IsNullOrWhiteSpace($inputDeployment)) { $inputDeployment = $defaultDeployment }

Write-OK "Azure OpenAI credentials captured."

# ==============================================================================
# STEP 5 - Log mode selection (interactive)
# ==============================================================================
Write-Step 5 $TOTAL_STEPS "Selecting default log mode ..."
Write-Host ""
Write-Host "        Choose the default logging level for main.py:" -ForegroundColor White
Write-Host ""
Write-Host "          [1]  INFO   - Human-readable summary (recommended for production)" -ForegroundColor Green
Write-Host "          [2]  DEBUG  - Full trace including raw AI responses (for dev/testing)" -ForegroundColor Cyan
Write-Host ""

$logChoice = ""
$LOG_LEVEL = "INFO"
while ($logChoice -notin @("1", "2")) {
    $logChoice = Read-Host "        Enter choice [1 or 2]"
    if ($logChoice -eq "1") {
        $LOG_LEVEL = "INFO"
        Write-OK "Log mode set to INFO."
    } elseif ($logChoice -eq "2") {
        $LOG_LEVEL = "DEBUG"
        Write-OK "Log mode set to DEBUG."
    } else {
        Write-Host "        Please enter 1 or 2." -ForegroundColor Red
        $logChoice = ""
    }
}

# ==============================================================================
# STEP 6 - Write .env file
# ==============================================================================
Write-Step 6 $TOTAL_STEPS "Writing .env configuration file ..."

# Build .env content using a here-string
# Note: variables inside @"..."@ are expanded by PowerShell
$envContent = @"
# Azure OpenAI
AZURE_OPENAI_ENDPOINT=$inputEndpoint
AZURE_OPENAI_API_KEY=$inputApiKey
AZURE_OPENAI_API_VERSION=$inputApiVersion
AZURE_OPENAI_DEPLOYMENT=$inputDeployment

# Application defaults
# Log level used by main.py when --log-level is not passed on the CLI
# Valid values: DEBUG | INFO | WARNING | ERROR | CRITICAL
LOG_LEVEL=$LOG_LEVEL

# Folder paths (relative to project root; override if needed)
EMAIL_DATA_DIR=email_data
RESULT_DIR=result
LOG_DIR=logs
"@

$envPath = Join-Path $PSScriptRoot ".env"
$envContent | Out-File -FilePath $envPath -Encoding utf8
Write-OK ".env written to: $envPath"
Write-NOTE "Edit .env at any time to update credentials or change LOG_LEVEL."

# ==============================================================================
# STEP 7 - Create application folders
# ==============================================================================
Write-Step 7 $TOTAL_STEPS "Creating application folder structure ..."

$folders = @("email_data", "result", "logs", "config", "src", "ui")
foreach ($folder in $folders) {
    $folderPath = Join-Path $PSScriptRoot $folder
    if (-Not (Test-Path $folderPath)) {
        New-Item -ItemType Directory -Path $folderPath | Out-Null
        Write-OK "Created : $folder"
    } else {
        Write-OK "Exists  : $folder"
    }
}

# Place a README in email_data so users know where to drop files
$readmePath = Join-Path $PSScriptRoot "email_data\README.txt"
if (-Not (Test-Path $readmePath)) {
    $readmeContent = @"
email_data folder
=================
Drop your test email files here (.pdf or .xlsx).
Files uploaded via the HTML dashboard are also saved here automatically.

Supported formats:
  .pdf   - one or more emails per document
  .xlsx  - one email per row (columns: From, To, Subject, Date, Body)

Run from CLI:
  python main.py --data-dir email_data
  python main.py --data-dir email_data --log-level DEBUG
"@
    $readmeContent | Out-File -FilePath $readmePath -Encoding utf8
}

# ==============================================================================
# Summary
# ==============================================================================
Write-Host ""
Write-Host "  +----------------------------------------------------------+" -ForegroundColor Cyan
Write-Host "  |  Setup complete!                                         |" -ForegroundColor Cyan
Write-Host "  +----------------------------------------------------------+" -ForegroundColor Cyan
Write-Host "  |  Run modes:                                              |" -ForegroundColor White
Write-Host "  |                                                          |" -ForegroundColor White
Write-Host "  |  Start API server (for HTML dashboard):                  |" -ForegroundColor White
Write-Host "  |    python main.py --server                               |" -ForegroundColor Green
Write-Host "  |                                                          |" -ForegroundColor White
Write-Host "  |  Analyse all files in email_data folder:                 |" -ForegroundColor White
Write-Host "  |    python main.py --data-dir email_data                  |" -ForegroundColor Green
Write-Host "  |                                                          |" -ForegroundColor White
Write-Host "  |  Analyse a single file with DEBUG logging:               |" -ForegroundColor White
Write-Host "  |    python main.py --file email_data/test_emails.xlsx     |" -ForegroundColor Green
Write-Host "  |                   --log-level DEBUG                      |" -ForegroundColor Green
Write-Host "  |                                                          |" -ForegroundColor White
Write-Host "  |  Open ui/dashboard.html in your browser for the GUI      |" -ForegroundColor White
Write-Host "  +----------------------------------------------------------+" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Log level default : $LOG_LEVEL" -ForegroundColor Magenta
Write-Host "  Logs saved to     : logs/" -ForegroundColor Magenta
Write-Host "  Results saved to  : result/" -ForegroundColor Magenta
Write-Host "  Email data folder : email_data/" -ForegroundColor Magenta
Write-Host ""
