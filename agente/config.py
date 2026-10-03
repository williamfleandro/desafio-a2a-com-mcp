"""Configuracao do agente, lida do ambiente (e de um .env na raiz, se existir)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Config:
    host: str
    porta: int
    mcp_url: str
    public_url: str


def carregar() -> Config:
    load_dotenv(RAIZ / ".env", override=False)
    return Config(
        host=os.environ.get("AGENT_HOST", "127.0.0.1"),
        porta=int(os.environ.get("AGENT_PORT", "7300")),
        mcp_url=os.environ.get("MCP_URL", "http://127.0.0.1:7301/mcp"),
        public_url=os.environ.get("AGENT_PUBLIC_URL", "http://127.0.0.1:7300/a2a"),
    )
