"""
src/scoring_engine.py
---------------------
Calculates the final compliance priority score for each email finding.

Score formula
-------------
  raw  = Σ category.base_weight  for each detected category
  raw *= multi_category_bonus     (if ≥ 2 categories)
  raw *= high_confidence_bonus    (if confidence ≥ high threshold)
  score = min(100, int(raw / max_raw_score × 100))

Priority band : CRITICAL | HIGH | MEDIUM | LOW | COMPLIANT
Alert level   : HIGH | MEDIUM | LOW | NONE
"""

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class ScoringEngine:

    def __init__(self, config: Dict[str, Any]):
        self.categories_cfg  = config.get("categories", {})
        self.scoring_cfg     = config.get("scoring", {})
        self.multipliers     = self.scoring_cfg.get("multipliers", {})
        self.priority_bands  = self.scoring_cfg.get("priority_bands", {})
        self.conf_thresholds = self.scoring_cfg.get("confidence_thresholds", {})
        self.max_raw         = float(self.scoring_cfg.get("max_raw_score", 10))
        logger.debug("ScoringEngine initialised  max_raw=%s  bands=%s",
                     self.max_raw, self.priority_bands)

    def score(self, finding: Dict[str, Any]) -> Dict[str, Any]:
        """Augment finding with priority_score, priority_band, alert_level, score_breakdown."""
        categories = finding.get("categories", [])
        confidence = float(finding.get("confidence", 0.0))

        if not categories or finding.get("is_compliant", True):
            finding.update({
                "priority_score": 0,
                "priority_band":  "COMPLIANT",
                "alert_level":    "NONE",
                "score_breakdown": {},
            })
            logger.debug("Email id=%s scored as COMPLIANT", finding.get("id"))
            return finding

        breakdown: Dict[str, Any] = {}
        raw_score = 0.0

        for cat_id in categories:
            weight    = float(self.categories_cfg.get(cat_id, {}).get("base_weight", 5))
            raw_score += weight
            breakdown[cat_id] = {"base_weight": weight}
            logger.debug("  category=%s  weight=%.1f  running_raw=%.2f", cat_id, weight, raw_score)

        applied: List[str] = []

        if len(categories) >= 2:
            m = float(self.multipliers.get("multi_category_bonus", 1.0))
            raw_score *= m
            applied.append(f"multi_category ×{m}")
            logger.debug("  multi_category bonus applied ×%.2f → raw=%.2f", m, raw_score)

        high_threshold = float(self.conf_thresholds.get("high", 0.8))
        if confidence >= high_threshold:
            m = float(self.multipliers.get("high_confidence_bonus", 1.0))
            raw_score *= m
            applied.append(f"high_confidence ×{m}")
            logger.debug("  high_confidence bonus applied ×%.2f → raw=%.2f", m, raw_score)

        breakdown["multipliers_applied"] = applied
        priority_score = min(100, int((raw_score / self.max_raw) * 100))
        priority_band  = self._band(priority_score)
        alert_level    = self._alert(confidence)

        finding.update({
            "priority_score":  priority_score,
            "priority_band":   priority_band,
            "alert_level":     alert_level,
            "score_breakdown": breakdown,
        })

        logger.info(
            "Scored  id=%-30s  score=%3d  band=%-10s  alert=%-6s  cats=%s",
            finding.get("id"), priority_score, priority_band, alert_level, categories,
        )
        logger.debug("Breakdown: %s", breakdown)
        return finding

    def score_batch(self, findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [self.score(f) for f in findings]

    def _band(self, score: int) -> str:
        for band in ("critical", "high", "medium", "low"):
            if score >= int(self.priority_bands.get(band, 0)):
                return band.upper()
        return "LOW"

    def _alert(self, confidence: float) -> str:
        high   = float(self.conf_thresholds.get("high",   0.8))
        medium = float(self.conf_thresholds.get("medium", 0.5))
        if confidence >= high:
            return "HIGH"
        elif confidence >= medium:
            return "MEDIUM"
        return "LOW"
