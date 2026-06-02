"""
src/email_reader.py
-------------------
Reads email content from PDF or Excel files.

PDF  : uses pdfplumber (pure-Python, no DLL/VC++ dependency)
Excel: uses pandas + openpyxl

Public API
----------
load_emails(file_path)           -> List[dict]
load_emails_from_folder(folder)  -> List[dict]
"""

import logging
import re
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".xlsx", ".xls", ".xlsm"}


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def load_emails(file_path: str) -> List[Dict[str, Any]]:
    """Detect file type and dispatch to the correct extractor."""
    ext = Path(file_path).suffix.lower()
    logger.debug("load_emails: '%s' (ext=%s)", file_path, ext)
    if ext == ".pdf":
        return _extract_pdf(file_path)
    elif ext in (".xlsx", ".xls", ".xlsm"):
        return _extract_excel(file_path)
    else:
        raise ValueError(
            f"Unsupported file type '{ext}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )


def load_emails_from_folder(folder: str) -> List[Dict[str, Any]]:
    """Scan a folder and return all emails from every supported file."""
    folder_path = Path(folder)
    if not folder_path.is_dir():
        raise NotADirectoryError(f"Not a directory: {folder_path}")

    files = sorted(
        p for p in folder_path.iterdir()
        if p.suffix.lower() in SUPPORTED_EXTENSIONS and p.is_file()
    )
    if not files:
        logger.warning("No supported email files in folder: %s", folder_path)
        return []

    logger.info("Found %d file(s) in '%s': %s",
                len(files), folder_path, [f.name for f in files])

    all_emails: List[Dict[str, Any]] = []
    for fp in files:
        try:
            emails = load_emails(str(fp))
            logger.info("  %s -> %d email(s)", fp.name, len(emails))
            all_emails.extend(emails)
        except Exception as exc:
            logger.error("  Failed to read '%s': %s", fp.name, exc)

    logger.info("Total emails loaded from folder: %d", len(all_emails))
    return all_emails


# ─────────────────────────────────────────────────────────────────────────────
# PDF extractor  (pdfplumber - pure Python, no native DLLs required)
# ─────────────────────────────────────────────────────────────────────────────

def _extract_pdf(file_path: str) -> List[Dict[str, Any]]:
    try:
        import pdfplumber
    except ImportError:
        raise ImportError(
            "pdfplumber is required for PDF reading.\n"
            "Run: pip install pdfplumber --prefer-binary"
        )

    with pdfplumber.open(file_path) as pdf:
        full_text = "\n".join(
            page.extract_text() or "" for page in pdf.pages
        )

    blocks = _split_on_boundaries(full_text)
    emails: List[Dict[str, Any]] = []
    for idx, block in enumerate(blocks):
        email = _parse_block(block)
        email["id"]     = f"pdf_{Path(file_path).stem}_{idx + 1}"
        email["source"] = str(file_path)
        logger.debug("PDF email[%d]: id=%s subject='%s'",
                     idx, email["id"], email["subject"])
        emails.append(email)

    logger.info("Extracted %d email(s) from PDF '%s'",
                len(emails), Path(file_path).name)
    return emails


# ─────────────────────────────────────────────────────────────────────────────
# Excel extractor
# ─────────────────────────────────────────────────────────────────────────────

def _extract_excel(file_path: str) -> List[Dict[str, Any]]:
    try:
        import pandas as pd
    except ImportError:
        raise ImportError(
            "pandas and openpyxl are required for Excel reading.\n"
            "Run: pip install pandas openpyxl --prefer-binary"
        )

    df = pd.read_excel(file_path, engine="openpyxl")
    df.columns = [str(c).strip().lower() for c in df.columns]

    col_aliases = {
        "from":    ["from", "sender", "from_address"],
        "to":      ["to", "recipient", "to_address"],
        "subject": ["subject", "sub", "email_subject"],
        "date":    ["date", "sent_date", "timestamp"],
        "body":    ["body", "content", "email_body", "message"],
    }

    def _find(aliases):
        for a in aliases:
            if a in df.columns:
                return a
        return None

    emails: List[Dict[str, Any]] = []
    for idx, row in df.iterrows():
        email: Dict[str, Any] = {
            "id":      f"xls_{Path(file_path).stem}_{idx + 1}",
            "source":  str(file_path),
            "from":    "", "to": "", "subject": "", "date": "", "body": "",
        }
        for field, aliases in col_aliases.items():
            col = _find(aliases)
            if col:
                val = row[col]
                email[field] = str(val) if pd.notna(val) else ""
        logger.debug("Excel email[%d]: id=%s subject='%s'",
                     idx, email["id"], email["subject"])
        emails.append(email)

    logger.info("Extracted %d email(s) from Excel '%s'",
                len(emails), Path(file_path).name)
    return emails


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _split_on_boundaries(text: str) -> List[str]:
    """Split a document into per-email blocks at 'From:' boundaries."""
    pattern = re.compile(r"(?=^From:\s)", re.IGNORECASE | re.MULTILINE)
    blocks  = pattern.split(text)
    blocks  = [b.strip() for b in blocks if b.strip()]
    return blocks if blocks else [text.strip()]


def _parse_block(block: str) -> Dict[str, str]:
    """Parse email headers from a raw text block."""
    result  = {"from": "", "to": "", "subject": "", "date": "", "body": ""}
    pattern = re.compile(
        r"^(From|To|Subject|Date|Cc|Bcc):\s*(.+)$",
        re.IGNORECASE | re.MULTILINE,
    )
    header_end = 0
    for m in pattern.finditer(block):
        key = m.group(1).lower()
        if key in result:
            result[key] = m.group(2).strip()
        header_end = max(header_end, m.end())
    result["body"] = block[header_end:].strip() if header_end else block.strip()
    return result
