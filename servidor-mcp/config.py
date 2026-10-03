"""Configuracao do servidor MCP, lida do ambiente (e de um .env na raiz, se existir)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
DADOS = RAIZ / "dados"
TAMANHO_MINIMO_SEGREDO = 32


class ErroDeConfiguracao(Exception):
    """Configuracao ausente ou invalida."""


@dataclass(frozen=True)
class Config:
    host: str
    porta: int
    request_state_secret: str | None


def carregar() -> Config:
    load_dotenv(RAIZ / ".env", override=False)
    return Config(
        host=os.environ.get("MCP_HOST", "127.0.0.1"),
        porta=int(os.environ.get("MCP_PORT", "7301")),
        request_state_secret=os.environ.get("REQUEST_STATE_SECRET") or None,
    )


def exigir_segredo(config: Config) -> bytes:
    """Devolve REQUEST_STATE_SECRET validado. Usado a partir da fase de MRTR."""
    segredo = config.request_state_secret
    if not segredo:
        raise ErroDeConfiguracao(
            "REQUEST_STATE_SECRET nao definido. Gere com: "
            'python -c "import secrets; print(secrets.token_hex(32))"'
        )
    bruto = segredo.encode()
    if len(bruto) < TAMANHO_MINIMO_SEGREDO:
        raise ErroDeConfiguracao(f"REQUEST_STATE_SECRET precisa de no minimo {TAMANHO_MINIMO_SEGREDO} bytes")
    return bruto
