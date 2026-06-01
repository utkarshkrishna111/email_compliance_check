"""
main.py
=======
Entry point for the Email Compliance AI Agent.

Modes
-----
  Server  (default)    Start the Flask API for the HTML dashboard
  File    (--file)     Analyse a single PDF / Excel file
  Folder  (--data-dir) Scan an entire folder and analyse every file found

Usage examples
--------------
  # Start API server (INFO logging, default folders)
  python main.py --server

  # Analyse all files in email_data/ with INFO log
  python main.py --data-dir email_data

  # Analyse all files in email_data/ with DEBUG log
  python main.py --data-dir email_data --log-level DEBUG

  # Analyse a single file, custom log dir and filename
  python main.py --file email_data/test_emails.xlsx --log-level DEBUG \\
                 --log-dir logs --log-file sprint01

  # Use LOG_LEVEL from .env (set by setup.ps1)
  python main.py --data-dir email_data

Logging
-------
  Console  – colourised, at requested level
  logs/<stem>.info.log   – always written  (INFO+)
  logs/<stem>.debug.log  – only when --log-level DEBUG
  logs/latest.info.log   – symlink to most recent info log
  logs/latest.debug.log  – symlink to most recent debug log

  Log directory  : controlled by --log-dir  (default: <project>/logs)
  Log filename   : controlled by --log-file (default: compliance_<YYYYMMDD_HHMMSS>)
  Both rotate at 10 MB, keeping 5 backups each.

Folders
-------
  email_data/   input email files (PDF / Excel) – default --data-dir value
  result/       per-run JSON output files
  logs/         rotating log files
"""

import argparse
import logging
import logging.handlers
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

# ── load .env first so LOG_LEVEL and folder paths are available ──────────────
load_dotenv()

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

# Defaults can be overridden by .env
_DEFAULT_EMAIL_DATA_DIR = PROJECT_ROOT / os.environ.get("EMAIL_DATA_DIR", "email_data")
_DEFAULT_RESULT_DIR     = PROJECT_ROOT / os.environ.get("RESULT_DIR",     "result")
_DEFAULT_LOG_DIR        = PROJECT_ROOT / os.environ.get("LOG_DIR",        "logs")
_DEFAULT_LOG_LEVEL      = os.environ.get("LOG_LEVEL", "INFO").upper()


# ═══════════════════════════════════════════════════════════════════════════════
# Logging
# ═══════════════════════════════════════════════════════════════════════════════

_LOG_FORMAT_CONSOLE = "%(asctime)s [%(levelname)-8s] %(name)s – %(message)s"
_LOG_FORMAT_FILE    = (
    "%(asctime)s [%(levelname)-8s] %(name)s "
    "[%(filename)s:%(lineno)d] – %(message)s"
)
_DATE_FMT = "%Y-%m-%d %H:%M:%S"

