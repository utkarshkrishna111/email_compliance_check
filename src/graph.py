"""
src/graph.py
LangGraph StateGraph — full compliance pipeline.

Node flow:
  detect_thread → retrieve_history → build_context → compliance_agent
    → guardrail_check → [verify | flag_review] → score → persist → END
"""

import logging
import os
from typing import Any, Dict, List

from langgraph.graph import END, StateGraph
from typing_extensions import TypedDict

from .anomaly_detector import detect_volume_anomaly
from .circular_trading_detector import detect_circular_trading
from .compliance_agent import ComplianceAgent
from .config_loader import load_config
from .context_builder import build_thread_context
from .guardrails import ComplianceVerifier, GuardrailValidator
from .history_store import HistoryStore
from .quid_pro_quo_detector import detect_quid_pro_quo
from .scoring_engine import ScoringEngine
from .sender_risk import compute_risk_profile
from .storage import ResultsStorage
from .thread_detector import detect_thread, extract_recipients, is_external_recipient

logger = logging.getLogger(__name__)


# ── State ─────────────────────────────────────────────────────────────────────

class ComplianceState(TypedDict):
    email:            Dict[str, Any]
    thread_id:        str
    recipients:       List[str]
    is_external:      bool
    thread_history:   List[Dict[str, Any]]
    sender_risk:      Dict[str, Any]
    volume_anomaly:   Dict[str, Any]
    extra_context:    str
    finding:          Dict[str, Any]
    guardrail_issues: List[str]
    scored_finding:   Dict[str, Any]


# ── Nodes ─────────────────────────────────────────────────────────────────────

def _detect_thread(state: ComplianceState, store: HistoryStore, internal_domain: str) -> Dict:
    email       = state["email"]
    thread_id   = detect_thread(email)
    recipients  = extract_recipients(email)
    is_ext      = is_external_recipient(email, internal_domain)
    logger.info("Thread detected  id=%s  recipients=%s  external=%s", thread_id, recipients, is_ext)
    return {"thread_id": thread_id, "recipients": recipients, "is_external": is_ext}


def _retrieve_history(state: ComplianceState, store: HistoryStore) -> Dict:
    sender          = state["email"].get("from", "")
    thread_history  = store.get_thread_history(state["thread_id"])
    sender_stats    = store.get_sender_stats(sender)
    weekly_vols     = store.get_weekly_volumes(sender)

    # current week count = thread emails this week (approximate as 1 for new email)
    sender_risk     = compute_risk_profile(sender_stats)
    volume_anomaly  = detect_volume_anomaly(weekly_vols, current_week_count=1)

    logger.info(
        "History  thread_prior=%d  sender_risk=%s  anomaly=%s",
        len(thread_history), sender_risk["risk_band"], volume_anomaly["is_anomalous"],
    )
    return {
        "thread_history":  thread_history,
        "sender_risk":     sender_risk,
        "volume_anomaly":  volume_anomaly,
    }


def _build_context(state: ComplianceState) -> Dict:
    context = build_thread_context(state["thread_history"])

    # append sender risk note if elevated
    risk = state["sender_risk"]
    if risk.get("risk_score", 0) >= 40:
        context += (
            f"\n[SENDER RISK PROFILE: {risk['risk_band']} "
            f"score={risk['risk_score']} — {'; '.join(risk.get('factors', []))}]\n"
        )

    # append anomaly note if triggered
    anomaly = state["volume_anomaly"]
    if anomaly.get("is_anomalous"):
        context += f"\n[COMMUNICATION ANOMALY: {anomaly['reason']}]\n"

    return {"extra_context": context}


def _compliance_agent(state: ComplianceState, agent: ComplianceAgent) -> Dict:
    finding = agent.analyse(state["email"], extra_context=state.get("extra_context", ""))
    return {"finding": finding}


def _guardrail_check(
    state: ComplianceState,
    validator: GuardrailValidator,
) -> Dict:
    _, issues = validator.validate(state["finding"], state["email"])
    return {"guardrail_issues": issues}


def _verify(state: ComplianceState, verifier: ComplianceVerifier) -> Dict:
    verified = verifier.verify(state["finding"], state["email"])
    return {"finding": verified}


def _flag_review(state: ComplianceState) -> Dict:
    logger.warning(
        "Email flagged for manual review  id=%s  issues=%s",
        state["finding"].get("id"), state["guardrail_issues"],
    )
    scored = dict(state["finding"])
    scored.update({
        "priority_score":    0,
        "priority_band":     "REVIEW_REQUIRED",
        "alert_level":       "HIGH",
        "guardrail_issues":  state["guardrail_issues"],
        "score_breakdown":   {},
    })
    return {"scored_finding": scored}


