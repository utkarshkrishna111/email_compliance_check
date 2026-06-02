"""
src/circular_trading_detector.py
---------------------------------
Circular / wash-trading detector.

Builds a directed communication graph from the recipient_network table,
restricted to edges where flagged_count >= min_flagged AND the sender has
at least one market_manipulation or circular_trading finding.

Then runs DFS cycle detection (length 3–max_cycle_length) to surface
coordinated round-trip trading arrangements like A → B → C → A.
"""

import logging
import sqlite3
from typing import Any, Dict, List, Set, Tuple

logger = logging.getLogger(__name__)

_CIRCULAR_CATEGORIES = ("market_manipulation", "circular_trading")


def detect_circular_trading(
    db_path: str,
    min_flagged: int = 1,
    max_cycle_length: int = 6,
) -> List[Dict[str, Any]]:
    """
    Find circular trading patterns in the recipient_network graph.

    Parameters
    ----------
    db_path          : path to history.db (SQLite)
    min_flagged      : minimum flagged_count on a recipient_network edge to include it
    max_cycle_length : maximum number of participants per cycle (3 = triangle)

    Returns a list of cycle alert dicts.
    """
    edges = _load_flagged_edges(db_path, min_flagged)
    if not edges:
        logger.info("Circular trading scan: no flagged edges found")
        return []

    graph: Dict[str, Set[str]] = {}
    for sender, recipient in edges:
        graph.setdefault(sender, set()).add(recipient)

    cycles = _find_cycles(graph, max_length=max_cycle_length)
    if not cycles:
        logger.info(
            "Circular trading scan: no cycles found  nodes=%d  edges=%d",
            len(graph), len(edges),
        )
        return []

    alerts: List[Dict[str, Any]] = []
    for cycle in sorted(cycles, key=len):
        description = " → ".join(cycle) + f" → {cycle[0]}"
        severity = "CRITICAL" if len(cycle) <= 4 else "HIGH"
        alert: Dict[str, Any] = {
            "pattern":      "CIRCULAR_TRADING",
            "participants": cycle,
            "cycle_length": len(cycle),
            "description":  description,
            "severity":     severity,
            "reasoning": (
                f"Circular communication pattern detected among {len(cycle)} parties "
                f"with market-manipulation–flagged emails: {description}"
            ),
        }
        alerts.append(alert)
        logger.warning(
            "Circular trading alert  length=%d  path=%s  severity=%s",
            len(cycle), description, severity,
        )

    logger.info(
        "Circular trading scan complete  nodes=%d  edges=%d  cycles=%d",
        len(graph), len(edges), len(alerts),
    )
    return alerts


# ── helpers ───────────────────────────────────────────────────────────────────

def _load_flagged_edges(db_path: str, min_flagged: int) -> List[Tuple[str, str]]:
    """Return (sender, recipient) pairs involved in market-manipulation findings."""
    cats_filter = " OR ".join(
        f"h.categories LIKE '%{cat}%'" for cat in _CIRCULAR_CATEGORIES
    )
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT DISTINCT rn.sender, rn.recipient
            FROM recipient_network rn
            WHERE rn.flagged_count >= ?
              AND EXISTS (
                SELECT 1 FROM historical_llm_response h
                WHERE h.sender = rn.sender
                  AND h.recipients LIKE '%' || rn.recipient || '%'
                  AND h.is_compliant = 0
                  AND ({cats_filter})
              )
            """,
            (min_flagged,),
        ).fetchall()
    logger.debug("Loaded %d flagged edges from recipient_network", len(rows))
    return rows


def _find_cycles(
    graph: Dict[str, Set[str]],
    max_length: int,
) -> List[List[str]]:
    """
    Return unique directed cycles of length 3..max_length.

    Each cycle is represented starting from its lexicographically smallest node,
    so A→B→C→A and B→C→A→B are stored as the same tuple.
    """
    found: Set[Tuple[str, ...]] = set()
    for start in sorted(graph):
        _dfs(graph, start, start, [start], found, max_length)
    return [list(c) for c in found]


def _dfs(
    graph: Dict[str, Set[str]],
    current: str,
    start: str,
    path: List[str],
    found: Set[Tuple[str, ...]],
    max_length: int,
) -> None:
    if len(path) > max_length:
        return
    for nbr in graph.get(current, set()):
        if nbr == start and len(path) >= 3:
            # Only record cycle when start is its lexicographic minimum
            if all(start <= node for node in path):
                found.add(tuple(path))
        elif nbr not in path and nbr > start:
            # Restrict intermediates to nodes > start to avoid duplicate cycles
            _dfs(graph, nbr, start, path + [nbr], found, max_length)
