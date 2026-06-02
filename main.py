"""
main.py
=======
Entry point for the Email Compliance AI Agent.

Modes
-----
  Server  (default)        Start the Flask API for the HTML dashboard
  File    (--file PATH)    Analyse a single PDF / Excel file
  Folder  (--data-dir DIR) Scan a folder and analyse every supported file
         (positional)      Same as --data-dir: python main.py email_data

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

Logging
-------
  Console                    colourised, at requested level
  logs/<stem>.info.log       always written (INFO+)
  logs/<stem>.debug.log      only when --log-level DEBUG (full trace)
  logs/latest.info.log       symlink to most recent info log
  logs/latest.debug.log      symlink to most recent debug log
"""

# ─────────────────────────────────────────────────────────────────────────────
# VENV GUARD  – runs before any third-party import so the error message is
# clear even when the user forgets to activate the virtual environment.
# ─────────────────────────────────────────────────────────────────────────────
import sys
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent

def _check_venv() -> None:
    """
    Detect common 'venv not activated' situations and print a friendly fix
    before Python raises a cryptic ModuleNotFoundError.
    """
    # If we're already inside a venv, everything is fine.
    if sys.prefix != sys.base_prefix:
        return

    # Check whether a venv exists in the project folder.
    venv_python_win = PROJECT_ROOT / "venv" / "Scripts" / "python.exe"
    venv_python_unix = PROJECT_ROOT / "venv" / "bin" / "python"
    venv_exists = venv_python_win.exists() or venv_python_unix.exists()

    sep = "=" * 62
    print(sep)
    print("  ERROR: Virtual environment is not activated.")
    print(sep)
    if venv_exists:
        print()
        print("  A venv exists in this project. Activate it first:")
        print()
        print("  Windows PowerShell:")
        print(r"    .\venv\Scripts\Activate.ps1")
        print()
        print("  Windows CMD:")
        print(r"    venv\Scripts\activate.bat")
        print()
        print("  Then re-run:")
        print("    python main.py --data-dir email_data")
    else:
        print()
        print("  No venv found. Run setup first:")
        print()
        print("  Windows PowerShell:")
        print(r"    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass")
        print(r"    .\setup.ps1")
    print()
    print("  Or open PyCharm Settings → Python Interpreter and select")
    print(r"  the interpreter at:  venv\Scripts\python.exe")
    print(sep)
    sys.exit(1)

_check_venv()

# ─────────────────────────────────────────────────────────────────────────────
# Standard library imports (safe before venv check)
# ─────────────────────────────────────────────────────────────────────────────
import argparse
import logging
import logging.handlers
from datetime import datetime

# ─────────────────────────────────────────────────────────────────────────────
# Third-party imports (only reached if venv is active)
# ─────────────────────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    print("ERROR: python-dotenv is not installed.")
    print("Run:  pip install python-dotenv   (inside your activated venv)")
    sys.exit(1)

load_dotenv()

sys.path.insert(0, str(PROJECT_ROOT))

# Defaults read from .env (written by setup.ps1)
_DEFAULT_EMAIL_DATA_DIR = PROJECT_ROOT / os.environ.get("EMAIL_DATA_DIR", "email_data")
_DEFAULT_RESULT_DIR     = PROJECT_ROOT / os.environ.get("RESULT_DIR",     "result")
_DEFAULT_LOG_DIR        = PROJECT_ROOT / os.environ.get("LOG_DIR",        "logs")
_DEFAULT_LOG_LEVEL      = os.environ.get("LOG_LEVEL", "INFO").upper()


# ═══════════════════════════════════════════════════════════════════════════════
# Logging
# ═══════════════════════════════════════════════════════════════════════════════

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

    def format(self, record: logging.LogRecord) -> str:
        msg = super().format(record)
        if self._ENABLED:
            msg = f"{self._COLOURS.get(record.levelno, '')}{msg}{self._RESET}"
        return msg


def _symlink(target: Path, link: Path) -> None:
    try:
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(target.name)
    except (OSError, NotImplementedError):
        pass


def configure_logging(
    log_level: str = "INFO",
    log_dir:   str | None = None,
    log_file:  str | None = None,
) -> tuple[Path, Path | None]:
    level        = _LEVEL_MAP.get(log_level.upper(), logging.INFO)
    log_dir_path = Path(log_dir) if log_dir else _DEFAULT_LOG_DIR
    log_dir_path.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem  = Path(log_file).stem if log_file else f"compliance_{stamp}"

    info_log  = log_dir_path / f"{stem}.info.log"
    debug_log = log_dir_path / f"{stem}.debug.log" if level == logging.DEBUG else None

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


# ═══════════════════════════════════════════════════════════════════════════════
# Pipeline
# ═══════════════════════════════════════════════════════════════════════════════

