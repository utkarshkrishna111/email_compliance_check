"""
src/quid_pro_quo_detector.py
----------------------------
Cross-thread Quid Pro Quo detector.

Finds party-pairs (A, B) where both A→B and B→A have independently flagged
emails (bribery / market_manipulation / employee_ethics) within a rolling
time window — the hallmark of a reciprocal-favour arrangement.

Queries historical_llm_response and recipient_network in SQLite; no LLM call.
"""

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

_DEFAULT_WINDOW_DAYS = 30
_QPQ_CATEGORIES = {"bribery", "market_manipulation", "employee_ethics"}


def detect_quid_pro_quo(
    db_path: str,
    days_window: int = _DEFAULT_WINDOW_DAYS,
) -> List[Dict[str, Any]]:
    """
    Scan the history DB for reciprocal flagged email pairs.

    Parameters
    ----------
    db_path     : path to history.db (SQLite)
    days_window : only consider emails within the last N days

    Returns a list of QPQ alert dicts, one per unique (party_a, party_b) pair.
    """
    since = (datetime.utcnow() - timedelta(days=days_window)).isoformat() + "Z"

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                h1.id,         h1.sender,     h1.recipients, h1.subject,
                h1.date,       h1.categories, h1.confidence, h1.reasoning,
                h2.id,         h2.sender,     h2.recipients, h2.subject,
                h2.date,       h2.categories, h2.confidence, h2.reasoning
            FROM historical_llm_response h1
            JOIN historical_llm_response h2
              ON  h1.sender  != h2.sender
             AND  h1.is_compliant = 0
             AND  h2.is_compliant = 0
             AND  h1.created_at  >= ?
             AND  h2.created_at  >= ?
             AND  h1.id < h2.id
            """,
            (since, since),
        ).fetchall()

    alerts: List[Dict[str, Any]] = []
    seen_pairs: set = set()

    for row in rows:
        (id1, sender1, recips1_raw, subj1, date1, cats1_raw, conf1, reason1,
         id2, sender2, recips2_raw, subj2, date2, cats2_raw, conf2, reason2) = row

        cats1 = set(json.loads(cats1_raw or "[]"))
        cats2 = set(json.loads(cats2_raw or "[]"))

        # Both sides must involve QPQ-relevant violation categories
        if not (cats1 & _QPQ_CATEGORIES) or not (cats2 & _QPQ_CATEGORIES):
            continue

        recips1 = json.loads(recips1_raw or "[]")
        recips2 = json.loads(recips2_raw or "[]")

        # Verify reciprocal addressing: sender1 mailed sender2 AND sender2 mailed sender1
        a_to_b = any(sender2.lower() in r.lower() for r in recips1)
        b_to_a = any(sender1.lower() in r.lower() for r in recips2)
        if not (a_to_b and b_to_a):
            continue

        pair_key = tuple(sorted([sender1, sender2]))
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)

        avg_conf = (conf1 + conf2) / 2
        severity = "CRITICAL" if avg_conf >= 0.8 else "HIGH"

        alert: Dict[str, Any] = {
            "pattern":            "QUID_PRO_QUO",
            "party_a":            sender1,
            "party_b":            sender2,
            "email_a_id":         id1,
            "email_b_id":         id2,
            "email_a_subject":    subj1,
            "email_b_subject":    subj2,
            "email_a_date":       date1,
            "email_b_date":       date2,
            "email_a_categories": sorted(cats1),
            "email_b_categories": sorted(cats2),
            "avg_confidence":     round(avg_conf, 3),
            "severity":           severity,
            "reasoning": (
                f"Reciprocal flagged communication between {sender1} and {sender2} "
                f"within {days_window} days. "
                f"A→B ({', '.join(sorted(cats1))}): {reason1[:120].strip()}… | "
                f"B→A ({', '.join(sorted(cats2))}): {reason2[:120].strip()}…"
            ),
        }
        alerts.append(alert)
        logger.warning(
            "QPQ alert  %s ↔ %s  emails=[%s, %s]  severity=%s  avg_conf=%.2f",
            sender1, sender2, id1, id2, severity, avg_conf,
        )

    logger.info(
        "QPQ scan complete  window=%d days  candidates_checked=%d  alerts=%d",
        days_window, len(rows), len(alerts),
    )
    return alerts
