"""Resources do servidor MCP."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

import config


def ler_politica() -> str:
    # Modo texto normaliza CRLF do checkout no Windows para o LF do repositorio.
    return (config.DADOS / "politica-de-uso.md").read_text(encoding="utf-8")


def versao_politica() -> str:
    """Valor declarado na primeira linha da politica: 'versao: 2026-11-01' -> '2026-11-01'."""
    primeira = ler_politica().splitlines()[0]
    return primeira.split(":", 1)[1].strip()


def registrar(servidor: MCPServer) -> None:
    @servidor.resource("politica://uso", name="politica-de-uso", mime_type="text/markdown")
    def politica_de_uso() -> str:
        """Politica de uso das salas. A primeira linha declara a versao."""
        return ler_politica()
