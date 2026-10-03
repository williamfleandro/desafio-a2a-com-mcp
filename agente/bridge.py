"""Ponte MCP <-> A2A: traduz resultados MCP em estados da Task. Sem regra de negocio de sala."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import parser
from mcp_client import ClienteMCP, ErroMCP
from task_model import CANCELED, COMPLETED, FAILED, INPUT_REQUIRED, WORKING, PendenciaMCP, Task, novo_id

log = logging.getLogger("agente.bridge")

URI_POLITICA = "politica://uso"
ESCOLHA_RECUSAR = "recusar"
_VERSAO = re.compile(r"^versao:\s*(\S+)")
CAMPOS_ARTIFACT = ("reserva", "sala", "inicio", "fim", "responsavel")


class Ponte:
    def __init__(self, cliente: ClienteMCP) -> None:
        self.cliente = cliente

    async def iniciar(self, task: Task, texto: str) -> None:
        """Task nova em WORKING: descobre a tool, le a politica e faz o primeiro tools/call."""
        pedido = parser.parse_pedido(texto)
        if pedido is None:
            task.mudar(FAILED, "Pedido invalido. Formato: reservar sala=<id> inicio=<iso8601> fim=<iso8601> responsavel=<nome>")
            return
        verbo, argumentos = pedido
        try:
            tools = await self.cliente.listar_tools(task.trace_id)
            tool = escolher_tool(tools, verbo, argumentos)
            if tool is None:
                task.mudar(FAILED, f"Nenhuma tool do servidor MCP atende ao pedido '{verbo}'")
                return
            task.politica = versao_politica(await self.cliente.ler_resource(URI_POLITICA, task.trace_id))
            resultado = await self.cliente.chamar_tool(tool, argumentos, task.trace_id)
        except ErroMCP as e:
            task.mudar(FAILED, f"Erro MCP: {e}")
            return
        self.aplicar(task, resultado, tool, argumentos)

    async def continuar(self, task: Task, texto: str) -> None:
        """Task em INPUT_REQUIRED recebeu 'escolha=...': retry MCP com id novo, ou repete a pergunta."""
        pend = task.pendente
        assert pend is not None
        escolha = parser.parse_escolha(texto)
        if escolha == ESCOLHA_RECUSAR:
            resposta: dict[str, Any] = {"action": "decline"}
        elif escolha in pend.alternativas:
            resposta = {"action": "accept", "content": {pend.campo: escolha}}
        else:
            # Fora do enum: nada vai ao MCP e o requestState continua guardado.
            task.mudar(INPUT_REQUIRED, linha_de_alternativas(pend.alternativas))
            return
        task.mudar(WORKING)
        try:
            resultado = await self.cliente.chamar_tool(
                pend.tool, pend.argumentos, task.trace_id, {pend.chave: resposta}, pend.request_state
            )
        except ErroMCP as e:
            task.mudar(FAILED, f"Erro MCP: {e}")
            return
        self.aplicar(task, resultado, pend.tool, pend.argumentos)

    def aplicar(self, task: Task, resultado: dict[str, Any], tool: str, argumentos: dict[str, Any]) -> None:
        """Resultado MCP -> estado A2A."""
        if resultado.get("resultType") == "input_required":
            pend = pendencia_de(resultado, tool, argumentos)
            if pend is None:
                task.mudar(FAILED, "input_required do servidor MCP em formato nao suportado")
                return
            # A ponte: o input_required do MCP vira TASK_STATE_INPUT_REQUIRED, e o
            # requestState fica guardado na Task (privado) ate a continuacao.
            task.pendente = pend
            task.mudar(INPUT_REQUIRED, linha_de_alternativas(pend.alternativas))
            return
        if resultado.get("isError"):
            task.mudar(FAILED, texto_do_resultado(resultado))
            return
        dados = resultado.get("structuredContent") or json.loads(texto_do_resultado(resultado) or "{}")
        if not dados.get("reservado"):
            task.mudar(CANCELED, "Reserva recusada.")
            return
        conteudo = {c: dados.get(c) for c in CAMPOS_ARTIFACT}
        conteudo["politica"] = task.politica
        task.artefatos.append({"artifactId": novo_id("art"), "name": "reserva",
                               "parts": [{"text": json.dumps(conteudo, ensure_ascii=False)}]})
        task.mudar(COMPLETED, f"Reserva {dados.get('reserva')} confirmada na {dados.get('sala')}.")


def pendencia_de(resultado: dict[str, Any], tool: str, argumentos: dict[str, Any]) -> PendenciaMCP | None:
    """Extrai do input_required a unica elicitation form com um campo enum/const. Nao abre o requestState."""
    pedidos = resultado.get("inputRequests") or {}
    estado = resultado.get("requestState")
    if len(pedidos) != 1 or not isinstance(estado, str):
        return None
    chave, pedido = next(iter(pedidos.items()))
    params = pedido.get("params") or {}
    propriedades = (params.get("requestedSchema") or {}).get("properties") or {}
    if pedido.get("method") != "elicitation/create" or params.get("mode", "form") != "form" or len(propriedades) != 1:
        return None
    campo, schema = next(iter(propriedades.items()))
    opcoes = schema.get("enum") or ([schema["const"]] if "const" in schema else [])
    if not opcoes:
        return None
    return PendenciaMCP(request_state=estado, chave=chave, campo=campo, alternativas=[str(o) for o in opcoes],
                        tool=tool, argumentos=argumentos)


def linha_de_alternativas(alternativas: list[str]) -> str:
    return "alternativas: " + ", ".join(alternativas)


def escolher_tool(tools: list[dict[str, Any]], verbo: str, argumentos: dict[str, str]) -> str | None:
    """Tool descoberta cujo nome comeca pelo verbo e cujo inputSchema exige exatamente os campos do pedido."""
    for t in tools:
        exigidos = set((t.get("inputSchema") or {}).get("required") or [])
        if t.get("name", "").startswith(verbo) and exigidos == set(argumentos):
            return t["name"]
    return None


def versao_politica(texto: str) -> str | None:
    m = _VERSAO.match(texto.splitlines()[0] if texto else "")
    return m.group(1) if m else None


def texto_do_resultado(resultado: dict[str, Any]) -> str:
    return " ".join(p.get("text", "") for p in resultado.get("content") or [] if isinstance(p, dict))
