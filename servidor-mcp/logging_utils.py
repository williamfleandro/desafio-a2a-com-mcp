"""Logging do servidor MCP: tudo em stderr, stdout fica livre."""

from __future__ import annotations

import logging
import sys

FORMATO = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configurar_logging(nivel: int = logging.INFO) -> logging.Logger:
    """Instala um unico handler de stderr no logger raiz e devolve o logger do processo."""
    raiz = logging.getLogger()
    for handler in list(raiz.handlers):
        raiz.removeHandler(handler)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(FORMATO))
    raiz.addHandler(handler)
    raiz.setLevel(nivel)
    return logging.getLogger("servidor-mcp")
