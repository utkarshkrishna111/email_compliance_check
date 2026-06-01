"""
src/compliance_agent.py
-----------------------
LangChain-based AI Agent that analyses each email for compliance violations
using Azure OpenAI GPT-4o.

Output schema (JSON):
{
    "categories":   [str],    # detected non-compliant category IDs
    "intent":       str,      # one-sentence sender intent summary
    "confidence":   float,    # 0.0 – 1.0
    "evidence":     [str],    # source lines / paraphrases from the email
    "reasoning":    str,      # brief explanation
    "is_compliant": bool
}
"""

import json
import logging
import os
from typing import Any, Dict, List

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Prompts
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a financial compliance expert AI agent specialising in
email surveillance for banking and financial institutions.

Your task is to analyse email communications and detect any non-compliant behaviour.

Non-compliance categories to detect:
1. market_manipulation  – attempts to artificially influence prices or markets
2. bribery              – offering or accepting improper payments / quid pro quo
3. secrecy              – sharing confidential or non-public information improperly
4. employee_ethics      – code-of-conduct violations, conflicts of interest
5. change_in_communication – moving conversation off monitored channels
6. complaints           – formal or informal regulatory/client complaints

You MUST respond ONLY with a valid JSON object (no markdown, no preamble):
{
  "categories": ["<category_id>", ...],
  "intent": "<one sentence describing sender intent>",
  "confidence": <float 0.0-1.0>,
  "evidence": ["<exact or closely paraphrased line from email>", ...],
  "reasoning": "<clear explanation of the finding>",
  "is_compliant": <true|false>
}

Rules:
- If the email is fully compliant return categories=[], is_compliant=true, confidence=1.0
- confidence reflects how certain you are of a non-compliance finding
- evidence must be actual text from the email
- reasoning must be at least one clear sentence
- Do not hallucinate; if unsure lower confidence and explain in reasoning
"""

ANALYSIS_TEMPLATE = """Analyse the following email for compliance violations.

--- EMAIL START ---
From:    {from_}
To:      {to}
Subject: {subject}
Date:    {date}

{body}
--- EMAIL END ---

Return your analysis as a JSON object following the schema provided.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Agent
# ─────────────────────────────────────────────────────────────────────────────

class ComplianceAgent:
    """Wraps an Azure OpenAI LLM to perform compliance analysis on emails."""

    def __init__(self):
        logger.debug("Initialising ComplianceAgent …")
        self._llm = self._build_llm()
        logger.info("ComplianceAgent ready  (deployment=%s)",
                    os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o"))

    # ── public ───────────────────────────────────────────────────────────────

    def analyse(self, email: Dict[str, Any]) -> Dict[str, Any]:
        """Analyse one email dict; return merged compliance finding."""
        prompt = ANALYSIS_TEMPLATE.format(
            from_=email.get("from", ""),
            to=email.get("to", ""),
            subject=email.get("subject", ""),
            date=email.get("date", ""),
            body=email.get("body", ""),
        )
        logger.info("Analysing email  id=%-35s  subject='%s'",
                    email.get("id"), email.get("subject", "")[:60])
        logger.debug("Analysis prompt:\n%s", prompt)

        raw = self._invoke(prompt)
        logger.debug("Raw LLM response for %s:\n%s", email.get("id"), raw)

        finding = self._parse(raw, email["id"])
        logger.info(
            "Agent result  id=%-35s  compliant=%s  cats=%s  conf=%.2f",
            email.get("id"), finding.get("is_compliant"),
            finding.get("categories"), finding.get("confidence"),
        )

        return {
            "id":      email["id"],
            "source":  email["source"],
            "from":    email.get("from", ""),
            "to":      email.get("to", ""),
            "subject": email.get("subject", ""),
            "date":    email.get("date", ""),
            **finding,
        }

    def analyse_batch(self, emails: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        logger.info("Starting batch analysis of %d email(s) …", len(emails))
        results = [self.analyse(e) for e in emails]
        nc = sum(1 for r in results if not r.get("is_compliant", True))
        logger.info("Batch complete – %d non-compliant out of %d", nc, len(results))
        return results

    # ── private ──────────────────────────────────────────────────────────────

    def _build_llm(self):
        try:
            from langchain_openai import AzureChatOpenAI
        except ImportError:
            raise ImportError("langchain-openai required: pip install langchain-openai")

        return AzureChatOpenAI(
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"),
            azure_deployment=os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o"),
            temperature=0.0,
            max_tokens=1500,
        )

    def _invoke(self, user_prompt: str) -> str:
        from langchain_core.messages import HumanMessage, SystemMessage
        messages = [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=user_prompt)]
        return self._llm.invoke(messages).content

    def _parse(self, raw: str, email_id: str) -> Dict[str, Any]:
        try:
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("```")[1]
                if cleaned.lower().startswith("json"):
                    cleaned = cleaned[4:]
            data = json.loads(cleaned)
            for key in ("categories", "intent", "confidence", "evidence", "reasoning", "is_compliant"):
                if key not in data:
                    raise ValueError(f"Missing key: {key}")
            return data
        except Exception as exc:
            logger.error("Failed to parse agent response for %s: %s\nRaw: %s",
                         email_id, exc, raw)
            return {
                "categories":   [],
                "intent":       "Unable to determine – parse error.",
                "confidence":   0.0,
                "evidence":     [],
                "reasoning":    f"Parse error: {exc}",
                "is_compliant": True,
            }
