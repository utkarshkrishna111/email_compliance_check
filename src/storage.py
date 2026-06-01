"""
src/storage.py
--------------
Persists scored compliance findings to the  result/  folder.

Each run creates a timestamped JSON file:
    result/compliance_<YYYYMMDD_HHMMSS>.json

A stable alias  result/latest.json  is also written so the dashboard
can always load the most recent run without knowing the timestamp.
"""

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class ResultsStorage:

    def __init__(self, result_dir: str = "result"):
        self.result_dir = Path(result_dir)
        self.result_dir.mkdir(parents=True, exist_ok=True)
        logger.debug("ResultsStorage initialised  dir=%s", self.result_dir.resolve())

    # ── save ─────────────────────────────────────────────────────────────────

    def save(
        self,
        findings: List[Dict[str, Any]],
        run_label: str | None = None,
    ) -> str:
        """
        Save findings to a timestamped JSON file in result/.
        Also writes result/latest.json pointing to this run.

        Returns the full path of the timestamped file.
        """
        stamp    = datetime.now().strftime("%Y%m%d_%H%M%S")
        label    = run_label or stamp
        filename = f"compliance_{label}.json"
        out_path = self.result_dir / filename

        payload = {
            "generated_at":  datetime.utcnow().isoformat() + "Z",
            "run_label":     label,
            "total_emails":  len(findings),
            "non_compliant": sum(1 for f in findings if not f.get("is_compliant", True)),
            "compliant":     sum(1 for f in findings if f.get("is_compliant", True)),
            "findings":      findings,
        }

        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)

        # ── write stable  latest.json  alias ──
        latest_path = self.result_dir / "latest.json"
        shutil.copy2(out_path, latest_path)

        logger.info("Results saved  → %s", out_path)
        logger.info("Latest alias   → %s", latest_path)
        logger.debug("Payload summary: total=%d  non_compliant=%d",
                     payload["total_emails"], payload["non_compliant"])
        return str(out_path)

    # ── load ─────────────────────────────────────────────────────────────────

    def load_latest(self) -> Dict[str, Any]:
        """Load the most recent results (latest.json)."""
        latest = self.result_dir / "latest.json"
        if not latest.exists():
            logger.warning("No latest.json found in %s", self.result_dir)
            return {}
        with open(latest, "r", encoding="utf-8") as fh:
            return json.load(fh)

    def load(self, filename: str = "latest.json") -> Dict[str, Any]:
        path = self.result_dir / filename
        if not path.exists():
            logger.warning("Result file not found: %s", path)
            return {}
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    def list_runs(self) -> List[str]:
        """Return sorted list of all result filenames (newest first)."""
        files = sorted(
            self.result_dir.glob("compliance_*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return [f.name for f in files]
