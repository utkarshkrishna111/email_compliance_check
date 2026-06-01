"""
src/api_server.py
-----------------
Flask REST API consumed by the HTML dashboard.

Endpoints
---------
POST /api/analyse            Upload files → run pipeline → return findings
GET  /api/results            Return latest saved results
GET  /api/results/list       Return list of all past result filenames
GET  /api/results/<filename> Return a specific result file
GET  /api/health             Health-check
"""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS

load_dotenv()

app = Flask(__name__)
CORS(app)

logger         = logging.getLogger(__name__)
PROJECT_ROOT   = Path(__file__).parent.parent
EMAIL_DATA_DIR = PROJECT_ROOT / os.environ.get("EMAIL_DATA_DIR", "email_data")
RESULT_DIR     = PROJECT_ROOT / os.environ.get("RESULT_DIR",     "result")
UPLOAD_EXT     = {".pdf", ".xlsx", ".xls", ".xlsm"}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _run_pipeline(file_paths: list[str]) -> dict:
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
        emails   = load_emails(fp)
        findings = agent.analyse_batch(emails)
        for finding, email in zip(findings, emails):
            is_valid, issues = validator.validate(finding, email)
            finding["guardrail_passed"] = is_valid
            finding["guardrail_issues"] = issues
            finding = verifier.verify(finding, email)
            finding = scorer.score(finding)
            all_findings.append(finding)

    result_path = storage.save(all_findings)
    logger.info("API pipeline complete – %d findings, saved to %s",
                len(all_findings), result_path)
    return {
        "total_emails":  len(all_findings),
        "non_compliant": sum(1 for f in all_findings if not f.get("is_compliant", True)),
        "result_file":   Path(result_path).name,
        "findings":      all_findings,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "email_data_dir": str(EMAIL_DATA_DIR),
                    "result_dir": str(RESULT_DIR)})


@app.route("/api/analyse", methods=["POST"])
def analyse():
    """
    Accepts multipart file uploads (field name: 'files').
    Saves each file to email_data/ then runs the pipeline.
    """
    if "files" not in request.files:
        return jsonify({"error": "No files uploaded. Use field name 'files'."}), 400

    uploaded = request.files.getlist("files")
    if not uploaded:
        return jsonify({"error": "Empty file list."}), 400

    EMAIL_DATA_DIR.mkdir(parents=True, exist_ok=True)
    saved_paths: list[str] = []

    for upload in uploaded:
        filename = upload.filename or "upload"
        ext      = Path(filename).suffix.lower()
        if ext not in UPLOAD_EXT:
            return jsonify({"error": f"Unsupported file '{filename}'. Use PDF or Excel."}), 400

        save_path = EMAIL_DATA_DIR / filename
        upload.save(str(save_path))
        saved_paths.append(str(save_path))
        logger.info("Uploaded file saved → %s", save_path)

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
def get_result_by_name(filename: str):
    from src.storage import ResultsStorage
    data = ResultsStorage(str(RESULT_DIR)).load(filename)
    if not data:
        return jsonify({"error": f"Result not found: {filename}"}), 404
    return jsonify(data)


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(host="0.0.0.0", port=5050, debug=False)
