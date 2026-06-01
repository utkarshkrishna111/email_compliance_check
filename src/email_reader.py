"""
src/email_reader.py
-------------------
Reads email content from PDF or Excel files.

PDF strategy  : split pages at "From:" boundary markers; fall back to whole
                document as one email.
Excel strategy: one row per email; columns From / To / Subject / Date / Body
                (case-insensitive aliases supported).

Public API
----------
load_emails(file_path)          → List[dict]
load_emails_from_folder(folder) → List[dict]   ← scans a whole directory
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
    """
    Detect file type and dispatch to the appropriate extractor.
    """
    ext = Path(file_path).suffix.lower()
    logger.debug("load_emails called for '%s'  (ext=%s)", file_path, ext)

    if ext == ".pdf":
        return extract_emails_from_pdf(file_path)
    elif ext in (".xlsx", ".xls", ".xlsm"):
        return extract_emails_from_excel(file_path)
    else:
        raise ValueError(
            f"Unsupported file type '{ext}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )


def load_emails_from_folder(folder: str) -> List[Dict[str, Any]]:
    """
    Scan *folder* for all supported email files and return a flat list of
    all emails found across every file.

    Returns an empty list (not an error) if the folder contains no
    supported files.
    """
    folder_path = Path(folder)
    if not folder_path.is_dir():
        raise NotADirectoryError(f"Not a directory: {folder_path}")

    all_emails: List[Dict[str, Any]] = []
    files_found = sorted(
        p for p in folder_path.iterdir()
        if p.suffix.lower() in SUPPORTED_EXTENSIONS and p.is_file()
    )

    if not files_found:
        logger.warning("No supported email files found in folder: %s", folder_path)
        return all_emails

    logger.info("Found %d file(s) in '%s': %s",
                len(files_found), folder_path,
                [f.name for f in files_found])

    for file_path in files_found:
        try:
            emails = load_emails(str(file_path))
            logger.info("  %s → %d email(s)", file_path.name, len(emails))
            all_emails.extend(emails)
        except Exception as exc:
            logger.error("  Failed to read '%s': %s", file_path.name, exc)

    logger.info("Total emails loaded from folder: %d", len(all_emails))
    return all_emails


# ─────────────────────────────────────────────────────────────────────────────
# PDF extractor
# ─────────────────────────────────────────────────────────────────────────────

def extract_emails_from_pdf(file_path: str) -> List[Dict[str, Any]]:
    try:
        import fitz  # PyMuPDF
    except ImportError:
        raise ImportError("PyMuPDF is required: pip install PyMuPDF")

    doc = fitz.open(file_path)
    full_text = "\n".join(page.get_text() for page in doc)
    doc.close()

    raw_blocks = _split_on_email_boundaries(full_text)
    emails: List[Dict[str, Any]] = []
    for idx, block in enumerate(raw_blocks):
        email = _parse_email_block(block)
        email["id"]     = f"pdf_{Path(file_path).stem}_{idx + 1}"
        email["source"] = str(file_path)
        emails.append(email)
        logger.debug("PDF email[%d]: id=%s subject='%s'", idx, email["id"], email["subject"])

    logger.info("Extracted %d email(s) from PDF '%s'", len(emails), Path(file_path).name)
    return emails


# ─────────────────────────────────────────────────────────────────────────────
# Excel extractor
# ─────────────────────────────────────────────────────────────────────────────

def extract_emails_from_excel(file_path: str) -> List[Dict[str, Any]]:
    try:
        import pandas as pd
    except ImportError:
        raise ImportError("pandas is required: pip install pandas openpyxl")

    df = pd.read_excel(file_path, engine="openpyxl")
    df.columns = [c.strip().lower() for c in df.columns]

    col_map = {
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
            "from":    "",
            "to":      "",
            "subject": "",
            "date":    "",
            "body":    "",
        }
        import pandas as pd  # noqa: F811
        for field, aliases in col_map.items():
            col = _find(aliases)
            if col:
                email[field] = str(row[col]) if pd.notna(row[col]) else ""
        emails.append(email)
        logger.debug("Excel email[%d]: id=%s subject='%s'", idx, email["id"], email["subject"])

    logger.info("Extracted %d email(s) from Excel '%s'", len(emails), Path(file_path).name)
    return emails


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _split_on_email_boundaries(text: str) -> List[str]:
    pattern = re.compile(r"(?=^From:\s)", re.IGNORECASE | re.MULTILINE)
    blocks   = pattern.split(text)
    blocks   = [b.strip() for b in blocks if b.strip()]
    return blocks if blocks else [text.strip()]


def _parse_email_block(block: str) -> Dict[str, str]:
    result = {"from": "", "to": "", "subject": "", "date": "", "body": ""}
    header_pattern = re.compile(
        r"^(From|To|Subject|Date|Cc|Bcc):\s*(.+)$",
        re.IGNORECASE | re.MULTILINE,
    )
    header_end = 0
    for match in header_pattern.finditer(block):
        key   = match.group(1).lower()
        value = match.group(2).strip()
        if key in result:
            result[key] = value
        header_end = max(header_end, match.end())
    result["body"] = block[header_end:].strip() if header_end else block.strip()
    return result
