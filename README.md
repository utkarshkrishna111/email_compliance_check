# Email Compliance AI Agent

AI-powered communication surveillance for banking email monitoring.
Detects non-compliant behaviour, assigns priority scores, surfaces findings through a web dashboard,
and runs **cross-email pattern analysis** to catch Quid Pro Quo arrangements and Circular Trading schemes.

---

## What's New

| Feature | Module | Description |
|---|---|---|
| **Quid Pro Quo Detection** | `src/quid_pro_quo_detector.py` | Finds reciprocal flagged-email pairs (A→B and B→A) across threads within a rolling window |
| **Circular Trading Detection** | `src/circular_trading_detector.py` | Graph cycle detection (A→B→C→A) on market-manipulation flagged communication networks |
| **`circular_trading` category** | `compliance_matrix.yaml` | New LLM category (weight 10) with keywords for coordinated round-trip trades |
| **Expanded QPQ keywords** | `compliance_matrix.yaml` | `bribery` category enriched with 10 conditional-exchange language patterns |
| **`/api/patterns` endpoint** | `src/api_server.py` | REST endpoint that returns QPQ + Circular Trading alerts on demand |
| **HistoryStore in CLI pipeline** | `main.py` | Findings now persisted to SQLite inside every `--file` / `--data-dir` run |

---

## Project Structure

```
email_compliance_check/
│
├── config/
│   └── compliance_matrix.yaml     ← scoring weights, thresholds, category keywords (edit to tune)
│
├── src/
│   ├── __init__.py
│   ├── config_loader.py           ← YAML config loader
│   ├── email_reader.py            ← PDF & Excel email extraction + folder scanning
│   ├── compliance_agent.py        ← LangChain AI Agent (Azure OpenAI GPT-4o)
│   ├── guardrails.py              ← Output validation & second-pass LLM verification
│   ├── scoring_engine.py          ← Priority score 0-100 from compliance matrix
│   ├── storage.py                 ← Saves results to result/ folder (JSON)
│   ├── api_server.py              ← Flask REST API (used by dashboard)
│   │
│   ├── graph.py                   ← ★ LangGraph pipeline + run_cross_pattern_analysis()
│   ├── history_store.py           ← SQLite + ChromaDB (historical findings & networks)
│   ├── thread_detector.py         ← Email thread grouping & internal/external detection
│   ├── context_builder.py         ← Thread context substitution (token optimisation)
│   ├── sender_risk.py             ← Sender risk profile (score 0-100, CLEAN → HIGH_RISK)
│   ├── anomaly_detector.py        ← Communication volume anomaly detection (Z-score)
│   │
│   ├── quid_pro_quo_detector.py   ← ★ NEW: Cross-thread reciprocal exchange detector
│   └── circular_trading_detector.py  ← ★ NEW: Graph cycle detector for wash trading
│
├── ui/
│   ├── dashboard.html             ← Upload & results web dashboard
│   └── architecture.html          ← ★ Full interactive system architecture diagram
│
├── email_data/                    ← ★ DROP EMAIL FILES HERE (PDF / Excel)
│   ├── README.txt
│   ├── test_emails.xlsx           ← 17 test emails (included)
│   └── test_emails.pdf            ← 5 test emails (included)
│
├── result/                        ← ★ RESULTS & HISTORY written here
│   ├── compliance_<timestamp>.json
│   ├── latest.json                ← always points to the most recent run
│   ├── history.db                 ← SQLite: findings, recipient network, weekly volumes
│   └── chroma/                    ← ChromaDB: semantic vector index of all findings
│
├── logs/
│   ├── compliance_<timestamp>.info.log
│   ├── compliance_<timestamp>.debug.log   (only when --log-level DEBUG)
│   ├── latest.info.log            ← symlink to most recent info log
│   └── latest.debug.log           ← symlink to most recent debug log
│
├── main.py                        ← ★ ENTRY POINT
├── requirements.txt
├── setup.ps1                      ← Windows 11 setup & interactive config
└── README.md
```

---

## Quick Start (Windows 11)

### Step 1 — Run setup script

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\setup.ps1
```

The setup script will:
- Check Python 3.10+
- Create and activate a virtual environment
- Install all dependencies
- Prompt for Azure OpenAI credentials interactively
- Prompt to choose INFO or DEBUG as the default log mode
- Write `.env` with all settings
- Create all required folders

### Step 2 — Install graph and vector dependencies

```powershell
pip install langgraph chromadb
```

### Step 3 — Activate venv (subsequent runs)

```powershell
.\venv\Scripts\Activate.ps1
```

### Step 4 — Run

```powershell
# Analyse all files in email_data/ — also runs QPQ + Circular Trading after the batch
python main.py --data-dir email_data

