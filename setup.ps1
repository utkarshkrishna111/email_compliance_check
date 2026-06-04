# ==============================================================================
# setup.ps1  -  Email Compliance AI Agent  |  Windows 11 Setup Script
# ==============================================================================
# What this script does:
#   1. Validates Python 3.10+
#   2. Creates & activates a virtual environment
#   3. Installs all Python dependencies (Python 3.14 compatible, no compiler needed)
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

# ---------------------------------------------------------------------------
# Helper: return "major.minor" for a given exe, or $null if it is a stub /
# launcher / Microsoft Store redirect that produces no real output.
# ---------------------------------------------------------------------------
function Get-PythonVersion([string]$exePath) {
    if ($exePath -like "*WindowsApps*") { return $null }
    if (-not (Test-Path $exePath))      { return $null }
    try {
        $raw = (& $exePath --version 2>&1) | Out-String
        if ($raw -match 'Python\s+(\d+)\.(\d+)') {
            return "$($Matches[1]).$($Matches[2])"
        }
    } catch { }
    return $null
}

# ---------------------------------------------------------------------------
# Helper: py.exe is the Windows Python Launcher - it is NOT a Python
# interpreter and cannot create venvs.  Ask it where the real interpreter
# lives and return that path instead.
# ---------------------------------------------------------------------------
function Resolve-PyLauncher([string]$exePath) {
    if ($exePath -notlike "*\py.exe") { return $exePath }
    try {
        $real = (& $exePath -c "import sys; print(sys.executable)" 2>&1).Trim()
        if ($real -and (Test-Path $real) -and ($real -notlike "*WindowsApps*") -and ($real -notlike "*\py.exe")) {
            return $real
        }
    } catch { }
    return $exePath
}

# ---------------------------------------------------------------------------
# Build candidate list:
#   Priority 1 - real install directories (newest folder first)
#   Priority 2 - PATH-resolved commands
# ---------------------------------------------------------------------------
$candidates = [System.Collections.Generic.List[string]]::new()

$installRoots = @(
    "$env:LOCALAPPDATA\Programs\Python",
    "C:\Program Files\Python*",
    "C:\Program Files (x86)\Python*",
    "C:\Python*"
)
foreach ($pattern in $installRoots) {
    $dirs = Get-Item $pattern -ErrorAction SilentlyContinue |
            Where-Object { $_.PSIsContainer } |
            Sort-Object Name -Descending
    foreach ($dir in $dirs) {
        $exe = Join-Path $dir.FullName "python.exe"
        if ((Test-Path $exe) -and ($exe -notlike "*WindowsApps*")) {
            if (-not $candidates.Contains($exe)) { $candidates.Add($exe) }
        }
    }
}

foreach ($name in @("python", "python3", "py")) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notlike "*WindowsApps*") {
        $resolved = Resolve-PyLauncher $cmd.Source
        if (-not $candidates.Contains($resolved)) { $candidates.Add($resolved) }
    }
}

# ---------------------------------------------------------------------------
# Walk candidates until one returns a real version number
# ---------------------------------------------------------------------------
$pythonExe = $null
$pyVerRaw  = $null

foreach ($exe in $candidates) {
    $ver = Get-PythonVersion $exe
    if ($ver) {
        $pythonExe = $exe
        $pyVerRaw  = $ver
        break
    }
}

if (-not $pythonExe) {
    Write-ERR "No working Python installation found."
    Write-Host ""
    Write-Host "        Steps to fix:" -ForegroundColor Yellow
    Write-Host "          1. Install Python 3.10+ from https://python.org" -ForegroundColor White
    Write-Host "             (tick 'Add Python to PATH' during install)" -ForegroundColor White
    Write-Host "          2. Restart PyCharm after installing" -ForegroundColor White
    exit 1
}

$pyMajor = [int]($pyVerRaw.Split('.')[0])
$pyMinor = [int]($pyVerRaw.Split('.')[1])

if ($pyMajor -lt 3 -or ($pyMajor -eq 3 -and $pyMinor -lt 10)) {
    Write-ERR "Python $pyVerRaw found but 3.10+ is required. Please upgrade Python."
    exit 1
}
Write-OK "Python $pyVerRaw detected."
Write-Host "        Executable : $pythonExe" -ForegroundColor DarkGray

# ==============================================================================
# STEP 2 - Virtual environment
# ==============================================================================
Write-Step 2 $TOTAL_STEPS "Setting up virtual environment ..."

# Use the full pythonExe path (never py.exe) so venv creation is reliable
$venvPath = Join-Path $PSScriptRoot "venv"
if (-Not (Test-Path $venvPath)) {
    & $pythonExe -m venv $venvPath 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-ERR "Failed to create virtual environment."
        Write-ERR "Try running:  $pythonExe -m venv venv"
        exit 1
    }
    Write-OK "Virtual environment created."
} else {
    Write-OK "Virtual environment already exists - skipping creation."
}

