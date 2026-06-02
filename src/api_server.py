"""
src/api_server.py
-----------------
Flask REST API consumed by the HTML dashboard.

Endpoints
---------
POST /api/analyse            Upload files -> run pipeline -> return findings
GET  /api/results            Return latest saved results
GET  /api/results/list       Return list of all past result filenames
GET  /api/results/<filename> Return a specific result file
GET  /api/health             Health-check
"""

import logging
import os
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
from flask import Flask, jsonify, request, make_response
from flask_cors import CORS

load_dotenv()

app = Flask(__name__)

# Allow ALL origins and ALL methods (needed when dashboard.html is opened
# from disk as a file:// URL - the browser sends null or file:// as origin)
CORS(
    app,
    origins="*",
    allow_headers=["Content-Type", "Authorization"],
    methods=["GET", "POST", "OPTIONS"],
    supports_credentials=False,
)

logger         = logging.getLogger(__name__)
PROJECT_ROOT   = Path(__file__).parent.parent
EMAIL_DATA_DIR = PROJECT_ROOT / os.environ.get("EMAIL_DATA_DIR", "email_data")
RESULT_DIR     = PROJECT_ROOT / os.environ.get("RESULT_DIR",     "result")
UPLOAD_EXT     = {".pdf", ".xlsx", ".xls", ".xlsm"}


# ---------------------------------------------------------------------------
# Add CORS headers to every response including errors
# ---------------------------------------------------------------------------
@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"]  = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


@app.route("/api/<path:path>", methods=["OPTIONS"])
@app.route("/api/", methods=["OPTIONS"])
def options_handler(path=""):
    """Handle pre-flight CORS requests from the browser."""
    resp = make_response("", 204)
    resp.headers["Access-Control-Allow-Origin"]  = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp


# ---------------------------------------------------------------------------
# Pipeline helper
# ---------------------------------------------------------------------------
def _run_pipeline(file_paths):
    """Execute the full compliance pipeline on a list of file paths."""
    from src.compliance_agent import ComplianceAgent
    from src.config_loader import load_config
    from src.email_reader import load_emails
    from src.guardrails import ComplianceVerifier, GuardrailValidator
    from src.scoring_engine import ScoringEngine
    from src.storage import ResultsStorage

    config    = load_config()
    agent     = ComplianceAgent()
    validator = GuardrailValidator(config)
    verifier  = ComplianceVerifier()
    scorer    = ScoringEngine(config)
    storage   = ResultsStorage(str(RESULT_DIR))

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

    run_label   = datetime.now().strftime("%Y%m%d_%H%M%S")
    result_path = storage.save(all_findings, run_label=run_label)
    logger.info("Pipeline complete: %d findings saved to %s",
                len(all_findings), result_path)

    return {
        "total_emails":  len(all_findings),
        "non_compliant": sum(1 for f in all_findings if not f.get("is_compliant", True)),
        "result_file":   Path(result_path).name,
        "findings":      all_findings,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

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
    """Accept multipart file uploads, save to email_data/, run pipeline."""
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
        logger.info("Uploaded file saved -> %s", save_path)

    try:
        result = _run_pipeline(saved_paths)
        return jsonify(result)
    except Exception as exc:
        logger.error("Pipeline error: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


@app.route("/api/results", methods=["GET"])
def get_latest_results():
    from src.storage import ResultsStorage
    data = ResultsStorage(str(RESULT_DIR)).load_latest()
    return jsonify(data)


@app.route("/api/results/list", methods=["GET"])
def list_results():
    from src.storage import ResultsStorage
    runs = ResultsStorage(str(RESULT_DIR)).list_runs()
    return jsonify({"runs": runs})


@app.route("/api/results/<filename>", methods=["GET"])
def get_result_by_name(filename):
    from src.storage import ResultsStorage
    data = ResultsStorage(str(RESULT_DIR)).load(filename)
    if not data:
        return jsonify({"error": "Result not found: " + filename}), 404
    return jsonify(data)


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Starting Email Compliance API server on http://localhost:5050")
    app.run(host="0.0.0.0", port=5050, debug=False)
