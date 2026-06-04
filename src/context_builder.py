"""
src/context_builder.py
Replaces prior email bodies with their cached LLM summaries so only the new
email body is sent in full — reduces token usage on long threads.
"""

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def build_thread_context(thread_history: List[Dict[str, Any]]) -> str:
    """
    Return a compact context block summarising all prior emails in the thread.
    Returns empty string when there is no history (first email in thread).
    """
    logger.debug("→ build_thread_context  history_count=%d", len(thread_history))
    if not thread_history:
        logger.debug("  no prior thread history — returning empty context")
        return ""

    lines = ["=== THREAD HISTORY (prior emails — summarised to save tokens) ==="]
    for prior in thread_history:
        cats = ", ".join(prior.get("categories", [])) or "none"
        status = "COMPLIANT" if prior.get("is_compliant", True) else "NON-COMPLIANT"
        lines.append(
            f"[{prior.get('date', '?')}] "
            f"From: {prior.get('from', '?')} | "
            f"Status: {status} | "
            f"Categories: {cats} | "
            f"Confidence: {prior.get('confidence', 0.0):.2f} | "
            f"Summary: {prior.get('reasoning', '')}"
        )
    lines.append("=== NEW EMAIL (analyse only this) ===")

    result = "\n".join(lines) + "\n"
    logger.debug("  context built: %d prior finding(s)  output_len=%d chars",
                 len(thread_history), len(result))
    return result
