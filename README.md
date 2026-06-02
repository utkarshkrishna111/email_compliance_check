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
│   ├── api_server.py            ← Flask REST API (used by dashboard)
│   │
│   ├── graph.py                 ← ★ LangGraph pipeline (entry point for analysis)
│   ├── history_store.py         ← SQLite + ChromaDB (historical_llm_response)
│   ├── thread_detector.py       ← Email thread grouping & internal/external detection
│   ├── context_builder.py       ← Thread context substitution (token optimisation)
│   ├── sender_risk.py           ← Sender risk profile (score 0-100)
│   └── anomaly_detector.py      ← Communication volume anomaly detection (Z-score)
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
│   ├── compliance_<timestamp>.json
│   ├── latest.json              ← always points to the most recent run
│   ├── history.db               ← SQLite: historical_llm_response + network tables
│   └── chroma/                  ← ChromaDB: semantic vector index
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

### Step 2 — Install new dependencies

```powershell
pip install langgraph chromadb
```

### Step 3 — Activate venv (subsequent runs)

```powershell
.\venv\Scripts\Activate.ps1
```

### Step 4 — Run

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

## Pipeline Architecture (LangGraph)

Each email now flows through a stateful LangGraph pipeline instead of a simple function chain.
Every node receives the full pipeline state and returns only the fields it updates.

```
Email Input
    │
    ▼
detect_thread        derives thread_id from subject + participants
    │
    ▼
retrieve_history     loads prior findings from SQLite; computes sender risk + volume anomaly
    │
    ▼
build_context        replaces prior email bodies with cached LLM summaries (token saving)
                     appends sender risk and anomaly notes if triggered
    │
    ▼
compliance_agent     LLM call 1 — Azure GPT-4o analyses the email
    │
    ▼
guardrail_check      rule-based validation of LLM output
    │
    ├─ PASS ──▶ verify       LLM call 2 — confirms or corrects the finding
    │
    └─ FAIL ──▶ flag_review  marks finding as REVIEW_REQUIRED, skips LLM 2
    │
    ▼
score                calculates priority score; applies sender risk boost if applicable
    │
    ▼
persist              writes to SQLite + ChromaDB + result/latest.json
```

### Using the graph directly

```python
from src.graph import build_graph, make_initial_state

graph = build_graph(internal_domain="yourbank.com")
result = graph.invoke(make_initial_state(email_dict))
scored_finding = result["scored_finding"]
```

---

## Historical LLM Response Database

All findings are persisted to `result/history.db` (SQLite) and `result/chroma/` (ChromaDB).

### SQLite tables

| Table | Contents |
|---|---|
| `historical_llm_response` | Every scored finding — categories, confidence, reasoning, scores, thread_id |
| `recipient_network` | Per sender–recipient pair: email count, flagged count, first/last seen |
| `sender_weekly_volume` | Email count per sender per ISO week — feeds anomaly detection |

### Thread context substitution

When an email belongs to an existing thread, prior email bodies are **replaced by their
cached LLM summaries** before the new email is sent to the LLM.

```
3-email thread WITHOUT substitution:  ~380 tokens
3-email thread WITH substitution:     ~145 tokens   (~62% saving)
```

Savings compound as threads grow longer.

### ChromaDB (semantic search)

Each finding is embedded and stored in ChromaDB under the `email_compliance` collection.
Use `HistoryStore.semantic_search(query_text)` to find past violations similar to a
free-text description.

```python
from src.history_store import HistoryStore
store = HistoryStore()
results = store.semantic_search("coordinated trade at 3pm", n_results=5)
```

> ChromaDB is optional. If not installed the pipeline continues normally and only
> SQLite is used. Install with: `pip install chromadb`

---

## Enhancements

### Sender Risk Profile

Every sender accumulates a risk score (0–100) derived from their full history in
`historical_llm_response`. The score is recomputed on each new email and injected
into the LLM prompt as context when the sender is ELEVATED or above.

**Score formula**

| Component | Weight | Source |
|---|---|---|
| Violation rate (non-compliant / total emails) | 50 % | SQLite |
| Average AI confidence on flagged emails | 30 % | SQLite |
| Category severity score (normalised) | 20 % | SQLite + compliance_matrix.yaml |

**Risk bands**

| Band | Score |
|---|---|
| `HIGH_RISK` | ≥ 70 |
| `ELEVATED` | ≥ 40 |
| `LOW_RISK` | ≥ 10 |
| `CLEAN` | < 10 |
| `UNKNOWN` | No history yet |

A `HIGH_RISK` sender receives a **+10 % score boost** on any new non-compliant finding.

---

### Communication Volume Anomaly Detection

Tracks each sender's weekly email volume and flags statistically unusual spikes using
a Z-score against their own baseline (requires ≥ 3 weeks of history).

**Why this matters:** Criminals rarely announce surveillance evasion in writing.
An unusual burst of monitored emails shortly before a flagged event is a signal
that keyword matching structurally cannot detect.

| Parameter | Value |
|---|---|
| Spike threshold | Z-score > 2.0 |
| Minimum history | 3 weeks |

When an anomaly is detected the flag is appended to the LLM prompt and added to
the final scored finding as `volume_anomaly_flag: true`.

---

### Recipient Network

Every email's sender–recipient pairs are recorded in the `recipient_network` table.
This surface:
- New communication links (sender has never contacted this recipient before)
- Flagged pair counts (how many of their exchanges were non-compliant)
- The `external_recipient_bonus` multiplier in `compliance_matrix.yaml` is now
  fully populated — internal vs external is detected automatically from the
  `internal_domain` setting passed to `build_graph()`.

Query the network for a sender:

```python
from src.history_store import HistoryStore
store = HistoryStore()
network = store.get_recipient_network("tom@yourbank.com")
# [{"recipient": "harry@yourbank.com", "email_count": 8, "flagged_count": 3, ...}]
```

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
    multi_category_bonus: 1.20        # applied when 2+ categories detected
    high_confidence_bonus: 1.15       # applied when confidence >= 0.80
    external_recipient_bonus: 1.10    # applied when email goes outside org
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
