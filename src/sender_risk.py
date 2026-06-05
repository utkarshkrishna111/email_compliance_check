"""
src/sender_risk.py
Feature #1 — Sender Risk Profile.

Aggregates historical findings for a sender into a risk score (0-100)
and a risk band.  No LLM call; pure SQL aggregation from HistoryStore.

Score formula:
  violation_rate  × 50   (how often this sender is flagged)
  avg_confidence  × 30   (how certain the AI has been about past flags)
  severity_score  × 20   (weighted sum of category severities, normalised)
"""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

# mirrors base_weight in compliance_matrix.yaml
_CATEGORY_SEVERITY: Dict[str, int] = {
    "market_manipulation":    10,
    "bribery":                 9,
    "secrecy":                 8,
    "employee_ethics":         7,
    "change_in_communication": 6,
    "complaints":              4,
}


def compute_risk_profile(stats: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compute a risk profile from aggregated sender stats returned by
    HistoryStore.get_sender_stats_sqlite().
    """
    logger.debug("→ compute_risk_profile  sender=%s  total_emails=%d",
                 stats.get("sender"), stats.get("total", 0))
    total = stats.get("total", 0)
    if total == 0:
        return {
            "risk_score": 0,
            "risk_band":  "UNKNOWN",
            "factors":    [],
            "sender":     stats.get("sender", ""),
        }

    non_compliant    = stats.get("non_compliant", 0)
    avg_conf         = float(stats.get("avg_confidence", 0.0))
    category_counts  = stats.get("category_counts", {})

    violation_rate    = non_compliant / total
    severity_raw      = sum(
        _CATEGORY_SEVERITY.get(cat, 5) * count
        for cat, count in category_counts.items()
    )
    # normalise: max possible is total * 10 (all emails, highest weight)
    normalised_severity = min(1.0, severity_raw / max(total * 10, 1))

    raw_score = (
        violation_rate       * 50 +
        avg_conf             * 30 +
        normalised_severity  * 20
    )
    risk_score = min(100, int(raw_score))
    risk_band  = _band(risk_score)

    factors = []
    if violation_rate > 0.5:
        factors.append(f"High violation rate ({violation_rate:.0%} of {total} emails)")
    if avg_conf > 0.8:
        factors.append(f"High avg AI confidence ({avg_conf:.2f})")
    if category_counts:
        top_cat = max(category_counts, key=lambda c: category_counts[c])
        factors.append(f"Most frequent category: {top_cat} ({category_counts[top_cat]}x)")

    logger.debug(
        "Sender risk  sender=%s  score=%d  band=%s  factors=%s",
        stats.get("sender"), risk_score, risk_band, factors,
    )
    return {
        "sender":         stats.get("sender", ""),
        "risk_score":     risk_score,
        "risk_band":      risk_band,
        "violation_rate": round(violation_rate, 3),
        "top_category":   max(category_counts, key=lambda c: category_counts[c]) if category_counts else None,
        "factors":        factors,
    }


def _band(score: int) -> str:
    if score >= 70:
        return "HIGH_RISK"
    if score >= 40:
        return "ELEVATED"
    if score >= 10:
        return "LOW_RISK"
    return "CLEAN"