_LEVEL_MAP = {
    "DEBUG":    logging.DEBUG,
    "INFO":     logging.INFO,
    "WARNING":  logging.WARNING,
    "ERROR":    logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


class _ColourFormatter(logging.Formatter):
    """ANSI-coloured console formatter; degrades gracefully on Windows CMD."""
    _COLOURS = {
        logging.DEBUG:    "\033[36m",    # cyan
        logging.INFO:     "\033[32m",    # green
        logging.WARNING:  "\033[33m",    # yellow
        logging.ERROR:    "\033[31m",    # red
        logging.CRITICAL: "\033[1;31m",  # bold red
    }
    _RESET    = "\033[0m"
    _ENABLED  = (
        (sys.stdout.isatty() and os.name != "nt")
        or os.environ.get("TERM_PROGRAM") in ("vscode", "iTerm.app")
        or os.environ.get("WT_SESSION") is not None   # Windows Terminal
    )

    def format(self, record: logging.LogRecord) -> str:
        msg = super().format(record)
        if self._ENABLED:
            msg = f"{self._COLOURS.get(record.levelno, '')}{msg}{self._RESET}"
        return msg


def _symlink(target: Path, link: Path) -> None:
    """Create / refresh a symlink; silently skip if OS/permissions deny it."""
    try:
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(target.name)
    except (OSError, NotImplementedError):
        pass


def configure_logging(
    log_level: str  = "INFO",
    log_dir:   str  | None = None,
    log_file:  str  | None = None,
) -> tuple[Path, Path | None]:
    """
    Attach handlers to the root logger.

    Always creates  <log_dir>/<stem>.info.log   (INFO+).
    Only creates    <log_dir>/<stem>.debug.log  when log_level == DEBUG.
    Symlinks latest.info.log / latest.debug.log to the newest file.

    Returns (info_log_path, debug_log_path | None).
    """
    level        = _LEVEL_MAP.get(log_level.upper(), logging.INFO)
    log_dir_path = Path(log_dir) if log_dir else _DEFAULT_LOG_DIR
    log_dir_path.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem  = Path(log_file).stem if log_file else f"compliance_{stamp}"

    info_log  = log_dir_path / f"{stem}.info.log"
    debug_log = log_dir_path / f"{stem}.debug.log" if level == logging.DEBUG else None

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)   # capture all; handlers filter
    root.handlers.clear()

    # console
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(level)
    ch.setFormatter(_ColourFormatter(_LOG_FORMAT_CONSOLE, datefmt=_DATE_FMT))
    root.addHandler(ch)

    # INFO file (always)
    ih = logging.handlers.RotatingFileHandler(
        info_log, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    ih.setLevel(logging.INFO)
    ih.setFormatter(logging.Formatter(_LOG_FORMAT_FILE, datefmt=_DATE_FMT))
    root.addHandler(ih)

    # DEBUG file (only when requested)
    if debug_log:
        dh = logging.handlers.RotatingFileHandler(
            debug_log, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        dh.setLevel(logging.DEBUG)
        dh.setFormatter(logging.Formatter(_LOG_FORMAT_FILE, datefmt=_DATE_FMT))
        root.addHandler(dh)

    _symlink(info_log,  log_dir_path / "latest.info.log")
    if debug_log:
        _symlink(debug_log, log_dir_path / "latest.debug.log")

    # Quieten noisy third-party libs
    for lib in ("httpcore", "httpx", "openai", "urllib3", "werkzeug", "multipart"):
        logging.getLogger(lib).setLevel(logging.WARNING)

    return info_log, debug_log


# ═══════════════════════════════════════════════════════════════════════════════
# Pipeline
# ═══════════════════════════════════════════════════════════════════════════════

def _run_pipeline(
    emails_source: list,        # list of file paths (str)
    result_dir:    Path,
    from_folder:   bool = False,
) -> None:
    """
    Core pipeline: ingest → analyse → validate → verify → score → store → print.
    Works for a single file or a pre-loaded list of file paths.
    """
    logger = logging.getLogger("main.pipeline")

    from src.compliance_agent import ComplianceAgent
    from src.config_loader import load_config
    from src.email_reader import load_emails, load_emails_from_folder
    from src.guardrails import ComplianceVerifier, GuardrailValidator
    from src.scoring_engine import ScoringEngine
    from src.storage import ResultsStorage

    logger.info("══════════════════════════════════════════════════════════")
    logger.info("  Email Compliance AI Agent  –  Pipeline Start")
    logger.info("══════════════════════════════════════════════════════════")

    # ── config ────────────────────────────────────────────────────────────────
    logger.debug("Loading compliance matrix …")
    config = load_config()
    logger.info("Config loaded: %d categories", len(config.get("categories", {})))
    logger.debug("Full config dump: %s", config)

    # ── ingest ────────────────────────────────────────────────────────────────
    all_emails = []
    for fp in emails_source:
        try:
            emails = load_emails(fp)
            logger.info("Loaded %d email(s) from '%s'", len(emails), Path(fp).name)
            all_emails.extend(emails)
        except Exception as exc:
            logger.error("Failed to read '%s': %s", fp, exc)

    if not all_emails:
        logger.error("No emails could be loaded. Aborting pipeline.")
        return

    logger.info("Total emails to process: %d", len(all_emails))
    for i, e in enumerate(all_emails):
        logger.debug(
            "  email[%02d] id=%-35s subject='%s'  body_len=%d",
            i, e.get("id"), e.get("subject", "")[:60], len(e.get("body", ""))
        )

    # ── analyse ───────────────────────────────────────────────────────────────
    logger.info("Initialising AI Compliance Agent …")
    agent    = ComplianceAgent()
    logger.info("Running compliance analysis …")
    findings = agent.analyse_batch(all_emails)

    # ── validate / verify / score ─────────────────────────────────────────────
    validator       = GuardrailValidator(config)
    verifier        = ComplianceVerifier()
    scorer          = ScoringEngine(config)
    scored_findings = []

    for idx, (finding, email) in enumerate(zip(findings, all_emails)):
        logger.debug("── Processing %d/%d  id=%s ──", idx + 1, len(findings), finding.get("id"))

        is_valid, issues = validator.validate(finding, email)
        finding["guardrail_passed"] = is_valid
        finding["guardrail_issues"] = issues

        if is_valid:
            logger.info("Guardrail PASSED  id=%s", finding.get("id"))
        else:
            logger.warning("Guardrail FAILED  id=%s  issues=%s", finding.get("id"), issues)

        finding = verifier.verify(finding, email)
        logger.info("Verified  id=%-35s  note='%s'",
                    finding.get("id"), finding.get("verification_note", ""))
        logger.debug("Post-verify finding: %s", finding)

        finding = scorer.score(finding)
        logger.info(
            "Scored    id=%-35s  score=%3d  band=%-10s  alert=%s",
            finding.get("id"), finding.get("priority_score", 0),
            finding.get("priority_band", "?"), finding.get("alert_level", "?"),
        )
        logger.debug("Score breakdown: %s", finding.get("score_breakdown"))
        scored_findings.append(finding)

    # ── store ─────────────────────────────────────────────────────────────────
    storage    = ResultsStorage(str(result_dir))
    run_label  = datetime.now().strftime("%Y%m%d_%H%M%S")
    result_path = storage.save(scored_findings, run_label=run_label)
    logger.info("Results saved → %s", result_path)

    # ── print summary ─────────────────────────────────────────────────────────
    non_compliant = [f for f in scored_findings if not f.get("is_compliant", True)]
    compliant     = len(scored_findings) - len(non_compliant)

    logger.info(
        "Pipeline complete  total=%d  non_compliant=%d  compliant=%d",
        len(scored_findings), len(non_compliant), compliant,
    )

    sep = "═" * 68
    print(f"\n{sep}")
    print("  EMAIL COMPLIANCE AI AGENT  –  ANALYSIS SUMMARY")
    print(sep)
    print(f"  Total emails analysed : {len(scored_findings)}")
    print(f"  Non-compliant         : {len(non_compliant)}")
    print(f"  Compliant             : {compliant}")
    print(f"  Results saved to      : {result_path}")
    print("─" * 68)

    for f in scored_findings:
        flag   = "⚠  NON-COMPLIANT" if not f.get("is_compliant", True) else "✓  COMPLIANT   "
        band   = f"{f.get('priority_band', '?'):10s}"
        subj   = f.get("subject", "(no subject)")[:50]
        score  = f.get("priority_score", 0)
        alert  = f.get("alert_level", "NONE")

        print(f"  [{band}] {flag} | {subj}")
        if f.get("categories"):
            print(f"                 Categories : {', '.join(f['categories'])}")
        print(f"                 Score      : {score:3d}/100  Alert: {alert}")
        print()
    print(sep)


# ═══════════════════════════════════════════════════════════════════════════════
# Server
# ═══════════════════════════════════════════════════════════════════════════════

def run_server() -> None:
    logger = logging.getLogger("main.server")
    from src.api_server import app

    logger.info("Starting Email Compliance API server on http://localhost:5050")
    logger.info("Open ui/dashboard.html in your browser for the GUI.")
    logger.info("Email data folder : %s", _DEFAULT_EMAIL_DATA_DIR)
    logger.info("Result folder     : %s", _DEFAULT_RESULT_DIR)
    app.run(host="0.0.0.0", port=5050, debug=False)


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Email Compliance AI Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Folder defaults (overridable via .env):
  Email input : {_DEFAULT_EMAIL_DATA_DIR}
  Results     : {_DEFAULT_RESULT_DIR}
  Logs        : {_DEFAULT_LOG_DIR}
  Log level   : {_DEFAULT_LOG_LEVEL}   (set LOG_LEVEL= in .env to change)

Examples:
  python main.py --server                              Start dashboard API
  python main.py --data-dir email_data                 Analyse all files in folder
  python main.py --data-dir email_data --log-level DEBUG
  python main.py --file email_data/test_emails.xlsx
  python main.py --file email_data/test_emails.pdf --log-level DEBUG
  python main.py --file emails.pdf --result-dir result --log-dir logs --log-file run01
        """,
    )

    # ── mode ──────────────────────────────────────────────────────────────────
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--server",
        action="store_true",
        help="Start the Flask API server for the HTML dashboard (default when no input given)",
    )
    mode.add_argument(
        "--file",
        type=str,
        metavar="PATH",
        help="Path to a single PDF or Excel file to analyse",
    )
    mode.add_argument(
        "--data-dir",
        type=str,
        metavar="DIR",
        default=None,
        help=(
            f"Folder to scan for email files (PDF / Excel). "
            f"Default: {_DEFAULT_EMAIL_DATA_DIR}"
        ),
    )

    # ── output ────────────────────────────────────────────────────────────────
    io_group = parser.add_argument_group("Output options")
    io_group.add_argument(
        "--result-dir",
        type=str,
        default=str(_DEFAULT_RESULT_DIR),
        metavar="DIR",
        help=f"Directory where result JSON files are saved (default: {_DEFAULT_RESULT_DIR})",
    )

    # ── logging ───────────────────────────────────────────────────────────────
    log_group = parser.add_argument_group("Logging options")
    log_group.add_argument(
        "--log-level",
        type=str,
        default=_DEFAULT_LOG_LEVEL,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        metavar="LEVEL",
        help=(
            "Log verbosity: DEBUG | INFO | WARNING | ERROR | CRITICAL  "
            f"(default from .env: {_DEFAULT_LOG_LEVEL}). "
            "DEBUG also writes a separate .debug.log file."
        ),
    )
    log_group.add_argument(
        "--log-dir",
        type=str,
        default=str(_DEFAULT_LOG_DIR),
        metavar="DIR",
        help=f"Directory for log files (default: {_DEFAULT_LOG_DIR})",
    )
    log_group.add_argument(
        "--log-file",
        type=str,
        default=None,
        metavar="STEM",
        help=(
            "Filename stem for log files (e.g. 'run01' → run01.info.log, run01.debug.log). "
            "Default: compliance_<YYYYMMDD_HHMMSS>"
        ),
    )

    return parser


# ═══════════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = build_parser()
    args   = parser.parse_args()

    # ── configure logging before anything else ────────────────────────────────
    info_log, debug_log = configure_logging(
        log_level=args.log_level,
        log_dir=args.log_dir,
        log_file=args.log_file,
    )

    logger = logging.getLogger("main")
    logger.info("══════════════════════════════════════════════════════════")
    logger.info("  Email Compliance AI Agent  –  Starting Up")
    logger.info("══════════════════════════════════════════════════════════")
    logger.info("Log level    : %s", args.log_level.upper())
    logger.info("INFO log     : %s", info_log)
    if debug_log:
        logger.info("DEBUG log    : %s", debug_log)
    logger.info("Result dir   : %s", args.result_dir)
    logger.debug("All CLI args : %s", vars(args))

    # ── ensure required folders exist ────────────────────────────────────────
    for folder in (_DEFAULT_EMAIL_DATA_DIR, Path(args.result_dir), Path(args.log_dir)):
        folder.mkdir(parents=True, exist_ok=True)

    # ── dispatch ─────────────────────────────────────────────────────────────
    if args.file:
        fp = Path(args.file)
        if not fp.exists():
            logger.error("File not found: %s", fp)
            sys.exit(1)
        logger.info("Mode: single file  → %s", fp)
        _run_pipeline([str(fp)], result_dir=Path(args.result_dir))

    elif args.data_dir:
        dd = Path(args.data_dir)
        if not dd.is_dir():
            logger.error("Directory not found: %s", dd)
            sys.exit(1)
        logger.info("Mode: folder scan  → %s", dd)

        # collect files from folder
        supported = {".pdf", ".xlsx", ".xls", ".xlsm"}
        files = sorted(p for p in dd.iterdir()
                       if p.suffix.lower() in supported and p.is_file())
        if not files:
            logger.error("No supported email files found in: %s", dd)
            sys.exit(1)
        logger.info("Found %d file(s): %s", len(files), [f.name for f in files])
        _run_pipeline([str(f) for f in files], result_dir=Path(args.result_dir))

    else:
        logger.info("Mode: API server")
        run_server()


if __name__ == "__main__":
    main()
