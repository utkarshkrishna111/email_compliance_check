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

from .compliance_agent import ComplianceAgent
from .config_loader import load_config
from .context_builder import build_thread_context
from .guardrails import ComplianceVerifier, GuardrailValidator
from .history_store import HistoryStore
from .quid_pro_quo_detector import detect_quid_pro_quo
from .scoring_engine import ScoringEngine
from .sender_risk import compute_risk_profile
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
    extra_context:    str
    finding:          Dict[str, Any]
    guardrail_issues: List[str]
    scored_finding:   Dict[str, Any]


# ── Nodes ─────────────────────────────────────────────────────────────────────

def _detect_thread(state: ComplianceState, store: HistoryStore, internal_domain: str) -> Dict:
    email       = state["email"]
    logger.info("▶ [1/8] detect_thread  email_id=%s  subject='%s'",
                email.get("id"), email.get("subject", "")[:60])
    logger.debug("  internal_domain=%r  from=%s  to=%s",
                 internal_domain, email.get("from"), email.get("to"))
    thread_id   = detect_thread(email)
    recipients  = extract_recipients(email)
    is_ext      = is_external_recipient(email, internal_domain)
    logger.info("  thread_id=%s  recipients=%s  external=%s", thread_id, recipients, is_ext)
    return {"thread_id": thread_id, "recipients": recipients, "is_external": is_ext}


def _retrieve_history(state: ComplianceState, store: HistoryStore) -> Dict:
    sender          = state["email"].get("from", "")
    logger.info("▶ [2/8] retrieve_history  email_id=%s  sender=%s  thread_id=%s",
                state["email"].get("id"), sender, state.get("thread_id"))
    thread_history  = store.get_thread_history(state["thread_id"])
    sender_stats    = store.get_sender_stats(sender)
    logger.debug("  thread_history_count=%d  sender_total_emails=%d",
                 len(thread_history), sender_stats.get("total", 0))

    sender_risk = compute_risk_profile(sender_stats)

    logger.info("  thread_prior=%d  sender_risk=%s", len(thread_history), sender_risk["risk_band"])
    logger.debug("  sender_risk_detail=%s", sender_risk)
    return {
        "thread_history": thread_history,
        "sender_risk":    sender_risk,
    }


def _build_context(state: ComplianceState) -> Dict:
    logger.info("▶ [3/8] build_context  email_id=%s  history_count=%d",
                state["email"].get("id"), len(state.get("thread_history", [])))
    context = build_thread_context(state["thread_history"])

    # append sender risk note if elevated
    risk = state["sender_risk"]
    if risk.get("risk_score", 0) >= 40:
        context += (
            f"\n[SENDER RISK PROFILE: {risk['risk_band']} "
            f"score={risk['risk_score']} — {'; '.join(risk.get('factors', []))}]\n"
        )
        logger.debug("  risk profile injected into context  band=%s  score=%d",
                     risk["risk_band"], risk["risk_score"])

    logger.debug("  context_len=%d chars  has_risk=%s",
                 len(context), risk.get("risk_score", 0) >= 40)
    return {"extra_context": context}


def _compliance_agent(state: ComplianceState, agent: ComplianceAgent) -> Dict:
    logger.info("▶ [4/8] compliance_agent  email_id=%s", state["email"].get("id"))
    logger.debug("  extra_context_len=%d chars", len(state.get("extra_context", "")))
    finding = agent.analyse(state["email"], extra_context=state.get("extra_context", ""))
    logger.debug("  finding: compliant=%s  categories=%s  confidence=%.2f",
                 finding.get("is_compliant"), finding.get("categories"), finding.get("confidence", 0.0))
    return {"finding": finding}


def _guardrail_check(
    state: ComplianceState,
    validator: GuardrailValidator,
) -> Dict:
    logger.info("▶ [5/8] guardrail_check  email_id=%s", state["finding"].get("id"))
    _, issues = validator.validate(state["finding"], state["email"])
    if issues:
        logger.debug("  issues=%s", issues)
    return {"guardrail_issues": issues}


