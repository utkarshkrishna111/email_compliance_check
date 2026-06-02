"""
main.py
=======
Entry point for the Email Compliance AI Agent.

Modes
-----
  Server  (default)        Start the Flask API for the HTML dashboard
  File    (--file PATH)    Analyse a single PDF / Excel file
  Folder  (--data-dir DIR) Scan a folder and analyse every supported file
         (positional)      Shorthand: python main.py email_data

Usage examples
--------------
  python main.py                                  Start API server
  python main.py --server                         Same as above
  python main.py email_data                       Analyse folder (shorthand)
  python main.py --data-dir email_data            Analyse folder (explicit)
  python main.py --data-dir email_data --log-level DEBUG
  python main.py --file email_data/test_emails.xlsx
  python main.py --file email_data/test_emails.pdf --log-level DEBUG
  python main.py --help
"""

import sys
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent

# =============================================================================
# VENV GUARD - runs before any third-party import
# =============================================================================

def _find_venv():
    """Return path to a venv folder in the project root, or None.
    Checks common names: .venv, venv, env."""
    for name in (".venv", "venv", "env"):
        candidate = PROJECT_ROOT / name
        if (candidate / "pyvenv.cfg").exists():
            return candidate
    return None


def _check_venv():
    """
    Exit with a clear message when not running inside any virtual environment.

    Detection (any one passing = we are in a venv, return silently):
      1. sys.prefix != sys.base_prefix   standard venv indicator
      2. VIRTUAL_ENV env var             set by Activate.ps1 and PyCharm
      3. CONDA_PREFIX env var            conda environments
      4. Running python.exe lives inside a venv folder on disk
    """
    if sys.prefix != sys.base_prefix:
        return
    if os.environ.get("VIRTUAL_ENV"):
        return
    if os.environ.get("CONDA_PREFIX"):
        return

    # Physical path check
    running = Path(sys.executable).resolve()
    venv = _find_venv()
    if venv:
        try:
            running.relative_to(venv.resolve())
            return
        except ValueError:
            pass

    # Nothing matched - print helpful fix and exit
    venv = _find_venv()
    sep = "=" * 62
    print(sep)
    print("  ERROR: Virtual environment is not activated.")
    print(sep)
    if venv:
        n = venv.name
        print()
        print("  Found a venv at: " + str(venv))
        print()
        print("  Activate in PowerShell:  .\\" + n + "\\Scripts\\Activate.ps1")
        print("  Activate in CMD:         " + n + "\\Scripts\\activate.bat")
        print()
        print("  Then re-run:  python main.py email_data")
        print()
        print("  Or in PyCharm: Settings -> Python Interpreter -> Add Interpreter")
        print("    -> Existing -> " + str(venv / "Scripts" / "python.exe"))
    else:
        print()
        print("  No venv found. Run setup first:")
        print("    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass")
        print("    .\\setup.ps1")
    print(sep)
    sys.exit(1)


_check_venv()

# =============================================================================
# Standard library imports
# =============================================================================
import argparse
import logging
import logging.handlers
import subprocess
from datetime import datetime

# =============================================================================
# Auto-install missing packages into the active venv
# =============================================================================

def _ensure(pip_name, import_name=None):
    """Import a package; pip-install it quietly if not present."""
    mod = import_name or pip_name
    try:
        __import__(mod)
    except ModuleNotFoundError:
        print("  [auto-install] " + pip_name + " not found - installing ...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", pip_name,
             "--quiet", "--prefer-binary"],
            stdout=subprocess.DEVNULL,
        )
        print("  [auto-install] " + pip_name + " installed.")

# ---------------------------------------------------------------------------
# Required packages: pip name and Python import name.
#
# Key constraints verified for Python 3.10-3.14 on Windows:
#   openai >=2.26.0       required by langchain-openai 1.x
#   tiktoken >=0.7.0      required by langchain-openai 1.x
#   langchain-community   removed - not used by this app
#   pdfplumber: pure-Python PDF reader, no DLL/VC++ dependency
# ---------------------------------------------------------------------------
_REQUIRED_PACKAGES = [
    # (pip_install_name,        python_import_name)
    ("python-dotenv",           "dotenv"),
    ("pyyaml",                  "yaml"),
    ("pdfplumber",               "pdfplumber"),  # pure-Python PDF reader, no DLL/VC++ needed
    ("pandas",                  "pandas"),
    ("openpyxl",                "openpyxl"),
    ("openai>=2.26.0",          "openai"),
    ("langchain",               "langchain"),
    ("langchain-openai",        "langchain_openai"),
    ("langchain-core",          "langchain_core"),
    ("flask",                   "flask"),
    ("flask-cors",              "flask_cors"),
    ("tiktoken>=0.7.0",         "tiktoken"),
    ("colorlog",                "colorlog"),
    ("reportlab",               "reportlab"),
]

_any_installed = False
for _pip_name, _import_name in _REQUIRED_PACKAGES:
    try:
        __import__(_import_name)
    except ModuleNotFoundError:
        if not _any_installed:
            print("  [auto-install] Installing missing packages ...")
            _any_installed = True
        _display = _pip_name.split(">")[0].split("=")[0].split("<")[0]
        print("  [auto-install] Installing " + _display + " ...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", _pip_name,
             "--quiet", "--prefer-binary"],
            stdout=subprocess.DEVNULL,
        )