# With DEBUG logging
python main.py --data-dir email_data --log-level DEBUG

# Single file
python main.py --file email_data\test_emails.xlsx

# Start dashboard API server
python main.py --server
```

---

## Pipeline Architecture

### Per-Email LangGraph Pipeline

Each email flows through a stateful LangGraph pipeline. Every node receives the full pipeline
state and returns only the fields it updates.

```
Email Input
    │
    ▼
detect_thread         derives stable thread_id from subject + sorted participant set
    │
    ▼
retrieve_history      loads prior findings from SQLite; computes sender risk + volume anomaly
    │
    ▼
build_context         replaces prior email bodies with cached LLM summaries (token saving)
                      appends sender risk note and anomaly flag if triggered
    │
    ▼
compliance_agent      LLM call 1 — Azure GPT-4o analyses the email against all categories
    │
    ▼
guardrail_check       rule-based validation: required fields, confidence range, category IDs,
                      evidence count, reasoning length, soft hallucination guard
    │
    ├─ PASS ──▶ verify         LLM call 2 — confirms or corrects classification
    │
    └─ FAIL ──▶ flag_review    marks finding as REVIEW_REQUIRED; skips second LLM call
    │
    ▼
score                 calculates 0-100 priority score; applies sender risk boost (+10%)
                      if sender is HIGH_RISK; tags volume_anomaly_flag if applicable
    │
    ▼
persist               writes to SQLite (historical_llm_response, recipient_network,
                      sender_weekly_volume) + ChromaDB + result/latest.json
```

### Post-Batch Cross-Pattern Analysis

After **all** emails in a batch are processed and persisted, two additional detectors
run against the accumulated SQLite history:

```
All emails persisted
    │
    ├──▶ detect_quid_pro_quo()       SQL join: finds (A,B) pairs where A flagged B
    │                                AND B flagged A within the time window
    │
    └──▶ detect_circular_trading()   Builds directed graph from recipient_network;
                                     DFS cycle detection finds A→B→C→A patterns
```

Results are printed to the console and returned via `GET /api/patterns`.

### Using the graph directly

```python
from src.graph import build_graph, make_initial_state, run_cross_pattern_analysis

# Per-email pipeline
graph = build_graph(internal_domain="yourbank.com")
result = graph.invoke(make_initial_state(email_dict))
scored_finding = result["scored_finding"]

# Post-batch cross-pattern analysis
alerts = run_cross_pattern_analysis("result/history.db")
print(alerts["quid_pro_quo"])
print(alerts["circular_trading"])
```

---

## Cross-Pattern Analysis

### Quid Pro Quo Detection

**What it detects:** A mutual-favour arrangement where party A provides something for party B
*and* party B independently provides something for party A — detected across separate email threads.
No single email reveals this; only the cross-thread pattern does.

**How it works (`src/quid_pro_quo_detector.py`):**

1. Queries `historical_llm_response` for all non-compliant findings within `days_window` (default 30 days).
2. Self-joins the table to find pairs (email1 from A to B, email2 from B to A).
3. Filters: both emails must involve at least one QPQ-relevant category (`bribery`, `market_manipulation`, `employee_ethics`).
4. Verifies the actual addressing: sender1 is in recipients of email2, and sender2 is in recipients of email1.
5. De-duplicates by canonical pair key so A↔B and B↔A are one alert.

**Severity:**

| Condition | Severity |
|---|---|
| Average confidence ≥ 0.80 | CRITICAL |
| Average confidence < 0.80 | HIGH |

**Trigger keywords in emails (via LLM):**

> `in return for` · `if you do this for us` · `as a favor` · `once you arrange` ·
> `our understanding` · `scratch your back` · `reciprocate` · `mutual arrangement` ·
> `you take care of` · `I'll make it worth your while` · `our deal stands`

**Programmatic usage:**

```python
from src.quid_pro_quo_detector import detect_quid_pro_quo

alerts = detect_quid_pro_quo("result/history.db", days_window=30)
for a in alerts:
    print(a["severity"], a["party_a"], "↔", a["party_b"])
    print(a["reasoning"])
```

