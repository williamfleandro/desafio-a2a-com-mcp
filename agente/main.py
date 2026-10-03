"""Entrypoint do agente A2A: python agente/main.py"""

from __future__ import annotations

import uvicorn

import config
from logging_utils import configurar_logging
from server import criar_app


def main() -> None:
    cfg = config.carregar()
    log = configurar_logging()
    log.info("agente A2A em http://%s:%d/a2a (MCP em %s)", cfg.host, cfg.porta, cfg.mcp_url)
    uvicorn.run(criar_app(cfg), host=cfg.host, port=cfg.porta, log_config=None)


if __name__ == "__main__":
    main()