if _any_installed:
    print("  [auto-install] All packages installed. Starting application ...")
    print()

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, str(PROJECT_ROOT))

_DEFAULT_EMAIL_DATA_DIR = PROJECT_ROOT / os.environ.get("EMAIL_DATA_DIR", "email_data")
_DEFAULT_RESULT_DIR     = PROJECT_ROOT / os.environ.get("RESULT_DIR",     "result")
_DEFAULT_LOG_DIR        = PROJECT_ROOT / os.environ.get("LOG_DIR",        "logs")
_DEFAULT_LOG_LEVEL      = os.environ.get("LOG_LEVEL", "INFO").upper()


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

def _run_pipeline(file_paths, result_dir):
    logger = logging.getLogger("main.pipeline")

    from src.circular_trading_detector import detect_circular_trading
    from src.compliance_agent import ComplianceAgent
    from src.config_loader import load_config
    from src.email_reader import load_emails
    from src.guardrails import ComplianceVerifier, GuardrailValidator
    from src.history_store import HistoryStore
    from src.quid_pro_quo_detector import detect_quid_pro_quo
    from src.scoring_engine import ScoringEngine
    from src.storage import ResultsStorage
    from src.thread_detector import detect_thread, extract_recipients, is_external_recipient

    logger.info("=" * 60)
    logger.info("  Email Compliance AI Agent  -  Pipeline Start")
    logger.info("=" * 60)

    config = load_config()
    logger.info("Config loaded: %d categories", len(config.get("categories", {})))

    db_path = str(result_dir / "history.db")
    chroma_path = str(result_dir / "chroma")
    history_store = HistoryStore(db_path=db_path, chroma_path=chroma_path)
    internal_domain = os.environ.get("INTERNAL_DOMAIN", "")

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

    logger.info("Initialising AI Compliance Agent ...")
    agent    = ComplianceAgent()
    findings = agent.analyse_batch(all_emails)

    validator       = GuardrailValidator(config)
    verifier        = ComplianceVerifier()
    scorer          = ScoringEngine(config)
    scored_findings = []

    for finding, email in zip(findings, all_emails):
        is_valid, issues = validator.validate(finding, email)
        finding["guardrail_passed"] = is_valid
        finding["guardrail_issues"] = issues
        if is_valid:
            logger.info("Guardrail PASSED  id=%s", finding.get("id"))
        else:
            logger.warning("Guardrail FAILED  id=%s  issues=%s", finding.get("id"), issues)

        finding = verifier.verify(finding, email)
        finding = scorer.score(finding)
        logger.info(
            "Scored  id=%-35s  score=%3d  band=%-10s  alert=%s",
            finding.get("id"), finding.get("priority_score", 0),
            finding.get("priority_band", "?"), finding.get("alert_level", "?"),
        )
        scored_findings.append(finding)

        # Persist to HistoryStore (SQLite + ChromaDB) for cross-pattern analysis
        thread_id   = detect_thread(email)
        recipients  = extract_recipients(email)
        is_external = is_external_recipient(email, internal_domain)
        history_store.save_finding(finding, thread_id, recipients, is_external)

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

    # ── Cross-pattern analysis (Quid Pro Quo + Circular Trading) ─────────────
    logger.info("Running cross-pattern analysis ...")
    qpq_alerts = detect_quid_pro_quo(db_path)
    ct_alerts  = detect_circular_trading(db_path)

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

    print("  Circular Trading patterns detected: " + str(len(ct_alerts)))
    for a in ct_alerts:
        print("  [" + a["severity"] + "] " + a["description"])
        print("        Participants: " + str(a["cycle_length"]))
        print()

    print(sep)


# =============================================================================
# Server
# =============================================================================

def run_server():
    logger = logging.getLogger("main.server")
    logger.info("Starting Email Compliance server ...")
    from src.api_server import start
    # start() serves the dashboard at http://localhost:5050 and opens the browser
    start(port=5050, open_browser=True)


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
            "  python main.py email_data                   analyse folder (shorthand)\n"
            "  python main.py --data-dir email_data        same, explicit flag\n"
            "  python main.py --data-dir email_data --log-level DEBUG\n"
            "  python main.py --file email_data/test_emails.xlsx\n"
            "  python main.py --server                     start dashboard API\n"
            "  python main.py --server --log-level DEBUG\n"
            "\n"
            "Defaults (set by setup.ps1 in .env):\n"
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
    if args.file:
        fp = Path(args.file)
        if not fp.exists():
            logger.error("File not found: %s", fp)
            sys.exit(1)
        logger.info("Mode: single file -> %s", fp)
        _run_pipeline([str(fp)], result_dir=Path(args.result_dir))

    elif args.data_dir:
        dd = Path(args.data_dir)
        if not dd.is_dir():
            logger.error("Directory not found: %s", dd)
            sys.exit(1)
        logger.info("Mode: folder scan -> %s", dd)
        supported = {".pdf", ".xlsx", ".xls", ".xlsm"}
        files = sorted(
            p for p in dd.iterdir()
            if p.suffix.lower() in supported and p.is_file()
        )
        if not files:
            logger.error("No supported email files (.pdf/.xlsx) found in: %s", dd)
            sys.exit(1)
        logger.info("Found %d file(s): %s", len(files), [f.name for f in files])
        _run_pipeline([str(f) for f in files], result_dir=Path(args.result_dir))

    else:
        logger.info("Mode: API server")
        run_server()


if __name__ == "__main__":
    main()
