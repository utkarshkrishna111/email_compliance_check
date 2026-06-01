"""
src/config_loader.py
--------------------
Loads and validates the compliance_matrix.yaml configuration file.
Supports an optional override path; falls back to config/compliance_matrix.yaml.
"""

import logging
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config" / "compliance_matrix.yaml"


def load_config(config_path: str | None = None) -> Dict[str, Any]:
    """
    Load the YAML compliance configuration.

    Parameters
    ----------
    config_path : str or None
        Path to compliance_matrix.yaml.  Defaults to config/compliance_matrix.yaml.

    Returns
    -------
    dict – parsed configuration
    """
    try:
        import yaml
    except ImportError:
        raise ImportError("PyYAML is required: pip install pyyaml")

    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, "r", encoding="utf-8") as fh:
        config = yaml.safe_load(fh)

    logger.info("Compliance config loaded from %s  (%d categories)",
                path, len(config.get("categories", {})))
    logger.debug("Config contents: %s", config)
    return config