# Resolve the venv's own python.exe - use this for all pip calls
$venvPython = Join-Path $venvPath "Scripts\python.exe"
$venvPip    = Join-Path $venvPath "Scripts\pip.exe"

# Activate for the current session (nice to have but not required for installs)
$activateScript = Join-Path $venvPath "Scripts\Activate.ps1"
if (Test-Path $activateScript) {
    & $activateScript
    Write-OK "Virtual environment activated."
} else {
    Write-NOTE "Activate.ps1 not found - continuing without activation (installs still work)."
}

# ==============================================================================
# STEP 3 - Install Python dependencies
# ==============================================================================
Write-Step 3 $TOTAL_STEPS "Installing Python dependencies ..."

# Upgrade pip first using the venv python directly (avoids the "modify pip" error)
Write-Host "        Upgrading pip ..." -ForegroundColor DarkGray
& $venvPython -m pip install --upgrade pip --quiet
if ($LASTEXITCODE -ne 0) {
    Write-NOTE "pip upgrade returned non-zero - continuing anyway."
}

# ---------------------------------------------------------------------------
# Package list - versions chosen to have pre-built wheels for Python 3.10-3.14
# on Windows (no C compiler required).
#
# Key changes from the original pinned list:
#   - openai            unpinned (1.x latest) - 1.30 doesn't have a 3.14 wheel
#   - langchain family  unpinned (0.3.x latest) - 0.2.x depends on numpy<2
#   - pydantic          unpinned (2.x latest)
#   - PyMuPDF           unpinned (latest ships universal wheels)
#   - pandas            unpinned (latest has 3.13/3.14 wheels)
#   - openpyxl          unpinned (pure Python, any version works)
#   - flask / flask-cors unpinned (pure Python)
#   - tiktoken          unpinned (wheels available for 3.14)
#   - PyYAML            unpinned (has 3.14 wheels)
#   - colorlog          unpinned (pure Python)
#   - reportlab         unpinned (has Windows wheels)
# ---------------------------------------------------------------------------
$packages = @(
    "python-dotenv>=1.0.1",
    "pyyaml>=6.0.1",
    "pdfplumber>=0.10.0",
    "pandas>=2.2.2",
    "openpyxl>=3.1.4",
    "openai>=2.26.0",
    "langchain>=1.0.0",
    "langchain-openai>=1.1.0",
    "langchain-core>=1.2.0",
    "flask>=3.0.3",
    "flask-cors>=4.0.0",
    "tiktoken>=0.7.0",
    "colorlog>=6.8.2",
    "reportlab>=4.2.2"
)

$failed = @()
foreach ($pkg in $packages) {
    Write-Host "        Installing $pkg ..." -ForegroundColor DarkGray
    & $venvPython -m pip install $pkg --quiet --prefer-binary
    if ($LASTEXITCODE -ne 0) {
        Write-NOTE "Warning: $pkg install returned non-zero exit code."
        $failed += $pkg
    } else {
        Write-OK "$pkg installed."
    }
}

if ($failed.Count -gt 0) {
    Write-Host ""
    Write-NOTE "The following packages had install warnings: $($failed -join ', ')"
    Write-NOTE "The app may still work. If not, run manually:"
    Write-NOTE "  $venvPython -m pip install $($failed -join ' ')"
    Write-Host ""
} else {
    Write-OK "All $($packages.Count) packages installed successfully."
}

# ==============================================================================
# STEP 4 - Azure OpenAI credentials (interactive)
# ==============================================================================
Write-Step 4 $TOTAL_STEPS "Configuring Azure OpenAI connection ..."
Write-Host ""
Write-Host "        Enter your Azure OpenAI credentials." -ForegroundColor White
Write-Host "        (Press ENTER to keep the placeholder and edit .env later)" -ForegroundColor DarkGray
Write-Host ""

$defaultEndpoint   = "https://dev-openai-service-02.openai.azure.com"
$defaultApiKey     = "<YOUR_AZURE_OPENAI_API_KEY>"
$defaultApiVersion = "2025-01-01-preview"
$defaultDeployment = "aprbatch1-22520ec1-fb36-4c4c-947b-32f783a023ce"

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
Write-Host "  Python used        : $pythonExe" -ForegroundColor Magenta
Write-Host "  Log level default  : $LOG_LEVEL" -ForegroundColor Magenta
Write-Host "  Logs saved to      : logs/" -ForegroundColor Magenta
Write-Host "  Results saved to   : result/" -ForegroundColor Magenta
Write-Host "  Email data folder  : email_data/" -ForegroundColor Magenta
Write-Host ""