def _run_pipeline(file_paths: list, result_dir: Path) -> None:
    logger = logging.getLogger("main.pipeline")

    from src.compliance_agent import ComplianceAgent
    from src.config_loader import load_config
    from src.email_reader import load_emails
    from src.guardrails import ComplianceVerifier, GuardrailValidator
    from src.scoring_engine import ScoringEngine
    from src.storage import ResultsStorage

    logger.info("=" * 60)
    logger.info("  Email Compliance AI Agent  -  Pipeline Start")
    logger.info("=" * 60)

    logger.debug("Loading compliance matrix ...")
    config = load_config()
    logger.info("Config loaded: %d categories", len(config.get("categories", {})))

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

    for idx, (finding, email) in enumerate(zip(findings, all_emails)):
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
    print(f"\n{sep}")
    print("  EMAIL COMPLIANCE AI AGENT  -  ANALYSIS SUMMARY")
    print(sep)
    print(f"  Total emails analysed : {len(scored_findings)}")
    print(f"  Non-compliant         : {len(non_compliant)}")
    print(f"  Compliant             : {compliant}")
    print(f"  Results saved to      : {result_path}")
    print("-" * 68)
    for f in scored_findings:
        flag  = "!  NON-COMPLIANT" if not f.get("is_compliant", True) else "OK COMPLIANT   "
        band  = f"{f.get('priority_band', '?'):10s}"
        subj  = f.get("subject", "(no subject)")[:50]
        score = f.get("priority_score", 0)
        alert = f.get("alert_level", "NONE")
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
    app.run(host="0.0.0.0", port=5050, debug=False)


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python main.py",
        description="Email Compliance AI Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Examples (all equivalent ways to analyse the default folder):
  python main.py email_data
  python main.py --data-dir email_data
  python main.py --data-dir email_data --log-level DEBUG

Single file:
  python main.py --file email_data/test_emails.xlsx
  python main.py --file email_data/test_emails.pdf --log-level DEBUG

Dashboard server:
  python main.py --server
  python main.py --server --log-level DEBUG

Full options:
  python main.py --data-dir email_data --result-dir result --log-dir logs --log-level DEBUG --log-file run01

Defaults (from .env set by setup.ps1):
  Email input : {_DEFAULT_EMAIL_DATA_DIR}
  Results     : {_DEFAULT_RESULT_DIR}
  Logs        : {_DEFAULT_LOG_DIR}
  Log level   : {_DEFAULT_LOG_LEVEL}
        """,
    )

    # ── positional shorthand: python main.py email_data ───────────────────────
    parser.add_argument(
        "path",
        nargs="?",
        default=None,
        metavar="PATH",
        help=(
            "Shorthand: a folder path → same as --data-dir, "
            "a file path → same as --file. "
            "Example: python main.py email_data"
        ),
    )

    # ── named mode flags ──────────────────────────────────────────────────────
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
        help=f"Folder to scan for email files. Default: {_DEFAULT_EMAIL_DATA_DIR}",
    )

    # ── output ────────────────────────────────────────────────────────────────
    io_group = parser.add_argument_group("Output options")
    io_group.add_argument(
        "--result-dir",
        type=str,
        default=str(_DEFAULT_RESULT_DIR),
        metavar="DIR",
        help=f"Directory for result JSON files (default: {_DEFAULT_RESULT_DIR})",
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
            "DEBUG | INFO | WARNING | ERROR | CRITICAL  "
            f"(default from .env: {_DEFAULT_LOG_LEVEL}). "
            "DEBUG also writes a .debug.log file."
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
            "Filename stem for log files. "
            "E.g. 'run01' produces run01.info.log and run01.debug.log. "
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

    # ── resolve positional shorthand ─────────────────────────────────────────
    # Allows:  python main.py email_data          (folder)
    #          python main.py emails/batch1.xlsx  (file)
    if args.path and not args.server and not args.file and not args.data_dir:
        p = Path(args.path)
        if p.is_dir():
            args.data_dir = str(p)
        elif p.is_file():
            args.file = str(p)
        else:
            print(f"ERROR: '{args.path}' is not a valid file or folder.")
            print(f"       Check the path and try again.")
            sys.exit(1)

    # ── configure logging first ───────────────────────────────────────────────
    info_log, debug_log = configure_logging(
        log_level=args.log_level,
        log_dir=args.log_dir,
        log_file=args.log_file,
    )

    logger = logging.getLogger("main")
    logger.info("Email Compliance AI Agent starting up")
    logger.info("Log level    : %s", args.log_level.upper())
    logger.info("INFO log     : %s", info_log)
    if debug_log:
        logger.info("DEBUG log    : %s", debug_log)
    logger.info("Result dir   : %s", args.result_dir)
    logger.debug("All CLI args : %s", vars(args))

    # ── ensure folders exist ──────────────────────────────────────────────────
    for folder in (_DEFAULT_EMAIL_DATA_DIR, Path(args.result_dir), Path(args.log_dir)):
        folder.mkdir(parents=True, exist_ok=True)

    # ── dispatch ──────────────────────────────────────────────────────────────
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
