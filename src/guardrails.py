"""
src/guardrails.py
-----------------
Two-stage output quality control:

  GuardrailValidator  – rule-based checks on the AI JSON output
  ComplianceVerifier  – lightweight second LLM call to confirm the finding
"""

import logging
import os
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

VALID_CATEGORIES = {
    "market_manipulation", "bribery", "secrecy",
    "employee_ethics", "change_in_communication", "complaints",
}


# ─────────────────────────────────────────────────────────────────────────────
# Guardrail validator
# ─────────────────────────────────────────────────────────────────────────────

class GuardrailValidator:
    """Rule-based validation of a compliance finding dict."""

    def __init__(self, config: Dict[str, Any]):
        self.min_evidence  = config.get("guardrails", {}).get("min_evidence_lines", 1)
        self.min_reasoning = config.get("guardrails", {}).get("min_reasoning_length", 30)

    def validate(
        self,
        finding: Dict[str, Any],
        original_email: Dict[str, Any],
    ) -> Tuple[bool, List[str]]:
        logger.debug("→ GuardrailValidator.validate  id=%s  categories=%s",
                     finding.get("id"), finding.get("categories", []))
        issues: List[str] = []

        # required keys
        for key in ("categories", "intent", "confidence", "evidence", "reasoning", "is_compliant"):
            if key not in finding:
                issues.append(f"Missing required field: '{key}'")
        if issues:
            return False, issues

        # types
        if not isinstance(finding["categories"], list):
            issues.append("'categories' must be a list")
        if not isinstance(finding["evidence"], list):
            issues.append("'evidence' must be a list")
        if not isinstance(finding["confidence"], (int, float)):
            issues.append("'confidence' must be a number")
        elif not (0.0 <= float(finding["confidence"]) <= 1.0):
            issues.append(f"'confidence' must be in [0,1], got {finding['confidence']}")
        if not isinstance(finding["is_compliant"], bool):
            issues.append("'is_compliant' must be boolean")

        # unknown categories
        unknown = [c for c in finding.get("categories", []) if c not in VALID_CATEGORIES]
        if unknown:
            issues.append(f"Unknown categories: {unknown}")

        # evidence requirement for non-compliant findings
        if not finding.get("is_compliant", True) and finding.get("categories"):
            if len(finding.get("evidence", [])) < self.min_evidence:
                issues.append(
                    f"Non-compliant finding needs ≥{self.min_evidence} evidence "
                    f"line(s); got {len(finding.get('evidence', []))}"
                )

        # reasoning length
        reasoning = finding.get("reasoning", "")
        if len(reasoning.strip()) < self.min_reasoning:
            issues.append(
                f"Reasoning too short ({len(reasoning)} chars); "
                f"minimum is {self.min_reasoning}"
            )

        # soft hallucination guard
        email_text = (
            original_email.get("body", "") + " " + original_email.get("subject", "")
        ).lower()
        for ev in finding.get("evidence", []):
            fingerprint = " ".join(ev.lower().split()[:5])
            if fingerprint and len(fingerprint) > 10 and fingerprint not in email_text:
                logger.warning("Evidence fingerprint not found verbatim (may be paraphrase): '%s'", fingerprint)

        is_valid = len(issues) == 0
        if is_valid:
            logger.debug("Guardrail PASSED for email id=%s", finding.get("id"))
        else:
            logger.warning("Guardrail FAILED for email id=%s: %s", finding.get("id"), issues)
        return is_valid, issues


# ─────────────────────────────────────────────────────────────────────────────
# Verifier (second LLM pass)
# ─────────────────────────────────────────────────────────────────────────────

_VERIFY_SYSTEM = """You are a compliance audit verifier.
Given an email and a preliminary compliance finding, confirm or correct it.
Respond ONLY with valid JSON:
{
  "confirmed": <true|false>,
  "corrected_categories": ["<category_id>", ...],
  "corrected_confidence": <float 0.0-1.0>,
  "verification_note": "<one sentence>"
}"""

_VERIFY_PROMPT = """Email:
Subject: {subject}
Body: {body}

Preliminary finding:
Categories : {categories}
Intent     : {intent}
Confidence : {confidence}
Reasoning  : {reasoning}

Confirm or correct this finding."""


class ComplianceVerifier:
    """Second-pass LLM call to confirm/correct the initial finding."""

    def __init__(self):
        logger.debug("Initialising ComplianceVerifier …")
        self._llm = self._build_llm()

    def verify(
        self,
        finding: Dict[str, Any],
        email: Dict[str, Any],
    ) -> Dict[str, Any]:
        logger.debug("→ ComplianceVerifier.verify  id=%s  categories=%s  confidence=%.2f",
                     finding.get("id"), finding.get("categories", []),
                     float(finding.get("confidence", 0.0)))
        import json

        prompt = _VERIFY_PROMPT.format(
            subject=email.get("subject", ""),
            body=email.get("body", ""),
            categories=finding.get("categories", []),
            intent=finding.get("intent", ""),
            confidence=finding.get("confidence", 0.0),
            reasoning=finding.get("reasoning", ""),
        )
        logger.debug("Verifier prompt for id=%s:\n%s", finding.get("id"), prompt)

        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            messages = [SystemMessage(content=_VERIFY_SYSTEM), HumanMessage(content=prompt)]
            raw = self._llm.invoke(messages).content.strip()
            logger.debug("Verifier raw response for id=%s:\n%s", finding.get("id"), raw)

            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.lower().startswith("json"):
                    raw = raw[4:]
            v = json.loads(raw)

            if not v.get("confirmed", True):
                logger.info("Verifier CORRECTED finding id=%s: %s",
                            finding.get("id"), v.get("verification_note"))
                finding["categories"]  = v.get("corrected_categories", finding["categories"])
                finding["confidence"]  = v.get("corrected_confidence",  finding["confidence"])
                finding["is_compliant"] = len(finding["categories"]) == 0
            else:
                logger.info("Verifier CONFIRMED finding id=%s: %s",
                            finding.get("id"), v.get("verification_note", "OK"))

            finding["verification_note"] = v.get("verification_note", "Confirmed.")

        except Exception as exc:
            exc_str = str(exc)
            if "content_filter" in exc_str or "content management policy" in exc_str:
                logger.warning(
                    "Verification skipped for id=%s: Azure content filter triggered "
                    "(email content flagged by content policy; finding kept as-is)",
                    finding.get("id"),
                )
                finding["verification_note"] = "Verification skipped: content filter triggered on email body."
            else:
                logger.error("Verification failed for id=%s: %s", finding.get("id"), exc)
                finding["verification_note"] = f"Verification skipped: {exc}"

        return finding

    def _build_llm(self):
        try:
            from langchain_openai import AzureChatOpenAI, ChatOpenAI
        except ImportError:
            raise ImportError("langchain-openai required")

        provider = os.environ.get("OPENAI_PROVIDER", "azure").lower()

        if provider == "openai":
            model = (os.environ.get("OPENAI_VERIFIER_MODEL")
                     or os.environ.get("OPENAI_MODEL", "gpt-4o"))
            logger.debug("ComplianceVerifier using provider=openai  model=%s", model)
            return ChatOpenAI(
                api_key=os.environ["OPENAI_API_KEY"],
                model=model,
                temperature=0.0,
                max_tokens=400,
            )

        deployment = (os.environ.get("AZURE_OPENAI_VERIFIER_DEPLOYMENT")
                      or os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini"))
        logger.debug("ComplianceVerifier using provider=azure  deployment=%s", deployment)
        return AzureChatOpenAI(
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"),
            azure_deployment=deployment,
            temperature=0.0,
            max_tokens=400,
        )
