"""
main.py
=======
Entry point for the Email Compliance AI Agent.

Modes
-----
  Setup   (--setup)           Create venv and install all dependencies
  Server  (default)           Start the Flask API for the HTML dashboard
  File    (--file PATH)       Analyse a single PDF / Excel file
  Folder  (--data-dir DIR)    Scan a folder and analyse every supported file
           (positional)       Shorthand: python main.py email_data

Usage examples
--------------
  python main.py --setup                              create venv + install packages
  python main.py                                      start API server (venv must be active)
  python main.py --server                             same as above
  python main.py email_data                           analyse folder (shorthand)
  python main.py --data-dir email_data                analyse folder (explicit)
  python main.py --data-dir email_data --log-level DEBUG
  python main.py --file email_data/test_emails.xlsx
  python main.py --inspect-db                         show SQLite & ChromaDB records
  python main.py --help
"""

import sys
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent

# =============================================================================
# --setup: runs before venv guard and before any third-party import
# =============================================================================

if "--setup" in sys.argv:
    from utils.venv_setup import setup_venv
    setup_venv(PROJECT_ROOT)
    sys.exit(0)

# =============================================================================
# VENV GUARD - runs before any third-party import
# =============================================================================

from utils.venv_setup import check_venv
check_venv(PROJECT_ROOT)

# =============================================================================
# Standard library imports
# =============================================================================
import argparse
import logging
import logging.handlers
from datetime import datetime

# =============================================================================
# Third-party setup
# =============================================================================

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, str(PROJECT_ROOT))

from src.config import (
    INPUT_DIR   as _DEFAULT_EMAIL_DATA_DIR,
    RESULT_DIR  as _DEFAULT_RESULT_DIR,
    LOG_DIR     as _DEFAULT_LOG_DIR,
    DB_PATH     as _DEFAULT_DB_PATH,
    CHROMA_PATH as _DEFAULT_CHROMA_PATH,
)
_DEFAULT_LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()


# =============================================================================
# Logging
# =============================================================================

