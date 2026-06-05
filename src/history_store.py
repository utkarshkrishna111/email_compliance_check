"""
src/history_store.py
Persists LLM findings to:
  - SQLite  : exact thread / sender lookups  (historical_llm_response,
              recipient_network, sender_weekly_volume)
  - ChromaDB: semantic similarity search across all past findings
"""

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS historical_llm_response (
    id              TEXT PRIMARY KEY,
    thread_id       TEXT NOT NULL,
    sender          TEXT,
    recipients      TEXT,
    subject         TEXT,
    date            TEXT,
    is_external     INTEGER DEFAULT 0,
    categories      TEXT,
    confidence      REAL,
    intent          TEXT,
    reasoning       TEXT,
    evidence        TEXT,
    is_compliant    INTEGER,
    priority_score  INTEGER,
    priority_band   TEXT,
    alert_level     TEXT,
    source          TEXT,
    created_at      TEXT
);

CREATE INDEX IF NOT EXISTS idx_hlr_thread ON historical_llm_response(thread_id);
CREATE INDEX IF NOT EXISTS idx_hlr_sender ON historical_llm_response(sender);

CREATE TABLE IF NOT EXISTS recipient_network (
    sender        TEXT NOT NULL,
    recipient     TEXT NOT NULL,
    email_count   INTEGER DEFAULT 0,
    flagged_count INTEGER DEFAULT 0,
    first_seen    TEXT,
    last_seen     TEXT,
    PRIMARY KEY (sender, recipient)
);

