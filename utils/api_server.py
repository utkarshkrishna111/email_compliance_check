"""
utils/api_server.py
--------------------
Thin wrapper that starts the Flask compliance API server.
"""

import logging


def run_server(port: int = 5050, open_browser: bool = True) -> None:
    logger = logging.getLogger("main.server")
    logger.info("Starting Email Compliance server ...")
    from src.api_server import start
    start(port=port, open_browser=open_browser)