---

### Circular Trading Detection

**What it detects:** A coordinated round-trip scheme where parties trade among themselves
to create artificial volume or price signals — A→B→C→A communication cycles in the
`recipient_network` where all edges carry `market_manipulation` or `circular_trading` flagged emails.

**How it works (`src/circular_trading_detector.py`):**

1. Queries `recipient_network` for edges where `flagged_count >= min_flagged` (default 1).
2. Verifies each edge: at least one underlying email must be flagged for `market_manipulation` or `circular_trading`.
3. Builds a directed adjacency graph: `{ sender: {recipient, ...}, ... }`.
4. Runs a DFS cycle detection starting from each node in lexicographic order.
   - Intermediate nodes are constrained to be lexicographically greater than `start` to avoid duplicate cycles.
   - A cycle is recorded only when `start` is the minimum node in the cycle.
5. Returns all unique cycles of length 3–`max_cycle_length` (default 6).

**Severity:**

| Cycle length | Severity |
|---|---|
| 3–4 participants | CRITICAL |
| 5–6 participants | HIGH |

**Trigger keywords in emails (via LLM):**

> `round trip` · `wash trade` · `mirror trade` · `coordinate our positions` ·
> `synchronized buy` · `you buy we sell` · `prearranged` · `paint the tape` ·
> `inflate volume` · `circular trade` · `we all trade between`

**Programmatic usage:**

```python
from src.circular_trading_detector import detect_circular_trading

alerts = detect_circular_trading("result/history.db", min_flagged=1, max_cycle_length=6)
for a in alerts:
    print(a["severity"], a["description"])
    # e.g. "CRITICAL  alice@bank.com → bob@hedge.com → carol@fund.com → alice@bank.com"
```

---

## Historical LLM Response Database

All findings are persisted to `result/history.db` (SQLite) and `result/chroma/` (ChromaDB).

### SQLite tables

| Table | Contents | Used by |
|---|---|---|
| `historical_llm_response` | Every scored finding — categories, confidence, reasoning, scores, thread_id | Thread context, sender risk, QPQ detector |
| `recipient_network` | Per sender–recipient pair: email count, flagged count, first/last seen | Circular trading detector, external bonus |
| `sender_weekly_volume` | Email count per sender per ISO week | Volume anomaly detector |

### Thread context substitution

When an email belongs to an existing thread, prior email bodies are replaced by their
cached LLM summaries before the new email is sent to the LLM.

```
3-email thread WITHOUT substitution:  ~380 tokens
3-email thread WITH substitution:     ~145 tokens   (~62% saving)
```

Savings compound as threads grow longer.

### ChromaDB (semantic search)

Each finding is embedded and stored in ChromaDB under the `email_compliance` collection.

```python
from src.history_store import HistoryStore
store = HistoryStore()
results = store.semantic_search("coordinated trade at 3pm", n_results=5)
```

> ChromaDB is optional. The pipeline continues without it. Install with: `pip install chromadb`

---

## Sender Risk Profile

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

| Band | Score | Effect |
|---|---|---|
| `HIGH_RISK` | ≥ 70 | +10 % score boost on new findings; risk note injected into LLM prompt |
| `ELEVATED` | ≥ 40 | Risk note injected into LLM prompt |
| `LOW_RISK` | ≥ 10 | No prompt injection |
| `CLEAN` | < 10 | No prompt injection |
| `UNKNOWN` | No history | No action |

---

## Communication Volume Anomaly Detection

Tracks each sender's weekly email volume and flags statistically unusual spikes using
a Z-score against their own baseline (requires ≥ 3 weeks of history).

**Why this matters:** An unusual burst of monitored emails shortly before a flagged event
is a signal that keyword matching structurally cannot detect.

| Parameter | Value |
|---|---|
| Spike threshold | Z-score > 2.0 |
| Minimum history | 3 weeks |

When an anomaly is detected, the flag is appended to the LLM prompt and added to
the final scored finding as `volume_anomaly_flag: true`.

---

## Recipient Network

Every email's sender–recipient pairs are recorded in the `recipient_network` table.

- Tracks new communication links (sender has never contacted this recipient before)
- Counts flagged pair exchanges — directly feeds the Circular Trading detector
- Feeds the `external_recipient_bonus` multiplier in `compliance_matrix.yaml`