def _verify(state: ComplianceState, verifier: ComplianceVerifier) -> Dict:
    logger.info("▶ [6a/8] verify  email_id=%s", state["finding"].get("id"))
    logger.debug("  pre-verify: categories=%s  confidence=%.2f",
                 state["finding"].get("categories"), state["finding"].get("confidence", 0.0))
    verified = verifier.verify(state["finding"], state["email"])
    logger.debug("  post-verify: categories=%s  confidence=%.2f",
                 verified.get("categories"), verified.get("confidence", 0.0))
    return {"finding": verified}


def _flag_review(state: ComplianceState) -> Dict:
    logger.info("▶ [6b/8] flag_review  email_id=%s  (guardrail failed)", state["finding"].get("id"))
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
    logger.info("▶ [7/8] score  email_id=%s", state["finding"].get("id"))
    scored = engine.score(dict(state["finding"]))

    # 10 % boost for HIGH_RISK senders on any non-compliant finding
    risk = state["sender_risk"]
    if risk.get("risk_band") == "HIGH_RISK" and scored.get("priority_score", 0) > 0:
        original = scored["priority_score"]
        scored["priority_score"] = min(100, int(original * 1.10))
        scored["sender_risk_boost"] = True
        logger.info("Score boosted: %d → %d (HIGH_RISK sender)", original, scored["priority_score"])

    scored["sender_risk"] = state["sender_risk"]
    return {"scored_finding": scored}


def _persist(state: ComplianceState, store: HistoryStore) -> Dict:
    logger.info("▶ [8/8] persist  email_id=%s  band=%s  score=%d",
                state["scored_finding"].get("id"),
                state["scored_finding"].get("priority_band"),
                state["scored_finding"].get("priority_score", 0))
    store.save_finding(
        state["scored_finding"],
        state["thread_id"],
        state["recipients"],
        state["is_external"],
    )
    logger.info("Persisted to SQLite+Chroma  id=%s", state["scored_finding"].get("id"))
    return {}


def _guardrail_router(state: ComplianceState) -> str:
    route = "verify" if not state.get("guardrail_issues") else "flag_review"
    logger.debug("  guardrail_router → %s  email_id=%s", route, state["finding"].get("id"))
    return route


# ── Factory ───────────────────────────────────────────────────────────────────

def build_graph(
    config_path:     str | None = None,
    db_path:         str = "result/history.db",
    chroma_path:     str = "result/chroma",
    internal_domain: str = "",
):
    """
    Build and compile the LangGraph compliance pipeline.

    Usage
    -----
    graph = build_graph(internal_domain="yourbank.com")
    result = graph.invoke(make_initial_state(email_dict))
    result["scored_finding"]  # the final scored finding
    """
    config    = load_config(config_path)
    store     = HistoryStore(db_path=db_path, chroma_path=chroma_path)
    agent     = ComplianceAgent(config)
    validator = GuardrailValidator(config)
    verifier  = ComplianceVerifier()
    engine    = ScoringEngine(config)

    g = StateGraph(ComplianceState)

    g.add_node("detect_thread",    lambda s: _detect_thread(s, store, internal_domain))
    g.add_node("retrieve_history", lambda s: _retrieve_history(s, store))
    g.add_node("build_context",    _build_context)
    g.add_node("compliance_agent", lambda s: _compliance_agent(s, agent))
    g.add_node("guardrail_check",  lambda s: _guardrail_check(s, validator))
    g.add_node("verify",           lambda s: _verify(s, verifier))
    g.add_node("flag_review",      _flag_review)
    g.add_node("score",            lambda s: _score(s, engine))
    g.add_node("persist",          lambda s: _persist(s, store))

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
        extra_context    = "",
        finding          = {},
        guardrail_issues = [],
        scored_finding   = {},
    )


def run_cross_pattern_analysis(
    db_path: str = "result/history.db",
    qpq_window_days: int = 30,
) -> Dict[str, Any]:
    """
    Run Quid Pro Quo detector against the history DB.

    Call this after a batch of emails has been processed through the graph
    (so findings are persisted to SQLite via HistoryStore).

    Returns a dict with key 'quid_pro_quo' holding a list of alert dicts.
    """
    logger.info("Running cross-pattern analysis  db=%s", db_path)

    qpq_alerts = detect_quid_pro_quo(db_path, days_window=qpq_window_days)

    logger.info("Cross-pattern analysis complete  qpq_alerts=%d", len(qpq_alerts))
    return {
        "quid_pro_quo": qpq_alerts,
    }