CREATE TABLE IF NOT EXISTS sender_weekly_volume (
    sender      TEXT NOT NULL,
    week        TEXT NOT NULL,
    email_count INTEGER DEFAULT 0,
    PRIMARY KEY (sender, week)
);
"""


class HistoryStore:

    def __init__(
        self,
        db_path: str = "result/history.db",
        chroma_path: str = "result/chroma",
    ):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._init_sqlite()
        self._chroma = self._init_chroma(chroma_path)
        logger.info("HistoryStore ready  db=%s", db_path)

    # ── write ─────────────────────────────────────────────────────────────────

    def save_finding_sqlite_chroma(
        self,
        finding: Dict[str, Any],
        thread_id: str,
        recipients: List[str],
        is_external: bool,
    ) -> None:
        now = datetime.now().isoformat() + "Z"
        sender = finding.get("from", "")
        week = datetime.now().strftime("%Y-%W")
        flagged = int(not finding.get("is_compliant", True))

        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO historical_llm_response
                (id, thread_id, sender, recipients, subject, date, is_external,
                 categories, confidence, intent, reasoning, evidence,
                 is_compliant, priority_score, priority_band, alert_level, source, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    finding["id"], thread_id, sender,
                    json.dumps(recipients),
                    finding.get("subject", ""), finding.get("date", ""),
                    int(is_external),
                    json.dumps(finding.get("categories", [])),
                    finding.get("confidence", 0.0),
                    finding.get("intent", ""),
                    finding.get("reasoning", ""),
                    json.dumps(finding.get("evidence", [])),
                    flagged,
                    finding.get("priority_score", 0),
                    finding.get("priority_band", "COMPLIANT"),
                    finding.get("alert_level", "NONE"),
                    finding.get("source", ""),
                    now,
                ),
            )

            # recipient network (feature #3)
            for recipient in recipients:
                conn.execute(
                    """
                    INSERT INTO recipient_network
                        (sender, recipient, email_count, flagged_count, first_seen, last_seen)
                    VALUES (?, ?, 1, ?, ?, ?)
                    ON CONFLICT(sender, recipient) DO UPDATE SET
                        email_count   = email_count + 1,
                        flagged_count = flagged_count + ?,
                        last_seen     = ?
                    """,
                    (sender, recipient, flagged, now, now, flagged, now),
                )

            # weekly volume (used by anomaly detector)
            conn.execute(
                """
                INSERT INTO sender_weekly_volume (sender, week, email_count)
                VALUES (?, ?, 1)
                ON CONFLICT(sender, week) DO UPDATE SET email_count = email_count + 1
                """,
                (sender, week),
            )

        self._save_to_chroma(finding, thread_id)
        logger.debug("Saved finding id=%s  thread=%s", finding["id"], thread_id)

    # ── read ──────────────────────────────────────────────────────────────────

    def get_thread_history_sqlite(self, thread_id: str) -> List[Dict[str, Any]]:
        """All prior findings for a thread, oldest first."""
        logger.debug("→ get_thread_history_sqlite  thread_id=%s", thread_id)
        with self._conn() as conn:
            rows = conn.execute(
            """ SELECT id, sender, subject, date, categories, confidence,
                intent, reasoning, evidence, is_compliant,
                priority_score, priority_band, alert_level, created_at
                    FROM historical_llm_response
                    WHERE thread_id = ?
                    ORDER BY created_at ASC
                """,
                (thread_id,),
            ).fetchall()

        logger.debug("  get_thread_history_sqlite → %d row(s) found", len(rows))
        return [
            {
                "id": r[0], "from": r[1], "subject": r[2], "date": r[3],
                "categories":   json.loads(r[4] or "[]"),
                "confidence":   r[5],
                "intent":       r[6],
                "reasoning":    r[7],
                "evidence":     json.loads(r[8] or "[]"),
                "is_compliant": not bool(r[9]),
                "priority_score": r[10], "priority_band": r[11],
                "alert_level":  r[12], "created_at": r[13],
            }
            for r in rows
        ]

    def get_sender_stats_sqlite(self, sender: str) -> Dict[str, Any]:
        logger.debug("→ get_sender_stats_sqlite  sender=%s", sender)
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT categories, confidence, is_compliant
                FROM historical_llm_response
                WHERE sender = ?
                """,
                (sender,),
            ).fetchall()

        if not rows:
            logger.debug("  get_sender_stats_sqlite → no history for sender")
            return {"sender": sender, "total": 0, "non_compliant": 0,
                    "category_counts": {}, "avg_confidence": 0.0}

        total = len(rows)
        non_compliant = sum(1 for r in rows if bool(r[2]))
        avg_conf = sum(r[1] for r in rows) / total
        category_counts: Dict[str, int] = {}
        for r in rows:
            for cat in json.loads(r[0] or "[]"):
                category_counts[cat] = category_counts.get(cat, 0) + 1

        stats = {
            "sender":         sender,
            "total":          total,
            "non_compliant":  non_compliant,
            "avg_confidence": round(avg_conf, 3),
            "category_counts": category_counts,
        }
        logger.debug("  get_sender_stats_sqlite → total=%d  non_compliant=%d  avg_conf=%.2f  cats=%s",
                     total, non_compliant, avg_conf, list(category_counts.keys()))
        return stats

    def get_weekly_volumes_sqlite(self, sender: str, weeks: int = 8) -> Dict[str, int]:
        logger.debug("→ get_weekly_volumes_sqlite  sender=%s  weeks=%d", sender, weeks)
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT week, email_count FROM sender_weekly_volume
                WHERE sender = ?
                ORDER BY week DESC
                LIMIT ?
                """,
                (sender, weeks),
            ).fetchall()
        result = {r[0]: r[1] for r in rows}
        logger.debug("  get_weekly_volumes_sqlite → %d week(s) of history", len(result))
        return result

    def get_recipient_network_sqlite(self, sender: str) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT recipient, email_count, flagged_count, first_seen, last_seen
                FROM recipient_network
                WHERE sender = ?
                ORDER BY email_count DESC
                """,
                (sender,),
            ).fetchall()
        return [
            {
                "recipient":    r[0],
                "email_count":  r[1],
                "flagged_count": r[2],
                "first_seen":   r[3],
                "last_seen":    r[4],
            }
            for r in rows
        ]

    # ── ChromaDB ──────────────────────────────────────────────────────────────

    def _init_chroma(self, path: str):
        try:
            import chromadb
            client = chromadb.PersistentClient(path=path)
            collection = client.get_or_create_collection(
                name="email_compliance",
                metadata={"hnsw:space": "cosine"},
            )
            logger.info("ChromaDB ready  path=%s", path)
            return collection
        except ImportError:
            logger.warning("chromadb not installed — semantic search disabled. "
                           "Run: pip install chromadb")
            return None

    def _save_to_chroma(self, finding: Dict[str, Any], thread_id: str) -> None:
        if self._chroma is None:
            return
        text = " ".join(filter(None, [
            finding.get("subject", ""),
            finding.get("reasoning", ""),
            " ".join(finding.get("evidence", [])),
        ]))
        try:
            self._chroma.upsert(
                ids=[finding["id"]],
                documents=[text],
                metadatas=[{
                    "thread_id":    thread_id,
                    "sender":       finding.get("from", ""),
                    "is_compliant": str(finding.get("is_compliant", True)),
                    "categories":   ",".join(finding.get("categories", [])),
                    "priority_band": finding.get("priority_band", "COMPLIANT"),
                }],
            )
        except Exception as exc:
            logger.warning("ChromaDB upsert failed for id=%s: %s", finding["id"], exc)

    def semantic_search_chroma(self, query_text: str, n_results: int = 5) -> List[Dict[str, Any]]:
        if self._chroma is None:
            return []
        try:
            results = self._chroma.query(query_texts=[query_text], n_results=n_results)
            return [
                {"id": id_, "metadata": meta, "distance": dist}
                for id_, meta, dist in zip(
                    results["ids"][0],
                    results["metadatas"][0],
                    results["distances"][0],
                )
            ]
        except Exception as exc:
            logger.warning("ChromaDB query failed: %s", exc)
            return []

    # ── maintenance ───────────────────────────────────────────────────────────

    def clean_db(self) -> None:
        """Delete all rows from every SQLite table and all documents from ChromaDB."""
        with self._conn() as conn:
            conn.execute("DELETE FROM historical_llm_response")
            conn.execute("DELETE FROM recipient_network")
            conn.execute("DELETE FROM sender_weekly_volume")
        logger.info("SQLite tables cleared")

        if self._chroma is not None:
            result = self._chroma.get()
            ids = result.get("ids", [])
            if ids:
                self._chroma.delete(ids=ids)
                logger.info("ChromaDB collection cleared  documents_removed=%d", len(ids))
            else:
                logger.info("ChromaDB collection was already empty")

    # ── internal ──────────────────────────────────────────────────────────────

    def _init_sqlite(self) -> None:
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)
