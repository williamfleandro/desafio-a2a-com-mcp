"""Host MCP do agente: cliente Streamable HTTP (MCP 2026-07-28) para o servidor de salas.

Escrito sobre httpx2 (o mesmo cliente HTTP do SDK mcp) em vez do `mcp.Client` porque:
- o `ClientSession` do SDK so declara elicitation quando ha callback, e entao anuncia
  {"form": {}, "url": {}}; o contrato pede exatamente {"elicitation": {"form": {}}};
- o agente nunca responde elicitation sozinho: ele precisa do input_required cru.
Cada request e independente (sem sessao): _meta completo e headers espelhados sempre.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx2

import traceparent as tp

PROTOCOLO = "2026-07-28"
CLIENT_INFO = {"name": "agente-central-de-salas", "version": "1.0.0"}
CAPABILITIES = {"elicitation": {"form": {}}}
METODOS_COM_NOME = {"tools/call": "name", "resources/read": "uri"}


class ErroMCP(Exception):
    """Erro de protocolo devolvido pelo servidor MCP (JSON-RPC error) ou falha de transporte."""

    def __init__(self, mensagem: str, codigo: int | None = None) -> None:
        super().__init__(mensagem)
        self.codigo = codigo


class ClienteMCP:
    def __init__(self, url: str) -> None:
        self.url = url
        self._http = httpx2.AsyncClient(timeout=30.0)

    async def fechar(self) -> None:
        await self._http.aclose()

    async def _rpc(self, metodo: str, params: dict[str, Any], trace_id: str | None) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "io.modelcontextprotocol/protocolVersion": PROTOCOLO,
            "io.modelcontextprotocol/clientInfo": CLIENT_INFO,
            "io.modelcontextprotocol/clientCapabilities": CAPABILITIES,
        }
        filho = tp.filho(trace_id)
        if filho:
            meta["traceparent"] = filho
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOLO,
            "Mcp-Method": metodo,
        }
        if metodo in METODOS_COM_NOME:
            headers["Mcp-Name"] = params[METODOS_COM_NOME[metodo]]
        # id novo a cada request: o retry do MRTR e um request independente.
        corpo = {"jsonrpc": "2.0", "id": f"agente-{uuid.uuid4().hex[:12]}", "method": metodo,
                 "params": {**params, "_meta": meta}}
        try:
            resposta = await self._http.post(self.url, json=corpo, headers=headers)
            dados = resposta.json()
        except (httpx2.HTTPError, ValueError) as e:
            raise ErroMCP(f"falha ao falar com o servidor MCP: {e.__class__.__name__}") from e
        if "error" in dados:
            erro = dados["error"] or {}
            raise ErroMCP(str(erro.get("message", "erro MCP")), erro.get("code"))
        return dados.get("result") or {}

    async def listar_tools(self, trace_id: str | None = None) -> list[dict[str, Any]]:
        return (await self._rpc("tools/list", {}, trace_id)).get("tools", [])

    async def ler_resource(self, uri: str, trace_id: str | None = None) -> str:
        conteudos = (await self._rpc("resources/read", {"uri": uri}, trace_id)).get("contents") or [{}]
        return conteudos[0].get("text", "")

    async def chamar_tool(
        self,
        nome: str,
        argumentos: dict[str, Any],
        trace_id: str | None = None,
        input_responses: dict[str, Any] | None = None,
        request_state: str | None = None,
    ) -> dict[str, Any]:
        """Devolve o result cru: resultType 'complete' (com isError ou nao) ou 'input_required'."""
        params: dict[str, Any] = {"name": nome, "arguments": argumentos}
        if input_responses is not None:
            params["inputResponses"] = input_responses
        if request_state is not None:
            params["requestState"] = request_state
        return await self._rpc("tools/call", params, trace_id)