```python
from src.history_store import HistoryStore
store = HistoryStore()
network = store.get_recipient_network("tom@yourbank.com")
# [{"recipient": "harry@fund.com", "email_count": 8, "flagged_count": 3, ...}]
```

---

## CLI Reference

```
python main.py [MODE] [OUTPUT OPTIONS] [LOGGING OPTIONS]

Modes (mutually exclusive):
  --server              Start Flask API server (default when no mode given)
  --file PATH           Analyse a single PDF or Excel file
  --data-dir DIR        Scan folder for all supported files (default: email_data)
  PATH                  Positional shorthand: python main.py email_data

Output options:
  --result-dir DIR      Where to write result JSON (default: result/)

Logging options:
  --log-level LEVEL     DEBUG | INFO | WARNING | ERROR | CRITICAL
  --log-dir DIR         Log file location (default: logs/)
  --log-file STEM       Log filename stem, e.g. "sprint01" → sprint01.info.log
```

### Log files

| File | Created when |
|---|---|
| `logs/<stem>.info.log` | Always |
| `logs/<stem>.debug.log` | Only when `--log-level DEBUG` — includes raw AI output |
| `logs/latest.info.log` | Symlink → most recent info log |
| `logs/latest.debug.log` | Symlink → most recent debug log |

---

## Configuration

Edit `config/compliance_matrix.yaml` to tune scoring **without changing any code**.

```yaml
categories:
  market_manipulation:
    base_weight: 10
  bribery:
    base_weight: 9
  circular_trading:
    base_weight: 10        # ← new category

scoring:
  multipliers:
    multi_category_bonus: 1.20
    high_confidence_bonus: 1.15
    external_recipient_bonus: 1.10
  priority_bands:
    critical: 80
    high:     60
    medium:   40
    low:       0
```

---

## Compliance Categories

| ID | Label | Weight | Notes |
|---|---|---|---|
| `market_manipulation` | Market Manipulation / Misconduct | 10 | Pump & dump, front-running, insider trading |
| `circular_trading` | Circular / Wash Trading Coordination | 10 | **New** — round-trip, prearranged, paint-the-tape |
| `bribery` | Market Bribery / Quid Pro Quo | 9 | Kickbacks + full QPQ conditional-language set |
| `secrecy` | Secrecy / Information Leakage | 8 | MNPI, off-record tips |
| `employee_ethics` | Employee Ethics Violation | 7 | Conflicts of interest, side deals |
| `change_in_communication` | Change in Communication Pattern | 6 | Off-channel evasion |
| `complaints` | Client / Regulatory Complaints | 4 | Disputes, legal threats |

---

## REST API (when running `--server`)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | Health check |
| `POST` | `/api/analyse` | Upload files (field: `files`) → run pipeline |
| `GET` | `/api/results` | Return latest result (from `result/latest.json`) |
| `GET` | `/api/results/list` | List all past result filenames |
| `GET` | `/api/results/<filename>` | Load a specific result file |
| `GET` | `/api/patterns` | **New** — run QPQ + Circular Trading detectors; returns alerts JSON |

### `/api/patterns` query parameters

| Parameter | Default | Description |
|---|---|---|
| `qpq_days` | `30` | Rolling window in days for Quid Pro Quo scan |
| `ct_min_flagged` | `1` | Minimum flagged edge count for Circular Trading graph |
| `ct_max_cycle` | `6` | Maximum cycle length for graph search |

```
GET /api/patterns?qpq_days=60&ct_min_flagged=2&ct_max_cycle=5
```

Response shape:

```json
{
  "quid_pro_quo": [
    {
      "pattern": "QUID_PRO_QUO",
      "party_a": "alice@bank.com",
      "party_b": "bob@fund.com",
      "severity": "CRITICAL",
      "avg_confidence": 0.91,
      "email_a_subject": "Re: approval needed",
      "email_b_subject": "Fwd: allocation confirmed",
      "email_a_categories": ["bribery"],
      "email_b_categories": ["market_manipulation"],
      "reasoning": "..."
    }
  ],
  "circular_trading": [
    {
      "pattern": "CIRCULAR_TRADING",
      "participants": ["alice@bank.com", "bob@hedge.com", "carol@fund.com"],
      "cycle_length": 3,
      "description": "alice@bank.com → bob@hedge.com → carol@fund.com → alice@bank.com",
      "severity": "CRITICAL",
      "reasoning": "..."
    }
  ],
  "quid_pro_quo_count": 1,
  "circular_trading_count": 1
}
```
