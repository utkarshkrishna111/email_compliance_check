"""
src/config.py
-------------
Central path configuration. All runtime data lives under DATA_FOLDER.

Default : ~/email_data
Override : set the DATA_FOLDER environment variable before starting.

Layout inside DATA_FOLDER
-------------------------
  input/        email files to analyse
  result/       JSON compliance reports per run
  history.db    SQLite — findings, sender network, weekly volumes
  chroma/       ChromaDB vector store
  logs/         rotating log files
"""

import os
from pathlib import Path

DATA_FOLDER = Path(os.environ.get("DATA_FOLDER", Path.home() / "data_email_compliance"))

INPUT_DIR   = DATA_FOLDER / "input"
RESULT_DIR  = DATA_FOLDER / "result"
DB_PATH     = DATA_FOLDER / "history.db"
CHROMA_PATH = DATA_FOLDER / "chroma"
LOG_DIR     = DATA_FOLDER / "logs"

for _d in (INPUT_DIR, RESULT_DIR, CHROMA_PATH, LOG_DIR):
    _d.mkdir(parents=True, exist_ok=True)
