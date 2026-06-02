"""
src/anomaly_detector.py
Feature #2 — Communication Volume Anomaly Detection.

Flags senders whose current-week email volume is statistically unusual
compared to their own history, using a Z-score threshold.

This catches surveillance-evasion patterns that keyword matching misses:
a sender who suddenly floods monitored channels (or goes unusually quiet)
before a flagged event.
"""

import logging
import math
from typing import Any, Dict

logger = logging.getLogger(__name__)

_SPIKE_Z_THRESHOLD = 2.0   # standard deviations above mean = anomalous
_MIN_HISTORY_WEEKS  = 3    # need at least this many weeks to make a judgement


def detect_volume_anomaly(
    weekly_volumes: Dict[str, int],
    current_week_count: int = 1,
) -> Dict[str, Any]:
    """
    Compare current_week_count against the sender's historical weekly volumes.

    Parameters
    ----------
    weekly_volumes    : {week_str: count} from HistoryStore.get_weekly_volumes()
    current_week_count: how many emails the sender has sent this week so far

    Returns a dict with is_anomalous, z_score, and a human-readable reason.
    """
    if len(weekly_volumes) < _MIN_HISTORY_WEEKS:
        return {
            "is_anomalous": False,
            "z_score":      None,
            "reason":       f"Insufficient history ({len(weekly_volumes)} week(s); need {_MIN_HISTORY_WEEKS})",
        }

    values = list(weekly_volumes.values())
    mean   = sum(values) / len(values)
    std    = math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))

    if std == 0:
        return {
            "is_anomalous": False,
            "z_score":      0.0,
            "reason":       "Volume completely flat — no variance to compare against",
        }

    z_score     = (current_week_count - mean) / std
    is_anomalous = z_score > _SPIKE_Z_THRESHOLD

    result = {
        "is_anomalous":        is_anomalous,
        "z_score":             round(z_score, 2),
        "mean_weekly":         round(mean, 1),
        "std_weekly":          round(std, 2),
        "current_week_count":  current_week_count,
        "reason": (
            f"Volume spike: {current_week_count} emails this week "
            f"vs avg {mean:.1f} ± {std:.1f} (z={z_score:.2f})"
            if is_anomalous
            else "Normal volume"
        ),
    }

    if is_anomalous:
        logger.warning("Volume anomaly: %s", result["reason"])
    else:
        logger.debug("Volume normal: z=%.2f", z_score)

    return result