def _score(state: ComplianceState, engine: ScoringEngine) -> Dict:
    scored = engine.score(dict(state["finding"]))

    # 10 % boost for HIGH_RISK senders on any non-compliant finding
    risk = state["sender_risk"]
    if risk.get("risk_band") == "HIGH_RISK" and scored.get("priority_score", 0) > 0:
        original = scored["priority_score"]
        scored["priority_score"] = min(100, int(original * 1.10))
        scored["sender_risk_boost"] = True
        logger.info("Score boosted: %d → %d (HIGH_RISK sender)", original, scored["priority_score"])

    if state["volume_anomaly"].get("is_anomalous"):
        scored["volume_anomaly_flag"] = True

    scored["sender_risk"]    = state["sender_risk"]
    scored["volume_anomaly"] = state["volume_anomaly"]
    return {"scored_finding": scored}


def _persist(
    state: ComplianceState,
    store: HistoryStore,
    result_storage: ResultsStorage,
) -> Dict:
    store.save_finding(
        state["scored_finding"],
        state["thread_id"],
        state["recipients"],
        state["is_external"],
    )
    result_storage.save([state["scored_finding"]])
    logger.info("Persisted  id=%s  band=%s",
                state["scored_finding"].get("id"),
                state["scored_finding"].get("priority_band"))
    return {}


def _guardrail_router(state: ComplianceState) -> str:
    return "verify" if not state.get("guardrail_issues") else "flag_review"


# ── Factory ───────────────────────────────────────────────────────────────────

def build_graph(
    config_path:     str | None = None,
    db_path:         str = "result/history.db",
    chroma_path:     str = "result/chroma",
    result_dir:      str = "result",
    internal_domain: str = "",
):
    """
    Build and compile the LangGraph compliance pipeline.

    Usage
    -----
    graph = build_graph(internal_domain="yourbank.com")
    result = graph.invoke({"email": email_dict, ...initial_state_defaults...})
    """
    config         = load_config(config_path)
    store          = HistoryStore(db_path=db_path, chroma_path=chroma_path)
    agent          = ComplianceAgent(config)
    validator      = GuardrailValidator(config)
    verifier       = ComplianceVerifier()
    engine         = ScoringEngine(config)
    result_storage = ResultsStorage(result_dir)

    g = StateGraph(ComplianceState)

    g.add_node("detect_thread",    lambda s: _detect_thread(s, store, internal_domain))
    g.add_node("retrieve_history", lambda s: _retrieve_history(s, store))
    g.add_node("build_context",    _build_context)
    g.add_node("compliance_agent", lambda s: _compliance_agent(s, agent))
    g.add_node("guardrail_check",  lambda s: _guardrail_check(s, validator))
    g.add_node("verify",           lambda s: _verify(s, verifier))
    g.add_node("flag_review",      _flag_review)
    g.add_node("score",            lambda s: _score(s, engine))
    g.add_node("persist",          lambda s: _persist(s, store, result_storage))

    g.set_entry_point("detect_thread")
    g.add_edge("detect_thread",    "retrieve_history")
    g.add_edge("retrieve_history", "build_context")
    g.add_edge("build_context",    "compliance_agent")
    g.add_edge("compliance_agent", "guardrail_check")
    g.add_conditional_edges(
        "guardrail_check",
        _guardrail_router,
        {"verify": "verify", "flag_review": "flag_review"},
    )
    g.add_edge("verify",      "score")
    g.add_edge("flag_review", "score")
    g.add_edge("score",       "persist")
    g.add_edge("persist",     END)

    return g.compile()


def make_initial_state(email: Dict[str, Any]) -> ComplianceState:
    """Convenience helper — returns a fully initialised state for one email."""
    return ComplianceState(
        email            = email,
        thread_id        = "",
        recipients       = [],
        is_external      = False,
        thread_history   = [],
        sender_risk      = {},
        volume_anomaly   = {},
        extra_context    = "",
        finding          = {},
        guardrail_issues = [],
        scored_finding   = {},
    )


def run_cross_pattern_analysis(
    db_path: str = "result/history.db",
    qpq_window_days: int = 30,
    ct_min_flagged: int = 1,
    ct_max_cycle_length: int = 6,
) -> Dict[str, Any]:
    """
    Run Quid Pro Quo and Circular Trading detectors against the history DB.

    Call this after a batch of emails has been processed through the graph
    (so findings are persisted to SQLite via HistoryStore).

    Returns a dict with keys 'quid_pro_quo' and 'circular_trading',
    each holding a list of alert dicts.
    """
    logger.info("Running cross-pattern analysis  db=%s", db_path)

    qpq_alerts = detect_quid_pro_quo(db_path, days_window=qpq_window_days)
    ct_alerts  = detect_circular_trading(
        db_path,
        min_flagged=ct_min_flagged,
        max_cycle_length=ct_max_cycle_length,
    )

    logger.info(
        "Cross-pattern analysis complete  qpq_alerts=%d  circular_trading_alerts=%d",
        len(qpq_alerts), len(ct_alerts),
    )
    return {
        "quid_pro_quo":      qpq_alerts,
        "circular_trading":  ct_alerts,
    }
