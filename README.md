# Email Compliance AI Agent

AI-powered communication surveillance for banking email monitoring.
Detects non-compliant behaviour, assigns priority scores, and surfaces findings through a web dashboard.

---

## Project Structure

```
email_compliance/
│
├── config/
│   └── compliance_matrix.yaml   ← scoring weights & thresholds (edit to tune)
│
├── src/
│   ├── __init__.py
│   ├── config_loader.py         ← YAML config loader
│   ├── email_reader.py          ← PDF & Excel email extraction + folder scanning
│   ├── compliance_agent.py      ← LangChain AI Agent (Azure OpenAI GPT-4o)
│   ├── guardrails.py            ← Output validation & second-pass verification
│   ├── scoring_engine.py        ← Priority score 0-100 from compliance matrix
│   ├── storage.py               ← Saves results to result/ folder
│   └── api_server.py            ← Flask REST API (used by dashboard)
│
├── ui/
│   ├── dashboard.html           ← Upload & results web dashboard
│   └── architecture.html        ← Interactive system architecture diagram
│
├── email_data/                  ← ★ DROP EMAIL FILES HERE (PDF / Excel)
│   ├── README.txt
│   ├── test_emails.xlsx         ← 17 test emails (included)
│   └── test_emails.pdf          ← 5 test emails (included)
│
├── result/                      ← ★ COMPLIANCE RESULTS written here per run
│   └── compliance_<timestamp>.json
│   └── latest.json              ← always points to the most recent run
│
├── logs/                        ← ★ APPLICATION LOGS written here
│   └── compliance_<timestamp>.info.log
│   └── compliance_<timestamp>.debug.log  (only when --log-level DEBUG)
│   └── latest.info.log          ← symlink to most recent info log
│   └── latest.debug.log         ← symlink to most recent debug log
│
├── main.py                      ← ★ ENTRY POINT
├── requirements.txt
├── setup.ps1                    ← Windows 11 setup & interactive config
└── README.md
```

---

## Quick Start (Windows 11)

### Step 1 — Run setup script

```powershell
# Open PowerShell in the project folder
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\setup.ps1
```

The setup script will:
- Check Python 3.10+
- Create and activate a virtual environment
- Install all dependencies
- Prompt for Azure OpenAI credentials **interactively**
- **Prompt you to choose INFO or DEBUG as the default log mode**
- Write `.env` with all settings
- Create all required folders

### Step 2 — Activate venv (subsequent runs)

```powershell
.\venv\Scripts\Activate.ps1
```

### Step 3 — Run

```powershell
# Analyse all files in email_data/ (uses log level from .env)
python main.py --data-dir email_data

# Analyse all files with DEBUG logging
python main.py --data-dir email_data --log-level DEBUG

# Analyse a single file
python main.py --file email_data\test_emails.xlsx

# Start the API server for the dashboard
python main.py --server
```

Then open `ui/dashboard.html` in your browser.

---

## CLI Reference

```
python main.py [MODE] [OUTPUT OPTIONS] [LOGGING OPTIONS]

Modes (mutually exclusive):
  --server              Start Flask API server (default when no mode given)
  --file PATH           Analyse a single PDF or Excel file
  --data-dir DIR        Scan folder for all supported files (default: email_data)

Output options:
  --result-dir DIR      Where to write result JSON (default: result/)

Logging options:
  --log-level LEVEL     DEBUG | INFO | WARNING | ERROR | CRITICAL
                        (default: value of LOG_LEVEL in .env, set during setup)
  --log-dir DIR         Log file location (default: logs/)
  --log-file STEM       Log filename stem, e.g. "sprint01" → sprint01.info.log
```

### Log files

| File | Created when |
|---|---|
| `logs/<stem>.info.log` | Always – human-readable summary |
| `logs/<stem>.debug.log` | Only when `--log-level DEBUG` – full trace incl. raw AI output |
| `logs/latest.info.log` | Symlink → most recent info log |
| `logs/latest.debug.log` | Symlink → most recent debug log |

---

## Configuration

Edit `config/compliance_matrix.yaml` to tune scoring **without changing any code**.

Key sections:

```yaml
categories:
  market_manipulation:
    base_weight: 10       # ← change severity here
  bribery:
    base_weight: 9

scoring:
  multipliers:
    multi_category_bonus: 1.20   # applied when 2+ categories detected
    high_confidence_bonus: 1.15  # applied when confidence >= 0.80
  priority_bands:
    critical: 80   # score >= 80
    high:     60
    medium:   40
    low:       0
```

---

## Compliance Categories

| ID | Label | Weight |
|---|---|---|
| `market_manipulation` | Market Manipulation / Misconduct | 10 |
| `bribery` | Market Bribery / Quid Pro Quo | 9 |
| `secrecy` | Secrecy / Information Leakage | 8 |
| `employee_ethics` | Employee Ethics Violation | 7 |
| `change_in_communication` | Change in Communication Pattern | 6 |
| `complaints` | Client / Regulatory Complaints | 4 |

---

## REST API (when running `--server`)

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/health` | Health check |
| POST | `/api/analyse` | Upload files (field: `files`) → run pipeline |
| GET | `/api/results` | Return latest result (from `result/latest.json`) |
| GET | `/api/results/list` | List all past result filenames |
| GET | `/api/results/<filename>` | Load a specific result file |

Uploaded files are saved to `email_data/` and results to `result/`.
