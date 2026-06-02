"""
src/thread_detector.py
Derives a stable thread_id from email metadata and classifies recipients.
"""

import hashlib
import re
from typing import Any, Dict, List


def detect_thread(email: Dict[str, Any]) -> str:
    """
    Derive a stable thread_id by hashing the normalised subject + sorted
    participant set.  Emails that share a subject and participants are treated
    as the same thread even without Message-ID / In-Reply-To headers.
    """
    subject = _normalise_subject(email.get("subject", ""))
    participants = _all_addresses(email)
    key = subject + "|" + "|".join(sorted(participants))
    return hashlib.md5(key.encode()).hexdigest()[:16]


def extract_recipients(email: Dict[str, Any]) -> List[str]:
    return _parse_addresses(email.get("to", ""))


def is_external_recipient(email: Dict[str, Any], internal_domain: str) -> bool:
    """Return True if any recipient address is outside internal_domain."""
    if not internal_domain:
        return False
    recipients = _parse_addresses(email.get("to", ""))
    return any(internal_domain.lower() not in addr.lower() for addr in recipients)


# ── helpers ───────────────────────────────────────────────────────────────────

def _normalise_subject(subject: str) -> str:
    # strip Re:/Fwd: prefixes, lowercase, collapse whitespace
    cleaned = re.sub(r"^(re|fwd?|fw)[\s:]+", "", subject.strip(), flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).lower().strip()


def _all_addresses(email: Dict[str, Any]) -> List[str]:
    addrs = _parse_addresses(email.get("from", "")) + _parse_addresses(email.get("to", ""))
    return list({a.lower() for a in addrs if a})


def _parse_addresses(field: str) -> List[str]:
    if not field:
        return []
    found = re.findall(r"[\w.+\-]+@[\w.\-]+\.\w+", field)
    return found if found else [field.strip()]
