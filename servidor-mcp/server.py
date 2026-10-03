"""Montagem do servidor MCP: MCPServer do SDK, log de request, tools e resources."""

from __future__ import annotations

import json
import logging

from mcp.server.mcpserver import MCPServer
from mcp.server.request_state import RequestStateSecurity
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

import resources
import tools

NOME = "central-de-salas"
VERSAO = "1.0.0"
TTL_REQUEST_STATE = 600.0  # segundos (10 min, dentro da faixa 5-30 min do enunciado)

log = logging.getLogger("servidor-mcp")


HEADER_MISMATCH = -32020


def _meta_de(msg: dict) -> dict:
    params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
    return params.get("_meta") if isinstance(params.get("_meta"), dict) else {}


def registrar_request(corpo: bytes) -> list[dict]:
    """Loga method, id e traceparent (do params._meta) de cada mensagem JSON-RPC recebida."""
    try:
        dados = json.loads(corpo)
    except (json.JSONDecodeError, UnicodeDecodeError):
        log.info("mcp_request corpo nao-JSON (%d bytes)", len(corpo))
        return []
    mensagens = [m for m in (dados if isinstance(dados, list) else [dados]) if isinstance(m, dict)]
    for msg in mensagens:
        log.info("mcp_request method=%s id=%s traceparent=%s", msg.get("method"), msg.get("id"),
                 _meta_de(msg).get("traceparent") or "-")
    return mensagens


def versao_divergente(mensagens: list[dict], header: str | None) -> dict | None:
    """Mensagem cujo _meta protocolVersion difere do header MCP-Protocol-Version.

    O SDK ja recusa Mcp-Method/Mcp-Name divergentes com -32020, mas nao a versao.
    """
    if header is None:
        return None
    for msg in mensagens:
        versao = _meta_de(msg).get("io.modelcontextprotocol/protocolVersion")
        if versao is not None and versao != header:
            return msg
    return None


class LogDeRequest:
    """ASGI: registra o request na entrada HTTP, antes do SDK, e repassa o corpo intacto.

    Fica na borda HTTP (e nao como ServerMiddleware do SDK) para registrar tambem os
    requests que o SDK rejeita antes do dispatch, como _meta incompleto. Tambem recusa
    com -32020 o header MCP-Protocol-Version que nao bate com o _meta.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "POST":
            await self.app(scope, receive, send)
            return
        mensagens: list[Message] = []
        corpo = b""
        while True:
            msg = await receive()
            mensagens.append(msg)
            if msg["type"] != "http.request":
                break
            corpo += msg.get("body", b"")
            if not msg.get("more_body", False):
                break
        mensagens_rpc = registrar_request(corpo)
        header = Headers(scope=scope).get("mcp-protocol-version")
        divergente = versao_divergente(mensagens_rpc, header)
        if divergente is not None:
            erro = {"code": HEADER_MISMATCH, "message": "MCP-Protocol-Version header does not match params._meta"}
            await JSONResponse({"jsonrpc": "2.0", "id": divergente.get("id"), "error": erro}, status_code=400)(
                scope, receive, send
            )
            return

        async def reenviar() -> Message:
            return mensagens.pop(0) if mensagens else await receive()

        await self.app(scope, reenviar, send)


def criar_app(segredo: bytes) -> ASGIApp:
    # Chave fixa vinda do ambiente: um requestState continua valido apos restart.
    # (Sem isto o MCPServer usaria RequestStateSecurity.ephemeral(), chave por processo.)
    seguranca = RequestStateSecurity(keys=[segredo], ttl=TTL_REQUEST_STATE)
    servidor = MCPServer(name=NOME, version=VERSAO, request_state_security=seguranca)
    tools.registrar(servidor)
    resources.registrar(servidor)
    return LogDeRequest(servidor.streamable_http_app(json_response=True, stateless_http=True))
