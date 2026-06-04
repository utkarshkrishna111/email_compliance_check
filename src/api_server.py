"""
src/api_server.py
-----------------
Flask server that:
  1. Serves the dashboard HTML at  http://localhost:5050/
  2. Serves the architecture page  http://localhost:5050/architecture
  3. Exposes all REST API endpoints under /api/

Opening the dashboard through Flask (http://localhost:5050) instead of
from disk (file://) eliminates all browser CORS/security blocks.
"""

import logging
import os
import webbrowser
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory, redirect

load_dotenv()

PROJECT_ROOT   = Path(__file__).parent.parent
UI_DIR         = PROJECT_ROOT / "ui"
EMAIL_DATA_DIR = PROJECT_ROOT / os.environ.get("EMAIL_DATA_DIR", "email_data")
RESULT_DIR     = PROJECT_ROOT / os.environ.get("RESULT_DIR",     "result")
UPLOAD_EXT     = {".pdf", ".xlsx", ".xls", ".xlsm"}

app    = Flask(__name__, static_folder=None)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Serve UI files directly from Flask (eliminates all file:// CORS issues)
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Serve the main dashboard."""
    return send_from_directory(str(UI_DIR), "dashboard.html")


@app.route("/architecture")
def architecture():
    """Serve the architecture diagram page."""
    return send_from_directory(str(UI_DIR), "architecture.html")


@app.route("/<path:filename>")
def static_files(filename):
    """Serve any other static file from the ui/ folder."""
    return send_from_directory(str(UI_DIR), filename)


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline helper
# ─────────────────────────────────────────────────────────────────────────────

def _run_pipeline(file_paths):
    from src.compliance_agent import ComplianceAgent
    from src.config_loader import load_config
    from src.email_reader import load_emails
    from src.guardrails import ComplianceVerifier, GuardrailValidator
    from src.history_store import HistoryStore
    from src.scoring_engine import ScoringEngine
    from src.storage import ResultsStorage
    from src.thread_detector import detect_thread, extract_recipients, is_external_recipient

    config    = load_config()
    agent     = ComplianceAgent()
    validator = GuardrailValidator(config)
    verifier  = ComplianceVerifier()
    scorer    = ScoringEngine(config)
    storage   = ResultsStorage(str(RESULT_DIR))
    history   = HistoryStore(
        db_path=str(RESULT_DIR / "history.db"),
        chroma_path=str(RESULT_DIR / "chroma"),
    )
    internal_domain = os.environ.get("INTERNAL_DOMAIN", "")

    all_findings = []
    for fp in file_paths:
        try:
            emails = load_emails(fp)
            logger.info("Loaded %d email(s) from %s", len(emails), Path(fp).name)
        except Exception as exc:
            logger.error("Failed to read %s: %s", fp, exc)
            continue

        findings = agent.analyse_batch(emails)
        for finding, email in zip(findings, emails):
            is_valid, issues = validator.validate(finding, email)
            finding["guardrail_passed"] = is_valid
            finding["guardrail_issues"] = issues
            finding = verifier.verify(finding, email)
            finding = scorer.score(finding)
            all_findings.append(finding)

            thread_id   = detect_thread(email)
            recipients  = extract_recipients(email)
            is_external = is_external_recipient(email, internal_domain)
            history.save_finding(finding, thread_id, recipients, is_external)

    run_label   = datetime.now().strftime("%Y%m%d_%H%M%S")
    result_path = storage.save(all_findings, run_label=run_label)
    logger.info("Pipeline complete: %d findings -> %s", len(all_findings), result_path)

    return {
        "total_emails":  len(all_findings),
        "non_compliant": sum(1 for f in all_findings if not f.get("is_compliant", True)),
        "result_file":   Path(result_path).name,
        "findings":      all_findings,
    }


# ─────────────────────────────────────────────────────────────────────────────
# API routes
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "status":         "ok",
        "email_data_dir": str(EMAIL_DATA_DIR),
        "result_dir":     str(RESULT_DIR),
        "server_time":    datetime.now().isoformat(),
    })


@app.route("/api/analyse", methods=["POST"])
def analyse():
    if "files" not in request.files:
        return jsonify({"error": "No files uploaded. Use field name 'files'."}), 400

    uploaded = request.files.getlist("files")
    if not uploaded:
        return jsonify({"error": "Empty file list."}), 400

    EMAIL_DATA_DIR.mkdir(parents=True, exist_ok=True)
    saved_paths = []

    for upload in uploaded:
        filename = upload.filename or "upload"
        ext      = Path(filename).suffix.lower()
        if ext not in UPLOAD_EXT:
            return jsonify({
                "error": "Unsupported file '" + filename + "'. Use PDF or Excel."
            }), 400
        save_path = EMAIL_DATA_DIR / filename
        upload.save(str(save_path))
        saved_paths.append(str(save_path))
        logger.info("Saved upload -> %s", save_path)

    try:
        result = _run_pipeline(saved_paths)
        return jsonify(result)
    except Exception as exc:
        logger.error("Pipeline error: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


@app.route("/api/results", methods=["GET"])
def get_latest_results():
    from src.storage import ResultsStorage
    return jsonify(ResultsStorage(str(RESULT_DIR)).load_latest())


@app.route("/api/results/list", methods=["GET"])
def list_results():
    from src.storage import ResultsStorage
    return jsonify({"runs": ResultsStorage(str(RESULT_DIR)).list_runs()})


@app.route("/api/results/<filename>", methods=["GET"])
def get_result_by_name(filename):
    from src.storage import ResultsStorage
    data = ResultsStorage(str(RESULT_DIR)).load(filename)
    if not data:
        return jsonify({"error": "Result not found: " + filename}), 404
    return jsonify(data)


@app.route("/api/patterns", methods=["GET"])
def get_cross_patterns():
    """
    Run Quid Pro Quo detector against the history DB and return alerts as JSON.

    Query params:
      qpq_days : int  look-back window for QPQ (default 30)
    """
    from src.quid_pro_quo_detector import detect_quid_pro_quo

    db_path = str(RESULT_DIR / "history.db")
    if not (RESULT_DIR / "history.db").exists():
        return jsonify({
            "quid_pro_quo": [],
            "note": "history.db not found — run the pipeline at least once first.",
        })

    try:
        qpq_days   = int(request.args.get("qpq_days", 30))
        qpq_alerts = detect_quid_pro_quo(db_path, days_window=qpq_days)

        return jsonify({
            "quid_pro_quo":       qpq_alerts,
            "quid_pro_quo_count": len(qpq_alerts),
        })
    except Exception as exc:
        logger.error("Cross-pattern analysis error: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


# ─────────────────────────────────────────────────────────────────────────────
def start(port=5050, open_browser=True):
    """Start the Flask server and optionally open the browser."""
    url = f"http://localhost:{port}"
    logger.info("=" * 55)
    logger.info("  Email Compliance Dashboard")
    logger.info("  Open this URL in your browser:")
    logger.info("  --> %s", url)
    logger.info("=" * 55)
    if open_browser:
        import threading
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host="0.0.0.0", port=port, debug=False)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    start()