_LOG_FORMAT_CONSOLE = "%(asctime)s [%(levelname)-8s] %(name)s - %(message)s"
_LOG_FORMAT_FILE    = (
    "%(asctime)s [%(levelname)-8s] %(name)s "
    "[%(filename)s:%(lineno)d] - %(message)s"
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
    _COLOURS = {
        logging.DEBUG:    "\033[36m",
        logging.INFO:     "\033[32m",
        logging.WARNING:  "\033[33m",
        logging.ERROR:    "\033[31m",
        logging.CRITICAL: "\033[1;31m",
    }
    _RESET   = "\033[0m"
    _ENABLED = (
        (sys.stdout.isatty() and os.name != "nt")
        or os.environ.get("TERM_PROGRAM") in ("vscode", "iTerm.app")
        or os.environ.get("WT_SESSION") is not None
    )

    def format(self, record):
        msg = super().format(record)
        if self._ENABLED:
            msg = self._COLOURS.get(record.levelno, "") + msg + self._RESET
        return msg


def _symlink(target, link):
    try:
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(target.name)
    except (OSError, NotImplementedError):
        pass


def configure_logging(log_level="INFO", log_dir=None, log_file=None):
    level        = _LEVEL_MAP.get(log_level.upper(), logging.INFO)
    log_dir_path = Path(log_dir) if log_dir else _DEFAULT_LOG_DIR
    log_dir_path.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem  = Path(log_file).stem if log_file else "compliance_" + stamp

    info_log  = log_dir_path / (stem + ".info.log")
    debug_log = log_dir_path / (stem + ".debug.log") if level == logging.DEBUG else None

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(level)
    ch.setFormatter(_ColourFormatter(_LOG_FORMAT_CONSOLE, datefmt=_DATE_FMT))
    root.addHandler(ch)

    ih = logging.handlers.RotatingFileHandler(
        info_log, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    ih.setLevel(logging.INFO)
    ih.setFormatter(logging.Formatter(_LOG_FORMAT_FILE, datefmt=_DATE_FMT))
    root.addHandler(ih)

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

    for lib in ("httpcore", "httpx", "openai", "urllib3", "werkzeug", "multipart"):
        logging.getLogger(lib).setLevel(logging.WARNING)

    return info_log, debug_log


# =============================================================================
# Pipeline
# =============================================================================

def _run_pipeline(file_paths, result_dir, skip_qpq=False):
    logger = logging.getLogger("main.pipeline")

    from src.email_reader import load_emails
    from src.graph import build_graph, make_initial_state
    from src.quid_pro_quo_detector import detect_quid_pro_quo
    from src.storage import ResultsStorage

    logger.info("=" * 60)
    logger.info("  Email Compliance AI Agent  -  Pipeline Start")
    logger.info("=" * 60)

    all_emails = []
    for fp in file_paths:
        try:
            emails = load_emails(fp)
            logger.info("Loaded %d email(s) from '%s'", len(emails), Path(fp).name)
            all_emails.extend(emails)
        except Exception as exc:
            logger.error("Failed to read '%s': %s", fp, exc)

    if not all_emails:
        logger.error("No emails could be loaded. Aborting.")
        return

    logger.info("Total emails to process: %d", len(all_emails))

    logger.info("Building LangGraph compliance pipeline ...")
    graph = build_graph(
        db_path=str(_DEFAULT_DB_PATH),
        chroma_path=str(_DEFAULT_CHROMA_PATH),
        internal_domain=os.environ.get("INTERNAL_DOMAIN", ""),
    )

    scored_findings = []
    for i, email in enumerate(all_emails, 1):
        logger.info("── Email %d/%d ──────────────────────────────────────────", i, len(all_emails))
        result = graph.invoke(make_initial_state(email))
        scored_findings.append(result["scored_finding"])

    storage     = ResultsStorage(str(result_dir))
    run_label   = datetime.now().strftime("%Y%m%d_%H%M%S")
    result_path = storage.save(scored_findings, run_label=run_label)
    logger.info("Results saved -> %s", result_path)

    non_compliant = [f for f in scored_findings if not f.get("is_compliant", True)]
    compliant     = len(scored_findings) - len(non_compliant)
    logger.info(
        "Pipeline complete  total=%d  non_compliant=%d  compliant=%d",
        len(scored_findings), len(non_compliant), compliant,
    )

    sep = "=" * 68
    print("\n" + sep)
    print("  EMAIL COMPLIANCE AI AGENT  -  ANALYSIS SUMMARY")
    print(sep)
    print("  Total emails analysed : " + str(len(scored_findings)))
    print("  Non-compliant         : " + str(len(non_compliant)))
    print("  Compliant             : " + str(compliant))
    print("  Results saved to      : " + str(result_path))
    print("-" * 68)
    for f in scored_findings:
        flag  = "!  NON-COMPLIANT" if not f.get("is_compliant", True) else "OK COMPLIANT   "
        band  = (f.get("priority_band", "?") + "          ")[:10]
        subj  = f.get("subject", "(no subject)")[:50]
        score = f.get("priority_score", 0)
        alert = f.get("alert_level", "NONE")
        print("  [" + band + "] " + flag + " | " + subj)
        if f.get("categories"):
            print("                 Categories : " + ", ".join(f["categories"]))
        print("                 Score      : " + str(score).rjust(3) + "/100  Alert: " + alert)
        print()
    print(sep)

    # ── Cross-pattern analysis (Quid Pro Quo) ────────────────────────────────
    if skip_qpq:
        logger.info("Quid Pro Quo check skipped (--skip-qpq)")
        return

    logger.info("Running Quid Pro Quo analysis ...")
    qpq_alerts = detect_quid_pro_quo(str(_DEFAULT_DB_PATH))

    print("\n" + sep)
    print("  CROSS-PATTERN ANALYSIS")
    print(sep)
    print("  Quid Pro Quo patterns detected  : " + str(len(qpq_alerts)))
    for a in qpq_alerts:
        print("  [" + a["severity"] + "] " + a["party_a"] + " ↔ " + a["party_b"])
        print("        Email A: " + a["email_a_subject"][:55])
        print("        Email B: " + a["email_b_subject"][:55])
        print("        Cats A : " + ", ".join(a["email_a_categories"]))
        print("        Cats B : " + ", ".join(a["email_b_categories"]))
        print("        Conf   : " + str(a["avg_confidence"]))
        print()
    print(sep)


# =============================================================================
# CLI argument parser
# =============================================================================

def build_parser():
    parser = argparse.ArgumentParser(
        prog="python main.py",
        description="Email Compliance AI Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python main.py --setup                      create venv + install packages\n"
            "  python main.py email_data                   analyse folder (shorthand)\n"
            "  python main.py --data-dir email_data        same, explicit flag\n"
            "  python main.py --data-dir email_data --log-level DEBUG\n"
            "  python main.py --file email_data/test_emails.xlsx\n"
            "  python main.py --server                     start dashboard API\n"
            "  python main.py --server --log-level DEBUG\n"
            "  python main.py --inspect-db                 show SQLite & ChromaDB records\n"
            "\n"
            "Defaults (set by setup in .env):\n"
            "  Email input : " + str(_DEFAULT_EMAIL_DATA_DIR) + "\n"
            "  Results     : " + str(_DEFAULT_RESULT_DIR) + "\n"
            "  Logs        : " + str(_DEFAULT_LOG_DIR) + "\n"
            "  Log level   : " + _DEFAULT_LOG_LEVEL
        ),
    )

    # Positional shorthand: python main.py email_data
    parser.add_argument(
        "path",
        nargs="?",
        default=None,
        metavar="PATH",
        help=(
            "Shorthand positional argument. "
            "Pass a folder path (same as --data-dir) or a file path (same as --file). "
            "Example: python main.py email_data"
        ),
    )

    parser.add_argument(
        "--setup",
        action="store_true",
        help=(
            "Create a virtual environment (if needed) and install all required packages. "
            "Runs before the venv guard — safe to run from the system Python. "
            "Exits after setup completes."
        ),
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--server",
        action="store_true",
        help="Start the Flask API server for the HTML dashboard",
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
        help="Folder to scan for email files. Default: " + str(_DEFAULT_EMAIL_DATA_DIR),
    )
    mode.add_argument(
        "--inspect-db",
        action="store_true",
        help="Show row counts and recent records from SQLite and ChromaDB, then exit.",
    )

    io_group = parser.add_argument_group("Output options")
    io_group.add_argument(
        "--result-dir",
        type=str,
        default=str(_DEFAULT_RESULT_DIR),
        metavar="DIR",
        help="Directory for result JSON files. Default: " + str(_DEFAULT_RESULT_DIR),
    )

    log_group = parser.add_argument_group("Logging options")
    log_group.add_argument(
        "--log-level",
        type=str,
        default=_DEFAULT_LOG_LEVEL,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        metavar="LEVEL",
        help=(
            "DEBUG | INFO | WARNING | ERROR | CRITICAL  "
            "(default from .env: " + _DEFAULT_LOG_LEVEL + "). "
            "DEBUG also writes a .debug.log file."
        ),
    )
    log_group.add_argument(
        "--log-dir",
        type=str,
        default=str(_DEFAULT_LOG_DIR),
        metavar="DIR",
        help="Directory for log files. Default: " + str(_DEFAULT_LOG_DIR),
    )
    log_group.add_argument(
        "--log-file",
        type=str,
        default=None,
        metavar="STEM",
        help=(
            "Filename stem for log files. "
            "E.g. 'run01' produces run01.info.log and run01.debug.log. "
            "Default: compliance_<YYYYMMDD_HHMMSS>"
        ),
    )

    parser.add_argument(
        "--skip-qpq",
        action="store_true",
        default=False,
        help="Skip the Quid Pro Quo cross-pattern analysis after processing.",
    )

    return parser


# =============================================================================
# Entry point
# =============================================================================

def main():
    parser = build_parser()
    args   = parser.parse_args()

    # Resolve positional shorthand: python main.py email_data
    if args.path and not args.server and not args.file and not args.data_dir:
        p = Path(args.path)
        if p.is_dir():
            args.data_dir = str(p)
        elif p.is_file():
            args.file = str(p)
        else:
            print("ERROR: '" + args.path + "' is not a valid file or folder.")
            sys.exit(1)

    # Configure logging first
    info_log, debug_log = configure_logging(
        log_level=args.log_level,
        log_dir=args.log_dir,
        log_file=args.log_file,
    )

    logger = logging.getLogger("main")
    logger.info("Email Compliance AI Agent starting up")
    logger.info("Log level  : %s", args.log_level.upper())
    logger.info("INFO log   : %s", info_log)
    if debug_log:
        logger.info("DEBUG log  : %s", debug_log)
    logger.debug("CLI args   : %s", vars(args))

    # Ensure folders exist
    for folder in (_DEFAULT_EMAIL_DATA_DIR, Path(args.result_dir), Path(args.log_dir)):
        folder.mkdir(parents=True, exist_ok=True)

    # Dispatch
    if args.inspect_db:
        from utils.chroma_utils import inspect_db
        inspect_db(Path(args.result_dir))
        sys.exit(0)

    if args.file:
        fp = _DEFAULT_EMAIL_DATA_DIR / Path(args.file).name
        if not fp.exists():
            logger.error("File not found: %s", fp)
            sys.exit(1)
        logger.info("Mode: single file -> %s", fp)
        _run_pipeline([str(fp)], result_dir=Path(args.result_dir), skip_qpq=args.skip_qpq)

    elif args.data_dir:
        dd = Path(args.data_dir)
        if not dd.is_dir():
            logger.error("Directory not found: %s", dd)
            sys.exit(1)
        logger.info("Mode: folder scan -> %s", dd)
        from src.email_reader import SUPPORTED_EXTENSIONS
        files = sorted(
            p for p in dd.iterdir()
            if p.suffix.lower() in SUPPORTED_EXTENSIONS and p.is_file()
        )
        if not files:
            logger.error("No supported email files %s found in: %s",
                         tuple(sorted(SUPPORTED_EXTENSIONS)), dd)
            sys.exit(1)
        logger.info("Found %d file(s): %s", len(files), [f.name for f in files])
        _run_pipeline([str(f) for f in files], result_dir=Path(args.result_dir), skip_qpq=args.skip_qpq)

    else:
        logger.info("Mode: API server")
        from utils.api_server import run_server
        run_server()


if __name__ == "__main__":
    main()
