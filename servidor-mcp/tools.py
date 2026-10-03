"""Tools do servidor MCP."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import AcceptedElicitation, Context, Elicit, ElicitationResult, MCPServer, Resolve
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field, create_model

import config
import domain
import reservations
import resources

MENSAGEM_ESCOLHA = "A sala pedida esta ocupada nesse intervalo. Escolha uma alternativa."


class SalaOut(BaseModel):
    id: str
    nome: str
    capacidade: int
    recursos: list[str]


class ListaDeSalas(BaseModel):
    salas: list[SalaOut]


class ConflitoOut(BaseModel):
    id: str
    inicio: str
    fim: str
    responsavel: str


class Disponibilidade(BaseModel):
    sala: str
    livre: bool
    conflitos: list[ConflitoOut]


class ReservaOut(BaseModel):
    reserva: str | None = None
    reservado: bool = True
    sala: str | None = None
    inicio: str | None = None
    fim: str | None = None
    responsavel: str | None = None
    politica: str | None = None
    motivo: str | None = None


def carregar_salas() -> list[dict]:
    with open(config.DADOS / "salas.json", encoding="utf-8") as f:
        return json.load(f)


def validar(sala: str, inicio: str, fim: str):
    """Regras comuns as tools; erro de regra vira erro de execucao da tool (isError)."""
    try:
        return domain.validar_pedido(sala, inicio, fim, carregar_salas())
    except domain.ErroDeRegra as e:
        raise ToolError(str(e)) from None


def schema_de_escolha(alternativas: list[str]) -> type[BaseModel]:
    """Schema plano da elicitation: 'sala' restrita as alternativas (enum; const se for uma so)."""
    campo = Literal[tuple(alternativas)]  # type: ignore[valid-type]
    return create_model("EscolhaDeSala", sala=(campo, Field(title="Sala", description="Sala alternativa escolhida")))


def escolha_de_sala(sala: str, inicio: str, fim: str, ctx: Context) -> Elicit[Any] | None:
    """Resolver do MRTR. Sala livre: nada a perguntar. Conflito: pergunta entre as alternativas.

    O SDK transforma o Elicit em input_required, sela a resposta no requestState e,
    no retry, injeta o resultado; este corpo roda de novo a cada rodada. Num retry
    (requestState presente) a pergunta e refeita mesmo que a sala pedida tenha ficado
    livre - por exemplo, apos um restart que apagou a reserva em memoria que causava o
    conflito -, para que a escolha selada seja honrada. Se as alternativas mudaram, a
    pergunta muda e o SDK pergunta de novo.
    """
    ini, fi = validar(sala, inicio, fim)
    livre = not domain.conflitos(sala, ini, fi, reservations.reservas)
    if livre and ctx.request_state is None:
        return None
    opcoes = domain.alternativas(sala, ini, fi, carregar_salas(), reservations.reservas)
    if not opcoes:
        if livre:
            return None
        raise ToolError(domain.ERRO_SEM_ALTERNATIVA)
    return Elicit(MENSAGEM_ESCOLHA, schema_de_escolha(opcoes))


def registrar(servidor: MCPServer) -> None:
    @servidor.tool()
    def listar_salas() -> ListaDeSalas:
        """Lista todas as salas com capacidade e recursos."""
        return ListaDeSalas(salas=carregar_salas())

    @servidor.tool()
    def consultar_disponibilidade(sala: str, inicio: str, fim: str) -> Disponibilidade:
        """Diz se uma sala esta livre no intervalo, e quais reservas conflitam."""
        ini, fi = validar(sala, inicio, fim)
        encontrados = domain.conflitos(sala, ini, fi, reservations.reservas)
        return Disponibilidade(sala=sala, livre=not encontrados, conflitos=[ConflitoOut(**r) for r in encontrados])

    @servidor.tool()
    def reservar_sala(
        sala: str,
        inicio: str,
        fim: str,
        responsavel: str,
        escolha: Annotated[ElicitationResult[BaseModel], Resolve(escolha_de_sala)],
    ) -> ReservaOut:
        """Reserva uma sala. Se o intervalo estiver ocupado, pergunta qual alternativa usar."""
        if not isinstance(escolha, AcceptedElicitation):
            return ReservaOut(reservado=False, motivo="recusado")
        destino = sala if escolha.data is None else escolha.data.sala
        r = reservations.criar(destino, inicio, fim, responsavel)
        return ReservaOut(reserva=r["id"], reservado=True, sala=destino, inicio=inicio, fim=fim,
                          responsavel=responsavel, politica=resources.versao_politica())
