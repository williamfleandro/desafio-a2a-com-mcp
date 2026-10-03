"""Entrypoint do servidor MCP: python servidor-mcp/main.py"""

from __future__ import annotations

import sys

import uvicorn

import config
from logging_utils import configurar_logging
from server import criar_app


def main() -> None:
    cfg = config.carregar()
    log = configurar_logging()
    try:
        segredo = config.exigir_segredo(cfg)
    except config.ErroDeConfiguracao as e:
        log.error("%s", e)
        sys.exit(1)
    log.info("servidor MCP em http://%s:%d/mcp", cfg.host, cfg.porta)
    uvicorn.run(criar_app(segredo), host=cfg.host, port=cfg.porta, log_config=None)


if __name__ == "__main__":
    main()
